#!/usr/bin/env python3
"""bike-hunter: Kleinanzeigen Fahrrad suche, filter, score."""
import html as H
import json
import random
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent
DB = BASE / "hunter.db"
CACHE = BASE / "cache"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

SEARCHES = [
    {"kind": "category", "categoryId": 217, "locationStr": "[REDACTED-LOCATION]", "radius": 20, "minPrice": 80, "maxPrice": 220},
    {"kind": "keyword", "q": "singlespeed", "locationStr": "[REDACTED-LOCATION]", "radius": 20, "minPrice": 80, "maxPrice": 220},
    {"kind": "keyword", "q": "fixie", "locationStr": "[REDACTED-LOCATION]", "radius": 20, "minPrice": 80, "maxPrice": 220},
    {"kind": "keyword", "q": "rennrad", "locationStr": "[REDACTED-LOCATION]", "radius": 20, "minPrice": 80, "maxPrice": 220},
    {"kind": "keyword", "q": "nabenschaltung", "locationStr": "[REDACTED-LOCATION]", "radius": 20, "minPrice": 80, "maxPrice": 220},
]
MAX_PAGES = 25
JITTER = (3.0, 7.0)
HOME_PLZ = ([REDACTED-COORDS])  # [REDACTED-LOCATION] approx

# ---------- http ----------
def get(url: str, ttl_days: float = 7) -> str:
    import hashlib
    CACHE.mkdir(exist_ok=True)
    key = CACHE / (hashlib.md5(url.encode()).hexdigest() + ".html")
    if key.exists() and (time.time() - key.stat().st_mtime) < ttl_days * 86400:
        return key.read_text(encoding="utf-8", errors="replace")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read().decode("utf-8", errors="replace")
            key.write_text(data, encoding="utf-8")
            time.sleep(random.uniform(*JITTER))
            return data
        except Exception as e:
            log(f"retry {attempt+1} {url}: {e}")
            time.sleep(10 + attempt * 15)
    raise RuntimeError(f"failed: {url}")

def log(msg: str):
    (BASE / "progress.log").open("a", encoding="utf-8").write(f"{time.strftime('%H:%M:%S')} {msg}\n")

# ---------- parse ----------
def clean(s: str) -> str:
    return H.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()

def parse_list(html: str) -> tuple[list[dict], str | None]:
    ads = []
    for m in re.finditer(r'<article class="aditem" data-adid="(\d+)"(.*?)</article>', html, re.S):
        b = m.group(2)
        t = re.search(r"<h2[^>]*>(.*?)</h2>", b, re.S)
        p = re.search(r'aditem-main--middle--price-shipping--price[^"]*"[^>]*>(.*?)</', b, re.S)
        loc = re.search(r'aditem-main--top--left[^"]*"[^>]*>(.*?)</div>', b, re.S)
        desc = re.search(r'aditem-main--middle--description[^>]*>(.*?)</p>', b, re.S)
        img = re.search(r'<img[^>]+src="([^"]+)"', b)
        ads.append({
            "id": m.group(1),
            "title": clean(t.group(1)) if t else "",
            "price": clean(p.group(1)) if p else "",
            "location": clean(loc.group(1)) if loc else "",
            "teaser": clean(desc.group(1)) if desc else "",
            "thumb": img.group(1) if img else "",
        })
    nxt = re.search(r'class="pagination-next"[^>]*href="([^"]+)"', html)
    next_url = None
    if nxt and "pagination-next--disabled" not in nxt.group(0):
        next_url = "https://www.kleinanzeigen.de" + nxt.group(1) if nxt.group(1).startswith("/") else nxt.group(1)
    return ads, next_url

def search_url(s: dict, page: int = 1) -> str:
    q = urllib.parse.quote(s.get("q", "")) if s["kind"] == "keyword" else ""
    params = {
        "keywords": q,
        "locationStr": s["locationStr"],
        "radius": s["radius"],
        "minPrice": s["minPrice"],
        "maxPrice": s["maxPrice"],
        "sortingField": "NEWEST_FIRST",
    }
    if s["kind"] == "category":
        params["categoryId"] = s["categoryId"]
    if page > 1:
        params["pageNum"] = str(page)
    return "https://www.kleinanzeigen.de/s-suchanfrage.html?" + urllib.parse.urlencode(params)

