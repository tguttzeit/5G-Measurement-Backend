"""Relative links in the repository's markdown files resolve."""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MARKDOWN_FILES = [
    p
    for p in REPO.rglob("*.md")
    if "node_modules" not in p.parts and ".venv" not in p.parts and ".git" not in p.parts
]
MARKDOWN_LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


@pytest.mark.parametrize("path", MARKDOWN_FILES, ids=lambda p: str(p.relative_to(REPO)))
def test_relative_markdown_links_resolve(path: Path):
    broken = []
    for target in MARKDOWN_LINK.findall(path.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        if not (path.parent / target).resolve().exists():
            broken.append(target)
    assert not broken, f"broken relative links in {path.relative_to(REPO)}: {broken}"
