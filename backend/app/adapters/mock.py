"""Marché simulé : permet de développer l'interface et les automatismes sans toucher au site."""
import asyncio
import math
import random
import time
import uuid

from ..models import Auction, Card, Sale

NAMES = [
    "France", "Paris", "Albert Einstein", "Napoléon Ier", "Tour Eiffel", "Mathématiques",
    "Leonhard Euler", "Carl Friedrich Gauss", "Évariste Galois", "Henri Poincaré", "Marie Curie",
    "Victor Hugo", "Révolution française", "Seconde Guerre mondiale", "Lune", "Soleil", "Jupiter",
    "Python (langage)", "Linux", "Internet", "Football", "Zinédine Zidane", "Kylian Mbappé",
    "Coupe du monde de football", "Orsay", "Université Paris-Saclay", "Nombre premier",
    "Intégrale de Lebesgue", "Probabilité", "Théorème de Fermat", "Bourbaki", "Alexandre Grothendieck",
    "Rome", "Égypte antique", "Dinosaure", "Chat", "Baguette", "Fromage", "Bordeaux (vin)", "Mont Blanc",
]
RARITY = [("commune", 10, 0.06), ("rare", 50, 0.08), ("épique", 250, 0.10), ("légendaire", 1500, 0.14)]
DAY_S = 86_400


def _ms() -> int:
    return int(time.time() * 1000)


