import json
from datetime import date

import pytest

from kleinscoutr.profile import ProfileError, load, validate
from kleinscoutr.rules import score


def minimal():
    return {
        "name": "test",
        "site": "kleinanzeigen",
        "location": "",
        "radius": 20,
        "price": [0, 2000],
        "searches": [{"kind": "keyword", "q": "test"}],
    }


def test_defaults_and_missing_optional_keys():
    p = validate(minimal())
    assert p["max_pages"] == 25
    assert p["image_rule"] == "$_59.JPG"
    assert p["detail_title_patterns"] == p["keep_patterns"] == []
    assert score(p, {"title": "anything"}, date(2026, 10, 10)) == (0, "", None)


@pytest.mark.parametrize("key", ["name", "site", "location", "radius", "price", "searches"])
def test_missing_required(key):
    p = minimal()
    del p[key]
    with pytest.raises(ProfileError, match=key):
        validate(p)


@pytest.mark.parametrize(
    "extra,key",
    [
        ({"keep_patterns": ["["]}, "keep_patterns"),
        ({"kills": [{"id": "test", "field": "title", "patterns": ["["]}]}, "kills"),
        (
            {
                "awards": [
                    {
                        "id": "test",
                        "field": "text",
                        "patterns": ["ok"],
                        "requires_patterns": ["["],
                        "points": 1,
                    }
                ]
            },
            "requires_patterns",
        ),
        ({"size": {"patterns": ["no group"]}}, "size.patterns"),
        ({"defects": {"patterns": [3]}}, "defects.patterns"),
        ({"condition": {"points": "2"}}, "condition.points"),
        ({"seller": []}, "seller"),
        ({"photos": {"threshold": True}}, "photos.threshold"),
        ({"searches": [{"kind": "keyword"}]}, "searches"),
        ({"price": [100, 0]}, "price"),
    ],
)
def test_bad_profile_error(extra, key):
    with pytest.raises(ProfileError, match=key):
        validate({**minimal(), **extra})


def test_local_override(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "profiles").mkdir()
    base = tmp_path / "profiles/test.json"
    base.write_text(json.dumps(minimal()))
    (tmp_path / "profiles/local.json").write_text('{"location": "Musterort"}')
    assert load(base)["location"] == "Musterort"
