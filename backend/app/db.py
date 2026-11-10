"""Stockage SQLite (WAL). Suffisant pour des millions de ventes, y compris sur un SBC."""
import json
import os
import time
from collections import defaultdict

import aiosqlite

from .models import Auction, Card, OrderRequest, Rule, Sale

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, rarity TEXT,
  attack REAL, defense REAL, url TEXT, updated_at INTEGER);

CREATE TABLE IF NOT EXISTS sales(
  id TEXT PRIMARY KEY, card_id TEXT NOT NULL, price REAL NOT NULL,
  ts INTEGER NOT NULL, kind TEXT, inferred INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_sales_card_ts ON sales(card_id, ts);
CREATE INDEX IF NOT EXISTS ix_sales_ts ON sales(ts);

CREATE TABLE IF NOT EXISTS auctions(
  id TEXT PRIMARY KEY, card_id TEXT NOT NULL, current_bid REAL, start_price REAL,
  bids INTEGER, ends_at INTEGER, seller TEXT, leader_is_me INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'open', first_seen INTEGER, updated_at INTEGER);
CREATE INDEX IF NOT EXISTS ix_auctions_status ON auctions(status, card_id);

-- Évolution des mises : utile pour étudier les enchères de dernière minute
CREATE TABLE IF NOT EXISTS bid_snapshots(
  auction_id TEXT, ts INTEGER, current_bid REAL, bids INTEGER,
  PRIMARY KEY(auction_id, ts));

-- Journal de TOUTES les actions d'écriture (manuelles, auto, dry-run, refusées)
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, kind TEXT NOT NULL,
  card_id TEXT, auction_id TEXT, amount REAL, source TEXT, status TEXT,
  reason TEXT, request TEXT, response TEXT);
CREATE INDEX IF NOT EXISTS ix_orders_ts ON orders(ts);

