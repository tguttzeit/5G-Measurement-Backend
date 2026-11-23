"""deploy/backup-db.sh: scheduled and pre-update dumps of the Postgres database.

The script is run against a fake `docker` on PATH that records its calls and stands in for
`pg_dump`/`pg_restore` inside the postgres container, so retention, permissions and failure
handling are checked without a running stack.
"""

import os
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "deploy" / "backup-db.sh"

FAKE_DUMP = b"PGDMP fake archive"

FAKE_DOCKER = """#!/usr/bin/env bash
echo "$PWD|$*" >> "$FAKE_DOCKER_LOG"
case "$*" in
  *pg_dump*)
    if [[ -n ${FAKE_DUMP_FAIL:-} ]]; then printf 'PGDMP half'; echo 'pg_dump: error' >&2; exit 1; fi
    printf 'PGDMP fake archive'
    ;;
  *pg_restore*)
    cat > "$FAKE_RESTORE_INPUT"
    if [[ -n ${FAKE_RESTORE_FAIL:-} ]]; then echo 'pg_restore: invalid archive' >&2; exit 1; fi
    ;;
esac
"""


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    compose_dir = tmp_path / "backend"
    compose_dir.mkdir()
    return {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BACKUP_DIR": str(tmp_path / "backups"),
        "COMPOSE_DIR": str(compose_dir),
        "BACKUP_MIN_FREE_MB": "0",
        "FAKE_DOCKER_LOG": str(tmp_path / "docker.log"),
        "FAKE_RESTORE_INPUT": str(tmp_path / "restore-input"),
    }


def run(env: dict[str, str], *args: str, **overrides: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env={**env, **overrides},
        capture_output=True,
        text=True,
        check=False,
    )


def dumps(env: dict[str, str], kind: str) -> list[Path]:
    directory = Path(env["BACKUP_DIR"]) / kind
    return sorted(directory.glob("*.dump")) if directory.exists() else []


def all_files(env: dict[str, str]) -> list[Path]:
    """Every file below BACKUP_DIR except the run lock."""
    backup_dir = Path(env["BACKUP_DIR"])
    return sorted(p for p in backup_dir.rglob("*") if p.is_file() and p != backup_dir / ".lock")


def docker_calls(env: dict[str, str]) -> list[str]:
    return Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def current_iso_week() -> str:
    year, week, _ = datetime.now(UTC).isocalendar()
    return f"{year}-W{week:02d}"


def seed(env: dict[str, str], kind: str, names: list[str]) -> None:
    directory = Path(env["BACKUP_DIR"]) / kind
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / f"measurement_backend-{name}.dump").write_bytes(b"old")


def test_daily_run_writes_a_custom_format_dump_from_the_postgres_container(env):
    result = run(env)

    assert result.returncode == 0, result.stderr
    [dump] = dumps(env, "daily")
    assert dump.read_bytes() == FAKE_DUMP
    dump_call = next(call for call in docker_calls(env) if "pg_dump" in call)
    assert dump_call == (
        f"{env['COMPOSE_DIR']}|compose exec -T postgres "
        "pg_dump -U postgres -d measurement_backend -Fc"
    )


def test_dump_is_verified_as_a_readable_archive(env):
    run(env)

    restore_call = next(call for call in docker_calls(env) if "pg_restore" in call)
    assert restore_call.endswith("compose exec -T postgres pg_restore --list")
    assert Path(env["FAKE_RESTORE_INPUT"]).read_bytes() == FAKE_DUMP


def test_run_logs_the_dump_size(env):
    result = run(env)

    [dump] = dumps(env, "daily")
    assert f"backup written: {dump} ({len(FAKE_DUMP)}B)" in result.stdout


def test_backups_are_only_readable_by_the_owner(env):
    run(env)

    backup_dir = Path(env["BACKUP_DIR"])
    assert mode(backup_dir) == 0o700
    assert mode(backup_dir / "daily") == 0o700
    assert all(mode(path) == 0o600 for path in all_files(env))


