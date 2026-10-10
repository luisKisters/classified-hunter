import sqlite3

import pytest

from kleinscoutr.store import STATUSES, Store


def test_status_transitions_and_persistence(tmp_path):
    path = tmp_path / "run/bike.db"
    store = Store(path)
    store.insert({"id": "1", "title": "Rennrad", "price": "1.200 €"})
    store.insert({"id": "1", "title": "Duplicate"})
    assert store.counts() == {s: int(s == "new") for s in STATUSES}
    assert store.rows("new")[0]["price_eur"] == 1200
    for status in ("kept", "detailed", "scored", "verified", "gone"):
        store.update("1", status=status)
        assert store.rows(status)[0]["id"] == "1"
    store.insert({"id": "2"})
    store.update("2", status="killed", kill_reason="size")
    assert store.rows("killed")[0]["kill_reason"] == "size"
    with pytest.raises(sqlite3.IntegrityError):
        store.update("1", status="invalid")
    store.close()
    store = Store(path)
    assert store.counts()["gone"] == store.counts()["killed"] == 1
    store.close()


def test_numeric_price_order(tmp_path):
    store = Store(tmp_path / "test.db")
    for aid, price, score in [
        ("1", "100 €", 1),
        ("2", "90 €", 1),
        ("3", "1.200 €", 1),
        ("4", "200 €", 2),
    ]:
        store.insert({"id": aid, "price": price})
        store.update(aid, status="scored", score=score)
    assert [ad["id"] for ad in store.candidates()] == ["4", "2", "1", "3"]
    store.close()
