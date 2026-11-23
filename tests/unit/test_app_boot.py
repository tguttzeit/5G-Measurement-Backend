"""App-boot smoke test.

Catches import-time errors (e.g. Pydantic v2 `__root__` misuse, a nonexistent import) instantly.
"""


def test_app_imports_and_boots():
    from app.main import app

    assert app is not None
    assert app.title
