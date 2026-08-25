# mtga-companion

A local MTG Arena companion. Tails Arena's log, keeps a card and deck database,
and serves it all to AI agents over MCP so they can reason about your decks and
suggest changes.

Everything runs on your machine. The MCP server binds to loopback only, and
Arena itself is only ever read — the log is tailed, and Arena's card database is
opened read-only.

## Setup

```sh
uv venv && uv pip install -e ".[dev]"
```

### Enable Arena's detailed logging (required)

By default Arena writes no game data at all. In MTG Arena:

**Settings (gear) → Account → tick "Detailed Logs (Plugin Support)"**, then
restart Arena.

Check it took effect:

```sh
mtga-companion status     # "detailed_logs_enabled": true
```

Until this is on, card search works but decks, matches and collection stay empty.

## Usage

```sh
mtga-companion sync-cards           # build the card database (~1 min, once a day)
mtga-companion status               # what data is loaded
mtga-companion ingest               # read new log lines once and exit
mtga-companion serve                # MCP server + live log tailing
mtga-companion import-collection FILE.csv
```

`serve` runs both surfaces on one port:

- **Browser UI** — <http://127.0.0.1:8765/>
- **MCP endpoint** — `http://127.0.0.1:8765/mcp`

Register the MCP endpoint with Claude Code:

```sh
claude mcp add --transport http mtga http://127.0.0.1:8765/mcp
```

Use `--no-web` to run the MCP server alone.

## The web UI

- **Dashboard** — rank and season record, wildcards, gold/gems, vault progress,
  deck and collection totals.
- **Decks** — your decks (Arena's ~108 precons are behind a toggle). Each opens
  with its card list, mana curve, land count and Arena export text.
- **Collection** — known-owned cards with colour, rarity and cost filters.
- **Cards** — search all 21,004 Arena cards with an owned count on each.
- **Deck Builder** — see below.

Cards show as an image grid by default with a table toggle; the choice is
remembered. Art is lazy-loaded from Scryfall, so the table view is also the
offline view.

## Deck builder

The app does not call a model. It prepares a brief carrying your real
constraints — format, colours, wildcard stock, the size of your legal card pool
— which you run in an MCP agent such as Claude Code. The agent works through
these tools and finishes by calling `save_suggested_deck`, at which point the
deck appears in the Deck Builder view with its wildcard cost and an
Arena-importable export.

| Tool | Purpose |
|---|---|
| `get_deck_candidates` | Format-legal cards you own, with wildcard stock |
| `validate_deck` | Size, four-copy limit *by card name*, legality, cost |
| `save_suggested_deck` | Write the finished deck back to the app |
| `export_deck_arena` | Arena import text for an existing deck |

There is also a `build_deck` MCP prompt carrying the same brief.

## MCP tools

| Tool | What it gives an agent |
|---|---|
| `status` | What data is loaded; flags disabled Arena logging |
| `list_decks` | Your decks with format, colors, size, last played |
| `get_deck` | Full mainboard and sideboard with resolved card data |
| `search_cards` | Search Arena cards by name or rules text, with filters |
| `get_collection` | Cards you're known to own, with a completeness flag |
| `get_inventory` | Wildcards, gold, gems, vault progress |
| `get_rank` | Constructed and limited rank |
| `get_match_history` | Recent matches, optionally per deck |
| `get_deck_stats` | Win rate, mana curve, land count, color spread |
| `import_collection` | Load an exact collection CSV |
| `refresh_cards` | Re-sync the card database |

Resources: `mtga://decks/{deck_id}` and `mtga://cards/{arena_id}`.

## About the collection

**Arena stopped reporting collection contents in its log in August 2021.**
`PlayerInventory.GetPlayerCardsV3` was removed and never replaced. Confirmed by
scanning every payload in both log files: no endpoint, no card-count structure,
and no local cache in Arena's own data directory.

It *is* still in the running client's memory — that's how other trackers get
it (Untapped's "Scry" attaches to the MTGA process and reads it out of the
Unity runtime), and `memread.py` does the same thing here.

### Reading the real collection from memory

```sh
sudo .venv/bin/python scripts/sync_collection.py
```

Requires root (`task_for_pid` on another user's process needs it — MTGA isn't
hardened-runtime, so no special entitlement is needed beyond that) and MTGA
running. **Entirely read-only against the game**: `mach_vm_read_overwrite`
copies bytes out without writing to, injecting into, or suspending the process.
The only write is to this app's own database, and file ownership is restored
to your user afterward.

**How it finds the table without any prior knowledge of Arena's internals:**
.NET's `int.GetHashCode()` returns the int itself, so a `Dictionary<int, int>`
entry stores its hash right next to its key — for every real entry,
`entry.hashCode == entry.key`. Two words matching exactly is a roughly
1-in-4-billion coincidence per position, so scanning every 4-byte-aligned
offset in the process for that pattern finds real dictionary entries with
almost no false positives, no IL2CPP struct layout required. Arena has more
than one int-keyed dictionary in memory, so the candidate region is then
validated against cards independently proven owned (from decks you built) —
only a region that matches most of those is trusted. Full write-up in
`memread.py`'s module docstring and `find_dictionary_entries()`.

If validation is inconclusive, `scripts/scan_memory.py` reports every
candidate region's numbers without writing anything, for troubleshooting.

**Caveats:**
- It's a snapshot. Cards obtained after a sync won't show up until you sync
  again — there's no live watcher, since it needs root.
- Basic lands read as quantity 1 regardless of how many you've used. That's
  expected: Arena never wildcard-gates basics, so the game doesn't track a
  real count for them. `deckbuilder.py` already treats basics as free and
  unlimited everywhere.
- An Arena-generated deck preview (e.g. an Alchemy upgrade suggestion) can list
  more copies of a card than you've actually crafted. When memory and a deck
  disagree, memory wins — see `collection.BEST_OWNERSHIP_SQL`.

### Without a memory sync

`get_collection` falls back to a **lower bound** built from evidence:

| Source | Meaning |
|---|---|
| `memory` | Read from Arena's own memory (above). Treated as exact. |
| `import` | From an exact CSV. Also treated as exact. |
| `deck` | In a deck **you built**. Arena's ~108 precons are excluded — it reports their contents to every account regardless of ownership. |
| `grant` | Arena granted it while the tracker was running (booster, reward). |
| `draft` | You picked it in a draft. |
| `played` | You cast it in one of your own games. |

Every `get_collection` response carries a `completeness` field, because an
agent that reads a missing card as "you don't own it" will give bad advice.

## Card data

Two sources, merged on Arena's `grpId`:

- **Scryfall** bulk export, filtered to printings carrying an `arena_id`. Supplies
  oracle text, type lines, mana values, legalities and EDHREC ranks.
- **Arena's own card database** (`Raw_CardDatabase_*.mtga`, plain SQLite, opened
  read-only) for printings Scryfall doesn't map — Alchemy rebalances, digital-only
  and very new sets. These get enriched with Scryfall oracle text by name where
  possible.

