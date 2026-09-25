/* MTGA Companion UI. Vanilla JS, no build step -- the backend is pure Python
   and a single-user local app does not justify a second toolchain. */

const $ = (sel, root = document) => root.querySelector(sel);
const main = $('#main');

const api = async (path) => {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
};

const el = (tag, attrs = {}, ...kids) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid.nodeType ? kid : document.createTextNode(kid));
  }
  return node;
};

const fmtNum = (n) => (n === null || n === undefined ? '—' : n.toLocaleString());
const colorClass = (c) => (c || '').split(',').filter(Boolean).join('');

/* Card display mode is a preference, not per-page state: someone who wants
   dense tables wants them everywhere, and wants that to survive a reload. */
const displayMode = {
  get: () => localStorage.getItem('cardDisplay') || 'grid',
  set: (v) => { localStorage.setItem('cardDisplay', v); render(); },
};

function displayToggle() {
  const mode = displayMode.get();
  return el('div', { class: 'toggle' },
    el('button', {
      class: mode === 'grid' ? 'active' : '',
      onclick: () => displayMode.set('grid'),
    }, 'Images'),
    el('button', {
      class: mode === 'table' ? 'active' : '',
      onclick: () => displayMode.set('table'),
    }, 'Table'));
}

/* ------------------------------------------------------------------ cards */

function cardTile(card) {
  const qty = card.quantity ?? card.owned;
  const unowned = card.owned === 0;
  return el('div', { class: 'cardtile', title: card.name },
    card.image_uri
      ? el('img', { src: card.image_uri, alt: card.name, loading: 'lazy' })
      : el('div', { class: 'fallback' },
          el('strong', {}, card.name), el('br'), card.mana_cost || '',
          el('br'), card.type_line || ''),
    qty ? el('div', { class: 'qty' }, `${qty}×`) : null,
    unowned ? el('div', { class: 'unowned' }, 'not owned') : null);
}

function cardTable(cards) {
  return el('table', {},
    el('thead', {}, el('tr', {},
      el('th', { class: 'num' }, 'Qty'), el('th', {}, 'Name'),
      el('th', {}, 'Cost'), el('th', { class: 'num' }, 'MV'),
      el('th', {}, 'Type'), el('th', {}, 'Rarity'), el('th', {}, 'Set'))),
    el('tbody', {}, cards.map((c) => el('tr', {},
      el('td', { class: 'num' }, fmtNum(c.quantity ?? c.owned ?? '')),
      el('td', {}, c.name),
      el('td', {}, c.mana_cost || ''),
      el('td', { class: 'num' }, c.cmc ?? ''),
      el('td', {}, (c.type_line || '').split('—')[0].trim()),
      el('td', {}, el('span', { class: `pill ${c.rarity || ''}` }, c.rarity || '')),
      el('td', {}, (c.set_code || '').toUpperCase())))));
}

const cardList = (cards) => (
  cards.length === 0
    ? el('div', { class: 'empty' }, 'Nothing matches those filters.')
    : displayMode.get() === 'grid'
      ? el('div', { class: 'cardgrid' }, cards.map(cardTile))
      : cardTable(cards));

/* -------------------------------------------------------------- dashboard */

const stat = (label, value, sub) =>
  el('div', { class: 'panel stat' },
    el('div', { class: 'label' }, label),
    el('div', { class: 'value' }, value),
    sub ? el('div', { class: 'sub' }, sub) : null);

