import json
from datetime import date

from . import rules
from .fetch import FRESH_TTL_DAYS, FetchError
from .sources import kleinanzeigen


def source_for(profile):
    if profile["site"] == "kleinanzeigen":
        return kleinanzeigen
    raise ValueError(f"unsupported site: {profile['site']}")


def lists(profile, store, fetch, source, fresh=False):
    ttl = FRESH_TTL_DAYS if fresh else 7
    for search in profile["searches"]:
        url = source.search_url(profile, search)
        seen = set()
        for page in range(1, profile.get("max_pages", 25) + 1):
            if not url or url in seen:
                break
            seen.add(url)
            ads, nxt = source.parse_list(fetch(url, ttl_days=ttl))
            for ad in ads:
                store.insert(ad)
            store.log(f"lists page {page}: {len(ads)} ads")
            url = nxt


def prefilter(profile, store, fetch, source):
    for ad in store.rows("new"):
        text = f"{ad['title']} {ad['teaser']}"
        killed = rules.evaluate_kills(profile, ad, text)
        store.update(ad["id"], status="killed" if killed else "kept", kill_reason=killed)


def details(profile, store, fetch, source, all_tiers=False):
    for ad in store.rows("kept"):
        patterns = profile.get("detail_title_patterns", [])
        if not all_tiers and patterns and not rules.matches(patterns, ad["title"]):
            continue
        try:
            body = fetch(source.detail_url(ad["id"]))
        except FetchError as e:
            store.log(f"detail {ad['id']}: fetch failed: {e}")
            continue
        if source.is_gone(body):
            store.update(ad["id"], status="gone")
        else:
            store.update(ad["id"], **source.parse_detail(body), status="detailed")


def score(profile, store, fetch, source, today=None):
    today = today if today is not None else date.today()
    for ad in store.rows("detailed"):
        points, reason, killed = rules.score(profile, ad, today)
        store.update(
            ad["id"],
            score=points,
            reason=reason,
            kill_reason=killed,
            status="killed" if killed else "scored",
        )


def verify(profile, store, fetch, source, top=None):
    root = store.root / "finalists"
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    manifest = {item["id"]: item for item in previous}
    limit = profile.get("verify_top", 20) if top is None else top
    for ad in store.candidates(limit):
        aid = ad["id"]
        if ad["status"] == "verified":
            continue
        try:
            body = fetch(source.detail_url(aid), ttl_days=0)
        except FetchError as e:
            store.log(f"verify {aid}: fetch failed (retryable): {e}")
            continue
        if source.is_gone(body):
            store.update(aid, status="gone")
            manifest[aid] = {**ad, "status": "gone", "online": False, "local_imgs": []}
            continue
        if not source.title_matches(body, ad["title"]):
            store.log(f"verify {aid}: title mismatch (retryable)")
            continue
        folder = root / aid
        folder.mkdir(exist_ok=True)
        files = []
        for i, url in enumerate(source.gallery_urls(body)[:6]):
            try:
                data = fetch(
                    source.image_url(url, profile.get("image_rule", "$_59.JPG")), binary=True
                )
                (folder / f"{i}.jpg").write_bytes(data)
                files.append(f"{aid}/{i}.jpg")
            except FetchError as e:
                store.log(f"img fail {aid} {i}: {e}")
        store.update(aid, status="verified")
        manifest[aid] = {**ad, "status": "verified", "online": True, "local_imgs": files}
        store.log(f"verify {aid}: online, {len(files)} images")
    manifest_path.write_text(
        json.dumps(list(manifest.values()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return list(manifest.values())


def report(profile, store, fetch, source, top=None):
    rows = store.candidates()
    limit = profile.get("report_top", 20) if top is None else top
    lines = [
        f"# kleinscoutr report — {profile['name']}",
        "",
        f"{len(rows)} candidates, showing top {min(limit, len(rows))}. Sorted by score, then price.",
        "",
        "| # | Titel | Preis | Ort | Score | Begründung | Link |",
        "|---|---|---|---|---|---|---|",
    ]

    def cell(value):
        return str(value or "").replace("|", "/").replace("\n", " ")

    for i, ad in enumerate(rows[:limit], 1):
        values = [
            i,
            ad["title"][:60],
            ad["price"],
            ad["location"][:30],
            str(ad["score"]),
            ad["reason"],
            source.report_link(ad["id"]),
        ]
        lines.append("| " + " | ".join(cell(v) for v in values) + " |")
    lines += [
        "",
        "Manual verification of descriptions and images is required before acting.",
        "See finalists/ for images and verified online status.",
    ]
    (store.root / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    store.log(f"report: {len(rows)} candidates")


def run(profile, store, fetch, source, fresh=False, all_tiers=False, top=None):
    lists(profile, store, fetch, source, fresh=fresh)
    prefilter(profile, store, fetch, source)
    details(profile, store, fetch, source, all_tiers=all_tiers)
    score(profile, store, fetch, source)
    verify(profile, store, fetch, source, top=top)
    report(profile, store, fetch, source)
