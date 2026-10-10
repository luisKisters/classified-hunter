from pathlib import Path

import pytest

from kleinscoutr.profile import load

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bike():
    return load(ROOT / "profiles/bike.json", local_path=ROOT / "tests/no-local.json")


@pytest.fixture
def pages():
    root = ROOT / "tests/fixtures/kleinanzeigen"
    return {name: (root / f"{name}.html").read_text() for name in ("search", "detail", "gone")}