async function viewDashboard() {
  const s = await api('/api/summary');
  const inv = s.inventory || {};
  const rank = s.rank || {};
  const st = s.status || {};
  const wrap = el('div', {});

  if (st.detailed_logs_enabled === false) {
    wrap.append(el('div', { class: 'banner warn' },
      el('strong', {}, 'Arena is not writing game data. '), st.action_required || ''));
  }

  const record = (rank.constructed_won ?? null) !== null
    ? `${rank.constructed_won}–${rank.constructed_lost}` : '—';
  const wr = rank.constructed_won && (rank.constructed_won + rank.constructed_lost)
    ? Math.round(100 * rank.constructed_won / (rank.constructed_won + rank.constructed_lost))
    : null;

  wrap.append(
    el('h2', {}, 'Overview'),
    el('div', { class: 'grid cols-4' },
      stat('Constructed', record, wr !== null ? `${wr}% win rate · level ${rank.constructed_level ?? '—'}` : null),
      stat('Limited level', fmtNum(rank.limited_level), 'season rank'),
      stat('Your decks', fmtNum(s.decks), 'excluding Arena precons'),
      stat('Known cards', fmtNum(s.owned_total), 'lower bound')),
    el('h3', { style: 'margin-top:22px' }, 'Wildcards & currency'),
    el('div', { class: 'grid cols-4' },
      stat('Common', fmtNum(inv.wc_common)),
      stat('Uncommon', fmtNum(inv.wc_uncommon)),
      stat('Rare', fmtNum(inv.wc_rare)),
      stat('Mythic', fmtNum(inv.wc_mythic)),
      stat('Gold', fmtNum(inv.gold)),
      stat('Gems', fmtNum(inv.gems)),
      stat('Vault', inv.vault_progress != null ? `${inv.vault_progress}%` : '—')),
    el('h3', { style: 'margin-top:22px' }, 'Known collection by rarity'),
    el('div', { class: 'grid cols-4' },
      ['mythic', 'rare', 'uncommon', 'common'].map((r) =>
        stat(r, fmtNum(s.owned_by_rarity?.[r] ?? 0), 'distinct cards'))));

  if (st.unverified_note) {
    wrap.append(el('div', { class: 'banner', style: 'margin-top:20px' },
      el('strong', {}, 'Not yet captured: '), st.unverified_note));
  }
  return wrap;
}

/* ------------------------------------------------------------------ decks */

let deckState = { id: null, includePrecon: false };

function curveChart(curve) {
  const entries = Object.entries(curve || {});
  if (!entries.length) return null;
  const max = Math.max(...entries.map(([, v]) => v));
  return el('div', { class: 'bar' }, entries.map(([mv, n]) =>
    el('div', { class: 'col' },
      el('div', { class: 'n' }, n),
      el('div', { class: 'fill', style: `height:${(n / max) * 80}px` }),
      el('div', { class: 'n' }, mv))));
}

async function viewDecks() {
  if (deckState.id) return viewDeckDetail(deckState.id);
  const decks = await api(`/api/decks?include_precon=${deckState.includePrecon ? 1 : 0}`);
  return el('div', {},
    el('h2', {}, 'Decks'),
    el('div', { class: 'toolbar' },
      el('label', {},
        el('input', {
          type: 'checkbox', ...(deckState.includePrecon ? { checked: 'checked' } : {}),
          onchange: (e) => { deckState.includePrecon = e.target.checked; render(); },
        }),
        ' Include Arena’s preconstructed decks')),
    decks.length === 0
      ? el('div', { class: 'empty' }, 'No decks found yet.')
      : el('div', { class: 'grid cols-2' }, decks.map((d) =>
          el('div', {
            class: 'panel clickable',
            onclick: () => { deckState.id = d.deck_id; render(); },
          },
            el('div', { style: 'display:flex;justify-content:space-between;gap:10px' },
              el('strong', {}, d.name || '(unnamed)'),
              el('span', { style: 'display:flex;gap:6px' },
                d.playstyle ? el('span', { class: 'pill' }, d.playstyle) : null,
                el('span', { class: `pill ${colorClass(d.colors)}` }, d.colors || '—'))),
            el('div', { class: 'muted', style: 'margin-top:6px;font-size:12px' },
              `${d.format || 'no format'} · ${d.mainboard_size} cards`
              + (d.sideboard_size ? ` · ${d.sideboard_size} sideboard` : '')),
            d.description ? el('div', {
              class: 'muted', style: 'font-size:12px;margin-top:4px;'
                + 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap',
            }, d.description) : null,
            el('div', { class: 'muted', style: 'font-size:12px;margin-top:2px' },
              d.last_played ? `last played ${d.last_played.slice(0, 10)}` : 'never played')))));
}

let notesDraft = null; // { deckId, description, playstyle, comments, recommendations }

function notesField(key, label, placeholder) {
  return el('div', { style: 'margin-bottom:10px' },
    el('div', { class: 'muted', style: 'font-size:12px;margin-bottom:4px' }, label),
    el('textarea', {
      placeholder, style: 'min-height:52px',
      onchange: (e) => { notesDraft[key] = e.target.value; },
    }, notesDraft[key]));
}

