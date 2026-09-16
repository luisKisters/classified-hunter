#!/usr/bin/env python3
"""Vision prep: download gallery images + seller stats for top-scored finalists."""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
from ka_hunter import get, UA, log  # noqa: E402

TOP_N = int(sys.argv[1]) if len(sys.argv) > 1 else 12
OUT = BASE / "finalists"

sc = json.loads((BASE / "scored.json").read_text(encoding="utf-8"))
top = sc[:TOP_N]
manifest = []
for cand in top:
    aid = cand["id"]
    d = OUT / aid
    d.mkdir(parents=True, exist_ok=True)
    html = get(f"https://www.kleinanzeigen.de/s-anzeige/{aid}")
    urls = []
    for m in re.finditer(r'galleryimage-element.*?<img[^>]+src="([^"]+)"', html, re.S):
        u = m.group(1)
        if u not in urls:
            urls.append(u)
    files = []
    for i, u in enumerate(urls[:6]):
        img_url = u.split("?")[0] + "?rule=$_59.JPG"
        try:
            req = urllib.request.Request(img_url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            f = d / f"{i}.jpg"
            f.write_bytes(data)
            files.append(f"{aid}/{i}.jpg")
            time.sleep(0.5)
        except Exception as e:
            log(f"img fail {aid} {i}: {e}")
    uid = re.search(r's-bestandsliste\.html\?userId=(\d+)', html)
    ship = re.search(r'(Versand|m[öo]glich[^<]{0,20})', html)
    manifest.append({**cand, "userId": uid.group(1) if uid else "", "local_imgs": files})
    log(f"finalist {aid}: {len(files)} imgs downloaded")

(OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
for m in manifest:
    print(f"\n=== [{m['id']}] score={m['score']} {m['price']} | {m['title']}")
    print(f"    typ={m['typ']} groesse={m['groesse']} why={m['why']}")
    print(f"    imgs: {len(m['local_imgs'])} in finalists/{m['id']}/")
