from urllib.parse import parse_qs, urlsplit

import pytest

from kleinscoutr.sources import kleinanzeigen as source


def test_parse_list(pages):
    ads, next_url = source.parse_list(pages["search"])
    assert len(ads) == 3
    assert ads[0] == {
        "id": "1001",
        "title": "Rennrad & Zubehör",
        "price": "100 €",
        "location": "10999 Musterort (3 km)",
        "teaser": "Neutraler Artikeltext.",
        "thumb": "https://images.example.test/thumb.jpg?rule=$_2.AUTO",
    }
    assert ads[1]["price"] == "1.200 €"
    assert next_url == source.BASE + "/s-10997/preis:80:400/seite:2/road-bike/k0l3401r20?a=1&b=2"
    assert source.parse_list(pages["search"].replace('aria-label="Nächste"', ""))[1] is None


def test_parse_detail(pages):
    ad = source.parse_detail(pages["detail"])
    assert ad == {
        "description": "RH 58 Kette Reifen Umzug Fuji Modell Rechnung beide bremsen Schutzblech",
        "images": 8,
        "seller_id": "seller-placeholder",
        "seller_since": "01.01.2020",
        "seller_badges": "Besonders freundlich|Sehr zuverlässig",
        "seller_ads": 2,
    }
    urls = source.gallery_urls(pages["detail"])
    assert len(urls) == 6
    assert urls[0] == "https://images.example.test/photo-0.jpg?rule=old"
    assert source.title_matches(pages["detail"], "Rennrad & Zubehör")
    assert source.is_gone(pages["gone"])
    assert not source.is_gone(pages["detail"])


@pytest.mark.parametrize(
    "text,expected",
    [("1 Anzeige online", 1), ("1.200 Anzeigen online", 1200), ("12 Anzeigen online", 12)],
)
def test_seller_ads(text, expected):
    assert source.parse_detail(f"<a>{text}</a>")["seller_ads"] == expected


def test_search_encoding(bike):
    url = source.search_url(bike, {"kind": "keyword", "q": "road bike & Zubehör"}, page=2)
    assert "keywords=road+bike+%26+Zubeh%C3%B6r" in url
    assert "%25" not in url
    assert parse_qs(urlsplit(url).query)["keywords"] == ["road bike & Zubehör"]
    assert parse_qs(urlsplit(url).query)["pageNum"] == ["2"]
    category = source.search_url(bike, {"kind": "category", "category_id": 217})
    assert parse_qs(urlsplit(category).query)["categoryId"] == ["217"]
    narrow = parse_qs(
        urlsplit(source.search_url(bike, {**bike["searches"][0], "price": [80, 150]})).query
    )
    assert (narrow["minPrice"], narrow["maxPrice"]) == (["80"], ["150"])


def test_deleted_words_in_description_are_not_deleted(pages):
    page = pages["detail"].replace("RH 58", "Nicht mehr verfügbar bei anderen Verkäufern. RH 58")
    assert not source.is_gone(page)
    assert not source.is_gone("<script>gelöscht</script><h1>Rennrad</h1>")
    assert not source.title_matches(
        "<script>Rennrad &amp; Zubehör</script><h1>Login</h1>", "Rennrad & Zubehör"
    )
