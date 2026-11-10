// À coller dans la console DevTools, sur un onglet www.wiki-masters.com où tu es connecté.
// Lecture seule : appelle les endpoints de marché et copie dans le presse-papier la FORME des
// réponses JSON avec un exemple de valeur tronqué. N'envoie aucun ordre, n'ouvre aucun pack.
(async () => {
  const shape = (v, d = 4) => {
    if (d < 0) return '…';
    if (Array.isArray(v)) return v.length ? [shape(v[0], d - 1), `×${v.length}`] : [];
    if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).slice(0, 50).map(([k, x]) => [k, shape(x, d - 1)]));
    if (typeof v === 'string') return /token|jwt|secret|email|password/i.test(v) ? 'str<masqué>' : `str: ${v.slice(0, 40)}`;
    return `${typeof v}: ${v}`;
  };
  const get = async (u) => { const r = await fetch(u, { credentials: 'include' }); return { status: r.status, body: shape(await r.json().catch(() => null)) }; };

  const out = {};
  const market = await fetch('/api/marketplace?page=1&limit=5&sort=recent', { credentials: 'include' }).then((r) => r.json());
  out['GET /api/marketplace'] = shape(market);
  const list = Array.isArray(market) ? market : Object.values(market).find(Array.isArray) ?? [];
  const first = list[0] ?? {};
  const auctionId = first.id;
  const cardId = first.card_id ?? first.cardId ?? first.card?.id;
  if (auctionId) out['GET /api/marketplace/{id}'] = await get(`/api/marketplace/${auctionId}`);
  if (cardId) out['GET /api/marketplace/cards/{id}/sales'] = await get(`/api/marketplace/cards/${cardId}/sales`);
  out['GET /api/wikibidous'] = await get('/api/wikibidous');
  out['GET /api/my-collection'] = await get('/api/my-collection?sort=rarity&page=0&stats=0');
  out['GET /api/trades'] = await get('/api/trades?active=1');
  out['GET /api/marketplace?page=2'] = await get('/api/marketplace?page=2&limit=5&sort=recent');

  const txt = JSON.stringify(out, null, 1);
  copy(txt);
  console.log(txt);
  console.log('✅ Copié dans le presse-papier : colle-le dans la conversation.');
})();