function notesPanel(deck) {
  if (!notesDraft || notesDraft.deckId !== deck.deck_id) {
    notesDraft = {
      deckId: deck.deck_id,
      description: deck.description || '',
      playstyle: deck.playstyle || '',
      comments: deck.comments || '',
      recommendations: deck.recommendations || '',
    };
  }
  return el('div', { class: 'panel', style: 'margin-bottom:18px' },
    el('div', { style: 'display:flex;justify-content:space-between;align-items:baseline' },
      el('h3', {}, 'Notes'),
      deck.notes_updated_at
        ? el('span', { class: 'muted', style: 'font-size:11px' },
            `updated ${deck.notes_updated_at.slice(0, 16)}`)
        : null),
    el('div', { style: 'margin-bottom:10px' },
      el('div', { class: 'muted', style: 'font-size:12px;margin-bottom:4px' }, 'Playstyle'),
      el('input', {
        type: 'text', placeholder: 'e.g. Aggro, Midrange, Control',
        value: notesDraft.playstyle,
        style: 'width:100%;background:var(--panel-2);border:1px solid var(--line);'
          + 'border-radius:8px;padding:7px 10px;color:inherit',
        onchange: (e) => { notesDraft.playstyle = e.target.value; },
      })),
    notesField('description', 'Description', "What this deck's plan is…"),
    notesField('comments', 'Comments', 'Free-form notes…'),
    notesField('recommendations', 'Recommendations', 'What to change or improve…'),
    el('button', {
      class: 'btn primary',
      onclick: async (e) => {
        const res = await fetch(`/api/decks/${encodeURIComponent(deck.deck_id)}/notes`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            description: notesDraft.description, playstyle: notesDraft.playstyle,
            comments: notesDraft.comments, recommendations: notesDraft.recommendations,
          }),
        });
        e.target.textContent = res.ok ? 'Saved' : 'Failed to save';
        setTimeout(render, 500);
      },
    }, 'Save notes'));
}

let improveState = null; // { deckId, focus, wcBudget, brief }

function improveDeckPanel(deck) {
  if (!improveState || improveState.deckId !== deck.deck_id) {
    improveState = {
      deckId: deck.deck_id, focus: '', brief: null,
      wcBudget: { common: '', uncommon: '', rare: '', mythic: '' },
    };
  }
  const panel = el('div', { class: 'panel', style: 'margin-bottom:18px' },
    el('h3', {}, 'Suggest improvements'),
    el('div', { class: 'muted', style: 'font-size:12px;margin-bottom:8px' },
      'Generates a brief for your MCP agent (Claude Code) to read this deck '
      + 'and propose changes — a quick note or a full revised build, saved '
      + 'back here without touching this deck.'),
    el('textarea', {
      placeholder: 'What to focus on (optional), e.g. "beat aggro" or "smooth the curve"',
      onchange: (e) => { improveState.focus = e.target.value; },
    }, improveState.focus),
    wildcardBudgetInputs(improveState.wcBudget),
    el('button', {
      class: 'btn primary', style: 'margin-top:10px',
      onclick: async (e) => {
        const qs = new URLSearchParams();
        if (improveState.focus) qs.set('focus', improveState.focus);
        for (const [r, v] of Object.entries(improveState.wcBudget)) {
          if (v !== '') qs.set(`max_${r}`, v);
        }
        improveState.brief = await api(
          `/api/decks/${encodeURIComponent(deck.deck_id)}/improve-brief?${qs}`);
        render();
      },
    }, 'Generate brief'));

  if (improveState.brief) {
    panel.append(
      el('pre', { class: 'export', style: 'margin-top:10px' }, improveState.brief.brief),
      el('button', {
        class: 'btn', style: 'margin-top:8px',
        onclick: (e) => {
          navigator.clipboard.writeText(improveState.brief.brief);
          e.target.textContent = 'Copied — paste into Claude Code';
        },
      }, 'Copy brief'));
  }
  return panel;
}

