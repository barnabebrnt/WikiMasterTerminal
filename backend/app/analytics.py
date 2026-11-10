"""Indicateurs calculés à partir de l'historique des ventes."""
import math
from statistics import median, pstdev

from .models import Sale

DAY = 86_400_000


def candles(sales: list[Sale], bucket_s: int) -> list[dict]:
    """OHLC + volume (nombre de ventes) par intervalle de temps."""
    out: list[dict] = []
    b_ms = bucket_s * 1000
    for s in sales:  # supposées triées par ts
        t = (s.ts // b_ms) * b_ms
        if out and out[-1]["t"] == t:
            c = out[-1]
            c["h"] = max(c["h"], s.price)
            c["l"] = min(c["l"], s.price)
            c["c"] = s.price
            c["v"] += 1
        else:
            out.append({"t": t, "o": s.price, "h": s.price, "l": s.price, "c": s.price, "v": 1})
    return out


def _log_returns(prices: list[float]) -> list[float]:
    return [math.log(b / a) for a, b in zip(prices, prices[1:]) if a > 0 and b > 0]


def stats(sales: list[Sale], now: int) -> dict:
    """Stats pour une carte. `sales` triées par ts, typiquement sur 7 à 30 jours."""
    if not sales:
        return {"last": None, "last_ts": None, "change_24h": None, "volume_24h": 0,
                "avg_24h": None, "median_7d": None, "high_7d": None, "low_7d": None,
                "vol_trade": None, "vol_daily": None}

    last = sales[-1]
    day = [s for s in sales if s.ts >= now - DAY]
    week = [s for s in sales if s.ts >= now - 7 * DAY]
    before = [s for s in sales if s.ts < now - DAY]
    ref = before[-1].price if before else None

    # Volatilité « par transaction » : écart-type des log-rendements entre ventes successives
    lr = _log_returns([s.price for s in sales[-50:]])
    vol_trade = pstdev(lr) if len(lr) >= 3 else None

    # Volatilité journalière : écart-type des log-rendements des clôtures quotidiennes
    closes: dict[int, float] = {}
    for s in sales:
        closes[s.ts // DAY] = s.price
    dlr = _log_returns([closes[k] for k in sorted(closes)])
    vol_daily = pstdev(dlr) if len(dlr) >= 3 else None

    return {
        "last": last.price,
        "last_ts": last.ts,
        "change_24h": (last.price / ref - 1) if ref else None,
        "volume_24h": len(day),
        "avg_24h": sum(s.price for s in day) / len(day) if day else None,
        "median_7d": median(s.price for s in week) if week else None,
        "high_7d": max((s.price for s in week), default=None),
        "low_7d": min((s.price for s in week), default=None),
        "vol_trade": vol_trade,
        "vol_daily": vol_daily,
    }
