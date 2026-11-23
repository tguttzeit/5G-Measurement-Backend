"""Static documentation site served under /docs by Caddy.

The site is built on the server by the documentation deployment timer (see the documentation
repository) into a timestamped release, with a `current` symlink switched over atomically.
Caddy serves that symlink, which puts two requirements on this repo's config and makes them
easy to break by "tidying up":

- The compose file mounts the base directory, not the symlink itself. Docker resolves a mounted
  symlink once at container start, so mounting `current` directly would keep serving the release
  that was live when the container started.
- `root` therefore points at `/srv/docs/current`, inside the mounted base directory, so Caddy
  resolves the symlink per request.

Like test_caddy_body_limits.py this is a static-config assertion: Caddy isn't running in the
pytest process.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CADDYFILE = REPO_ROOT / "deploy" / "Caddyfile"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"


def test_docs_path_is_served_from_the_current_symlink():
    contents = CADDYFILE.read_text()

    assert "handle_path /docs/*" in contents
    assert "root * /srv/docs/current" in contents
    assert "file_server" in contents


def test_docs_without_a_trailing_slash_redirects():
    # /docs does not match /docs/*, so without this redirect the bare path falls through to the
    # frontend catch-all and returns the SPA instead of the documentation.
    assert "redir /docs /docs/" in CADDYFILE.read_text()


def test_caddy_mounts_the_docs_base_directory_not_the_symlink():
    contents = COMPOSE_FILE.read_text()

    assert ":/srv/docs:ro" in contents
    assert "/current:/srv/docs" not in contents


def _redirect_lines(caddyfile: Path) -> list[str]:
    return [line.strip() for line in caddyfile.read_text().splitlines() if "redir" in line]


def test_builtin_api_documentation_paths_redirect_to_the_documentation_site():
    redirects = _redirect_lines(CADDYFILE)

    assert "redir /api/docs /docs/en/backend/dev/api/ permanent" in redirects
    assert "redir /api/redoc /docs/en/backend/dev/api/ permanent" in redirects
    assert "redir /api/openapi.json /docs/en/backend/dev/api/openapi.json permanent" in redirects


def test_api_documentation_redirects_come_before_the_api_proxy():
    contents = CADDYFILE.read_text()

    assert contents.index("redir /api/docs ") < contents.index("handle_path /api/*")
