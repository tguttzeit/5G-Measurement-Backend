"""The generated OpenAPI schema is the only API reference, so it has to be complete and public-safe.

Every operation carries a summary and a description, and the texts leave out what must stay
internal (issue numbers, hosts, development tooling).
"""

import json
import re

import pytest

from app.main import app

HTTP_METHODS = {"get", "put", "post", "patch", "delete"}
INTERNAL_MARKERS = re.compile(r"issue\s*#\d+|#\d+|\bdecision\b|\.md\b|/home/", re.IGNORECASE)

SCHEMA = app.openapi()
OPERATIONS = [
    (method.upper(), path, operation)
    for path, item in SCHEMA["paths"].items()
    for method, operation in item.items()
    if method in HTTP_METHODS
]


def _id(op):
    return f"{op[0]} {op[1]}"


@pytest.mark.parametrize("op", OPERATIONS, ids=_id)
def test_every_operation_has_summary_and_description(op):
    _, _, operation = op

    assert operation.get("summary", "").strip()
    assert operation.get("description", "").strip()


@pytest.mark.parametrize("op", OPERATIONS, ids=_id)
def test_operation_description_is_not_just_the_summary(op):
    _, _, operation = op

    assert operation["description"].strip() != operation["summary"].strip()


def test_schema_texts_contain_nothing_internal():
    texts = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"summary", "description", "title"} and isinstance(value, str):
                    texts.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads(json.dumps(SCHEMA)))
    leaks = [t for t in texts if INTERNAL_MARKERS.search(t)]
    assert not leaks, leaks
