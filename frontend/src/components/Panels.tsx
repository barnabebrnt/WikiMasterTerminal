import { useEffect, useState } from 'react';
import { api, fmt, hhmmss, left, pct, volp, type Account, type Auction, type ExecState, type Row, type Rule, type Sale } from '../api';

/* ---------------- Screener ---------------- */
const COLS: [keyof Row, string, (r: Row) => string][] = [
  ['name', 'Carte', (r) => r.name],
  ['last', 'Dernier', (r) => fmt(r.last)],
  ['change_24h', 'Δ24h', (r) => pct(r.change_24h)],
  ['volume_24h', 'Vol', (r) => String(r.volume_24h)],
  ['vol_daily', 'σ j', (r) => volp(r.vol_daily)],
  ['book_low', 'Carnet', (r) => (r.open_auctions ? `${fmt(r.book_low)} ×${r.open_auctions}` : '—')],
];

export function Screener({ rows, selected, onSelect, favs, sort, onSort }: {
  rows: Row[]; selected: string | null; onSelect: (id: string) => void;
  favs: Set<string>; sort: keyof Row; onSort: (k: keyof Row) => void;
}) {
  return (
    <div className="scroll">
      <table>
        <thead>
          <tr>{COLS.map(([k, h]) => (
            <th key={k} onClick={() => onSort(k)} className={sort === k ? 'sorted' : ''}>{h}</th>
          ))}</tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className={r.id === selected ? 'sel' : ''} onClick={() => onSelect(r.id)}>
              {COLS.map(([k, , f]) => (
                <td key={k} className={k === 'change_24h' ? ((r.change_24h ?? 0) >= 0 ? 'up' : 'down') : k === 'name' ? 'name' : 'num'}>
                  {k === 'name' && favs.has(r.id) ? '★ ' : ''}{f(r)}
                  {k === 'name' && <span className={`rar ${r.rarity ?? ''}`}>{r.rarity?.[0]?.toUpperCase()}</span>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------------- Stats ---------------- */
export function Stats({ r }: { r?: Row }) {
  if (!r) return <div className="empty">Sélectionne une carte</div>;
  const items: [string, string][] = [
    ['Dernier', fmt(r.last)], ['Δ 24h', pct(r.change_24h)], ['Moy 24h', fmt(r.avg_24h)],
    ['Ventes 24h', String(r.volume_24h)], ['Médiane 7j', fmt(r.median_7d)],
    ['H/B 7j', `${fmt(r.high_7d)} / ${fmt(r.low_7d)}`],
    ['σ/vente', volp(r.vol_trade)], ['σ jour', volp(r.vol_daily)],
    ['Att / Déf', `${r.attack ?? '—'} / ${r.defense ?? '—'}`], ['Rareté', r.rarity ?? '—'],
  ];
  return (
    <div className="stats">
      <div className="title">
        {r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.name}</a> : r.name}
      </div>
      {items.map(([k, v]) => <div key={k} className="kv"><span>{k}</span><b>{v}</b></div>)}
    </div>
  );
}

/* ---------------- Carnet (enchères ouvertes) ---------------- */
export function Book({ book, now, onPick }: { book: Auction[]; now: number; onPick: (a: Auction) => void }) {
  if (!book.length) return <div className="empty">Aucune enchère ouverte</div>;
  return (
    <div className="scroll">
      <table>
        <thead><tr><th>Fin</th><th>Prix</th><th>Mises</th><th>Vendeur</th></tr></thead>
        <tbody>
          {book.map((a) => (
            <tr key={a.id} onClick={() => onPick(a)} className={a.leader_is_me ? 'mine' : ''}
                title="Cliquer pour préremplir le ticket">
              <td className={a.ends_at - now < 30_000 ? 'down num' : 'num'}>{left(a.ends_at - now)}</td>
              <td className="num">{fmt(a.current_bid ?? a.start_price)}</td>
              <td className="num">{a.bids}</td>
              <td>{a.leader_is_me ? '● moi' : a.seller}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------------- Tape (ventes en direct) ---------------- */
export function Tape({ sales, names, onSelect }: { sales: Sale[]; names: Map<string, string>; onSelect: (id: string) => void }) {
  return (
    <div className="scroll tape">
      {sales.map((s) => (
        <div key={s.id} className="tick" onClick={() => onSelect(s.card_id)}>
          <span className="dim">{hhmmss(s.ts)}</span>
          <span className="name">{names.get(s.card_id) ?? s.card_id}</span>
          <span className="num">{fmt(s.price)}</span>
          {s.inferred && <span className="dim" title="Déduite d'une enchère terminée">~</span>}
        </div>
      ))}
    </div>
  );
}

/* ---------------- Ticket d'ordre ---------------- */
export function Ticket({ cardId, picked, account, exec, log }: {
  cardId: string | null; picked: Auction | null; account: Account | null; exec: ExecState | null;
  log: (msg: string, kind?: string) => void;
}) {
  const [amount, setAmount] = useState('');
  const [listPrice, setListPrice] = useState('');
  const [duration, setDuration] = useState('3600');
  useEffect(() => {
    if (picked) setAmount(String(Math.ceil((picked.current_bid ?? picked.start_price ?? 0) + 1)));
  }, [picked?.id, picked?.current_bid]);

  const send = async (body: object) => {
    try {
      const r = await api.order(body);
      log(`#${r.id} ${r.status}${r.reason ? ' : ' + r.reason : ''}`, r.status === 'sent' ? 'ok' : r.status === 'dry_run' ? 'info' : 'err');
    } catch (e) { log(String(e), 'err'); }
  };
  const owned = account?.inventory.find((i) => i.card_id === cardId)?.qty ?? 0;

  return (
    <div className="ticket">
      <div className={`mode ${exec?.dry_run ? 'dry' : 'live'}`}>{exec?.dry_run ? 'SIMULATION' : 'RÉEL'}</div>
      <div className="row">
        <label>Enchère</label>
        <span className="dim">{picked ? `${picked.id.slice(0, 8)} · ${fmt(picked.current_bid ?? picked.start_price)}` : 'clique une ligne du carnet'}</span>
      </div>
      <div className="row">
        <input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Mise" inputMode="decimal" />
        <button className="buy" disabled={!picked}
          onClick={() => send({ kind: 'bid', auction_id: picked!.id, card_id: picked!.card_id, amount: Number(amount) })}>
          Miser
        </button>
      </div>
      <hr />
      <div className="row"><label>Vendre</label><span className="dim">possédées : {owned}</span></div>
      <div className="row">
        <input value={listPrice} onChange={(e) => setListPrice(e.target.value)} placeholder="Prix départ" inputMode="decimal" />
        <select value={duration} onChange={(e) => setDuration(e.target.value)}>
          <option value="900">15 min</option><option value="3600">1 h</option>
          <option value="21600">6 h</option><option value="86400">24 h</option>
        </select>
        <button className="sell" disabled={!cardId || !owned}
          onClick={() => send({ kind: 'list', card_id: cardId, amount: Number(listPrice), duration_s: Number(duration) })}>
          Lister
        </button>
      </div>
      {picked?.seller === 'me' && (
        <button onClick={() => send({ kind: 'cancel_listing', auction_id: picked.id, card_id: picked.card_id })}>
          Annuler ma vente
        </button>
      )}
      <div className="dim small">Solde : {fmt(account?.balance)} · plafond/mise {fmt(exec?.max_bid, 0)} · budget 24 h {fmt(exec?.daily_budget, 0)}</div>
    </div>
  );
}

/* ---------------- Automatismes ---------------- */
export function Rules({ cardId, names, log }: { cardId: string | null; names: Map<string, string>; log: (m: string, k?: string) => void }) {
  const [rules, setRules] = useState<Rule[]>([]);
  const [kind, setKind] = useState<'auto_bid' | 'alert'>('auto_bid');
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const refresh = () => api.rules().then(setRules).catch(() => {});
  useEffect(() => { refresh(); }, []);

  const add = async () => {
    if (!cardId) return;
    const params: Record<string, number> = kind === 'auto_bid'
      ? { max_price: Number(a), increment: Number(b || 1) }
      : { ...(a ? { below: Number(a) } : {}), ...(b ? { above: Number(b) } : {}) };
    try { await api.saveRule({ kind, card_id: cardId, enabled: true, params }); refresh(); }
    catch (e) { log(String(e), 'err'); }
  };

  return (
    <div className="rules">
      <div className="row">
        <select value={kind} onChange={(e) => setKind(e.target.value as any)}>
          <option value="auto_bid">auto-mise</option><option value="alert">alerte</option>
        </select>
        <input value={a} onChange={(e) => setA(e.target.value)} placeholder={kind === 'auto_bid' ? 'prix max' : 'si <'} />
        <input value={b} onChange={(e) => setB(e.target.value)} placeholder={kind === 'auto_bid' ? 'pas' : 'si >'} />
        <button disabled={!cardId} onClick={add}>+</button>
      </div>
      <div className="scroll">
        {rules.map((r) => (
          <div key={r.id} className={`rule ${r.enabled ? '' : 'off'}`}>
            <span>{r.kind === 'auto_bid' ? '⚙' : '🔔'} {names.get(r.card_id) ?? r.card_id}</span>
            <span className="dim">{Object.entries(r.params).map(([k, v]) => `${k}=${v}`).join(' ')}</span>
            <button onClick={async () => { await api.saveRule({ ...r, enabled: !r.enabled }); refresh(); }}>{r.enabled ? 'on' : 'off'}</button>
            <button onClick={async () => { await api.deleteRule(r.id!); refresh(); }}>×</button>
          </div>
        ))}
      </div>
    </div>
  );
}
