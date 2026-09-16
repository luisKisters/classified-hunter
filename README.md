# classified-hunter

Config-driven pipeline that hunts for items on Kleinanzeigen (German classifieds) and ranks them against your criteria. Generalized from the `bike-hunter` prototype (see `legacy/`), which was validated end-to-end on a real hunt: ~2900 listings swept, defect-scoring bugs found and fixed, winner picked.

## How it works

One JSON profile (`profiles/bike.json`) defines a hunt: search sweep, price/radius, hard kills (type, size, defects), and scoring weights. Six resumable stages:

```
python3 hunter.py lists     --profile profiles/bike.json [--fresh]   # sweep searches (pagination, dedup)
python3 hunter.py prefilter --profile profiles/bike.json             # kill on title/teaser: price, type, size
python3 hunter.py details   --profile profiles/bike.json [--all]     # fetch detail pages (title-keep tier first)
python3 hunter.py score     --profile profiles/bike.json             # defect-aware scoring -> scored.json
python3 hunter.py verify    --profile profiles/bake.json [--top 20]  # live online check + image download
python3 hunter.py report    --profile profiles/bike.json             # report.md table
```

State lives in `<name>.db` (SQLite) + `cache/` (HTML, md5-keyed). Every stage is safe to interrupt and resume. `--fresh` bypasses the list cache (~1h TTL) so new listings come in.

## Writing a profile for another item type

Copy `profiles/bike.json` and change: `searches` (category id or keywords), `price`, `size` patterns + bounds, `type_kill` / `defects` / `defect_kill` regexes, scoring weights. The bike profile documents the patterns that matter empirically: frame sizes appear as `RH 60`, `Rahmenhöhe 60cm`, `60cm Stützrohr`, `60cm c-c` — cover the variants or you will silently miss winners.

## Empirical notes (Kleinanzeigen, validated 2026-08)

- curl gets through at low volume with a browser UA — no DataDome trouble at ~0.2 req/s. Never log in, never try to bypass anti-bot. If blocked, stop.
- Everything needed is server-rendered: description, photo count, `Aktiv seit`, seller badges, `X Anzeigen online`, userId.
- Fahrräder category is `c217`. Search URL grammar: `/s-suchanfrage.html?keywords=&categoryId=&locationStr=&radius=&minPrice=&maxPrice=&sortingField=NEWEST_FIRST&pageNum=`.
- Image CDN rule param must stay single-quoted in shells: `'?rule=$_59.JPG'` — `$_` is eaten otherwise.
- Listings move in hours. Rescan with `--fresh` before recommending anything older than ~2h.

## Status

Private, personal use. Not affiliated with or endorsed by Kleinanzeigen. Automated access is against their ToS; keep volume low, treat seller metadata as ephemeral (delete the DB after the hunt), and don't use this commercially. See the `classified-hunter` skill in [luiskisters/skills](https://github.com/luiskisters/skills) for the agent-facing workflow.

Related: `deal-radar` (planning repo for the always-on monitored version with Telegram push).
