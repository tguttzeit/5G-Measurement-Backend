"""Caddy must not buffer the heartbeat SSE stream.

Static-config assertion on the Caddyfile, same approach as test_caddy_body_limits.py.
"""
import re
from pathlib import Path

CADDYFILE = Path(__file__).resolve().parent.parent.parent / "deploy" / "Caddyfile"


def test_api_reverse_proxy_flushes_immediately():
    contents = CADDYFILE.read_text()

    assert re.search(r"reverse_proxy backend:8000 \{[^}]*flush_interval -1", contents)
