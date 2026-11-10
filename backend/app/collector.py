"""Boucles de collecte : enchères ouvertes (carnet), ventes, fiches cartes."""
import asyncio
import logging
import time

from .adapters.base import Adapter
from .config import Config
from .db import DB, now_ms
from .hub import Hub
from .models import Auction, Sale

log = logging.getLogger("wm.collector")


class Collector:
    def __init__(self, adapter: Adapter, db: DB, hub: Hub, cfg: Config) -> None:
        self.adapter, self.db, self.hub, self.cfg = adapter, db, hub, cfg
        self._last_sale_ts = 0
        self._known: set[str] = set()
        self.health = {"auctions_ok": None, "sales_ok": None, "last_error": None}

    async def run(self) -> None:
        self._known = await self.db.known_card_ids()
        self._last_sale_ts = await self.db.last_sale_ts()
        tasks = [self._loop("auctions", self.poll_auctions, self.cfg.poll_auctions_s)]
        if self.adapter.supports_sales:
            tasks.append(self._loop("sales", self.poll_sales, self.cfg.poll_sales_s))
        if self.adapter.supports_stream:
            tasks.append(self._stream())
        await asyncio.gather(*tasks)

    async def _loop(self, name: str, fn, interval: float) -> None:
        while True:
            t0 = time.monotonic()
            try:
                await fn()
                self.health[f"{name}_ok"] = now_ms()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # on ne tue jamais la boucle
                log.exception("poll %s", name)
                self.health["last_error"] = f"{name}: {e}"
            await asyncio.sleep(max(0.0, interval - (time.monotonic() - t0)))

    async def poll_auctions(self) -> None:
        live = await self.adapter.list_open_auctions()
        prev = await self.db.open_auctions()
        await self._ensure_cards({a.card_id for a in live})
        await self.db.upsert_auctions(live, prev)

        for a in live:
            if a.id not in prev or prev[a.id].current_bid != a.current_bid:
                self.hub.publish("auction", a.model_dump())

        live_ids = {a.id for a in live}
        gone = [a for i, a in prev.items() if i not in live_ids]
        if gone:
            await self.db.close_auctions([a.id for a in gone])
            if not self.adapter.supports_sales:
                # Pas d'historique officiel : une enchère disparue avec des mises = vente probable.
                t = now_ms()
                inferred = [Sale(id=f"auc:{a.id}", card_id=a.card_id, price=a.current_bid,
                                 ts=min(a.ends_at, t), inferred=True)
                            for a in gone if a.bids > 0 and a.current_bid]
                for s in await self.db.insert_sales(inferred):
                    self.hub.publish("sale", s.model_dump())
            for a in gone:
                self.hub.publish("auction_closed", {"id": a.id, "card_id": a.card_id})

    async def poll_sales(self) -> None:
        sales = await self.adapter.list_recent_sales(max(0, self._last_sale_ts - 60_000))
        await self._ensure_cards({s.card_id for s in sales})
        new = await self.db.insert_sales(sales)
        for s in sorted(new, key=lambda s: s.ts):
            self.hub.publish("sale", s.model_dump())
        if sales:
            self._last_sale_ts = max(self._last_sale_ts, max(s.ts for s in sales))

    async def _ensure_cards(self, ids: set[str]) -> None:
        missing = ids - self._known
        if not missing:
            return
        cards = await asyncio.gather(*(self.adapter.get_card(i) for i in missing), return_exceptions=True)
        ok = [c for c in cards if c and not isinstance(c, Exception)]
        if ok:
            await self.db.upsert_cards(ok)
            self._known |= {c.id for c in ok}

    async def _stream(self) -> None:
        while True:
            try:
                async for ev in self.adapter.stream():
                    if ev["type"] == "sale":
                        s = ev["data"] if isinstance(ev["data"], Sale) else Sale(**ev["data"])
                        for n in await self.db.insert_sales([s]):
                            self.hub.publish("sale", n.model_dump())
                    elif ev["type"] == "auction":
                        a = ev["data"] if isinstance(ev["data"], Auction) else Auction(**ev["data"])
                        await self.db.upsert_auctions([a], await self.db.open_auctions(a.card_id))
                        self.hub.publish("auction", a.model_dump())
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("stream")
            await asyncio.sleep(5)
