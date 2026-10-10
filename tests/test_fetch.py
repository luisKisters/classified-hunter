import io
import os
from urllib.error import HTTPError, URLError

import pytest

from kleinscoutr import fetch as module
from kleinscoutr.fetch import Fetch, FetchError


class Response(io.BytesIO):
    pass


def test_cache_text_binary_and_ttl(tmp_path, monkeypatch):
    calls, sleeps = [], []

    def get(req, timeout):
        calls.append((req.full_url, timeout))
        return Response(b"Rennrad &amp; Zubeh\xc3\xb6r")

    monkeypatch.setattr(module, "urlopen", get)
    monkeypatch.setattr(module.time, "sleep", sleeps.append)
    fetch = Fetch(tmp_path / "cache", lambda msg: None, jitter=(0, 0))
    assert fetch("https://example.test/ad") == "Rennrad &amp; Zubehör"
    assert fetch("https://example.test/ad", binary=True) == b"Rennrad &amp; Zubeh\xc3\xb6r"
    assert len(calls) == 1
    fetch("https://example.test/ad", ttl_days=0)
    assert len(calls) == 2
    path = next((tmp_path / "cache").iterdir())
    os.utime(path, (0, 0))
    fetch("https://example.test/ad")
    assert len(calls) == 3
    assert sleeps == [0, 0, 0]


def test_retry_failure(tmp_path, monkeypatch):
    logs, sleeps = [], []

    def fail(req, timeout):
        raise URLError("offline")

    monkeypatch.setattr(module, "urlopen", fail)
    monkeypatch.setattr(module.time, "sleep", sleeps.append)
    fetch = Fetch(tmp_path / "cache", logs.append)
    with pytest.raises(FetchError, match="failed"):
        fetch("https://example.test/ad")
    assert len(logs) == 3
    assert sleeps == [10, 25]
    assert not list((tmp_path / "cache").iterdir())


def test_deleted_http_body(tmp_path, monkeypatch):
    def gone(req, timeout):
        raise HTTPError(req.full_url, 404, "gone", {}, io.BytesIO(b"Anzeige nicht mehr verfuegbar"))

    monkeypatch.setattr(module, "urlopen", gone)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    fetch = Fetch(tmp_path / "cache", lambda _: None)
    assert "Anzeige" in fetch("https://example.test/ad")
