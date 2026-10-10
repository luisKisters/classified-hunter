import html
import re
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin

BASE = "https://www.kleinanzeigen.de"


def clean(text):
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", text, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def search_url(profile, search, page=1):
    lo, hi = search.get("price", profile["price"])
    params = {
        "keywords": search.get("q", "") if search["kind"] == "keyword" else "",
        "locationStr": profile["location"],
        "radius": profile["radius"],
        "minPrice": lo,
        "maxPrice": hi,
        "sortingField": "NEWEST_FIRST",
    }
    if search["kind"] == "category":
        params["categoryId"] = search["category_id"]
    if page > 1:
        params["pageNum"] = page
    return BASE + "/s-suchanfrage.html?" + urlencode(params)


def detail_url(aid):
    return BASE + "/s-anzeige/" + aid


def report_link(aid):
    return detail_url(aid)


def parse_list(page):
    ads = []
    for m in re.finditer(r"<article\b([^>]*)>(.*?)</article>", page, re.S):
        attrs, body = m.groups()
        aid = re.search(r'data-adid="(\d+)"', attrs)
        if not aid:
            continue
        body = re.sub(r"<(script|svg)\b.*?</\1>", "", body, flags=re.S)

        def field(pattern):
            hit = re.search(pattern, body, re.S)
            return clean(hit.group(1)) if hit else ""

        place = re.search(r"<span>(\d{5}[^<]*)</span>(?:\s*<span[^>]*>([^<]*)</span>)?", body)
        img = re.search(r'<img[^>]+src="([^"]+)"', body)
        ads.append(
            {
                "id": aid.group(1),
                "title": field(r"<h3\b[^>]*>(.*?)</h3>"),
                "price": field(r'<p class="[^"]*\btext-title3\b[^"]*">(.*?)</p>'),
                "location": clean(" ".join(g for g in place.groups() if g)) if place else "",
                "teaser": field(r'<p class="[^"]*\btext-bodyRegular\b[^"]*">(.*?)</p>'),
                "thumb": html.unescape(img.group(1)) if img else "",
            }
        )
    nxt = re.search(r'<a\b[^>]*aria-label="Nächste"[^>]*>', page)
    href = re.search(r'href="([^"]+)"', nxt.group(0)) if nxt else None
    return ads, urljoin(BASE, html.unescape(href.group(1))) if href else None


def gallery_urls(page):
    class Gallery(HTMLParser):
        def __init__(self):
            super().__init__()
            self.divs = []
            self.urls = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "div":
                self.divs.append("galleryimage-element" in attrs.get("class", "").split())
            if tag == "img" and any(self.divs) and attrs.get("src"):
                url = attrs["src"]
                if url not in self.urls:
                    self.urls.append(url)

        def handle_endtag(self, tag):
            if tag == "div" and self.divs:
                self.divs.pop()

    parser = Gallery()
    parser.feed(page)
    return parser.urls


def parse_detail(page):
    desc = re.search(r'<(p|div)[^>]*id="viewad-description-text"[^>]*>(.*?)</\1>', page, re.S)
    text = clean(page)
    sid = re.search(r'userId=([^&"\s<>]+)', html.unescape(page))
    since = re.search(r"Aktiv seit ([0-9.]+)", text)
    ads = re.search(r"\b(\d+(?:\.\d{3})*) Anzeigen? online", text)
    badges = re.findall(
        r"Sehr zuverl\w*|Besonders freundlich|OK Zufriedenheit|Antwortet \w+|Sehr kommunikativ",
        text,
    )
    return {
        "description": clean(desc.group(2)) if desc else "",
        "images": len(re.findall(r"galleryimage-element", page)),
        "seller_id": sid.group(1) if sid else "",
        "seller_since": since.group(1) if since else "",
        "seller_badges": "|".join(sorted(set(badges))),
        "seller_ads": int(ads.group(1).replace(".", "")) if ads else None,
    }


def is_gone(page):
    if re.search(r'id=["\']viewad-description-text["\']', page):
        return False
    text = clean(page)
    return bool(
        re.search(r"nicht mehr verf[üu]gbar|gel[öo]scht|existiert nicht|nicht gefunden", text, re.I)
    )


def title_matches(page, title):
    return clean(title)[:20].casefold() in clean(page).casefold()


def image_url(url, rule):
    return url.split("?")[0] + "?rule=" + rule
