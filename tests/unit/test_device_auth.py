"""Cross-cutting device-key auth tests.

Written against `app.device_auth.verify_device_auth`, the shared dependency every device-facing
endpoint imports. Guards in particular against parsing the request body before auth is checked.

Uses a throwaway FastAPI app/route instead of `app.main.app`, so these tests don't need a real
device-facing endpoint to exist yet and don't touch the database.
"""
import hashlib

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.db import get_db
from app.device_auth import verify_device_auth
from app.models import Device

KNOWN_DEVICE_ID = "probe-device-01"
KNOWN_DEVICE_KEY = "correct-horse-battery-staple"
KNOWN_DEVICE = Device(
    device_id=KNOWN_DEVICE_ID,
    api_key_hash=hashlib.sha256(KNOWN_DEVICE_KEY.encode()).hexdigest(),
)


class FakeSession:
    """Stands in for a SQLAlchemy Session: only `.get(Device, pk)` is exercised."""

    def __init__(self, devices: dict[str, Device]):
        self._devices = devices

    def get(self, model, pk):
        assert model is Device
        return self._devices.get(pk)


def fake_get_db():
    yield FakeSession({KNOWN_DEVICE_ID: KNOWN_DEVICE})


class ProbeBody(BaseModel):
    """A body with required fields, standing in for a real endpoint's request schema."""

    required_field: str
    another_required: int = 0


probe_app = FastAPI()


@probe_app.post("/probe")
def probe(body: ProbeBody, device: Device = Depends(verify_device_auth)):
    return {"device_id": device.device_id}


class MismatchProbeBody(BaseModel):
    device_id: str


@probe_app.post("/probe-mismatch")
def probe_mismatch(body: MismatchProbeBody, device: Device = Depends(verify_device_auth)):
    """Demonstrates the pattern device-facing endpoints follow for payload/auth device_id checks.

    The dependency only verifies *who* is calling; matching that identity against the payload's
    own device_id is endpoint-specific and happens after the dependency succeeds.
    """
    from fastapi import HTTPException, status

    if body.device_id != device.device_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="payload device_id does not match authenticated device",
        )
    return {"device_id": device.device_id}


probe_app.dependency_overrides[get_db] = fake_get_db
client = TestClient(probe_app)

VALID_BODY = {"required_field": "x", "another_required": 1}
VALID_HEADERS = {"X-Device-ID": KNOWN_DEVICE_ID, "X-Device-Key": KNOWN_DEVICE_KEY}


def test_valid_credentials_and_body_succeed():
    response = client.post("/probe", json=VALID_BODY, headers=VALID_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"device_id": KNOWN_DEVICE_ID}


def test_malformed_body_with_no_credentials_returns_401_not_422():
    response = client.post("/probe", json={"bogus": "data"})

    assert response.status_code == 401


def test_syntactically_invalid_json_still_422s_before_auth_runs():
    """FastAPI parses raw JSON syntax before resolving any dependency, auth included — so
    unparseable JSON 422s regardless of how auth is wired. This documents that boundary rather
    than asserting something no `Depends()` can change; the guarantee this suite actually enforces
    is auth-before-*schema*-validation (missing fields, oversized values), covered by
    `test_malformed_body_with_no_credentials_returns_401_not_422` above.
    """
    response = client.post(
        "/probe", content=b"not even json", headers={"content-type": "application/json"}
    )

    assert response.status_code == 422


def test_missing_device_id_header_returns_401():
    response = client.post(
        "/probe", json=VALID_BODY, headers={"X-Device-Key": KNOWN_DEVICE_KEY}
    )

    assert response.status_code == 401


def test_missing_device_key_header_returns_401():
    response = client.post(
        "/probe", json=VALID_BODY, headers={"X-Device-ID": KNOWN_DEVICE_ID}
    )

    assert response.status_code == 401


def test_unknown_device_id_returns_401():
    response = client.post(
        "/probe",
        json=VALID_BODY,
        headers={"X-Device-ID": "no-such-device", "X-Device-Key": KNOWN_DEVICE_KEY},
    )

    assert response.status_code == 401


def test_wrong_device_key_returns_401():
    response = client.post(
        "/probe",
        json=VALID_BODY,
        headers={"X-Device-ID": KNOWN_DEVICE_ID, "X-Device-Key": "wrong-key"},
    )

    assert response.status_code == 401


def test_unknown_device_and_wrong_key_return_the_same_status_and_body_shape():
    """Not a timing test (impractical to assert reliably in a unit test) — just confirms the two
    failure modes aren't distinguishable by status code or response shape, which is the part
    within a unit test's reach. Constant-time comparison (hmac.compare_digest) is what protects
    the timing side of this; see app/device_auth.py (which also dummy-compares on an unknown
    device_id specifically so device existence isn't a timing oracle either).
    """
    unknown_device = client.post(
        "/probe",
        json=VALID_BODY,
        headers={"X-Device-ID": "no-such-device", "X-Device-Key": KNOWN_DEVICE_KEY},
    )
    wrong_key = client.post(
        "/probe",
        json=VALID_BODY,
        headers={"X-Device-ID": KNOWN_DEVICE_ID, "X-Device-Key": "wrong-key"},
    )

    assert unknown_device.status_code == wrong_key.status_code == 401
    assert set(unknown_device.json().keys()) == set(wrong_key.json().keys())


def test_payload_device_id_mismatch_returns_403():
    response = client.post(
        "/probe-mismatch",
        json={"device_id": "some-other-device"},
        headers=VALID_HEADERS,
    )

    assert response.status_code == 403


def test_payload_device_id_match_succeeds():
    response = client.post(
        "/probe-mismatch",
        json={"device_id": KNOWN_DEVICE_ID},
        headers=VALID_HEADERS,
    )

    assert response.status_code == 200