class MockAdapter:
    supports_sales = True
    supports_stream = False

    def __init__(self, seed: int = 42) -> None:
        rnd = random.Random(seed)
        self.rnd = rnd
        self.cards: dict[str, Card] = {}
        self.fv: dict[str, float] = {}      # « juste valeur » cachée, marche aléatoire
        self.sigma: dict[str, float] = {}
        for i, name in enumerate(NAMES):
            r, base, sig = RARITY[min(3, int(rnd.paretovariate(2.2)) - 1)]
            cid = f"c{i:03d}"
            self.cards[cid] = Card(id=cid, name=name, rarity=r,
                                   attack=round(rnd.uniform(10, 99)), defense=round(rnd.uniform(10, 99)),
                                   url=f"https://fr.wikipedia.org/wiki/{name.replace(' ', '_')}")
            self.fv[cid] = base * rnd.uniform(0.6, 1.8)
            self.sigma[cid] = sig
        self.auctions: dict[str, Auction] = {}
        self.sales: list[Sale] = []
        self.balance = 5000.0
        self.inventory: dict[str, int] = {cid: 1 for cid in list(self.cards)[:6]}
        self._last = time.time()
        self._backfill(days=7)
        self._step()

    # ---------- simulation ----------
    def _backfill(self, days: int) -> None:
        """Génère un historique passé pour que les graphiques aient des données."""
        now = time.time()
        for cid in self.cards:
            fv = self.fv[cid]
            path = []
            t = now - days * DAY_S
            rate = self.rnd.uniform(4, 40) / DAY_S  # ventes / seconde
            while True:
                t += self.rnd.expovariate(rate)
                if t >= now:
                    break
                path.append(t)
            # marche aléatoire en remontant vers la valeur actuelle
            prices, p = [], fv
            for _ in path:
                prices.append(p)
                p *= math.exp(self.rnd.gauss(0, self.sigma[cid] * 0.35))
            for t, p in zip(path, reversed(prices)):
                self.sales.append(Sale(id=uuid.uuid4().hex, card_id=cid,
                                       price=round(p * self.rnd.uniform(0.85, 1.15), 1), ts=int(t * 1000)))
        self.sales.sort(key=lambda s: s.ts)

    def _step(self) -> None:
        now = time.time()
        dt = max(0.0, now - self._last)
        self._last = now
        for cid in self.fv:  # dérive de la juste valeur
            self.fv[cid] *= math.exp(self.rnd.gauss(0, self.sigma[cid] * math.sqrt(dt / 3600)))
        for a in list(self.auctions.values()):
            fv = self.fv[a.card_id]
            # les autres joueurs misent tant que le prix est sous leur estimation
            if self.rnd.random() < min(1, dt / 8) and (a.current_bid or a.start_price) < fv * self.rnd.uniform(0.8, 1.15):
                a.current_bid = round((a.current_bid or a.start_price) * self.rnd.uniform(1.03, 1.12), 1)
                a.bids += 1
                a.leader_is_me = False
            if a.ends_at <= now * 1000:
                del self.auctions[a.id]
                if a.bids > 0:
                    self.sales.append(Sale(id=uuid.uuid4().hex, card_id=a.card_id,
                                           price=a.current_bid, ts=a.ends_at))
                    if a.leader_is_me:
                        self.inventory[a.card_id] = self.inventory.get(a.card_id, 0) + 1
                    if a.seller == "me":
                        self.balance += a.current_bid
                elif a.seller == "me":
                    self.inventory[a.card_id] = self.inventory.get(a.card_id, 0) + 1
        while len(self.auctions) < 70:
            cid = self.rnd.choice(list(self.cards))
            self._new_auction(cid, self.fv[cid] * self.rnd.uniform(0.4, 0.9),
                              self.rnd.uniform(30, 900), seller=f"joueur{self.rnd.randint(1, 500)}")

    def _new_auction(self, cid: str, start: float, duration_s: float, seller: str) -> Auction:
        a = Auction(id=uuid.uuid4().hex[:10], card_id=cid, start_price=round(start, 1),
                    current_bid=None, bids=0, ends_at=_ms() + int(duration_s * 1000), seller=seller)
        self.auctions[a.id] = a
        return a

    # ---------- lecture ----------
    async def list_open_auctions(self) -> list[Auction]:
        await asyncio.sleep(0.05)
        self._step()
        return [a.model_copy() for a in self.auctions.values()]

    async def list_recent_sales(self, since_ms: int) -> list[Sale]:
        self._step()
        return [s for s in self.sales if s.ts >= since_ms]

    async def get_card(self, card_id: str) -> Card | None:
        return self.cards.get(card_id)

    async def get_balance(self) -> float | None:
        return round(self.balance, 1)

    async def get_inventory(self) -> list[dict]:
        return [{"card_id": c, "qty": q} for c, q in self.inventory.items() if q > 0]

    async def stream(self):  # pragma: no cover
        if False:
            yield {}

    # ---------- écriture ----------
    async def place_bid(self, auction_id: str, amount: float) -> dict:
        a = self.auctions.get(auction_id)
        if not a:
            raise RuntimeError("enchère introuvable ou terminée")
        floor = a.current_bid or a.start_price
        if amount <= floor:
            raise RuntimeError(f"mise trop basse (minimum > {floor})")
        if amount > self.balance:
            raise RuntimeError("solde insuffisant")
        a.current_bid, a.bids, a.leader_is_me = round(amount, 1), a.bids + 1, True
        return {"ok": True, "auction_id": auction_id, "current_bid": a.current_bid}

    async def create_listing(self, card_id: str, start_price: float, duration_s: int) -> dict:
        if self.inventory.get(card_id, 0) < 1:
            raise RuntimeError("carte absente de l'inventaire")
        self.inventory[card_id] -= 1
        a = self._new_auction(card_id, start_price, duration_s, seller="me")
        return {"ok": True, "auction_id": a.id}

    async def cancel_listing(self, auction_id: str) -> dict:
        a = self.auctions.get(auction_id)
        if not a or a.seller != "me":
            raise RuntimeError("pas une de tes ventes")
        if a.bids:
            raise RuntimeError("impossible : il y a déjà des mises")
        del self.auctions[auction_id]
        self.inventory[a.card_id] = self.inventory.get(a.card_id, 0) + 1
        return {"ok": True}

    async def send_trade_offer(self, trade: dict) -> dict:
        return {"ok": True, "offer_id": uuid.uuid4().hex[:8], "echo": trade}

    async def aclose(self) -> None:
        pass
