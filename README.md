# WM Terminal

Terminal de trading façon IBKR pour **WikiMasters** : screener du marché, graphiques en chandeliers,
carnet des enchères ouvertes, flux des ventes en direct, ticket d'ordre et automatismes.

```
 navigateur ──HTTP/WS──▶ FastAPI ──▶ Executor (garde-fous) ──▶ Adapter ──▶ wiki-masters.com
                           │  ▲                                  ▲
                           │  └── Hub (événements temps réel)    │
                           ├──▶ Collector (polling / stream) ────┘
                           ├──▶ Automation (règles) ──▶ Executor
                           └──▶ SQLite (cartes, ventes, enchères, ordres, règles)
```

## Démarrage rapide (Mac mini, données simulées)

```bash
cp .env.example .env                       # WM_ADAPTER=mock par défaut

cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload    # http://localhost:8000/docs pour l'API

cd ../frontend && npm install && npm run dev   # http://localhost:5173
```

Le mode mock simule ~40 cartes, 7 jours d'historique et un marché vivant. Il accepte aussi
les ordres, ce qui permet de tester l'interface et les automatismes sans toucher au jeu.

## Brancher le vrai site

1. Chrome → DevTools → **Network**, coche *Preserve log*, filtre *Fetch/XHR* + *WS*.
2. Navigue à la main : marché, fiche d'une carte, mise, mise en vente, proposition d'échange.
3. Clic droit → *Save all as HAR with content* → `capture.har` (il contient ta session : ne le partage pas).
4. `python3 tools/har_explore.py capture.har --host wiki-masters > api.md`
   → liste des endpoints, des paramètres et de la **forme** des réponses JSON (tokens masqués).
5. Remplis les `TODO` de `backend/app/adapters/wikimasters.py`, puis mets `supports_sales` /
   `supports_stream` à `True` si tu trouves un historique des ventes ou un WebSocket.
6. Dans `.env` : `WM_ADAPTER=wikimasters` + `WM_COOKIE` (ou `WM_BEARER`) copié depuis DevTools.

S'il n'y a pas d'endpoint d'historique, le collecteur **déduit** les ventes des enchères qui
disparaissent avec au moins une mise (marquées `~` dans le flux). Attention à la pagination de
la liste des enchères : une page manquante ferait croire à de fausses ventes.

## Écriture et garde-fous

Toutes les écritures (manuelles **et** automatiques) passent par `executor.py` :

| Garde-fou | Réglage |
|---|---|
| Liste blanche : `bid`, `list`, `cancel_listing`, `trade_offer` | `models.OrderKind` ; **aucune** ouverture de packs |
| Mode simulation (journalise sans envoyer) | `WM_DRY_RUN=true` par défaut, bouton SIMULATION/RÉEL |
| Arrêt d'urgence (bloque tout, y compris les règles) | bouton STOP |
| Plafond par mise | `WM_MAX_BID` |
| Budget de mises envoyées sur 24 h glissantes | `WM_DAILY_BUDGET` |
| Intervalle minimal entre deux ordres | `WM_MIN_ORDER_INTERVAL_S` |
| Journal de chaque ordre, y compris les refus | table `orders`, `GET /api/orders` |

## Automatismes (`backend/app/automation.py`)

- **alert** `{below, above, book_below}` → notification dans le terminal.
- **auto_bid** `{max_price, increment, last_seconds?}` → surenchérit sur les enchères d'une carte
  tant que le prix reste ≤ `max_price` (optionnellement seulement dans les N dernières secondes).

Pour ajouter une règle : une méthode `_rule_<kind>` + l'ajouter au `Literal` de `models.Rule`.
Idées : relister automatiquement les invendus, alerte d'écart carnet / médiane 7 j,
arbitrage entre enchères d'une même carte.

## Raccourcis

`/` rechercher · `j`/`k` ou ↑/↓ naviguer · `f` favori · `w` watchlist seule · `1`–`5` unité de temps · `Échap` effacer

## Homelab (Rock 5T ou autre SBC arm64)

```bash
docker compose up -d --build     # interface + API sur http://<sbc>:8000
```

La collecte tourne alors 24 h/24, et l'historique s'accumule même quand le Mac dort.
Depuis le Mac, tu peux développer le front contre le SBC : `WM_API=http://rock5t.local:8000 npm run dev`.

⚠ L'interface n'a **pas d'authentification**. Garde-la sur ton LAN ou derrière Tailscale /
un reverse proxy avec mot de passe : n'importe qui y ayant accès peut passer des ordres.

## Pistes pour l'interface

L'interface est volontairement légère (React + [lightweight-charts](https://github.com/tradingview/lightweight-charts)
de TradingView, Apache-2.0). Pour aller plus loin sans réécrire :
- fenêtres déplaçables façon TWS : [FlexLayout](https://github.com/caplin/FlexLayout) ou [dockview](https://github.com/mathuo/dockview) ;
- grilles très denses (milliers de lignes) : [AG Grid Community](https://github.com/ag-grid/ag-grid) ;
- graphiques plus riches (indicateurs, outils de dessin) : [KLineChart](https://github.com/klinecharts/KLineChart).
