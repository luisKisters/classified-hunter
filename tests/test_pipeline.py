import json
from datetime import date

import pytest

from kleinscoutr import pipeline
from kleinscoutr.fetch import FetchError
from kleinscoutr.sources import kleinanzeigen as source
from kleinscoutr.store import Store


class FakeFetch:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def __call__(self, url, ttl_days=7, binary=False):
        self.calls.append((url, ttl_days, binary))
        if url not in self.pages:
            raise AssertionError(f"Unexpected URL: {url}")
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        assert isinstance(value, bytes if binary else str)
        return value


def test_offline_pipeline_and_resume(bike, pages, tmp_path):
    bike["searches"] = [{"kind": "keyword", "q": "road bike"}]
    url = source.search_url(bike, bike["searches"][0])
    nxt = source.parse_list(pages["search"])[1]
    mapping = {
        url: pages["search"],
        nxt: "<html></html>",
        source.detail_url("1001"): pages["detail"],
        source.detail_url("1003"): pages["gone"],
    }
    mapping.update(
        {
            source.image_url(u, bike["image_rule"]): b"fixture image"
            for u in source.gallery_urls(pages["detail"])
        }
    )
    fetch = FakeFetch(mapping)
    store = Store(tmp_path / "runs/bike/bike.db")
    pipeline.run(bike, store, fetch, source)
    assert store.counts() == {
        "new": 0,
        "kept": 0,
        "killed": 1,
        "detailed": 0,
        "scored": 0,
        "verified": 1,
        "gone": 1,
    }
    report = (store.root / "report.md").read_text()
    assert "Rennrad & Zubehör" in report
    assert "two_brakes (beide bremsen)" in report
    assert source.report_link("1001") in report
    assert "1002" not in report
    assert not (store.root / "scored.json").exists()
    manifest = json.loads((store.root / "finalists/manifest.json").read_text())
    assert manifest[0]["status"] == "verified"
    assert len(manifest[0]["local_imgs"]) == 6
    assert (store.root / "finalists/1001/0.jpg").read_bytes() == b"fixture image"
    calls = fetch.calls.copy()
    store.close()
    store = Store(tmp_path / "runs/bike/bike.db")
    pipeline.run(bike, store, fetch, source)
    assert fetch.calls == calls
    assert sum(store.counts().values()) == 3
    store.close()


def candidate(store, aid="1001", title="Rennrad & Zubehör"):
    store.insert({"id": aid, "title": title, "price": "100 €"})
    store.update(aid, status="detailed")


def test_score_twice_then_verify(bike, pages, tmp_path):
    store = Store(tmp_path / "bike.db")
    candidate(store)
    fetch = FakeFetch(
        {
            source.detail_url("1001"): pages["detail"],
            **{
                source.image_url(u, bike["image_rule"]): b"image"
                for u in source.gallery_urls(pages["detail"])
            },
        }
    )
    pipeline.score(bike, store, fetch, source, today=date(2026, 10, 10))
    pipeline.score(bike, store, fetch, source, today=date(2026, 10, 10))
    assert len(store.candidates()) == 1
    pipeline.verify(bike, store, fetch, source)
    assert store.counts()["verified"] == 1
    store.close()


@pytest.mark.parametrize(
    "body,status",
    [
        (FetchError("offline"), "scored"),
        ("<h1>Different page</h1>", "scored"),
        ("<h1>Anzeige nicht mehr verfügbar</h1>", "gone"),
        ("<h1>Rennrad &amp; Zubehör</h1>", "verified"),
    ],
)
def test_verify_states(bike, tmp_path, body, status):
    store = Store(tmp_path / "bike.db")
    candidate(store)
    pipeline.score(bike, store, None, source, today=date(2026, 10, 10))
    fetch = FakeFetch({source.detail_url("1001"): body})
    pipeline.verify(bike, store, fetch, source)
    assert store.rows(status)[0]["id"] == "1001"
    if isinstance(body, FetchError):
        assert "retryable" in (store.root / "progress.log").read_text()
        fetch.pages[source.detail_url("1001")] = "<h1>Rennrad &amp; Zubehör</h1>"
        pipeline.verify(bike, store, fetch, source)
        assert store.counts()["verified"] == 1
    store.close()


def test_verify_empty(bike, tmp_path):
    store = Store(tmp_path / "bike.db")
    assert pipeline.verify(bike, store, FakeFetch({}), source) == []
    assert (store.root / "finalists/manifest.json").read_text().strip() == "[]"
    store.close()


def test_detail_tier_and_retry(bike, pages, tmp_path):
    store = Store(tmp_path / "bike.db")
    store.insert({"id": "1", "title": "Fahrrad", "price": "100 €"})
    fetch = FakeFetch({source.detail_url("1"): FetchError("offline")})
    pipeline.prefilter(bike, store, fetch, source)
    pipeline.details(bike, store, fetch, source)
    assert not fetch.calls
    pipeline.details(bike, store, fetch, source, all_tiers=True)
    assert store.counts()["kept"] == 1
    fetch.pages[source.detail_url("1")] = pages["detail"]
    pipeline.details(bike, store, fetch, source, all_tiers=True)
    assert store.counts()["detailed"] == 1
    store.close()


def test_fresh_list_ttl(bike, pages, tmp_path):
    bike["searches"] = [{"kind": "keyword", "q": "test"}]
    bike["max_pages"] = 1
    url = source.search_url(bike, bike["searches"][0])
    fetch = FakeFetch({url: pages["search"]})
    store = Store(tmp_path / "bike.db")
    pipeline.lists(bike, store, fetch, source)
    pipeline.lists(bike, store, fetch, source, fresh=True)
    assert [call[1] for call in fetch.calls] == [7, 0.05]
    assert sum(store.counts().values()) == 3
    store.close()
