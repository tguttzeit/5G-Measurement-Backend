#!/usr/bin/env python3
"""
Rotate a registered device's API key and HMAC secret.

Usage:
    uv run scripts/rotate_device_credentials.py <device_id>

Generates a new API key and HMAC secret the same way register_device.py does, replaces the old
ones and prints the new values once. There is no grace period: the old key is rejected from the
moment this commits, and the device rejects heartbeat responses until its config carries the new
HMAC secret. Queued config overrides and commands stay queued and are signed with the new secret
when they are delivered.
"""
import os
import secrets
import sys
from contextlib import contextmanager

# Add the project root to the path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models import Device  # noqa: E402
from scripts.register_device import generate_api_key, hash_api_key  # noqa: E402


class UnknownDeviceError(LookupError):
    pass


def rotate_credentials(session: Session, device_id: str) -> tuple[str, str]:
    """Replace the device's credentials and return the new (API key, HMAC secret)."""
    device = session.get(Device, device_id)
    if device is None:
        raise UnknownDeviceError(device_id)

    api_key = generate_api_key()
    hmac_secret = secrets.token_hex(32)
    device.api_key_hash = hash_api_key(api_key)
    device.hmac_secret = hmac_secret
    session.commit()
    return api_key, hmac_secret


@contextmanager
def _open_session():
    engine = create_engine(get_settings().database_url)
    with Session(engine) as session:
        yield session


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <device_id>", file=sys.stderr)
        sys.exit(1)

    device_id = sys.argv[1]
    with _open_session() as session:
        try:
            api_key, hmac_secret = rotate_credentials(session, device_id)
        except UnknownDeviceError:
            print(f"Error: Device '{device_id}' does not exist.", file=sys.stderr)
            sys.exit(1)

    print(f"Credentials of device '{device_id}' rotated. The old API key no longer works.")
    print(f"API Key: {api_key}")
    print(f"HMAC Secret: {hmac_secret}")
    print(
        "\nWARNING: Neither value will be shown again. Put both into the device's "
        "config.local.toml now; until then the device cannot reach the backend."
    )


if __name__ == "__main__":
    main()
