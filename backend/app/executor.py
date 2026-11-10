"""Point de passage UNIQUE de toutes les écritures (manuelles et automatiques).

Garde-fous appliqués à chaque ordre :
  - liste blanche des types d'ordres (pas d'ouverture de packs)
  - arrêt d'urgence (kill switch)
  - mode dry-run (journalise sans envoyer)
  - plafond par mise et budget glissant sur 24 h
  - intervalle minimal entre deux ordres envoyés
Tout est journalisé dans la table `orders`, y compris les refus.
"""
import asyncio
import logging
import time
from typing import get_args

from .adapters.base import Adapter
from .config import Config
from .db import DB, now_ms
from .hub import Hub
from .models import OrderKind, OrderRequest, OrderResult

log = logging.getLogger("wm.executor")
ALLOWED = set(get_args(OrderKind))


class Executor:
    def __init__(self, adapter: Adapter, db: DB, hub: Hub, cfg: Config) -> None:
        self.adapter, self.db, self.hub, self.cfg = adapter, db, hub, cfg
        self.dry_run = cfg.dry_run
        self.killed = False
        self._lock = asyncio.Lock()
        self._last_sent = 0.0

    def state(self) -> dict:
        return {"dry_run": self.dry_run, "killed": self.killed,
                "max_bid": self.cfg.max_bid, "daily_budget": self.cfg.daily_budget}

    async def _check(self, req: OrderRequest) -> str | None:
        if req.kind not in ALLOWED:
            return f"type d'ordre non autorisé : {req.kind}"
        if self.killed:
            return "arrêt d'urgence actif"
        if req.kind == "bid":
            if not req.auction_id or not req.amount or req.amount <= 0:
                return "bid : auction_id et amount requis"
            if req.amount > self.cfg.max_bid:
                return f"mise {req.amount} > plafond {self.cfg.max_bid}"
            if not self.dry_run:
                spent = await self.db.spent_since(now_ms() - 86_400_000)
                if spent + req.amount > self.cfg.daily_budget:
                    return f"budget 24 h dépassé ({spent:.0f} + {req.amount:.0f} > {self.cfg.daily_budget:.0f})"
        if req.kind == "list" and (not req.card_id or not req.amount or not req.duration_s):
            return "list : card_id, amount et duration_s requis"
        if req.kind == "cancel_listing" and not req.auction_id:
            return "cancel_listing : auction_id requis"
        if req.kind == "trade_offer" and not req.trade:
            return "trade_offer : trade requis"
        return None

    async def submit(self, req: OrderRequest) -> OrderResult:
        async with self._lock:  # un ordre à la fois : simple et prévisible
            reason = await self._check(req)
            if reason:
                return await self._done(req, "rejected", reason)
            if self.dry_run:
                return await self._done(req, "dry_run", "mode simulation : rien n'a été envoyé")

            wait = self.cfg.min_order_interval_s - (time.monotonic() - self._last_sent)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                if req.kind == "bid":
                    resp = await self.adapter.place_bid(req.auction_id, req.amount)
                elif req.kind == "list":
                    resp = await self.adapter.create_listing(req.card_id, req.amount, req.duration_s)
                elif req.kind == "cancel_listing":
                    resp = await self.adapter.cancel_listing(req.auction_id)
                else:
                    resp = await self.adapter.send_trade_offer(req.trade)
            except Exception as e:
                log.warning("ordre refusé par le site : %s", e)
                return await self._done(req, "error", str(e))
            finally:
                self._last_sent = time.monotonic()
            return await self._done(req, "sent", None, resp if isinstance(resp, dict) else {"raw": resp})

    async def _done(self, req: OrderRequest, status: str, reason: str | None,
                    response: dict | None = None) -> OrderResult:
        oid = await self.db.log_order(req, status, reason, response)
        res = OrderResult(id=oid, status=status, reason=reason, response=response)
        self.hub.publish("order", {"request": req.model_dump(), "result": res.model_dump()})
        return res
