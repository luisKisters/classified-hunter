import sqlite3
from pathlib import Path

from .rules import parse_price

STATUSES = ("new", "kept", "killed", "detailed", "scored", "verified", "gone")


class Store:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.root = path.parent
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS ads (
            id TEXT PRIMARY KEY, title TEXT, price TEXT, price_eur INTEGER,
            location TEXT, teaser TEXT, thumb TEXT, description TEXT DEFAULT '',
            images INTEGER DEFAULT 0, seller_id TEXT DEFAULT '', seller_since TEXT DEFAULT '',
            seller_badges TEXT DEFAULT '', seller_ads INTEGER, score INTEGER, reason TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'new'
                CHECK(status IN ('new','kept','killed','detailed','scored','verified','gone')),
            kill_reason TEXT)""")

    def close(self):
        self.db.close()

    def insert(self, ad):
        fields = ("id", "title", "price", "location", "teaser", "thumb")
        self.db.execute(
            "INSERT OR IGNORE INTO ads (" + ",".join(fields) + ",price_eur) VALUES (?,?,?,?,?,?,?)",
            [ad.get(k, "") for k in fields] + [parse_price(ad.get("price", ""))],
        )
        self.db.commit()

    def update(self, aid, **fields):
        columns = {r[1] for r in self.db.execute("PRAGMA table_info(ads)")}
        if not fields or not fields.keys() <= columns - {"id"}:
            raise ValueError("invalid ad fields")
        self.db.execute(
            "UPDATE ads SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?",
            [*fields.values(), aid],
        )
        self.db.commit()

    def rows(self, *statuses):
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT * FROM ads WHERE status IN (" + ",".join("?" for _ in statuses) + ")",
                statuses,
            )
        ]

    def candidates(self, limit=None, statuses=("scored", "verified")):
        sql = (
            "SELECT * FROM ads WHERE status IN ("
            + ",".join("?" for _ in statuses)
            + ") ORDER BY score DESC, price_eur ASC, id ASC"
        )
        params = list(statuses)
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [dict(row) for row in self.db.execute(sql, params)]

    def counts(self):
        counts = dict.fromkeys(STATUSES, 0)
        counts.update(dict(self.db.execute("SELECT status, COUNT(*) FROM ads GROUP BY status")))
        return counts

    def log(self, message):
        with (self.root / "progress.log").open("a", encoding="utf-8") as f:
            f.write(message + "\n")
