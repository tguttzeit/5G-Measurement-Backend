"""Per-device API key authentication, shared by every device-facing endpoint."""

import hashlib
import hmac

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Device

# Compared against when the device_id doesn't exist, so an unknown device_id and a
# known device_id with a wrong key take the same amount of work - otherwise device_id
# existence would be a timing oracle.
_DUMMY_KEY_HASH = hashlib.sha256(b"").hexdigest()


def verify_device_auth(
    x_device_id: str | None = Header(None, alias="X-Device-ID"),
    x_device_key: str | None = Header(None, alias="X-Device-Key"),
    db: Session = Depends(get_db),
) -> Device:
    """Verify device authentication using the X-Device-ID and X-Device-Key headers.

    Takes its inputs as FastAPI-resolved headers/dependencies (rather than being called
    manually from inside an endpoint body) so it runs - and can reject a request - before
    the request body is parsed and validated.
    """
    if not x_device_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Device-ID header",
        )

    if not x_device_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Device-Key header",
        )

    device = db.get(Device, x_device_id)
    key_hash = hashlib.sha256(x_device_key.encode()).hexdigest()

    if device is None:
        hmac.compare_digest(key_hash, _DUMMY_KEY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown device_id",
        )

    if not hmac.compare_digest(key_hash, device.api_key_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    return device
