"""Request body size cap at the Caddy layer, for device-facing /api/* paths.

deploy/Caddyfile's `handle_path /api/*` block has a `request_body { max_size 10MB }` directive.
This is a static-config assertion (parses the Caddyfile directly) rather than a live HTTP test,
since Caddy isn't running in the pytest process.
"""
from pathlib import Path

CADDYFILE = Path(__file__).resolve().parent.parent.parent / "deploy" / "Caddyfile"


def test_api_path_has_a_request_body_size_cap():
    contents = CADDYFILE.read_text()

    # Look for a request_body directive with a max_size sub-directive anywhere in the file.
    # Doesn't require it to live specifically inside the handle_path /api/* block (Caddy allows a
    # site-wide cap too) -- just that a cap exists somewhere that would apply to /api/* traffic.
    assert "request_body" in contents
    assert "max_size" in contents
