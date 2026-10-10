from datetime import date

import pytest

from kleinscoutr import rules

TODAY = date(2026, 10, 10)


@pytest.mark.parametrize(
    "description,fields,expected,killed",
    [
        ("", {}, 0, None),
        *[(text, {}, 2, None) for text in ("RH 58", "RH 61", "Rahmen L", "Rahmen XL")],
        *[(text, {}, None, "size") for text in ("RH 57", "RH 62")],
        ("Kette Reifen", {}, 2, None),
        ("platt platt Kette Reifen", {}, -2, None),
        ("platt kaputt locker", {}, -4, None),
        ("Fuji", {}, 0, None),
        ("Fuji Modell", {}, 1, None),
        *[(text, {}, 1, None) for text in ("Umzug", "Rechnung", "beide bremsen", "Schutzblech")],
        ("dringend", {}, -2, None),
        ("nicht verkehrssicher", {}, None, "defekt-sicherheit"),
        ("", {"title": "Helm"}, None, "notitem"),
        ("", {"title": "Fahrrad"}, None, "keep"),
        ("", {"images": 3}, 0, None),
        ("", {"images": 4}, 1, None),
        ("", {"seller_ads": 2}, 0, None),
        ("", {"seller_ads": 3}, -3, None),
        ("", {"seller_since": "01.01.2020"}, 1, None),
        ("", {"seller_since": "01.01.2026"}, -1, None),
        ("", {"seller_badges": "Sehr zuverl|Besonders freundlich"}, 2, None),
        (
            "RH 58 Kette Reifen Umzug Fuji Modell Rechnung beide bremsen Schutzblech",
            {
                "images": 4,
                "seller_since": "01.01.2020",
                "seller_badges": "Sehr zuverl|Besonders freundlich",
            },
            13,
            None,
        ),
    ],
)
def test_original_scoring_table(bike, description, fields, expected, killed):
    ad = {"title": "Rennrad", "description": description, "price": "100 €", **fields}
    points, _, reason = rules.score(bike, ad, TODAY)
    assert (points, reason) == (expected, killed)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1.200 €", 1200),
        ("100 € VB", 100),
        ("12.345,00 €", 12345),
        ("VB", None),
        ("Zu verschenken", None),
        ("", None),
    ],
)
def test_price(text, expected):
    assert rules.parse_price(text) == expected


def test_shared_kills_and_score_only_keep(bike):
    for text, reason in [
        ("nicht verkehrssicher", "defekt-sicherheit"),
        ("federgabel", "bodyguard"),
    ]:
        ad = {"title": "Rennrad", "teaser": text, "description": text, "price": "100 €"}
        assert rules.evaluate_kills(bike, ad, f"{ad['title']} {ad['teaser']}") == reason
        assert rules.score(bike, ad, TODAY)[2] == reason
    # Safety defects now kill during prefilter; bodyguard now also kills during score.
    ad = {"title": "Fahrrad", "price": "100 €"}
    assert rules.evaluate_kills(bike, ad, "Fahrrad") is None
    assert rules.score(bike, ad, TODAY)[2] == "keep"
    # Prices are checked again after details, using the same rules.
    assert rules.score(bike, {"title": "Rennrad", "price": "1.200 €"}, TODAY)[2] == "price"


def test_size_range_is_profile_data(bike):
    assert rules.extract_size("RH 39", bike["size"]) == (None, None)
    cfg = {**bike["size"], "recognition_range": [30, 80]}
    assert rules.extract_size("RH 39", cfg) == ("num", 39)


@pytest.mark.parametrize("since", ["99.99.2020", "99.99.2026", "29.02.2025"])
def test_invalid_seller_date(bike, since):
    assert rules.score(bike, {"title": "Rennrad", "seller_since": since}, TODAY)[0] == 0


def test_generic_award_reasons(bike):
    points, reason, _ = rules.score(
        bike, {"title": "Rennrad", "description": "Fuji Modell beide bremsen"}, TODAY
    )
    assert points == 2
    assert "+1 brand (Fuji)" in reason
    assert "+1 two_brakes (beide bremsen)" in reason


def test_optional_size_capture():
    assert rules.extract_size("RH", {"patterns": [r"RH(?: (\d{2}))?"]}) == (None, None)