async function viewDeckDetail(id) {
  const deck = await api(`/api/decks/${encodeURIComponent(id)}`);
  const stats = deck.stats || {};
  const boards = [['Mainboard', deck.mainboard], ['Sideboard', deck.sideboard]]
    .filter(([, c]) => c && c.length);

  return el('div', {},
    el('div', { class: 'toolbar' },
      el('button', { class: 'btn', onclick: () => { deckState.id = null; render(); } },
        '← All decks'),
      el('div', { class: 'spacer' }), displayToggle()),
    el('h2', {}, deck.name || '(unnamed)'),
    el('div', { class: 'muted', style: 'margin-bottom:16px' },
      `${deck.format || 'no format'} · ${stats.mainboard_size ?? '?'} cards · `
      + `${stats.lands ?? '?'} lands`),
    el('div', { class: 'grid cols-2', style: 'margin-bottom:18px' },
      el('div', { class: 'panel' }, el('h3', {}, 'Mana curve'), curveChart(stats.mana_curve)),
      el('div', { class: 'panel' }, el('h3', {}, 'Arena export'),
        el('pre', { class: 'export' }, deck.arena_export || ''),
        el('button', {
          class: 'btn', style: 'margin-top:8px',
          onclick: (e) => {
            navigator.clipboard.writeText(deck.arena_export || '');
            e.target.textContent = 'Copied';
          },
        }, 'Copy for Arena'))),
    notesPanel(deck),
    improveDeckPanel(deck),
    boards.map(([label, cards]) =>
      el('div', { style: 'margin-bottom:18px' },
        el('h3', {}, `${label} (${cards.reduce((a, c) => a + c.quantity, 0)})`),
        cardList(cards))));
}

/* ------------------------------------------------------- collection/cards */

let filters = { q: '', colors: '', rarity: '', maxCmc: '', ownedOnly: false };

function filterBar(onChange, { showSearch = true, showOwnedToggle = false } = {}) {
  const mk = (key, opts, label) => el('select', {
    onchange: (e) => { filters[key] = e.target.value; onChange(); },
  }, opts.map(([v, t]) =>
    el('option', { value: v, ...(filters[key] === v ? { selected: 'selected' } : {}) },
      t || label)));

  return el('div', { class: 'toolbar' },
    showSearch ? el('input', {
      type: 'search', placeholder: 'Search name or rules text…', value: filters.q,
      onchange: (e) => { filters.q = e.target.value; onChange(); },
    }) : null,
    mk('colors', [['', 'Any colour'], ['W', 'White'], ['U', 'Blue'], ['B', 'Black'],
      ['R', 'Red'], ['G', 'Green']]),
    mk('rarity', [['', 'Any rarity'], ['mythic', 'Mythic'], ['rare', 'Rare'],
      ['uncommon', 'Uncommon'], ['common', 'Common']]),
    mk('maxCmc', [['', 'Any cost'], ['1', 'MV ≤ 1'], ['2', 'MV ≤ 2'],
      ['3', 'MV ≤ 3'], ['4', 'MV ≤ 4'], ['6', 'MV ≤ 6']]),
    showOwnedToggle ? el('label', { style: 'display:flex;align-items:center;gap:6px' },
      el('input', {
        type: 'checkbox', ...(filters.ownedOnly ? { checked: 'checked' } : {}),
        onchange: (e) => { filters.ownedOnly = e.target.checked; onChange(); },
      }),
      ' Owned only') : null,
    el('div', { class: 'spacer' }), displayToggle());
}

let matchState = { id: null };

function matchRow(m) {
  const resultClass = m.result === 'win' ? 'owned' : m.result === 'loss' ? 'missing' : '';
  const resultLabel = m.result
    ? m.result.toUpperCase()
    : (m.ended_at ? '—' : 'IN PROGRESS');
  return el('div', {
    class: 'panel clickable', style: 'margin-bottom:10px',
    onclick: () => { matchState.id = m.match_id; render(); },
  },
    el('div', { style: 'display:flex;justify-content:space-between;gap:10px' },
      el('strong', {}, `vs ${m.opponent_name || 'unknown opponent'}`),
      el('span', { class: `pill ${resultClass}` }, resultLabel)),
    el('div', { class: 'muted', style: 'margin-top:6px;font-size:12px' },
      [m.format, m.event_name, m.deck_name].filter(Boolean).join(' · ') || 'no details'),
    el('div', { class: 'muted', style: 'font-size:12px;margin-top:2px' },
      (m.games_won || m.games_lost) ? `${m.games_won || 0}–${m.games_lost || 0} games · ` : '',
      m.started_at ? m.started_at.slice(0, 16) : ''));
}

