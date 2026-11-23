"""HMAC-SHA256 signing of heartbeat responses.

Signs with each device's dedicated `hmac_secret` - a plaintext secret separate from the
`api_key_hash` used to authenticate the device's own requests, so a leak of one can't be used
to forge the other direction. Response authentication is mandatory here (unlike the read-only
heartbeat POST itself): a spoofed or tampered response could actively break a device via
injected commands.
"""
import hashlib
import hmac
import json

from app.models import Device

SIGNATURE_PREFIX = "hmac-sha256:"


def sign_heartbeat_response(device: Device, body: dict) -> str:
    """Sign a heartbeat response body (everything except the signature field itself).

    `body` must be exactly what will be serialized alongside the returned signature, so the
    device can reproduce this signature by hashing the response it actually received.
    """
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    digest = hmac.new(
        device.hmac_secret.encode(), canonical.encode(), hashlib.sha256
    ).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


__all__ = ["SIGNATURE_PREFIX", "sign_heartbeat_response"]
