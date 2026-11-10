"""Moteur d'automatismes : évalue les règles actives à chaque tick.

Règles fournies :
  alert    : notifie quand le dernier prix / le meilleur prix du carnet franchit un seuil.
  auto_bid : sur toutes les enchères ouvertes d'une carte, mise (prix + incrément) tant que
             ça reste <= max_price, optionnellement seulement dans les `last_seconds` finales.

Toutes les écritures passent par l'Executor (dry-run, plafonds, journal).
Pour ajouter un type : une méthode `_rule_<kind>` + l'ajouter au Literal dans models.Rule.
"""
import asyncio
import logging

from .config import Config
from .db import DB, now_ms
from .executor import Executor
from .hub import Hub
from .models import OrderRequest, Rule

log = logging.getLogger("wm.automation")


class Automation:
    def __init__(self, db: DB, hub: Hub, executor: Executor, cfg: Config) -> None:
        self.db, self.hub, self.ex, self.cfg = db, hub, executor, cfg
        self._fired: dict[tuple, int] = {}  # anti-spam : (rule_id, clé) -> ts

    async def run(self) -> None:
        while True:
            try:
                for rule in await self.db.rules(only_enabled=True):
                    await getattr(self, f"_rule_{rule.kind}")(rule)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("automation tick")
            await asyncio.sleep(self.cfg.automation_tick_s)

    def _once(self, key: tuple, cooldown_ms: int) -> bool:
        t = now_ms()
        if t - self._fired.get(key, 0) < cooldown_ms:
            return False
        self._fired[key] = t
        return True

    async def _rule_alert(self, r: Rule) -> None:
        p = r.params
        sales = await self.db.sales_for(r.card_id, now_ms() - 7 * 86_400_000)
        last = sales[-1].price if sales else None
        book = await self.db.open_auctions(r.card_id)
        low = min((a.current_bid or a.start_price for a in book.values()), default=None)
        msgs = []
        if last is not None and "below" in p and last < p["below"]:
            msgs.append(f"dernier prix {last} < {p['below']}")
        if last is not None and "above" in p and last > p["above"]:
            msgs.append(f"dernier prix {last} > {p['above']}")
        if low is not None and "book_below" in p and low < p["book_below"]:
            msgs.append(f"enchère à {low} < {p['book_below']}")
        for m in msgs:
            if self._once((r.id, m.split(" ")[0]), 10 * 60_000):
                self.hub.publish("alert", {"rule_id": r.id, "card_id": r.card_id, "message": m})

    async def _rule_auto_bid(self, r: Rule) -> None:
        p = r.params
        max_price = float(p["max_price"])
        inc = float(p.get("increment", 1))
        last_s = p.get("last_seconds")
        t = now_ms()
        for a in (await self.db.open_auctions(r.card_id)).values():
            if a.leader_is_me or a.seller == "me":
                continue
            if last_s is not None and a.ends_at - t > last_s * 1000:
                continue
            target = round((a.current_bid or a.start_price or 0) + inc, 2)
            if target > max_price:
                continue
            # au plus une tentative par enchère et par niveau de prix
            if not self._once((r.id, a.id, a.current_bid), 3_600_000):
                continue
            await self.ex.submit(OrderRequest(kind="bid", card_id=a.card_id, auction_id=a.id,
                                              amount=target, source=f"rule:{r.id}"))
