#!/usr/bin/env python3
"""
Register (or reset) a dev device with fixed, known credentials.

Unlike register_device.py, which generates a random key and secret and shows them once, this
takes them as arguments (with documented defaults) so they can be typed into a device config
ahead of time. That makes the credentials worthless as secrets, so it refuses to run with
ENVIRONMENT=production.

Usage:
    uv run python scripts/seed_dev_device.py [device_id] [--device-key KEY] [--hmac-secret SECRET]

Idempotent: an existing device with that id gets the given key and secret.
"""
import argparse
import hashlib
import os
import sys

# Add the project root to the path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models import Device  # noqa: E402

DEFAULT_DEVICE_ID = "devbox-1"
DEFAULT_DEVICE_KEY = "lan-dev-device-key-0123456789abcdef0123456789abcdef"
DEFAULT_HMAC_SECRET = "lan-dev-hmac-secret-fedcba9876543210fedcba9876543210"


def seed_device(session: Session, device_id: str, device_key: str, hmac_secret: str) -> bool:
    """Create the device, or reset its credentials. Returns True if it was newly created."""
    api_key_hash = hashlib.sha256(device_key.encode()).hexdigest()
    device = session.get(Device, device_id)
    created = device is None
    if device is None:
        device = Device(device_id=device_id, api_key_hash=api_key_hash, hmac_secret=hmac_secret)
        session.add(device)
    else:
        device.api_key_hash = api_key_hash
        device.hmac_secret = hmac_secret
    session.commit()
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("device_id", nargs="?", default=DEFAULT_DEVICE_ID)
    parser.add_argument("--device-key", default=DEFAULT_DEVICE_KEY)
    parser.add_argument("--hmac-secret", default=DEFAULT_HMAC_SECRET)
    args = parser.parse_args()

    settings = get_settings()
    if settings.environment == "production":
        print(
            "Refusing to seed a device with known credentials while ENVIRONMENT=production.",
            file=sys.stderr,
        )
        sys.exit(1)

    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        created = seed_device(session, args.device_id, args.device_key, args.hmac_secret)

    print(f"Device '{args.device_id}' {'registered' if created else 'credentials reset'}.")
    print(f"device_id:   {args.device_id}")
    print(f"device_key:  {args.device_key}   (sent as X-Device-Key)")
    print(f"hmac_secret: {args.hmac_secret}   (verifies heartbeat response signatures)")


if __name__ == "__main__":
    main()
