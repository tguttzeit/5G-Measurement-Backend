#!/usr/bin/env python3
"""
Device registration CLI script.

Usage:
    uv run scripts/register_device.py <device_id>

Generates a random API key, stores its hash in the database, and prints the plaintext key.
The maintainer should copy this key into the device's config.
"""
import os
import secrets
import sys

# Add the project root to the path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models import Device  # noqa: E402


def generate_api_key() -> str:
    """Generate a random API key (32 bytes, hex encoded)."""
    return secrets.token_hex(32)


def hash_api_key(key: str) -> str:
    """Hash the API key using SHA-256."""
    import hashlib
    return hashlib.sha256(key.encode()).hexdigest()


def register_device(device_id: str) -> tuple[str, str]:
    """Register a new device and return its (API key, HMAC secret)."""
    settings = get_settings()
    engine = create_engine(settings.database_url)

    with Session(engine) as session:
        # Check if device already exists
        existing = session.get(Device, device_id)
        if existing:
            print(f"Error: Device '{device_id}' already exists.", file=sys.stderr)
            sys.exit(1)

        # Generate key and hash
        api_key = generate_api_key()
        api_key_hash = hash_api_key(api_key)
        # Distinct secret used to HMAC-sign heartbeat responses -
        # kept separate from the API key so a leak of one can't forge the other direction.
        hmac_secret = secrets.token_hex(32)

        # Create and store device
        device = Device(device_id=device_id, api_key_hash=api_key_hash, hmac_secret=hmac_secret)
        session.add(device)
        session.commit()

        return api_key, hmac_secret


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <device_id>", file=sys.stderr)
        sys.exit(1)

    device_id = sys.argv[1]
    api_key, hmac_secret = register_device(device_id)

    print(f"Device '{device_id}' registered successfully.")
    print(f"API Key: {api_key}")
    print(f"HMAC Secret: {hmac_secret}")
    print(
        "\nWARNING: Neither value will be shown again. Copy both to the device's config."
    )


if __name__ == "__main__":
    main()