function whoPill(isSelf) {
  return el('span', { class: `pill ${isSelf ? 'owned' : ''}` },
    isSelf === 1 ? 'you' : isSelf === 0 ? 'opponent' : '?');
}

function playRow(p) {
  return el('div', {
    style: 'display:flex;justify-content:space-between;gap:10px;padding:6px 0;'
      + 'border-bottom:1px solid var(--line)',
  },
    el('span', {}, whoPill(p.is_self), ' ', p.name || `#${p.arena_id}`),
    el('span', { class: 'muted', style: 'font-size:12px' },
      p.action === 'land' ? 'land' : 'cast',
      p.game_number ? ` · game ${p.game_number}` : ''));
}

function combatRow(c) {
  const who = c.name || `#${c.arena_id}`;
  const detail = c.action === 'attack'
    ? (c.target_is_player ? 'attacked you/opponent directly'
        : c.target_name ? `attacked ${c.target_name}` : 'attacked')
    : (c.target_name ? `blocked ${c.target_name}` : 'blocked');
  return el('div', {
    style: 'display:flex;justify-content:space-between;gap:10px;padding:6px 0;'
      + 'border-bottom:1px solid var(--line)',
  },
    el('span', {}, whoPill(c.is_self), ' ', who, ' ', detail),
    el('span', { class: 'muted', style: 'font-size:12px' },
      c.turn_number ? `turn ${c.turn_number}` : '',
      c.game_number ? ` · game ${c.game_number}` : ''));
}

async function viewMatchDetail(id) {
  const [matches, plays, combat] = await Promise.all([
    api('/api/matches?limit=50'),
    api(`/api/matches/${encodeURIComponent(id)}/plays`),
    api(`/api/matches/${encodeURIComponent(id)}/combat`),
  ]);
  const m = matches.matches.find((x) => x.match_id === id);
  return el('div', {},
    el('button', { class: 'btn', onclick: () => { matchState.id = null; render(); } },
      '← Matches'),
    el('h2', { style: 'margin-top:10px' }, `vs ${m ? m.opponent_name : 'unknown opponent'}`),
    m ? matchRow(m) : null,
    el('h3', {}, 'Plays'),
    plays.count === 0
      ? el('div', { class: 'empty' },
          'No play-by-play recorded for this match -- either it predates this '
          + 'feature, or it was played before the app started tailing the log.')
      : el('div', { class: 'panel', style: 'margin-bottom:18px' }, plays.plays.map(playRow)),
    el('h3', {}, 'Combat'),
    combat.count === 0
      ? el('div', { class: 'empty' },
          'No combat recorded for this match -- either it predates this feature, '
          + 'or no creature attacked or blocked.')
      : el('div', { class: 'panel' }, combat.combat.map(combatRow)));
}

async function viewMatches() {
  if (matchState.id) return viewMatchDetail(matchState.id);
  const matches = await api('/api/matches?limit=50');
  return el('div', {},
    el('h2', {}, 'Matches'),
    matches.count === 0
      ? el('div', { class: 'empty' },
          'No matches captured yet. Matches are only picked up while ',
          el('code', {}, 'mtga-companion serve'), ' is running -- play one with it up.')
      : el('div', {}, matches.matches.map(matchRow)));
}

async function viewCollection() {
  const qs = new URLSearchParams({ limit: 300 });
  if (filters.colors) qs.set('colors', filters.colors);
  if (filters.rarity) qs.set('rarity', filters.rarity);
  const data = await api(`/api/collection?${qs}`);

  return el('div', {},
    el('h2', {}, 'Collection'),
    el('div', { class: 'banner' },
      el('strong', {},
        data.completeness === 'exact' ? 'Exact collection. ' : 'Lower bound only. '),
      data.caveat),
    filterBar(render, { showSearch: false }),
    el('div', { class: 'muted', style: 'margin-bottom:10px' },
      `${data.count} cards shown`),
    cardList(data.cards));
}

