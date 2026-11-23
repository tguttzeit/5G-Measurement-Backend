"""systemd units for the daily database backup (deploy/5gm-db-backup.{service,timer}).

Static assertions on the unit files: systemd isn't running in the pytest process. They guard the
security properties the backups depend on, which are easy to lose when editing the units.
"""

import re
from configparser import ConfigParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE = REPO_ROOT / "deploy" / "5gm-db-backup.service"
TIMER = REPO_ROOT / "deploy" / "5gm-db-backup.timer"
SCRIPT = REPO_ROOT / "deploy" / "backup-db.sh"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
BACKUP_DIR = "/var/backups/5g-measurement-backend"


def unit(path: Path) -> ConfigParser:
    parser = ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read_string(path.read_text())
    return parser


def test_service_runs_the_backup_script_as_a_non_root_user():
    service = unit(SERVICE)["Service"]

    assert service["User"] not in ("", "root", "0")
    assert service["ExecStart"].endswith("/deploy/backup-db.sh")
    assert service["Type"] == "oneshot"


def test_service_can_only_write_to_the_backup_directory():
    service = unit(SERVICE)["Service"]

    assert service["ProtectSystem"] == "strict"
    assert service["ProtectHome"] == "read-only"
    assert service["ReadWritePaths"] == BACKUP_DIR
    assert service["Environment"] == f"BACKUP_DIR={BACKUP_DIR}"
    assert service["NoNewPrivileges"] == "yes"


def test_script_default_matches_the_unit_so_manual_runs_land_in_the_same_place():
    match = re.search(r"^BACKUP_DIR=\$\{BACKUP_DIR:-(.+)\}$", SCRIPT.read_text(), re.MULTILINE)

    assert match and match.group(1) == BACKUP_DIR


def test_timer_runs_daily_and_catches_up_after_downtime():
    timer = unit(TIMER)

    assert timer["Timer"]["OnCalendar"].startswith("*-*-* ")
    assert timer["Timer"]["Persistent"] == "true"
    assert timer["Timer"]["Unit"] == "5gm-db-backup.service"
    assert timer["Install"]["WantedBy"] == "timers.target"


def test_backup_directory_is_not_mounted_into_any_container():
    # Caddy serves what is mounted into it; a dump holds password and device key hashes.
    assert BACKUP_DIR not in COMPOSE_FILE.read_text()