def test_existing_backup_directory_is_tightened_to_owner_only(env):
    backup_dir = Path(env["BACKUP_DIR"])
    backup_dir.mkdir(mode=0o755)
    backup_dir.chmod(0o755)

    run(env)

    assert mode(backup_dir) == 0o700


def test_only_the_seven_newest_daily_dumps_are_kept(env):
    seed(env, "daily", [f"2020-01-{day:02d}T031500Z" for day in range(1, 10)])

    run(env)

    kept = [p.name for p in dumps(env, "daily")]
    assert len(kept) == 7
    assert "measurement_backend-2020-01-01T031500Z.dump" not in kept
    assert "measurement_backend-2020-01-03T031500Z.dump" not in kept
    assert "measurement_backend-2020-01-04T031500Z.dump" in kept
    assert any(p.read_bytes() == FAKE_DUMP for p in dumps(env, "daily"))


def test_first_dump_of_a_week_is_also_kept_as_the_weekly_dump(env):
    run(env)

    [weekly] = dumps(env, "weekly")
    assert weekly.name == f"measurement_backend-{current_iso_week()}.dump"
    assert weekly.read_bytes() == FAKE_DUMP


def test_later_dumps_of_the_same_week_leave_the_weekly_dump_alone(env):
    seed(env, "weekly", [current_iso_week()])

    run(env)

    [weekly] = dumps(env, "weekly")
    assert weekly.read_bytes() == b"old"


def test_only_the_four_newest_weekly_dumps_are_kept(env):
    seed(env, "weekly", [f"2020-W{week:02d}" for week in range(1, 6)])

    run(env)

    kept = [p.name for p in dumps(env, "weekly")]
    assert kept == [
        "measurement_backend-2020-W03.dump",
        "measurement_backend-2020-W04.dump",
        "measurement_backend-2020-W05.dump",
        f"measurement_backend-{current_iso_week()}.dump",
    ]


def test_failed_dump_leaves_no_file_behind_and_prunes_nothing(env):
    names = [f"2020-01-{day:02d}T031500Z" for day in range(1, 10)]
    seed(env, "daily", names)

    result = run(env, FAKE_DUMP_FAIL="1")

    assert result.returncode != 0
    assert [p.name for p in dumps(env, "daily")] == [
        f"measurement_backend-{name}.dump" for name in names
    ]
    assert dumps(env, "weekly") == []
    assert all(p.suffix == ".dump" for p in all_files(env))


def test_unreadable_dump_is_discarded(env):
    result = run(env, FAKE_RESTORE_FAIL="1")

    assert result.returncode != 0
    assert all_files(env) == []


def test_low_free_space_is_reported_as_a_warning(env):
    result = run(env, BACKUP_MIN_FREE_MB=str(10**12))

    assert result.returncode == 0
    assert "low disk space" in result.stderr
    assert len(dumps(env, "daily")) == 1


def test_enough_free_space_gives_no_warning(env):
    result = run(env)

    assert "low disk space" not in result.stderr


def test_warning_carries_the_journal_priority_prefix_under_systemd(env):
    result = run(env, BACKUP_MIN_FREE_MB=str(10**12), JOURNAL_STREAM="8:12345")

    assert result.stderr.startswith("<4>")


def test_pre_update_dump_is_kept_apart_from_the_rotation(env):
    seed(env, "pre-update", [f"2020-01-{day:02d}T120000Z" for day in range(1, 5)])

    result = run(env, "--pre-update")

    assert result.returncode == 0, result.stderr
    pre_update = dumps(env, "pre-update")
    assert len(pre_update) == 3
    assert pre_update[-1].read_bytes() == FAKE_DUMP
    assert dumps(env, "daily") == []
    assert dumps(env, "weekly") == []


def test_unknown_argument_is_rejected(env):
    result = run(env, "--restore")

    assert result.returncode != 0
    assert not Path(env["BACKUP_DIR"]).exists()