async function viewCards() {
  const qs = new URLSearchParams({ limit: 60 });
  if (filters.q) qs.set('q', filters.q);
  if (filters.colors) qs.set('colors', filters.colors);
  if (filters.rarity) qs.set('rarity', filters.rarity);
  if (filters.maxCmc) qs.set('max_cmc', filters.maxCmc);
  if (filters.ownedOnly) qs.set('owned_only', '1');
  const [data, collectionMeta] = await Promise.all([
    api(`/api/cards?${qs}`),
    api('/api/collection?limit=1'),
  ]);

  return el('div', {},
    el('h2', {}, 'Card search'),
    filterBar(render, { showOwnedToggle: true }),
    el('div', { class: 'muted', style: 'margin-bottom:10px' },
      `${data.count} of 21,004 Arena cards · owned counts are `
      + (collectionMeta.completeness === 'exact' ? 'exact' : 'a lower bound')),
    cardList(data.cards));
}

/* ---------------------------------------------------------- deck builder */

let builder = {
  format: 'standard', colors: '', strategy: '', brief: null,
  wcBudget: { common: '', uncommon: '', rare: '', mythic: '' },
  importName: '', importText: '', importError: null,
};

function wildcardBudgetInputs(wcBudget) {
  return el('div', { style: 'margin-top:10px' },
    el('div', { class: 'muted', style: 'font-size:12px;margin-bottom:6px' },
      'Wildcard budget for this deck (optional — leave blank for no limit):'),
    el('div', { class: 'toolbar' }, ['common', 'uncommon', 'rare', 'mythic'].map((r) =>
      el('label', { style: 'display:flex;align-items:center;gap:6px;font-size:12px' },
        r, el('input', {
          type: 'number', min: '0', style: 'width:56px',
          value: wcBudget[r],
          onchange: (e) => { wcBudget[r] = e.target.value; },
        })))));
}

async function viewBuilder() {
  const suggestions = await api('/api/suggestions');
  const formats = await api('/api/formats');

  const panel = el('div', { class: 'panel' },
    el('h3', {}, 'Brief for your agent'),
    el('div', { class: 'toolbar' },
      el('select', {
        onchange: (e) => { builder.format = e.target.value; },
      }, formats.map((f) => el('option', {
        value: f, ...(builder.format === f ? { selected: 'selected' } : {}),
      }, f))),
      el('select', { onchange: (e) => { builder.colors = e.target.value; } },
        [['', 'Any colours'], ['W', 'White'], ['U', 'Blue'], ['B', 'Black'],
          ['R', 'Red'], ['G', 'Green'], ['WU', 'Azorius'], ['UB', 'Dimir'],
          ['BR', 'Rakdos'], ['RG', 'Gruul'], ['WG', 'Selesnya']].map(([v, t]) =>
          el('option', { value: v, ...(builder.colors === v ? { selected: 'selected' } : {}) }, t)))),
    el('textarea', {
      placeholder: 'What are you after? e.g. "aggressive, cheap curve, under 10 rares"',
      onchange: (e) => { builder.strategy = e.target.value; },
    }),
    wildcardBudgetInputs(builder.wcBudget),
    el('button', {
      class: 'btn primary', style: 'margin-top:10px',
      onclick: async (e) => {
        const qs = new URLSearchParams({ format: builder.format });
        if (builder.colors) qs.set('colors', builder.colors);
        if (builder.strategy) qs.set('strategy', builder.strategy);
        for (const [r, v] of Object.entries(builder.wcBudget)) {
          if (v !== '') qs.set(`max_${r}`, v);
        }
        builder.brief = await api(`/api/brief?${qs}`);
        render();
      },
    }, 'Generate brief'));

  if (builder.brief) {
    panel.append(
      el('div', { class: 'muted', style: 'margin:12px 0 6px' },
        `${builder.brief.pool_size} known-owned legal cards in this pool`
        + (builder.brief.wildcard_budget
          ? ` · budget: ${JSON.stringify(builder.brief.wildcard_budget)}` : '')),
      el('pre', { class: 'export' }, builder.brief.brief),
      el('button', {
        class: 'btn', style: 'margin-top:8px',
        onclick: (e) => {
          navigator.clipboard.writeText(builder.brief.brief);
          e.target.textContent = 'Copied — paste into Claude Code';
        },
      }, 'Copy brief'));
  }

  const importPanel = el('div', { class: 'panel' },
    el('h3', {}, 'Import a decklist'),
    el('div', { class: 'muted', style: 'font-size:12px;margin-bottom:8px' },
      'Paste a decklist in Arena\'s import format to save it here for later — '
      + 'from an agent that answered in chat, or a list found elsewhere.'),
    el('input', {
      type: 'text', placeholder: 'Name for this deck', value: builder.importName,
      style: 'width:100%;margin-bottom:8px;background:var(--panel-2);'
        + 'border:1px solid var(--line);border-radius:8px;padding:7px 10px;color:inherit',
      onchange: (e) => { builder.importName = e.target.value; },
    }),
    el('textarea', {
      placeholder: 'Deck\n4 Lightning Bolt (STA) 42\n20 Mountain\n\nSideboard\n2 Negate',
      onchange: (e) => { builder.importText = e.target.value; },
    }),
    builder.importError
      ? el('div', { class: 'banner warn', style: 'margin-top:8px' }, builder.importError)
      : null,
    el('button', {
      class: 'btn primary', style: 'margin-top:8px',
      onclick: async (e) => {
        if (!builder.importName || !builder.importText) {
          builder.importError = 'Both a name and a decklist are required.';
          render();
          return;
        }
        const res = await fetch('/api/import-deck', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: builder.importName, text: builder.importText, format: builder.format,
          }),
        });
        const data = await res.json();
        if (!res.ok) {
          builder.importError = data.error || 'Import failed.';
          render();
          return;
        }
        builder.importName = ''; builder.importText = ''; builder.importError = null;
        const full = await api(`/api/suggestions/${data.suggestion_id}`);
        showSuggestion(full);
      },
    }, 'Import'));

  return el('div', {},
    el('h2', {}, 'Deck builder'),
    el('div', { class: 'banner' },
      'This app does not call a model. Generate a brief, run it in your MCP '
      + 'agent (Claude Code), and it will write the finished deck back here '
      + 'via save_suggested_deck.'),
    el('div', { class: 'grid cols-2' }, panel, importPanel),
    el('div', { class: 'panel', style: 'margin-top:14px' },
      el('h3', {}, 'Suggestions'),
      suggestions.length === 0
        ? el('div', { class: 'muted' }, 'None yet. Generate a brief and run it, '
            + 'or import a decklist.')
        : el('div', { class: 'decklist' }, suggestions.map((s) =>
            el('div', {
              class: 'deckrow clickable',
              onclick: async () => {
                const full = await api(`/api/suggestions/${s.suggestion_id}`);
                showSuggestion(full);
              },
            },
              el('span', { class: 'c' }, s.name),
              s.playstyle ? el('span', { class: 'pill' }, s.playstyle) : null,
              el('span', { class: 'pill' }, s.format || '—'))))));
}

