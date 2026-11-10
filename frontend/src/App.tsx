import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, type Account, type Auction, type Candle, type ExecState, type Row, type Sale } from './api';
import { useLive, type LiveEvent } from './useLive';
import { Chart } from './components/Chart';
import { Book, Rules, Screener, Stats, Tape, Ticket } from './components/Panels';

const BUCKETS: [string, number][] = [['5m', 1], ['15m', 2], ['1h', 7], ['4h', 14], ['1d', 30]];

function loadFavs(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem('wm.favs') ?? '[]')); } catch { return new Set(); }
}

export default function App() {
  const [rows, setRows] = useState<Row[]>([]);
  const [sort, setSort] = useState<keyof Row>('volume_24h');
  const [q, setQ] = useState('');
  const [onlyFavs, setOnlyFavs] = useState(false);
  const [favs, setFavs] = useState<Set<string>>(loadFavs);
  const [sel, setSel] = useState<string | null>(null);
  const [bucket, setBucket] = useState(2);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [book, setBook] = useState<Auction[]>([]);
  const [picked, setPicked] = useState<Auction | null>(null);
  const [tape, setTape] = useState<Sale[]>([]);
  const [exec, setExec] = useState<ExecState | null>(null);
  const [account, setAccount] = useState<Account | null>(null);
  const [logs, setLogs] = useState<{ t: number; msg: string; kind: string }[]>([]);
  const [now, setNow] = useState(Date.now());
  const search = useRef<HTMLInputElement>(null);
  const selRef = useRef(sel);
  selRef.current = sel;

  const log = useCallback((msg: string, kind = 'info') =>
    setLogs((l) => [{ t: Date.now(), msg, kind }, ...l].slice(0, 50)), []);

  // ---------- chargements ----------
  const loadRows = useCallback(() => api.cards(String(sort)).then(setRows).catch((e) => log(String(e), 'err')), [sort, log]);
  useEffect(() => { loadRows(); const i = setInterval(loadRows, 10_000); return () => clearInterval(i); }, [loadRows]);
  useEffect(() => { api.tape().then(setTape); api.account().then(setAccount); }, []);
  useEffect(() => { const i = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(i); }, []);
  useEffect(() => { const i = setInterval(() => api.account().then(setAccount).catch(() => {}), 15_000); return () => clearInterval(i); }, []);

  const loadCard = useCallback(() => {
    if (!sel) return;
    const [b, days] = BUCKETS[bucket];
    api.candles(sel, b, days).then(setCandles);
    api.book(sel).then(setBook);
  }, [sel, bucket]);
  useEffect(() => { setPicked(null); loadCard(); }, [loadCard]);
  useEffect(() => { if (!sel && rows.length) setSel(rows[0].id); }, [rows, sel]);

  // rafraîchissement groupé pour ne pas marteler l'API à chaque événement
  const pending = useRef<number | null>(null);
  const scheduleCard = useCallback(() => {
    if (pending.current) return;
    pending.current = window.setTimeout(() => { pending.current = null; loadCard(); }, 700);
  }, [loadCard]);

  // ---------- temps réel ----------
  const connected = useLive((e: LiveEvent) => {
    switch (e.type) {
      case 'sale':
        setTape((t) => [e.data, ...t].slice(0, 300));
        if (e.data.card_id === selRef.current) scheduleCard();
        break;
      case 'auction':
      case 'auction_closed':
        if (e.data.card_id === selRef.current) scheduleCard();
        setPicked((p) => (p && p.id === e.data.id && e.type === 'auction' ? e.data : p));
        break;
      case 'executor': setExec(e.data); break;
      case 'order': {
        const { request: r, result: s } = e.data;
        if (r.source !== 'manual') log(`[${r.source}] ${r.kind} ${r.amount ?? ''} → ${s.status}${s.reason ? ' : ' + s.reason : ''}`, s.status === 'sent' ? 'ok' : 'info');
        break;
      }
      case 'alert': log(`🔔 ${e.data.message}`, 'alert'); break;
    }
  });

  // ---------- dérivés ----------
  const names = useMemo(() => new Map(rows.map((r) => [r.id, r.name])), [rows]);
  const shown = useMemo(() => {
    const s = q.toLowerCase();
    return rows.filter((r) => (!onlyFavs || favs.has(r.id)) && (!s || r.name.toLowerCase().includes(s)));
  }, [rows, q, onlyFavs, favs]);
  const row = rows.find((r) => r.id === sel);

  const toggleFav = useCallback((id: string) => setFavs((f) => {
    const n = new Set(f); n.has(id) ? n.delete(id) : n.add(id);
    try { localStorage.setItem('wm.favs', JSON.stringify([...n])); } catch { /* stockage indisponible */ }
    return n;
  }), []);

  // ---------- clavier ----------
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement).tagName.match(/INPUT|SELECT|TEXTAREA/);
      if (e.key === 'Escape') { setQ(''); (document.activeElement as HTMLElement)?.blur(); return; }
      if (typing) { if (e.key === 'Enter' && shown[0]) setSel(shown[0].id); return; }
      const i = shown.findIndex((r) => r.id === sel);
      if (e.key === '/') { e.preventDefault(); search.current?.focus(); }
      else if (e.key === 'j' || e.key === 'ArrowDown') { e.preventDefault(); shown[i + 1] && setSel(shown[i + 1].id); }
      else if (e.key === 'k' || e.key === 'ArrowUp') { e.preventDefault(); shown[i - 1] && setSel(shown[i - 1].id); }
      else if (e.key === 'f' && sel) toggleFav(sel);
      else if (e.key === 'w') setOnlyFavs((v) => !v);
      else if (e.key >= '1' && e.key <= '5') setBucket(Number(e.key) - 1);
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [shown, sel, toggleFav]);

  return (
    <div className="app">
      <header>
        <b className="logo">WM▸TERM</b>
        <input ref={search} value={q} onChange={(e) => setQ(e.target.value)} placeholder="/ rechercher une carte…" />
        <button className={onlyFavs ? 'on' : ''} onClick={() => setOnlyFavs((v) => !v)}>★ watchlist (w)</button>
        <span className="spacer" />
        <span className={`dot ${connected ? 'ok' : 'ko'}`} title="flux temps réel" />
        {exec && (
          <>
            <button className={exec.dry_run ? 'dry' : 'live'}
              onClick={() => (exec.dry_run && !confirm('Passer en mode RÉEL ? Les ordres seront envoyés au jeu.')) ? null : api.executor({ dry_run: !exec.dry_run })}>
              {exec.dry_run ? 'SIMULATION' : 'RÉEL'}
            </button>
            <button className={exec.killed ? 'killed' : 'kill'} onClick={() => api.executor({ killed: !exec.killed })}>
              {exec.killed ? 'REPRENDRE' : 'STOP'}
            </button>
          </>
        )}
      </header>

      <section className="p-screener">
        <h3>Marché <span className="dim">{shown.length} cartes · j/k naviguer · f favori</span></h3>
        <Screener rows={shown} selected={sel} onSelect={setSel} favs={favs} sort={sort} onSort={setSort} />
      </section>

      <section className="p-chart">
        <h3>
          {row?.name ?? '—'}
          <span className="buckets">{BUCKETS.map(([b], i) => (
            <button key={b} className={i === bucket ? 'on' : ''} onClick={() => setBucket(i)}>{b}</button>
          ))}</span>
        </h3>
        <Chart data={candles} />
      </section>

      <section className="p-tape"><h3>Ventes en direct</h3><Tape sales={tape} names={names} onSelect={setSel} /></section>

      <section className="p-side">
        <Stats r={row} />
        <h3>Carnet <span className="dim">{book.length} enchères</span></h3>
        <Book book={book} now={now} onPick={setPicked} />
      </section>

      <section className="p-ticket">
        <h3>Ordre</h3>
        <Ticket cardId={sel} picked={picked} account={account} exec={exec} log={log} />
        <h3>Automatismes</h3>
        <Rules cardId={sel} names={names} log={log} />
      </section>

      <footer>
        {logs.slice(0, 3).map((l) => <span key={l.t + l.msg} className={`log ${l.kind}`}>{new Date(l.t).toLocaleTimeString('fr-FR')} {l.msg}</span>)}
      </footer>
    </div>
  );
}