# ---------- db ----------
def db() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS ads(
        id TEXT PRIMARY KEY, title TEXT, price TEXT, location TEXT, teaser TEXT, thumb TEXT,
        description TEXT, images INTEGER, seller_id TEXT, seller_since TEXT, seller_badges TEXT,
        seller_ads INTEGER, fetched_detail INTEGER DEFAULT 0, score INTEGER, verdict TEXT, reason TEXT)""")
    return c

# ---------- stages ----------
def stage_lists():
    c = db()
    total = 0
    for s in SEARCHES:
        url = search_url(s)
        page = 1
        while url and page <= MAX_PAGES:
            html = get(url, ttl_days=0.05)
            ads, nxt = parse_list(html)
            for a in ads:
                c.execute("INSERT OR IGNORE INTO ads(id,title,price,location,teaser,thumb) VALUES(?,?,?,?,?,?)",
                          (a["id"], a["title"], a["price"], a["location"], a["teaser"], a["thumb"]))
            c.commit()
            total += len(ads)
            log(f"[{s.get('q') or 'cat217'}] page {page}: +{len(ads)} (total {total})")
            url = nxt
            page += 1
    log(f"LISTS DONE total={total}")

def stage_details(tier1_only: bool = True):
    c = db()
    if tier1_only:
        rows = c.execute("""SELECT id FROM ads WHERE fetched_detail=0 AND (verdict IS NULL OR verdict='')
                            AND (title LIKE '%singlespeed%' COLLATE NOCASE OR title LIKE '%fixie%' COLLATE NOCASE
                              OR title LIKE '%rennrad%' COLLATE NOCASE OR title LIKE '%nabenschaltung%' COLLATE NOCASE
                              OR title LIKE '%cityrad%' COLLATE NOCASE OR title LIKE '%stadtrad%' COLLATE NOCASE)""").fetchall()
    else:
        rows = c.execute("SELECT id FROM ads WHERE fetched_detail=0 AND (verdict IS NULL OR verdict='')").fetchall()
    log(f"DETAILS START tier={'1' if tier1_only else 'all'} n={len(rows)}")
    for i, (aid,) in enumerate(rows, 1):
        try:
            html = get(f"https://www.kleinanzeigen.de/s-anzeige/{aid}")
        except RuntimeError:
            continue
        desc = re.search(r'id="viewad-description-text"[^>]*>(.*?)</div>', html, re.S)
        imgs = len(re.findall(r'galleryimage-element', html))
        sid = re.search(r's-bestandsliste\.html\?userId=(\d+)', html)
        since = re.search(r'Aktiv seit ([0-9.]+)', html)
        badges = "|".join(sorted(set(re.findall(r'(Sehr zuverl[a-z]*|Besonders freundlich|OK Zufriedenheit|Antwortet [a-z]+|Sehr kommunikativ)', html))))
        sad = re.search(r'(\d+) Anzeigen online', html)
        c.execute("""UPDATE ads SET description=?, images=?, seller_id=?, seller_since=?, seller_badges=?,
                     seller_ads=?, fetched_detail=1 WHERE id=?""",
                  (clean(desc.group(1)) if desc else "", imgs, sid.group(1) if sid else "",
                   since.group(1) if since else "", badges, int(sad.group(1)) if sad else None, aid))
        c.commit()
        log(f"detail {i}/{len(rows)} {aid} imgs={imgs} since={since.group(1) if since else '?'} ads={sad.group(1) if sad else '?'}")
    log(f"DETAILS DONE tier={'1' if tier1_only else 'all'}")

# ---------- rules ----------
KILL_TYPE = re.compile(r'\b(mtb|fully|hollandrad|e-?bike|pedelec|kinder(rad|fahrrad)|jugend(rad|fahrrad)|tiefeinsteiger|drei ?rad)\b', re.I)
SIZE_NUM = re.compile(r'(?:rahmen(?:h[öo]he|gr(?:ö|oe)(?:ß|ss)e)?|gr(?:ö|oe)(?:ß|ss)e)\D{0,12}(\d{2})\s*(?:cm)?', re.I)
SIZE_LETTER = re.compile(r'(?:rahmengr(?:ö|oe)(?:ß|ss)e|gr(?:ö|oe)(?:ß|ss)e)\W{0,8}\b(X?S|M|L|XL)\b', re.I)
KEEP_TYPE = re.compile(r'\b(singlespeed|fixie|rennrad|nabenschaltung|cityrad|stadtrad)\b', re.I)
STEEL_RACER = re.compile(r'(stahl.{0,25}rennrad|rennrad.{0,25}stahl|columbus|reynolds)', re.I)
CONDITION = re.compile(r'\b(kette|bremse[n]?|reifen|m[aä]ntel|zahnkranz|felge)\b', re.I)
REASON = re.compile(r'(umzug|brauche das geld|neues (rad|fahrrad)|platz|geerbt|geschenk|nicht mehr|zu gro|zu klein|nur noch)', re.I)
BRANDS = r'(koga|cinelli|fuji|bianchi|peugeot|raleigh|diamant|victoria|nsu|kettler|trek|specialized|cannondale|giant|rose|stevens|velorbis|creme|pegasus|hercules|kalkhoff|winora|batavus|gazelle|mbk|motobecane|faggin|colnago|olmo|atala|bottecchia|guerciotti|puch|torpado|legnano)'
BRAND_RE = re.compile(BRANDS, re.I)
MODEL_RE = re.compile(r'(\b[a-zäöü]+\s?\d{3,4}\b|\bmodell\b|\bmod\.\s*\w+)', re.I)
RECEIPT = re.compile(r'(rechnung|kaufbeleg|gekauft.{0,15}(19|20)\d{2}|kaufjahr|ez.{0,10}(19|20)\d{2})', re.I)
TWO_BRAKES = re.compile(r'(beide bremsen|bremsen.{0,25}(vorne.{0,15}hinten|vorne und hinten)|v-?brake|caliper|rücktritt.{0,30}handbremse|handbremsen)', re.I)
FAST = re.compile(r'(muss schnell weg|dringend|sofort (weg|verkaufen)|nur diese (woche|tage)|bis (morgen|freitag|samstag|sonntag) weg|heute noch weg)', re.I)
FENDERS = re.compile(r'schutzblech', re.I)
HUBGEAR = re.compile(r'nabenschaltung|nabengang|\d+-gang nabe', re.I)
DEFECT = re.compile(r'(platt|riss|rissig|defekt|kaputt|fehlt(?:en)?|nicht verkehrssicher|bastler|restaurationsobjekt|teiletr[aä]ger|unvollst[aä]ndig|wartungsbed[uü]rftig|nicht gepr[uü]ft|l[aä]nger nicht (gefahren|gewartet|bewegt)|m[uü]sste.{0,20}(erneuert|gemacht|durchgesehen)|sollten.{0,30}durchgesehen)', re.I)
DEFECT_KILL = re.compile(r'(nicht verkehrssicher|teiletr[aä]ger|restaurationsobjekt)', re.I)

def parse_size(text: str):
    m = SIZE_NUM.search(text)
    if m:
        n = int(m.group(1))
        if 40 <= n <= 70:
            return ("num", n)
    m = SIZE_LETTER.search(text)
    if m:
        return ("letter", m.group(1).upper())
    return (None, None)

def stage_prefilter():
    c = db()
    for aid, title, teaser, price in c.execute("SELECT id,title,teaser,price FROM ads WHERE verdict IS NULL").fetchall():
        blob = f"{title} {teaser}"
        v = None
        pm = re.search(r'(\d+)', price or "")
        if pm and not (80 <= int(pm.group(1)) <= 220):
            v = "kill_price"
        elif KILL_TYPE.search(blob):
            v = "kill_type"
        elif re.search(r'federgabel', blob, re.I):
            v = "kill_suspension"
        kind, n = parse_size(blob)
        if kind == "num" and n < 57:
            v = "kill_size"
        elif kind == "letter" and n in ("S", "M"):
            v = "kill_size"
        c.execute("UPDATE ads SET verdict=? WHERE id=?", (v or "", aid))
    c.commit()
    left = c.execute("SELECT COUNT(*) FROM ads WHERE verdict IS NULL OR verdict=''").fetchone()[0]
    killed = c.execute("SELECT COUNT(*) FROM ads WHERE verdict LIKE 'kill%'").fetchone()[0]
    log(f"PREFILTER DONE kept={left} killed={killed}")

def stage_score():
    c = db()
    out = []
    for row in c.execute("SELECT id,title,price,location,description,images,seller_since,seller_badges,seller_ads FROM ads WHERE fetched_detail=1 AND (verdict IS NULL OR verdict='')").fetchall():
        aid, title, price, loc, desc, imgs, since, badges, sad = row
        blob = f"{title} {desc}"
        kills = []
        if len(desc) < 150: kills.append("desc<150")
        if (imgs or 0) <= 1: kills.append("fotos<=1")
        kind, n = parse_size(blob)
        if kind == "num" and n < 57: kills.append("groesse<57")
        if kind == "letter" and n in ("S", "M"): kills.append("groesse M/S")
        if KILL_TYPE.search(blob): kills.append("typ")
        if re.search(r'federgabel', blob, re.I): kills.append("federgabel")
        if DEFECT_KILL.search(blob): kills.append("defekt-verkehrssicherheit")
        if kills:
            c.execute("UPDATE ads SET verdict=? WHERE id=?", ("kill_" + kills[0], aid))
            continue
        pts = 0; why = []
        if kind and ((kind == "num" and 58 <= n <= 61) or (kind == "letter" and n in ("L", "XL"))):
            pts += 2; why.append(f"+2 Groesse {n}")
        elif kind:
            why.append(f"+0 Groesse {n} genannt, nicht 58-61/L/XL")
        cond = set(m.group(0).lower() for m in CONDITION.finditer(blob))
        defects = set(m.group(0).lower() for m in DEFECT.finditer(blob))
        if defects:
            pts -= 2 * len(defects); why.append(f"-{2*len(defects)} Maengel ({'/'.join(sorted(defects)[:4])})")
        elif len(cond) >= 2:
            pts += 2; why.append("+2 Zustand (" + "/".join(sorted(cond)[:3]) + ")")
        if REASON.search(blob): pts += 1; why.append("+1 Verkaufsgrund")
        b = BRAND_RE.search(blob)
        if b and MODEL_RE.search(blob): pts += 1; why.append(f"+1 Marke/Modell ({b.group(1)})")
        if (imgs or 0) > 3: pts += 1; why.append(f"+1 Fotos {imgs}")
        if RECEIPT.search(blob): pts += 1; why.append("+1 Kaufbeleg/Jahr")
        is_fixie = bool(re.search(r'singlespeed|fixie', blob, re.I))
        if TWO_BRAKES.search(blob): pts += 1; why.append("+1 zwei Bremsen")
        elif is_fixie: pts -= 1; why.append("-1 Fixie ohne Bremsen-Erwährung")
        if FENDERS.search(blob): pts += 1; why.append("+1 Schutzbleche")
        if sad and sad >= 3: pts -= 3; why.append(f"-3 Verkäufer {sad} Anzeigen online")
        if FAST.search(blob): pts -= 2; why.append("-2 muss schnell weg")
        legit = 0; lwhy = []
        if since:
            d, m_, y = since.split(".")
            age = 2026 - int(y) - (0 if (int(m_), int(d)) <= (8, 26) else 1)
            if age >= 2: legit += 1; lwhy.append(f"+1 Konto {age}J")
        nb = len([x for x in (badges or "").split("|") if x])
        if nb >= 2: legit += 1; lwhy.append(f"+1 {nb} Badges")
        if re.search(r'Sehr zuverl|Besonders freundlich', badges or ""): legit += 1; lwhy.append("+1 Top-Badge")
        if nb == 0 and since and since.endswith("2026"): legit -= 1; lwhy.append("-1 frisches Konto")
        typ = "Singlespeed/Fixie" if is_fixie else ("Rennrad Stahl" if STEEL_RACER.search(blob) else ("City/Nabe" if HUBGEAR.search(blob) or re.search(r'cityrad|stadtrad', blob, re.I) else "?"))
        total = pts + legit
        buy = total >= 7
        c.execute("UPDATE ads SET score=?, reason=?, verdict=? WHERE id=?", (total, "; ".join(why + lwhy), "scored", aid))
        out.append({"id": aid, "title": title, "price": price, "typ": typ,
                    "groesse": str(n) if kind == "num" else (n or "?"), "score": total,
                    "why": "; ".join(why + lwhy), "buy": buy})
    out.sort(key=lambda x: -x["score"])
    (BASE / "scored.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"SCORE DONE {len(out)} candidates, top: {out[0]['score'] if out else '-'}")

if __name__ == "__main__":
    stage = sys.argv[1]
    if stage == "details":
        stage_details(tier1_only=("--all" not in sys.argv))
    else:
        {"lists": stage_lists, "prefilter": stage_prefilter, "score": stage_score}[stage]()
