#!/usr/bin/env python3
"""classified-hunter: config-driven listing hunt pipeline. Empirically validated against Kleinanzeigen (German classifieds). Stages: lists, prefilter, details, score, verify, report."""
import argparse
import hashlib
import html as H
import json
import random
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

BASE = Path(__file__).parent
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
JITTER = (3.0, 7.0)
FRESH_TTL_DAYS = 0.05
DELETED_RE = re.compile(r"nicht mehr verf[üu]gbar|gel[öo]scht|existiert nicht|nicht gefunden", re.I)


def clean(s: str) -> str:
    return H.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


def compile_cfg(v):
    return re.compile(v, re.I) if isinstance(v, str) else v


class Hunter:
    def __init__(self, profile: dict):
        self.p = profile
        self.name = profile["name"]
        self.db_path = BASE / f"{self.name}.db"
        self.cache = BASE / "cache"
        self.finalists = BASE / "finalists"
        self.rk = {k: compile_cfg(v) for k, v in {
            "title_keep": profile.get("title_keep", ""),
            "title_exclude": profile.get("title_exclude", ""),
            "type_kill": profile.get("type_kill", ""),
            "defect_kill": profile.get("defect_kill", ""),
            "defects": profile.get("defects", ""),
            "bodyguard": profile.get("bodyguard", ""),
        }.items() if v}
        s = profile["scoring"]
        self.sk = {k: compile_cfg(v) for k, v in {
            "condition_keywords": s.get("condition_keywords", ""),
            "reason_keywords": s.get("reason_keywords", ""),
            "brands": s.get("brands", ""),
            "model_pattern": s.get("model_pattern", ""),
            "receipt_pattern": s.get("receipt_pattern", ""),
            "two_brakes_pattern": s.get("two_brakes_pattern", ""),
            "accessories_pattern": s.get("accessories_pattern", ""),
            "fast_pattern": s.get("fast_pattern", ""),
            "seller_topbadge_pattern": s.get("seller_topbadge_pattern", ""),
        }.items() if v}
        self.size_patterns = [re.compile(x, re.I) for x in profile.get("size", {}).get("patterns", [])]

    def db(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.execute("""CREATE TABLE IF NOT EXISTS ads(
            id TEXT PRIMARY KEY, title TEXT, price TEXT, location TEXT, teaser TEXT, thumb TEXT,
            description TEXT, images INTEGER, seller_id TEXT, seller_since TEXT, seller_badges TEXT,
            seller_ads INTEGER, fetched_detail INTEGER DEFAULT 0, verdict TEXT, score INTEGER, reason TEXT)""")
        return c

    def get(self, url: str, ttl_days: float = 7) -> str:
        self.cache.mkdir(exist_ok=True)
        key = self.cache / (hashlib.md5(url.encode()).hexdigest() + ".html")
        if key.exists() and ttl_days > 0 and (time.time() - key.stat().st_mtime) < ttl_days * 86400:
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
                self.log(f"retry {attempt+1} {url}: {e}")
                time.sleep(10 + attempt * 15)
        raise RuntimeError(f"failed: {url}")

    def log(self, msg: str):
        (BASE / "progress.log").open("a", encoding="utf-8").write(f"{time.strftime('%H:%M:%S')} [{self.name}] {msg}\n")

    def search_url(self, s: dict, page: int = 1) -> str:
        q = urllib.parse.quote(s.get("q", "")) if s["kind"] == "keyword" else ""
        params = {
            "keywords": q,
            "locationStr": self.p["location"],
            "radius": self.p["radius"],
            "minPrice": self.p["price"][0],
            "maxPrice": self.p["price"][1],
            "sortingField": "NEWEST_FIRST",
        }
        if s["kind"] == "category":
            params["categoryId"] = s["category_id"]
        if page > 1:
            params["pageNum"] = str(page)
        return "https://www.kleinanzeigen.de/s-suchanfrage.html?" + urllib.parse.urlencode(params)

    def detail_url(self, aid: str) -> str:
        return f"https://www.kleinanzeigen.de/s-anzeige/{aid}"

    def parse_list(self, html: str):
        ads = []
        for m in re.finditer(r'<article class="aditem" data-adid="(\d+)"(.*?)</article>', html, re.S):
            b = m.group(2)
            t = re.search(r"<h2[^>]*>(.*?)</h2>", b, re.S)
            p_ = re.search(r'aditem-main--middle--price-shipping--price[^"]*"[^>]*>(.*?)</', b, re.S)
            loc = re.search(r'aditem-main--top--left[^"]*"[^>]*>(.*?)</div>', b, re.S)
            desc = re.search(r'aditem-main--middle--description[^>]*>(.*?)</p>', b, re.S)
            img = re.search(r'<img[^>]+src="([^"]+)"', b)
            ads.append({
                "id": m.group(1),
                "title": clean(t.group(1)) if t else "",
                "price": clean(p_.group(1)) if p_ else "",
                "location": clean(loc.group(1)) if loc else "",
                "teaser": clean(desc.group(1)) if desc else "",
                "thumb": img.group(1) if img else "",
            })
        nxt = re.search(r'class="pagination-next"[^>]*href="([^"]+)"', html)
        next_url = None
        if nxt and "pagination-next--disabled" not in nxt.group(0):
            next_url = "https://www.kleinanzeigen.de" + nxt.group(1) if nxt.group(1).startswith("/") else nxt.group(1)
        return ads, next_url

    def parse_detail(self, html: str) -> dict:
        desc = re.search(r'id="viewad-description-text"[^>]*>(.*?)</div>', html, re.S)
        imgs = len(re.findall(r"galleryimage-element", html))
        sid = re.search(r"s-bestandsliste\.html\?userId=(\d+)", html)
        since = re.search(r"Aktiv seit ([0-9.]+)", html)
        badges = "|".join(sorted(set(re.findall(r"(Sehr zuverl[a-z]*|Besonders freundlich|OK Zufriedenheit|Antwortet [a-z]+|Sehr kommunikativ)", html))))
        sad = re.search(r"(\d+) Anzeigen online", html)
        return {
            "description": clean(desc.group(1)) if desc else "",
            "images": imgs,
            "seller_id": sid.group(1) if sid else "",
            "seller_since": since.group(1) if since else "",
            "seller_badges": badges,
            "seller_ads": int(sad.group(1)) if sad else None,
        }

    def stage_lists(self, fresh: bool = False):
        c = self.db()
        total = 0
        for s in self.p["searches"]:
            url = self.search_url(s)
            page = 1
            while url and page <= self.p.get("max_pages", 25):
                html = self.get(url, ttl_days=FRESH_TTL_DAYS if fresh else 7)
                ads, nxt = self.parse_list(html)
                for a in ads:
                    c.execute("INSERT OR IGNORE INTO ads(id,title,price,location,teaser,thumb) VALUES(?,?,?,?,?,?)",
                              (a["id"], a["title"], a["price"], a["location"], a["teaser"], a["thumb"]))
                c.commit()
                total += len(ads)
                self.log(f"[{s.get('q') or s.get('category_id')}] page {page}: +{len(ads)} (total {total})")
                url = nxt
                page += 1
        self.log(f"LISTS DONE total={total}")

    def extract_size(self, text: str):
        cfg = self.p.get("size", {})
        for pat in self.size_patterns:
            m = pat.search(text)
            if not m:
                continue
            g = m.group(1)
            if g and g.isdigit():
                n = int(g)
                if 40 <= n <= 80:
                    return ("num", n)
            elif g:
                return ("label", g.upper())
        return (None, None)

    def size_ok(self, kind, n) -> bool:
        cfg = self.p.get("size", {})
        if kind == "num":
            return cfg.get("min", 0) <= n <= cfg.get("max", 999)
        if kind == "label":
            return n in cfg.get("labels", [])
        return True

    def stage_prefilter(self):
        c = self.db()
        lo, hi = self.p["price"]
        for aid, title, teaser, price in c.execute("SELECT id,title,teaser,price FROM ads WHERE verdict IS NULL").fetchall():
            blob = f"{title} {teaser}"
            v = None
            pm = re.search(r"(\d+)", price or "")
            if pm and not (lo <= int(pm.group(1)) <= hi):
                v = "kill_price"
            elif self.rk["title_exclude"].search(title or ""):
                v = "kill_notitem"
            elif self.rk["type_kill"].search(blob):
                v = "kill_type"
            elif self.rk["bodyguard"].search(blob):
                v = "kill_bodyguard"
            kind, n = self.extract_size(blob)
            if kind == "num" and not self.size_ok(kind, n):
                v = v or "kill_size"
            elif kind == "label" and n in self.p.get("size", {}).get("labels_kill", []):
                v = v or "kill_size"
            c.execute("UPDATE ads SET verdict=? WHERE id=?", (v or "", aid))
        c.commit()
        left = c.execute("SELECT COUNT(*) FROM ads WHERE verdict IS NULL OR verdict=''").fetchone()[0]
        killed = c.execute("SELECT COUNT(*) FROM ads WHERE verdict LIKE 'kill%'").fetchone()[0]
        self.log(f"PREFILTER DONE kept={left} killed={killed}")

    def stage_details(self, all_tiers: bool = False):
        c = self.db()
        base = c.execute("SELECT id, title FROM ads WHERE fetched_detail=0 AND (verdict IS NULL OR verdict='')").fetchall()
        if all_tiers or not self.rk.get("title_keep"):
            rows = [(r[0],) for r in base]
        else:
            rows = [(r[0],) for r in base if self.rk["title_keep"].search(r[1] or "")]
        self.log(f"DETAILS START tier={'all' if all_tiers else '1'} n={len(rows)}")
        for i, (aid,) in enumerate(rows, 1):
            try:
                html = self.get(self.detail_url(aid))
            except RuntimeError:
                continue
            d = self.parse_detail(html)
            c.execute("""UPDATE ads SET description=?, images=?, seller_id=?, seller_since=?, seller_badges=?,
                         seller_ads=?, fetched_detail=1 WHERE id=?""",
                      (d["description"], d["images"], d["seller_id"], d["seller_since"],
                       d["seller_badges"], d["seller_ads"], aid))
            c.commit()
            self.log(f"detail {i}/{len(rows)} {aid} imgs={d['images']} since={d['seller_since'] or '?'} ads={d['seller_ads'] if d['seller_ads'] is not None else '?'}")
        self.log(f"DETAILS DONE tier={'all' if all_tiers else '1'}")

    def seller_age_years(self, since: str):
        try:
            d, m, y = map(int, since.split("."))
            today = date.today()
            return today.year - y - (0 if (m, d) <= (today.month, today.day) else 1)
        except Exception:
            return None

    def stage_score(self):
        c = self.db()
        s = self.p["scoring"]
        out = []
        for row in c.execute("""SELECT id,title,price,location,description,images,seller_since,seller_badges,seller_ads
                                FROM ads WHERE fetched_detail=1 AND (verdict IS NULL OR verdict='')""").fetchall():
            aid, title, price, loc, desc, imgs, since, badges, sad = row
            blob = f"{title} {desc}"
            kills = []
            if self.rk["type_kill"].search(blob):
                kills.append("typ")
            if self.rk["title_exclude"].search(title or ""):
                kills.append("notitem")
            if self.rk.get("title_keep") and not self.rk["title_keep"].search(blob):
                kills.append("keep")
            if self.rk["defect_kill"].search(blob):
                kills.append("defekt-sicherheit")
            kind, n = self.extract_size(blob)
            if kind and not self.size_ok(kind, n):
                kills.append(f"size {n}")
            if kills:
                c.execute("UPDATE ads SET verdict=? WHERE id=?", ("kill_" + kills[0], aid))
                continue
            pts, why = 0, []
            if kind and self.size_ok(kind, n):
                pts += s.get("size_match", 2)
                why.append(f"+{s.get('size_match', 2)} Groesse {n}")
            defects = sorted({m.group(0).lower() for m in self.rk["defects"].finditer(blob)}) if self.rk.get("defects") else []
            if defects:
                pen = min(s.get("defect_penalty", 2) * len(defects), s.get("defect_cap", 4))
                pts -= pen
                why.append(f"-{pen} Maengel ({'/'.join(defects[:4])})")
            elif self.sk.get("condition_keywords"):
                cond = {m.group(0).lower() for m in self.sk["condition_keywords"].finditer(blob)}
                if len(cond) >= s.get("condition_min_distinct", 2):
                    pts += s.get("condition_points", 2)
                    why.append("+" + str(s.get("condition_points", 2)) + " Zustand (" + "/".join(sorted(cond)[:3]) + ")")
            if self.sk.get("reason_keywords") and self.sk["reason_keywords"].search(blob):
                pts += s.get("reason_points", 1)
                why.append(f"+{s.get('reason_points', 1)} Verkaufsgrund")
            b = self.sk["brands"].search(blob) if self.sk.get("brands") else None
            if b and (not self.sk.get("model_pattern") or self.sk["model_pattern"].search(blob)):
                pts += s.get("brand_points", 1)
                why.append(f"+{s.get('brand_points', 1)} Marke ({b.group(0)})")
            if (imgs or 0) > s.get("photos_threshold", 3):
                pts += s.get("photos_points", 1)
                why.append(f"+{s.get('photos_points', 1)} Fotos {imgs}")
            if self.sk.get("receipt_pattern") and self.sk["receipt_pattern"].search(blob):
                pts += s.get("receipt_points", 1)
                why.append(f"+{s.get('receipt_points', 1)} Kaufbeleg/Jahr")
            if self.sk.get("two_brakes_pattern") and self.sk["two_brakes_pattern"].search(blob):
                pts += s.get("two_brakes_points", 1)
                why.append(f"+{s.get('two_brakes_points', 1)} zwei Bremsen")
            if self.sk.get("accessories_pattern") and self.sk["accessories_pattern"].search(blob):
                pts += s.get("accessories_points", 1)
                why.append(f"+{s.get('accessories_points', 1)} Zubehoer")
            if sad is not None and sad >= s.get("dealer_ads_threshold", 3):
                pts -= s.get("dealer_ads_penalty", 3)
                why.append(f"-{s.get('dealer_ads_penalty', 3)} Verkaeufer {sad} Anzeigen online")
            if self.sk.get("fast_pattern") and self.sk["fast_pattern"].search(blob):
                pts -= s.get("fast_penalty", 2)
                why.append(f"-{s.get('fast_penalty', 2)} muss schnell weg")
            legit, lwhy = 0, []
            if since:
                age = self.seller_age_years(since)
                if age is not None and age >= s.get("seller_min_age_years", 2):
                    legit += s.get("seller_points_age", 1)
                    lwhy.append(f"+{s.get('seller_points_age', 1)} Konto {age}J")
            nb = len([x for x in (badges or "").split("|") if x])
            if nb >= 2:
                legit += s.get("seller_badges_points", 1)
                lwhy.append(f"+{s.get('seller_badges_points', 1)} {nb} Badges")
            if self.sk.get("seller_topbadge_pattern") and self.sk["seller_topbadge_pattern"].search(badges or ""):
                legit += s.get("seller_topbadge_points", 1)
                lwhy.append(f"+{s.get('seller_topbadge_points', 1)} Top-Badge")
            if nb == 0 and since and since.endswith(str(date.today().year)):
                legit -= s.get("fresh_account_penalty", 1)
                lwhy.append(f"-{s.get('fresh_account_penalty', 1)} frisches Konto")
            total = pts + legit
            c.execute("UPDATE ads SET score=?, reason=?, verdict='scored' WHERE id=?",
                      (total, "; ".join(why + lwhy), aid))
            out.append({"id": aid, "title": title, "price": price, "location": loc,
                        "size": n if kind == "num" else (n or "?"), "score": total,
                        "why": "; ".join(why + lwhy)})
        c.commit()
        out.sort(key=lambda x: -x["score"])
        (BASE / "scored.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        self.log(f"SCORE DONE {len(out)} candidates, top: {out[0]['score'] if out else '-'}")
        return out

    def stage_verify(self, top_n: int):
        sc = json.loads((BASE / "scored.json").read_text(encoding="utf-8")) if (BASE / "scored.json").exists() else []
        if not sc:
            sc = self.stage_score()
        manifest = []
        for cand in sc[:top_n]:
            aid = cand["id"]
            d = self.finalists / aid
            d.mkdir(parents=True, exist_ok=True)
            try:
                html = self.get(self.detail_url(aid), ttl_days=0)
            except RuntimeError:
                cand["online"] = False
                manifest.append({**cand, "local_imgs": []})
                self.log(f"finalist {aid}: OFFLINE (fetch failed)")
                continue
            title_hit = cand["title"][:20].lower() in html.lower() if cand["title"] else True
            online = not DELETED_RE.search(html) and title_hit
            cand["online"] = online
            urls = []
            for m in re.finditer(r'galleryimage-element.*?<img[^>]+src="([^"]+)"', html, re.S):
                u = m.group(1)
                if u not in urls:
                    urls.append(u)
            files = []
            if online:
                for i, u in enumerate(urls[:6]):
                    img_url = u.split("?")[0] + "?rule=" + self.p.get("image_rule", "$_59.JPG")
                    try:
                        req = urllib.request.Request(img_url, headers={"User-Agent": UA})
                        with urllib.request.urlopen(req, timeout=30) as r:
                            data = r.read()
                        (d / f"{i}.jpg").write_bytes(data)
                        files.append(f"{aid}/{i}.jpg")
                        time.sleep(0.5)
                    except Exception as e:
                        self.log(f"img fail {aid} {i}: {e}")
            self.log(f"finalist {aid}: online={online} imgs={len(files)}")
            manifest.append({**cand, "local_imgs": files})
        (self.finalists / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        return manifest

    def stage_report(self):
        c = self.db()
        rows = c.execute("""SELECT id,title,price,location,score,reason FROM ads
                            WHERE verdict='scored' ORDER BY score DESC, price ASC""").fetchall()
        n = self.p.get("report_top", 20)
        lines = [f"# classified-hunter report — {self.name} — {date.today().isoformat()}", "",
                 f"{len(rows)} scored candidates, showing top {min(n, len(rows))}. Sorted by score, then price.", "",
                 "| # | Titel | Preis | Ort | Score | Begründung | Link |", "|---|---|---|---|---|---|---|"]
        for i, (aid, title, price, loc, score, reason) in enumerate(rows[:n], 1):
            t = (title or "")[:60].replace("|", "/")
            r = (reason or "")[:140].replace("|", "/")
            l = (loc or "")[:30].replace("|", "/")
            lines.append(f"| {i} | {t} | {price} | {l} | {score} | {r} | https://www.kleinanzeigen.de/s-anzeige/{aid} |")
        lines += ["", f"Manual verification (description + images + online status) required before acting on any pick. See finalists/ for images."]
        (BASE / "report.md").write_text("\n".join(lines), encoding="utf-8")
        self.log(f"REPORT DONE {len(rows)} scored")


def main():
    ap = argparse.ArgumentParser(description="classified-hunter pipeline")
    ap.add_argument("stage", choices=["lists", "prefilter", "details", "score", "verify", "report", "all"])
    ap.add_argument("--profile", default="profiles/bike.json")
    ap.add_argument("--fresh", action="store_true", help="lists: bypass cache (TTL ~1h)")
    ap.add_argument("--all", action="store_true", help="details: fetch all, not just title-keep tier")
    ap.add_argument("--top", type=int, default=None, help="verify: top N to verify (default from profile)")
    a = ap.parse_args()
    profile = json.loads((BASE / a.profile if not Path(a.profile).is_absolute() else Path(a.profile)).read_text(encoding="utf-8"))
    local = BASE / 'profiles' / 'local.json'
    if not a.profile.endswith('local.json') and local.exists():
        profile.update(json.loads(local.read_text(encoding='utf-8')))
    h = Hunter(profile)
    if a.stage == "lists":
        h.stage_lists(fresh=a.fresh)
    elif a.stage == "prefilter":
        h.stage_prefilter()
    elif a.stage == "details":
        h.stage_details(all_tiers=a.all)
    elif a.stage == "score":
        h.stage_score()
    elif a.stage == "verify":
        h.stage_verify(a.top or h.p.get("verify_top", 20))
    elif a.stage == "report":
        h.stage_report()
    elif a.stage == "all":
        h.stage_lists(fresh=a.fresh)
        h.stage_prefilter()
        h.stage_details(all_tiers=a.all)
        h.stage_score()
        h.stage_verify(a.top or h.p.get("verify_top", 20))
        h.stage_report()


if __name__ == "__main__":
    main()
