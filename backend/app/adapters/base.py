"""Contrat entre le collecteur / l'exécuteur et une source de données.

Tout ce qui est spécifique au site (URL, format JSON, auth) vit dans un adaptateur.
Le reste du projet ne connaît que Card / Sale / Auction / OrderRequest.
"""
from typing import AsyncIterator, Protocol

from ..models import Auction, Card, Sale


class Adapter(Protocol):
    # Le site expose-t-il un historique des ventes ? Sinon le collecteur
    # déduit les ventes des enchères qui disparaissent avec au moins une mise.
    supports_sales: bool
    # Le site pousse-t-il des événements (WebSocket / SSE) ?
    supports_stream: bool

    # ----- lecture -----
    async def list_open_auctions(self) -> list[Auction]: ...
    async def list_recent_sales(self, since_ms: int) -> list[Sale]: ...
    async def get_card(self, card_id: str) -> Card | None: ...
    async def get_balance(self) -> float | None: ...
    async def get_inventory(self) -> list[dict]: ...  # [{"card_id":..., "qty":..., "instance_id":...}]
    def stream(self) -> AsyncIterator[dict]: ...

    # ----- écriture -----
    # Chaque méthode renvoie la réponse brute du site (dict) ou lève une exception.
    # Il n'y a PAS de méthode d'ouverture de packs, et il ne faut pas en ajouter.
    async def place_bid(self, auction_id: str, amount: float) -> dict: ...
    async def create_listing(self, card_id: str, start_price: float, duration_s: int) -> dict: ...
    async def cancel_listing(self, auction_id: str) -> dict: ...
    async def send_trade_offer(self, trade: dict) -> dict: ...

    async def aclose(self) -> None: ...
