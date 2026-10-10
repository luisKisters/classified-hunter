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


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network access is forbidden in tests")

    monkeypatch.setattr("urllib.request.urlopen", blocked)
    monkeypatch.setattr("kleinscoutr.fetch.urlopen", blocked)
