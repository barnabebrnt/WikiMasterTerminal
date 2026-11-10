"""API HTTP + WebSocket. Lancer : uvicorn app.main:app --reload (depuis backend/)."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .adapters import make_adapter
from .analytics import candles, stats
from .automation import Automation
from .collector import Collector
from .config import cfg
from .db import DB, now_ms
from .executor import Executor
from .hub import Hub
from .models import OrderRequest, Rule

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

DAY = 86_400_000
BUCKETS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}

db = DB(cfg.db_path)
hub = Hub()
adapter = make_adapter(cfg)
collector = Collector(adapter, db, hub, cfg)
executor = Executor(adapter, db, hub, cfg)
automation = Automation(db, hub, executor, cfg)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.open()
    tasks = [asyncio.create_task(collector.run()), asyncio.create_task(automation.run())]
    yield
    for t in tasks:
        t.cancel()
    await adapter.aclose()
    await db.close()


app = FastAPI(title="WikiMasters Terminal", lifespan=lifespan)


# ---------------- lecture ----------------
@app.get("/api/health")
async def health():
    return {"adapter": cfg.adapter, **collector.health, "executor": executor.state()}


@app.get("/api/cards")
async def list_cards(q: str | None = None, sort: str = "volume_24h", limit: int = 300):
    """Screener : toutes les cartes avec stats + résumé du carnet."""
    now = now_ms()
    grouped = await db.sales_since_grouped(now - 7 * DAY)
    book = await db.book_summary()
    rows = []
    for c in await db.cards(q):
        rows.append({**c.model_dump(), **stats(grouped.get(c.id, []), now),
                     **book.get(c.id, {"open_auctions": 0, "book_low": None,
                                       "book_high": None, "next_end": None})})
    rows.sort(key=lambda r: (r.get(sort) is None, -(r.get(sort) or 0)))
    return rows[:limit]


@app.get("/api/cards/{card_id}")
async def card_detail(card_id: str, days: int = 30):
    c = await db.card(card_id)
    if not c:
        raise HTTPException(404, "carte inconnue")
    sales = await db.sales_for(card_id, now_ms() - days * DAY)
    return {**c.model_dump(), "stats": stats(sales, now_ms())}


@app.get("/api/cards/{card_id}/sales")
async def card_sales(card_id: str, days: int = 7):
    return [s.model_dump() for s in await db.sales_for(card_id, now_ms() - days * DAY)]


@app.get("/api/cards/{card_id}/candles")
async def card_candles(card_id: str, bucket: str = "1h", days: int = 7):
    if bucket not in BUCKETS:
        raise HTTPException(400, f"bucket ∈ {list(BUCKETS)}")
    return candles(await db.sales_for(card_id, now_ms() - days * DAY), BUCKETS[bucket])


@app.get("/api/book")
async def order_book(card_id: str | None = None):
    """Carnet : enchères ouvertes, de la plus proche de la fin à la plus lointaine."""
    return [a.model_dump() for a in (await db.open_auctions(card_id)).values()]


@app.get("/api/tape")
async def tape(limit: int = 200):
    return [s.model_dump() for s in await db.recent_sales(limit)]


@app.get("/api/account")
async def account():
    bal, inv = await asyncio.gather(adapter.get_balance(), adapter.get_inventory())
    return {"balance": bal, "inventory": inv}


# ---------------- écriture ----------------
@app.post("/api/orders")
async def place_order(req: OrderRequest):
    req = req.model_copy(update={"source": "manual"})
    return await executor.submit(req)


@app.get("/api/orders")
async def list_orders(limit: int = 200):
    return await db.orders(limit)


class ExecutorPatch(BaseModel):
    dry_run: bool | None = None
    killed: bool | None = None


@app.patch("/api/executor")
async def patch_executor(p: ExecutorPatch):
    if p.dry_run is not None:
        executor.dry_run = p.dry_run
    if p.killed is not None:
        executor.killed = p.killed
    hub.publish("executor", executor.state())
    return executor.state()


@app.get("/api/rules")
async def get_rules():
    return await db.rules()


@app.post("/api/rules")
async def upsert_rule(rule: Rule):
    if rule.kind == "auto_bid" and "max_price" not in rule.params:
        raise HTTPException(400, "auto_bid : params.max_price requis")
    return await db.save_rule(rule)


@app.delete("/api/rules/{rule_id}")
async def remove_rule(rule_id: int):
    await db.delete_rule(rule_id)
    return {"ok": True}


# ---------------- temps réel ----------------
@app.websocket("/api/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    q = hub.subscribe()
    try:
        await sock.send_json({"type": "executor", "data": executor.state()})
        while True:
            await sock.send_json(await q.get())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unsubscribe(q)


# Interface compilée (prod / SBC). En dev, Vite sert le front sur :5173.
if os.path.isdir(cfg.static_dir):
    app.mount("/", StaticFiles(directory=cfg.static_dir, html=True), name="ui")