CREATE TABLE IF NOT EXISTS rules(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, card_id TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1, params TEXT NOT NULL DEFAULT '{}');
"""


def now_ms() -> int:
    return int(time.time() * 1000)


class DB:
    def __init__(self, path: str) -> None:
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA synchronous=NORMAL")
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    # ---------- cartes ----------
    async def upsert_cards(self, cards: list[Card]) -> None:
        t = now_ms()
        await self.conn.executemany(
            """INSERT INTO cards(id,name,rarity,attack,defense,url,updated_at)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, rarity=excluded.rarity,
               attack=excluded.attack, defense=excluded.defense, url=excluded.url,
               updated_at=excluded.updated_at""",
            [(c.id, c.name, c.rarity, c.attack, c.defense, c.url, t) for c in cards],
        )
        await self.conn.commit()

    async def known_card_ids(self) -> set[str]:
        async with self.conn.execute("SELECT id FROM cards") as cur:
            return {r["id"] for r in await cur.fetchall()}

    async def cards(self, q: str | None = None) -> list[Card]:
        sql, args = "SELECT * FROM cards", ()
        if q:
            sql, args = sql + " WHERE name LIKE ?", (f"%{q}%",)
        async with self.conn.execute(sql, args) as cur:
            return [Card(**{k: r[k] for k in Card.model_fields}) for r in await cur.fetchall()]

    async def card(self, card_id: str) -> Card | None:
        async with self.conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)) as cur:
            r = await cur.fetchone()
        return Card(**{k: r[k] for k in Card.model_fields}) if r else None

    # ---------- ventes ----------
    async def insert_sales(self, sales: list[Sale]) -> list[Sale]:
        """Insère et renvoie uniquement les ventes nouvelles (dédoublonnage par id)."""
        new = []
        for s in sales:
            cur = await self.conn.execute(
                "INSERT OR IGNORE INTO sales(id,card_id,price,ts,kind,inferred) VALUES(?,?,?,?,?,?)",
                (s.id, s.card_id, s.price, s.ts, s.kind, int(s.inferred)),
            )
            if cur.rowcount == 1:
                new.append(s)
        await self.conn.commit()
        return new

    async def last_sale_ts(self) -> int:
        async with self.conn.execute("SELECT MAX(ts) m FROM sales WHERE inferred=0") as cur:
            r = await cur.fetchone()
        return r["m"] or 0

    async def sales_for(self, card_id: str, since_ms: int) -> list[Sale]:
        async with self.conn.execute(
            "SELECT * FROM sales WHERE card_id=? AND ts>=? ORDER BY ts", (card_id, since_ms)
        ) as cur:
            return [self._sale(r) for r in await cur.fetchall()]

    async def sales_since_grouped(self, since_ms: int) -> dict[str, list[Sale]]:
        out: dict[str, list[Sale]] = defaultdict(list)
        async with self.conn.execute(
            "SELECT * FROM sales WHERE ts>=? ORDER BY ts", (since_ms,)
        ) as cur:
            for r in await cur.fetchall():
                out[r["card_id"]].append(self._sale(r))
        return out

    async def recent_sales(self, limit: int) -> list[Sale]:
        async with self.conn.execute(
            "SELECT * FROM sales ORDER BY ts DESC LIMIT ?", (limit,)
        ) as cur:
            return [self._sale(r) for r in await cur.fetchall()]

    @staticmethod
    def _sale(r) -> Sale:
        return Sale(id=r["id"], card_id=r["card_id"], price=r["price"], ts=r["ts"],
                    kind=r["kind"], inferred=bool(r["inferred"]))

    # ---------- enchères (carnet) ----------
    async def open_auctions(self, card_id: str | None = None) -> dict[str, Auction]:
        sql, args = "SELECT * FROM auctions WHERE status='open'", ()
        if card_id:
            sql, args = sql + " AND card_id=?", (card_id,)
        async with self.conn.execute(sql + " ORDER BY ends_at", args) as cur:
            return {r["id"]: Auction(**{k: r[k] for k in Auction.model_fields})
                    for r in await cur.fetchall()}

    async def upsert_auctions(self, auctions: list[Auction], prev: dict[str, Auction]) -> None:
        t = now_ms()
        await self.conn.executemany(
            """INSERT INTO auctions(id,card_id,current_bid,start_price,bids,ends_at,seller,leader_is_me,status,first_seen,updated_at)
               VALUES(?,?,?,?,?,?,?,?,'open',?,?)
               ON CONFLICT(id) DO UPDATE SET current_bid=excluded.current_bid, bids=excluded.bids,
               leader_is_me=excluded.leader_is_me,
               ends_at=excluded.ends_at, status='open', updated_at=excluded.updated_at""",
            [(a.id, a.card_id, a.current_bid, a.start_price, a.bids, a.ends_at, a.seller,
              int(a.leader_is_me), t, t)
             for a in auctions],
        )
        changed = [a for a in auctions
                   if a.id not in prev or prev[a.id].current_bid != a.current_bid]
        await self.conn.executemany(
            "INSERT OR IGNORE INTO bid_snapshots(auction_id,ts,current_bid,bids) VALUES(?,?,?,?)",
            [(a.id, t, a.current_bid, a.bids) for a in changed],
        )
        await self.conn.commit()

    async def close_auctions(self, ids: list[str]) -> None:
        await self.conn.executemany(
            "UPDATE auctions SET status='closed', updated_at=? WHERE id=?",
            [(now_ms(), i) for i in ids],
        )
        await self.conn.commit()

    async def book_summary(self) -> dict[str, dict]:
        async with self.conn.execute(
            """SELECT card_id, COUNT(*) n, MIN(COALESCE(current_bid,start_price)) lo,
                      MAX(COALESCE(current_bid,start_price)) hi, MIN(ends_at) next_end
               FROM auctions WHERE status='open' GROUP BY card_id"""
        ) as cur:
            return {r["card_id"]: {"open_auctions": r["n"], "book_low": r["lo"],
                                   "book_high": r["hi"], "next_end": r["next_end"]}
                    for r in await cur.fetchall()}

    # ---------- ordres (journal) ----------
    async def log_order(self, req: OrderRequest, status: str, reason: str | None = None,
                        response: dict | None = None) -> int:
        cur = await self.conn.execute(
            """INSERT INTO orders(ts,kind,card_id,auction_id,amount,source,status,reason,request,response)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (now_ms(), req.kind, req.card_id, req.auction_id, req.amount, req.source, status,
             reason, req.model_dump_json(), json.dumps(response) if response is not None else None),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def spent_since(self, since_ms: int) -> float:
        """Somme des mises ENVOYÉES (pas dry-run) depuis since_ms : sert au plafond journalier."""
        async with self.conn.execute(
            "SELECT COALESCE(SUM(amount),0) s FROM orders WHERE kind='bid' AND status='sent' AND ts>=?",
            (since_ms,),
        ) as cur:
            return (await cur.fetchone())["s"]

    async def orders(self, limit: int = 200) -> list[dict]:
        async with self.conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ---------- règles ----------
    async def rules(self, only_enabled: bool = False) -> list[Rule]:
        sql = "SELECT * FROM rules" + (" WHERE enabled=1" if only_enabled else "")
        async with self.conn.execute(sql) as cur:
            return [Rule(id=r["id"], kind=r["kind"], card_id=r["card_id"], enabled=bool(r["enabled"]),
                         params=json.loads(r["params"])) for r in await cur.fetchall()]

    async def save_rule(self, rule: Rule) -> Rule:
        if rule.id is None:
            cur = await self.conn.execute(
                "INSERT INTO rules(kind,card_id,enabled,params) VALUES(?,?,?,?)",
                (rule.kind, rule.card_id, int(rule.enabled), json.dumps(rule.params)))
            rule = rule.model_copy(update={"id": cur.lastrowid})
        else:
            await self.conn.execute(
                "UPDATE rules SET kind=?, card_id=?, enabled=?, params=? WHERE id=?",
                (rule.kind, rule.card_id, int(rule.enabled), json.dumps(rule.params), rule.id))
        await self.conn.commit()
        return rule

    async def delete_rule(self, rule_id: int) -> None:
        await self.conn.execute("DELETE FROM rules WHERE id=?", (rule_id,))
        await self.conn.commit()
