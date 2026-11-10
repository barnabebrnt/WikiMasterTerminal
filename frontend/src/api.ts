export type Card = {
  id: string; name: string; rarity: string | null; attack: number | null; defense: number | null; url: string | null;
};
export type Row = Card & {
  last: number | null; last_ts: number | null; change_24h: number | null; volume_24h: number;
  avg_24h: number | null; median_7d: number | null; high_7d: number | null; low_7d: number | null;
  vol_trade: number | null; vol_daily: number | null;
  open_auctions: number; book_low: number | null; book_high: number | null; next_end: number | null;
};
export type Sale = { id: string; card_id: string; price: number; ts: number; kind: string; inferred: boolean };
export type Auction = {
  id: string; card_id: string; current_bid: number | null; start_price: number | null;
  bids: number; ends_at: number; seller: string | null; leader_is_me: boolean;
};
export type Candle = { t: number; o: number; h: number; l: number; c: number; v: number };
export type ExecState = { dry_run: boolean; killed: boolean; max_bid: number; daily_budget: number };
export type OrderResult = { id: number; status: 'dry_run' | 'sent' | 'rejected' | 'error'; reason: string | null };
export type Rule = { id?: number; kind: 'alert' | 'auto_bid'; card_id: string; enabled: boolean; params: Record<string, number> };
export type Account = { balance: number | null; inventory: { card_id: string; qty: number }[] };

async function j<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { headers: { 'content-type': 'application/json' }, ...init });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export const api = {
  cards: (sort = 'volume_24h') => j<Row[]>(`/api/cards?sort=${sort}`),
  candles: (id: string, bucket: string, days: number) => j<Candle[]>(`/api/cards/${id}/candles?bucket=${bucket}&days=${days}`),
  book: (id?: string) => j<Auction[]>(`/api/book${id ? `?card_id=${id}` : ''}`),
  tape: () => j<Sale[]>('/api/tape?limit=150'),
  account: () => j<Account>('/api/account'),
  order: (body: object) => j<OrderResult>('/api/orders', { method: 'POST', body: JSON.stringify(body) }),
  executor: (patch: Partial<ExecState>) => j<ExecState>('/api/executor', { method: 'PATCH', body: JSON.stringify(patch) }),
  rules: () => j<Rule[]>('/api/rules'),
  saveRule: (r: Rule) => j<Rule>('/api/rules', { method: 'POST', body: JSON.stringify(r) }),
  deleteRule: (id: number) => j('/api/rules/' + id, { method: 'DELETE' }),
};

export const fmt = (n: number | null | undefined, d = 1) =>
  n == null ? '—' : n.toLocaleString('fr-FR', { maximumFractionDigits: d, minimumFractionDigits: d });
export const pct = (n: number | null | undefined) => (n == null ? '—' : `${n >= 0 ? '+' : ''}${(n * 100).toFixed(1)}%`);
export const hhmmss = (ts: number) => new Date(ts).toLocaleTimeString('fr-FR');
export const left = (ms: number) => {
  if (ms <= 0) return 'fini';
  const s = Math.floor(ms / 1000);
  return s >= 3600 ? `${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}`
    : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};
export const volp = (n: number | null | undefined) => (n == null ? '—' : `${(n * 100).toFixed(1)}%`);