Coverage is currently 100% of Arena's primary non-token cards, with oracle text
for all but ~0.2% (the newest digital-only printings).

## Log format notes

Written against a real Detailed-Logs capture. Several details differ from how
this format is usually described, and each one silently breaks a parser:

- **Responses span two lines and the header has no prefix.** Requests are
  `[UnityCrossThreadLogger]==> Label {json}` on one line, but responses are a
  bare `<== Label(uuid)` header with the JSON body on the *next* line. A parser
  that requires the prefix, or expects the payload inline, sees no responses at
  all.
- **Decks come from two sibling keys.** `DeckSummaries` holds names and
  attributes; `Decks` is a dict keyed by the same ids holding the card lists.
  Neither is usable alone.
- **Deck metadata is a name/value list.** Format, LastPlayed, LastUpdated and
  IsFavorite live in an `Attributes` array, not as fields, and timestamps arrive
  JSON-quoted.
- **`0001-01-01` means "never".** It is .NET's `DateTime.MinValue`; left as-is it
  reads as a real date and sorts as the oldest one.
- **Rank no longer reports a class.** There is no Bronze/Silver/Gold field any
  more — only levels and season match records.
- **Arena ships ~108 precon decks** in every `StartHook`. They are stored but
  flagged `precon` so they don't bury the dozen decks you built.
- **One card can appear twice in a deck** under different `grpId`s (two printings
  of Shock). Deck views merge them by name.

## Design notes

- **The log format is undocumented and shrinking.** Wizards has removed data over
  time, so each parser extractor is independent and fails soft; anything
  unrecognised lands in the `raw_events` table rather than crashing ingestion or
  being silently dropped. Check that table after a patch to spot format drift.
- **Match and draft extractors are still unverified.** They are written from the
  documented format but no game or draft has been captured yet, so treat them as
  provisional until `get_match_history` returns a real result.
- **Ingestion is idempotent.** Everything upserts on Arena's own ids, and byte
  offsets are persisted per log file, so re-reading a log changes nothing.
- **Arena rewrites `Player.log` on every launch.** The tailer detects the file
  shrinking and re-reads from the start; the previous session is backfilled from
  `Player-prev.log`.

## Development

```sh
.venv/bin/python -m pytest tests/ -q
```
