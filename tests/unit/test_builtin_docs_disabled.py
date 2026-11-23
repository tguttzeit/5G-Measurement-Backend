"""FastAPI's own documentation endpoints are off; the reference lives on the documentation site.

`app.openapi()` keeps working because the documentation build calls it directly instead of
requesting `/openapi.json`.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"])
def test_builtin_documentation_endpoints_are_not_served(path):
    assert client.get(path).status_code == 404


def test_openapi_schema_can_still_be_generated_in_process():
    schema = app.openapi()

    assert schema["info"]["title"] == app.title
    assert "/health" in schema["paths"]
