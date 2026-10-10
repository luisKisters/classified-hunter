import re
from datetime import date


def matches(patterns, text):
    return next((m for p in patterns for m in [re.search(p, text, re.I)] if m), None)


def distinct(patterns, text):
    return sorted({m.group(0).lower() for p in patterns for m in re.finditer(p, text, re.I)})


def parse_price(text):
    if not text or re.search(r"zu verschenken|^\s*VB\s*$", text, re.I):
        return None
    m = re.search(r"\d+(?:\.\d{3})*(?:,\d{2})?", text)
    return int(m.group(0).replace(".", "").split(",")[0]) if m else None


def extract_size(text, cfg):
    for p in cfg.get("patterns", []):
        m = re.search(p, text, re.I)
        if not m:
            continue
        value = m.group(1)
        if value.isdigit():
            n = int(value)
            lo, hi = cfg.get("recognition_range", [40, 80])
            if lo <= n <= hi:
                return "num", n
        elif value:
            return "label", value.upper()
    return None, None


def evaluate_kills(profile, ad, text):
    price = parse_price(ad.get("price", ""))
    lo, hi = profile["price"]
    if price is not None and not lo <= price <= hi:
        return "price"
    for rule in profile.get("kills", []):
        if matches(rule["patterns"], ad.get("title", "") if rule["field"] == "title" else text):
            return rule["id"]
    cfg = profile.get("size", {})
    kind, size = extract_size(text, cfg)
    if kind == "num" and not cfg.get("min", 0) <= size <= cfg.get("max", 999):
        return "size"
    if kind == "label" and size in cfg.get("labels_kill", []):
        return "size"
    return None


def score(profile, ad, today: date):
    text = f"{ad.get('title', '')} {ad.get('description', '')}"
    killed = evaluate_kills(profile, ad, text)
    if killed:
        return None, "", killed
    if profile.get("keep_patterns") and not matches(profile["keep_patterns"], text):
        return None, "", "keep"
    points, reasons = 0, []

    def add(n, reason):
        nonlocal points
        points += n
        reasons.append(f"{n:+d} {reason}")

    cfg = profile.get("size", {})
    kind, size = extract_size(text, cfg)
    if kind == "label" and size not in cfg.get("labels", []):
        return None, "", "size"
    if kind and "points" in cfg:
        add(cfg["points"], f"size {size}")
    cfg = profile.get("defects", {})
    defects = distinct(cfg.get("patterns", []), text)
    if defects:
        penalty = min(cfg.get("penalty_per_distinct", 0) * len(defects), cfg.get("penalty_cap", 0))
        add(-penalty, f"defects ({'/'.join(defects[:4])})")
    else:
        cfg = profile.get("condition", {})
        found = distinct(cfg.get("patterns", []), text)
        if found and len(found) >= cfg.get("min_distinct", 2):
            add(cfg.get("points", 0), f"condition ({'/'.join(found[:3])})")
    for award in profile.get("awards", []):
        target = (ad.get("seller_badges") or "") if award["field"] == "seller_badges" else text
        hit = matches(award["patterns"], target)
        required = award.get("requires_patterns", [])
        if hit and (not required or matches(required, target)):
            add(award["points"], f"{award['id']} ({hit.group(0)})")
    cfg = profile.get("photos", {})
    photos = ad.get("images") or 0
    if cfg and photos > cfg.get("threshold", 3):
        add(cfg.get("points", 0), f"photos {photos}")
    cfg = profile.get("seller", {})
    ads = ad.get("seller_ads")
    if "ads_threshold" in cfg and ads is not None and ads >= cfg["ads_threshold"]:
        add(-cfg.get("ads_penalty", 0), f"seller {ads} ads")
    since = None
    try:
        d, m, y = map(int, (ad.get("seller_since") or "").split("."))
        since = date(y, m, d)
    except ValueError:
        pass
    badges = len([x for x in (ad.get("seller_badges") or "").split("|") if x])
    if since and since <= today:
        age = today.year - since.year - ((today.month, today.day) < (since.month, since.day))
        if "min_age_years" in cfg and age >= cfg["min_age_years"]:
            add(cfg.get("age_points", 0), f"account {age}Y")
        if badges == 0 and since.year == today.year and "fresh_account_penalty" in cfg:
            add(-cfg["fresh_account_penalty"], "fresh account")
    if "min_badges" in cfg and badges >= cfg["min_badges"]:
        add(cfg.get("badges_points", 0), f"{badges} badges")
    return points, "; ".join(reasons), None
