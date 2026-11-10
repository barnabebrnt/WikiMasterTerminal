from typing import Literal

from pydantic import BaseModel, Field


class Card(BaseModel):
    id: str
    name: str
    rarity: str | None = None
    attack: float | None = None
    defense: float | None = None
    url: str | None = None


class Sale(BaseModel):
    """Une transaction réalisée (fin d'enchère avec gagnant, ou échange avec prix)."""
    id: str
    card_id: str
    price: float
    ts: int  # epoch ms
    kind: str = "auction"
    inferred: bool = False  # True = déduite d'une enchère disparue, pas lue directement


class Auction(BaseModel):
    """Une enchère ouverte = une ligne du « carnet »."""
    id: str
    card_id: str
    current_bid: float | None = None
    start_price: float | None = None
    bids: int = 0
    ends_at: int  # epoch ms
    seller: str | None = None
    leader_is_me: bool = False


# ---------- écriture ----------
# Liste FERMÉE des actions possibles. L'ouverture de packs n'en fait pas partie,
# volontairement : elle est interdite par les règles du jeu.
OrderKind = Literal["bid", "list", "cancel_listing", "trade_offer"]


class OrderRequest(BaseModel):
    kind: OrderKind
    card_id: str | None = None
    auction_id: str | None = None   # bid / cancel_listing
    amount: float | None = None     # mise, ou prix de départ d'une mise en vente
    duration_s: int | None = None   # mise en vente
    trade: dict | None = None       # trade_offer : {"to": ..., "give": [...], "want": [...]}
    source: str = "manual"          # "manual" ou "rule:<id>"


class OrderResult(BaseModel):
    id: int
    status: Literal["dry_run", "sent", "rejected", "error"]
    reason: str | None = None
    response: dict | None = None


class Rule(BaseModel):
    """Automatisme. Types fournis : alert, auto_bid. Ajoute les tiens dans automation.py."""
    id: int | None = None
    kind: Literal["alert", "auto_bid"]
    card_id: str
    enabled: bool = True
    params: dict = Field(default_factory=dict)
    # alert    : {"below": 120} et/ou {"above": 300}, {"book_below": 100}
    # auto_bid : {"max_price": 150, "increment": 5, "last_seconds": 20}