let suggestionNotesDraft = null; // { suggestionId, description, playstyle, comments, recommendations }

function suggestionNotesField(key, label, placeholder) {
  return el('div', { style: 'margin-bottom:10px' },
    el('div', { class: 'muted', style: 'font-size:12px;margin-bottom:4px' }, label),
    el('textarea', {
      placeholder, style: 'min-height:52px',
      onchange: (e) => { suggestionNotesDraft[key] = e.target.value; },
    }, suggestionNotesDraft[key]));
}

function suggestionNotesPanel(s) {
  if (!suggestionNotesDraft || suggestionNotesDraft.suggestionId !== s.suggestion_id) {
    suggestionNotesDraft = {
      suggestionId: s.suggestion_id,
      description: s.description || '',
      playstyle: s.playstyle || '',
      comments: s.comments || '',
      recommendations: s.recommendations || '',
    };
  }
  return el('div', { class: 'panel', style: 'margin-bottom:18px' },
    el('div', { style: 'display:flex;justify-content:space-between;align-items:baseline' },
      el('h3', {}, 'Notes'),
      s.notes_updated_at
        ? el('span', { class: 'muted', style: 'font-size:11px' },
            `updated ${s.notes_updated_at.slice(0, 16)}`)
        : null),
    el('div', { style: 'margin-bottom:10px' },
      el('div', { class: 'muted', style: 'font-size:12px;margin-bottom:4px' }, 'Playstyle'),
      el('input', {
        type: 'text', placeholder: 'e.g. Aggro, Midrange, Control',
        value: suggestionNotesDraft.playstyle,
        style: 'width:100%;background:var(--panel-2);border:1px solid var(--line);'
          + 'border-radius:8px;padding:7px 10px;color:inherit',
        onchange: (e) => { suggestionNotesDraft.playstyle = e.target.value; },
      })),
    suggestionNotesField('description', 'Description', "What this deck's plan is…"),
    suggestionNotesField('comments', 'Comments', 'Free-form notes…'),
    suggestionNotesField('recommendations', 'Recommendations', 'What to change or improve…'),
    el('button', {
      class: 'btn primary',
      onclick: async (e) => {
        const res = await fetch(`/api/suggestions/${s.suggestion_id}/notes`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            description: suggestionNotesDraft.description,
            playstyle: suggestionNotesDraft.playstyle,
            comments: suggestionNotesDraft.comments,
            recommendations: suggestionNotesDraft.recommendations,
          }),
        });
        const updated = await res.json();
        e.target.textContent = res.ok ? 'Saved' : 'Failed to save';
        if (res.ok) setTimeout(() => showSuggestion({ ...s, ...updated }), 500);
      },
    }, 'Save notes'));
}

