"""Adaptateur pour le vrai site. SQUELETTE : les chemins et les champs JSON sont des
suppositions à remplacer par ce que tu observes dans DevTools (voir tools/har_explore.py).

Méthode :
  1. Chrome → DevTools → Network → coche « Preserve log », filtre Fetch/XHR + WS.
  2. Fais les actions à la main : ouvrir le marché, une carte, miser, mettre en vente.
  3. Clic droit → « Save all as HAR with content » → python tools/har_explore.py fichier.har
  4. Reporte les endpoints et les champs ci-dessous (les « TODO »).
"""
import asyncio
import logging
import random

import httpx

from ..config import Config
from ..models import Auction, Card, Sale

log = logging.getLogger("wm.adapter")


# Auth : les routes /api du site ne portent ni Authorization ni token visible dans le HAR,
# donc c'est très probablement le cookie de session Supabase (sb-<ref>-auth-token) → WM_COOKIE.
# Pas d'ouverture de packs (/api/packs/open existe mais n'est volontairement PAS implémenté).
class WikiMastersAdapter:
    supports_sales = False   # historique uniquement par carte : /api/marketplace/cards/{id}/sales
    supports_stream = False  # TODO: True si le marché passe par un WebSocket

    def __init__(self, cfg: Config) -> None:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) wm-terminal",
            "Accept": "application/json",
        }
        if cfg.cookie:
            headers["Cookie"] = cfg.cookie
        if cfg.bearer:
            headers["Authorization"] = f"Bearer {cfg.bearer}"
        self.client = httpx.AsyncClient(base_url=cfg.base_url, headers=headers, timeout=15)
        self.sem = asyncio.Semaphore(cfg.max_concurrency)

    async def _req(self, method: str, path: str, **kw) -> dict | list:
        """Requête avec limite de concurrence et backoff sur 429 / 5xx."""
        delay = 1.0
        for attempt in range(5):
            async with self.sem:
                r = await self.client.request(method, path, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                wait = float(r.headers.get("Retry-After", delay))
                log.warning("%s %s -> %s, retry dans %.1fs", method, path, r.status_code, wait)
                await asyncio.sleep(wait + random.random())
                delay = min(delay * 2, 30)
                continue
            if r.status_code in (401, 403):
                raise RuntimeError("Session expirée : recopie WM_COOKIE / WM_BEARER depuis le navigateur")
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"{method} {path} : abandon après 5 essais")

    # ======================= LECTURE =======================
    async def list_open_auctions(self) -> list[Auction]:
        # Endpoint confirmé par le HAR : GET /api/marketplace?page=1&limit=50&sort=recent[&mine=1]
        # TODO: clé de la liste dans la réponse + condition d'arrêt de la pagination.
        out: list[Auction] = []
        for page in range(1, 41):
            data = await self._req("GET", "/api/marketplace",
                                   params={"page": page, "limit": 50, "sort": "recent"})
            items = data.get("items") or data.get("listings") or data.get("data") or [] \
                if isinstance(data, dict) else data
            out += [self._auction(x) for x in items]
            if len(items) < 50:
                break
        return out

    async def list_recent_sales(self, since_ms: int) -> list[Sale]:
        # Le HAR montre un historique PAR CARTE : GET /api/marketplace/cards/{card_id}/sales
        # (pas d'historique global). Voir card_sales() ; ici on reste sur la déduction.
        return []

    async def card_sales(self, card_id: str) -> list[Sale]:
        # TODO: champs à confirmer
        data = await self._req("GET", f"/api/marketplace/cards/{card_id}/sales")
        return [Sale(id=str(x["id"]), card_id=str(x["cardId"]), price=float(x["price"]),
                     ts=int(x["timestamp"])) for x in data]

    async def get_card(self, card_id: str) -> Card | None:
        # TODO
        x = await self._req("GET", f"/api/cards/{card_id}")
        return Card(id=str(x["id"]), name=x["title"], rarity=x.get("rarity"),
                    attack=x.get("attack"), defense=x.get("defense"), url=x.get("wikipediaUrl"))

    async def get_balance(self) -> float | None:
        # TODO
        # Le solde (« wikibidous ») : GET /api/wikibidous — TODO: nom du champ
        x = await self._req("GET", "/api/wikibidous")
        return x.get("balance") if isinstance(x, dict) else x

    async def get_inventory(self) -> list[dict]:
        # TODO
        # GET /api/my-collection?sort=rarity&page=0&stats=0 — TODO: pagination + champs
        data = await self._req("GET", "/api/my-collection", params={"sort": "rarity", "page": 0, "stats": 0})
        return [{"card_id": str(x["cardId"]), "qty": x.get("count", 1), "instance_id": x.get("id")}
                for x in data]

    async def stream(self):
        # Le site utilise Supabase Realtime (Phoenix) : wss://cyrxjeppjqsxxjayfrur.supabase.co/realtime/v1/websocket
        # Canaux privés vus dans le HAR (join avec access_token JWT) :
        #   realtime:auction:<auction_id>   événement BID  {bid: {id, amount, bidder: {id, username}}}
        #   realtime:profile:<user_id>      UPDATE du profil (solde…)
        #   realtime:notifications:<user_id> INSERT (ex. « Vous avez été surenchéri »)
        # Pas de canal « marché global » : on s'abonne aux enchères suivies, on poll le reste.
        # TODO: si le site utilise un WebSocket, se connecter avec `websockets`, en passant
        # le cookie dans les headers, puis convertir chaque message en
        # {"type": "auction"|"auction_closed"|"sale", "data": Auction/Sale}.
        if False:
            yield {}

    @staticmethod
    def _auction(x: dict) -> Auction:
        # TODO: adapter les noms de champs
        return Auction(
            id=str(x["id"]),
            card_id=str(x["cardId"]),
            current_bid=x.get("currentBid"),
            start_price=x.get("startPrice"),
            bids=x.get("bidCount", 0),
            ends_at=int(x["endsAt"]),
            seller=x.get("sellerName"),
            leader_is_me=bool(x.get("isMyBidHighest", False)),
        )

    # ======================= ÉCRITURE =======================
    # Pas d'ouverture de packs ici : interdit par les règles du jeu.
    async def place_bid(self, auction_id: str, amount: float) -> dict:
        # Confirmé par le HAR : POST /api/marketplace/{id}/bid  {"amount": <int>}
        return await self._req("POST", f"/api/marketplace/{auction_id}/bid", json={"amount": int(amount)})

    async def create_listing(self, card_id: str, start_price: float, duration_s: int) -> dict:
        # TODO: il faut souvent l'id d'INSTANCE de la carte (via get_inventory), pas l'id de carte
        return await self._req("POST", "/api/auctions",
                               json={"cardId": card_id, "startPrice": start_price, "duration": duration_s})

    async def cancel_listing(self, auction_id: str) -> dict:
        return await self._req("DELETE", f"/api/auctions/{auction_id}")

    async def send_trade_offer(self, trade: dict) -> dict:
        return await self._req("POST", "/api/trades", json=trade)

    async def aclose(self) -> None:
        await self.client.aclose()
