"""Configuration lue depuis l'environnement (ou un fichier .env)."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


@dataclass(frozen=True)
class Config:
    # "mock" = données simulées ; "wikimasters" = le vrai site (à compléter)
    adapter: str = _env("WM_ADAPTER", "mock")
    db_path: str = _env("WM_DB_PATH", "data/wm.sqlite")

    base_url: str = _env("WM_BASE_URL", "https://www.wiki-masters.com")
    # Copie depuis DevTools (ta propre session). Ne jamais committer.
    cookie: str = _env("WM_COOKIE", "")
    bearer: str = _env("WM_BEARER", "")

    poll_auctions_s: float = float(_env("WM_POLL_AUCTIONS_S", "5"))
    poll_sales_s: float = float(_env("WM_POLL_SALES_S", "15"))
    max_concurrency: int = int(_env("WM_MAX_CONCURRENCY", "4"))

    # ----- garde-fous d'écriture -----
    # true par défaut : les ordres sont journalisés mais PAS envoyés au site.
    dry_run: bool = _env("WM_DRY_RUN", "true").lower() == "true"
    max_bid: float = float(_env("WM_MAX_BID", "500"))            # plafond par mise
    daily_budget: float = float(_env("WM_DAILY_BUDGET", "2000"))  # plafond de mises envoyées / 24 h
    min_order_interval_s: float = float(_env("WM_MIN_ORDER_INTERVAL_S", "1.5"))  # anti-rafale
    automation_tick_s: float = float(_env("WM_AUTOMATION_TICK_S", "1"))

    static_dir: str = _env("WM_STATIC_DIR", "../frontend/dist")


cfg = Config()