function showSuggestion(s) {
  const cost = s.wildcard_cost || {};
  const needed = Object.entries(cost.wildcards_needed || {});
  const budgetCheck = (s.validation || {}).wildcard_budget_check;

  main.replaceChildren(el('div', {},
    el('div', { class: 'toolbar' },
      el('button', { class: 'btn', onclick: render }, '← Back'),
      el('div', { class: 'spacer' }),
      el('button', {
        class: 'btn',
        onclick: async () => {
          const newName = prompt('Name for the duplicate:', `${s.name} (copy)`);
          if (!newName) return;
          const res = await fetch('/api/duplicate-deck', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_name: newName, suggestion_id: s.suggestion_id }),
          });
          const data = await res.json();
          if (!res.ok) { alert(data.error || 'Duplicate failed.'); return; }
          const full = await api(`/api/suggestions/${data.suggestion_id}`);
          showSuggestion(full);
        },
      }, 'Duplicate')),
    el('h2', { style: 'margin-top:14px' }, s.name),
    el('div', { class: 'muted', style: 'margin-bottom:12px' }, s.rationale || ''),
    el('div', { class: 'grid cols-2', style: 'margin-bottom:16px' },
      el('div', { class: 'panel' }, el('h3', {}, 'Wildcard cost'),
        needed.length === 0
          ? el('div', { class: 'pill owned' }, 'Fully owned — costs nothing')
          : el('div', {}, needed.map(([r, n]) =>
              el('div', {}, el('span', { class: `pill ${r}` }, `${n} ${r}`), ' needed')),
              el('div', { class: cost.craftable_now ? 'pill owned' : 'pill missing',
                style: 'margin-top:8px' },
                cost.craftable_now ? 'You can craft this now' : 'Not enough wildcards')),
        budgetCheck && budgetCheck.budget_set
          ? el('div', { class: budgetCheck.within_budget ? 'pill owned' : 'pill missing',
              style: 'margin-top:6px' },
              budgetCheck.within_budget
                ? 'Within wildcard budget'
                : `Over budget: ${JSON.stringify(budgetCheck.over_budget)}`)
          : null),
      el('div', { class: 'panel' }, el('h3', {}, 'Arena export'),
        el('pre', { class: 'export' }, s.arena_export || ''),
        el('button', {
          class: 'btn', style: 'margin-top:8px',
          onclick: (e) => {
            navigator.clipboard.writeText(s.arena_export || '');
            e.target.textContent = 'Copied — paste into Arena';
          },
        }, 'Copy for Arena'))),
    suggestionNotesPanel(s),
    el('h3', {}, 'Decklist'), cardList(s.cards || [])));
}

/* ----------------------------------------------------------------- router */

const views = {
  dashboard: viewDashboard, decks: viewDecks, matches: viewMatches,
  collection: viewCollection, cards: viewCards, builder: viewBuilder,
};
let current = 'dashboard';

async function render() {
  try {
    main.replaceChildren(await views[current]());
  } catch (err) {
    main.replaceChildren(el('div', { class: 'banner warn' },
      el('strong', {}, 'Failed to load. '), String(err)));
  }
}

$('#nav').addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-view]');
  if (!btn) return;
  current = btn.dataset.view;
  deckState.id = null;
  matchState.id = null;
  for (const b of $('#nav').children) b.classList.toggle('active', b === btn);
  render();
});

render();
