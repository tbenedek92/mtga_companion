# mtga-companion

A local MTG Arena companion. Tails Arena's log, keeps a card and deck database,
reads your real collection out of the game's own memory, and serves all of it
to AI agents over MCP — plus a browsable web UI — so you (or an agent) can look
at your decks, build new ones from cards you own, and get something you can
paste straight back into Arena.

Everything runs on your machine, unauthenticated on loopback only. Arena is
only ever read: the log is tailed, its card database is opened read-only, and
the optional memory sync copies bytes out without writing to, injecting into,
or suspending the game process.

## Contents

- [Quick start](#quick-start)
- [Requirements](#requirements)
- [CLI reference](#cli-reference)
- [The web UI](#the-web-ui)
- [Deck builder](#deck-builder)
- [Deck notes](#deck-notes)
- [Improving an existing deck](#improving-an-existing-deck)
- [MCP tools](#mcp-tools)
- [About the collection](#about-the-collection)
- [Card data](#card-data)
- [Log format notes](#log-format-notes)
- [Design notes](#design-notes)
- [Troubleshooting](#troubleshooting)
- [Where things live](#where-things-live)
- [Development](#development)

## Quick start

```sh
# 1. Install
uv venv && uv pip install -e ".[dev]"

# 2. In MTG Arena: Settings (gear) -> Account -> tick
#    "Detailed Logs (Plugin Support)" -> restart Arena.
#    Without this, Arena writes no game data at all.

# 3. Build the card database (~1 min, downloads from Scryfall)
mtga-companion sync-cards

# 4. Read your decks, inventory and rank from the log
mtga-companion ingest

# 5. Check it worked
mtga-companion status
#   "detailed_logs_enabled": true
#   "decks": <your deck count>, "cards": 21000+

# 6. Start the app: web UI + MCP server on one port
mtga-companion serve
```

Open **<http://127.0.0.1:8765/>** for the dashboard, decks, collection and card
search.

To let an AI agent use it, register the MCP endpoint (in a separate terminal,
while `serve` keeps running):

```sh
claude mcp add --transport http mtga http://127.0.0.1:8765/mcp
```

Then in Claude Code, try: *"What decks do I have, and what colors are they?"*
— it should read your real decks back to you.

### Get your exact collection (recommended, one extra step)

Without this, `get_collection` only knows about cards seen in decks you've
built — a real but incomplete lower bound. To read your actual collection
straight out of Arena's memory (same trick Untapped's Companion uses), with
Arena running:

```sh
sudo .venv/bin/python scripts/sync_collection.py
```

See [About the collection](#about-the-collection) for what this does and why
it needs `sudo`. It's a snapshot — re-run it after opening boosters or
crafting cards to keep it current.

### Try the deck builder

1. Open the **Deck Builder** tab, pick a format and colors, optionally set a
   wildcard budget, click **Generate brief**, then **Copy brief**.
2. Paste it into Claude Code (with the MCP server registered as above).
3. The agent builds a deck from cards you own, checks it's legal and in
   budget, and saves it — it'll appear back in the Deck Builder tab with a
   wildcard cost and a **Copy for Arena** button that pastes directly into
   Arena's deck importer.

## Requirements

- **macOS** with MTG Arena installed (Steam or standalone). The memory-sync
  feature is macOS-specific; everything else has no OS-specific code but is
  only tested on macOS.
- **Python 3.10+** and [uv](https://docs.astral.sh/uv/) (or plain
  `pip`/`venv` — see below).
- Arena's own card database is read from the Steam install path by default; a
  standalone (non-Steam) install path is also checked. See `paths.py` if
  yours lives elsewhere.

Without `uv`:

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Every command below assumes `.venv/bin/` is on your `PATH` (e.g. via
`source .venv/bin/activate`) or is written with the explicit `.venv/bin/`
prefix — both work identically.

## CLI reference

```sh
mtga-companion status
mtga-companion sync-cards [--force]
mtga-companion ingest
mtga-companion import-collection FILE.csv
mtga-companion serve [--host HOST] [--port PORT] [--no-tail] [--no-web]
```

| Command | What it does |
|---|---|
| `status` | Prints what's loaded: card count, deck count, whether Arena's Detailed Logs are on, unparsed-event count. Run this first when something looks empty. |
| `sync-cards` | Refreshes the card database from Scryfall (+ Arena's local DB as fallback). Cached for ~20h; `--force` bypasses that. |
| `ingest` | Reads new lines from `Player.log` once and exits. `serve` does this continuously; use `ingest` for a one-off refresh without starting the server. |
| `import-collection FILE.csv` | Loads an exact collection export (Name + Quantity columns, Set optional) as ground truth. |
| `serve` | Runs the web UI and MCP server together, tailing the log live. `--no-web` serves MCP only; `--no-tail` skips log ingestion; `--host`/`--port` default to `127.0.0.1:8765`. |

`sudo .venv/bin/python scripts/sync_collection.py` and
`sudo .venv/bin/python scripts/scan_memory.py` are separate, root-requiring
scripts — see [About the collection](#about-the-collection).

Add `-v` before the subcommand for debug logging, e.g. `mtga-companion -v serve`.

## The web UI

Served by `mtga-companion serve` at `http://127.0.0.1:8765/` (disable with
`--no-web` if you only want the MCP endpoint).

- **Dashboard** — rank and season record, wildcards, gold/gems, vault progress,
  deck and collection totals.
- **Decks** — your decks (Arena's ~108 precons are behind a toggle). Each opens
  with its card list, mana curve, land count, an Arena export you can copy, and
  an editable **Notes** panel (description, playstyle, comments,
  recommendations) — see below.
- **Collection** — known-owned cards with color, rarity and cost filters, and
  a banner stating whether this is your exact collection or a lower bound.
- **Cards** — search all 21,000+ Arena cards with an owned count on each, and
  an "Owned only" toggle to restrict the search to your collection.
- **Deck Builder** — generate a brief for an agent, set a wildcard budget,
  paste in a decklist to save it, and review saved suggestions. See
  [Deck builder](#deck-builder).

Cards show as an image grid by default with a table toggle; the choice is
remembered in your browser. Art is lazy-loaded from Scryfall, so the table
view also works fully offline.

## Deck builder

The app does not call a model itself. It prepares a brief carrying your real
constraints — format, colors, wildcard stock, an optional spending budget, the
size of your legal card pool — which you run in an MCP agent such as Claude
Code. The agent works through the tools below and finishes by calling
`save_suggested_deck` (or `import_deck`), at which point the deck appears in
the Deck Builder view with its wildcard cost and an Arena-importable export.

| Tool | Purpose |
|---|---|
| `get_deck_candidates` | Format-legal cards you own, with wildcard stock |
| `validate_deck` | Size, four-copy limit *by card name*, legality, cost, budget |
| `save_suggested_deck` | Write the finished deck back to the app |
| `import_deck` | Parse Arena-format decklist text and save it, same as above |
| `export_deck_arena` | Arena import text for an existing deck |
| `list_suggestions` | List saved suggestions — check before building something new |
| `get_suggestion` | Full detail (cards, cost, notes) for one saved suggestion |
| `update_suggestion_notes` | Set description/playstyle/comments/recommendations on a suggestion |
| `duplicate_deck` | Clone a real deck or a suggestion into a new suggestion, to try a variant |

There is also a `build_deck` MCP prompt carrying the same brief, with
`format`/`colors`/`strategy`/`max_*_wildcards` arguments. For improving one of
your existing decks instead of building from scratch, see
[Improving an existing deck](#improving-an-existing-deck) below.

**Every path back to Arena is the same text format.** `validate_deck`,
`save_suggested_deck`, `import_deck` and `export_deck_arena` all return
`arena_export` — lines like `4 Lightning Bolt (STA) 42` under `Deck` /
`Sideboard` / `Commander` headers, which Arena's own deck importer accepts
directly. The GUI's "Copy for Arena" button on any deck or saved suggestion
copies this text; in MCP, ask the agent to give you the `arena_export` text
and it'll paste straight into Arena even if you never open the GUI.

**Wildcard budget.** Independent of what you can *afford* (wildcard stock,
checked automatically against your real inventory), you can cap what an agent
is allowed to *spend* on one deck — e.g. "at most 1 rare wildcard, 0 mythic."
Set it in the GUI's Deck Builder panel before generating a brief, or pass
`wildcard_budget` directly to `validate_deck`/`save_suggested_deck`
(`{"rare": 1, "mythic": 0}`). A rarity left out of the budget means **zero** of
that rarity is allowed, not unlimited — be explicit about every rarity you're
willing to spend.

**Two ways to get a deck into the app.** An agent can build one from scratch
via the tool chain above, or you can hand it (or the GUI's import box) a
decklist as plain Arena-format text — from an agent that answered in chat
without touching MCP, or a list found elsewhere — and `import_deck` parses,
validates, and saves it the same way.

**Revising a suggestion in place.** By default, `save_suggested_deck` and
`import_deck` always insert a new suggestion. Pass the `suggestion_id` of an
existing one (from `list_suggestions`) and they update it in place instead —
name, cards, cost and validation are fully replaced, while `rationale` and
`based_on_deck` are partial updates (omit to keep the old value). This is how
an agent iterates on the same deck across a session without cluttering the
Suggestions list with near-duplicates. Call `list_suggestions` before building
something new to check whether you're already iterating on one.

**Notes on suggestions**, same four fields as [deck notes](#deck-notes) below
— description, playstyle, comments, recommendations — settable at save time
(`save_suggested_deck`/`import_deck`) or edited later via
`update_suggestion_notes`, or in the GUI's Notes panel on a suggestion's detail
page. Same partial-update rule: omit a field to leave it, pass `""` to clear it.

**Duplicating a deck.** `duplicate_deck(new_name, deck_id=...)` or
`duplicate_deck(new_name, suggestion_id=...)` clones a real deck or an existing
suggestion's cards into a brand-new suggestion — useful for starting a variant
without losing the original. Notes are intentionally not copied, since the
whole point is a fresh decklist to annotate. In the GUI, the "Duplicate" button
on a suggestion's detail page does the same thing.

## Deck notes

Each of your decks (not precons) has four freeform fields you or an agent can
fill in: **description** (what the deck's plan is), **playstyle** (e.g.
"Aggro", "Midrange", "Control" — free text, no fixed list), **comments**, and
**recommendations**. Edit them in the GUI's Notes panel on a deck's detail
page, or via the `update_deck_notes` MCP tool. Agent suggestions carry the
same four fields — see [Notes on suggestions](#deck-builder) above.

These are entirely ours — Arena has no concept of them, so they're never
touched by log ingestion and survive every resync untouched. A natural agent
workflow: call `get_deck_stats` to analyze a deck's curve and win rate, then
`update_deck_notes(deck_id, recommendations="...")` to leave what it found for
you to see next time you open the app, without asking again.

Every field is a partial update — an omitted field keeps its current value;
pass an empty string to clear one instead of omitting it.

## Improving an existing deck

Beyond building from scratch, an agent can read one of your real decks and
suggest changes to it. The `improve_deck` MCP prompt (`deck_id`, optional
`focus`, optional `max_*_wildcards`) fills in a brief that has the agent:

1. Call `get_deck` and `get_deck_stats` to see the current build, win rate,
   mana curve, and color/type spread.
2. Call `get_deck_candidates` — scoped to the deck's own format and colors —
   for cards, owned or craftable, that could replace weak slots.
3. Call `validate_deck` on anything it proposes.

Then it writes back one of two ways, its choice based on how much needs to
change: a short note via `update_deck_notes(deck_id, recommendations="...")`
for a few targeted swaps (your real deck is never edited directly — only its
notes), or a full alternate 60 via `save_suggested_deck(..., based_on_deck=
deck_id)` saved as a separate suggestion you can compare against the original.

In the GUI, a deck's detail page has a "Suggest improvements" panel — optional
focus text and wildcard budget, a "Generate brief" button, and a copy button —
mirroring the Deck Builder's brief panel but scoped to that one deck. The same
brief is available directly as `GET /api/decks/{deck_id}/improve-brief`.

## MCP tools

Full list, beyond the deck builder above:

| Tool | What it gives an agent |
|---|---|
| `status` | What data is loaded; flags disabled Arena logging |
| `list_decks` | Your decks with format, colors, size, last played |
| `get_deck` | Full mainboard and sideboard with resolved card data |
| `search_cards` | Search Arena cards by name or rules text, with filters |
| `get_collection` | Cards you're known to own, with a completeness flag |
| `get_inventory` | Wildcards, gold, gems, vault progress |
| `get_rank` | Constructed and limited rank |
| `get_match_history` | Recent matches, optionally per deck (**unverified** — see below) |
| `get_deck_stats` | Win rate, mana curve, land count, color spread |
| `import_collection` | Load an exact collection CSV |
| `refresh_cards` | Re-sync the card database |
| `update_deck_notes` | Set description/playstyle/comments/recommendations on a deck |

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
for all but ~0.2% (the newest digital-only printings). Run `sync-cards` again
after a new set releases; it's cached for ~20 hours, so a same-day re-run needs
`--force`.

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
  provisional until `get_match_history` returns a real result. Play a match (or
  draft), run `mtga-companion ingest`, then check the `raw_events` table for
  rows with reason `no extractor matched` — those hold the real payloads needed
  to correct the extractors.
- **Ingestion is idempotent.** Everything upserts on Arena's own ids, and byte
  offsets are persisted per log file, so re-reading a log changes nothing.
- **Arena rewrites `Player.log` on every launch.** The tailer detects the file
  shrinking and re-reads from the start; the previous session is backfilled from
  `Player-prev.log`.

## Troubleshooting

**`status` shows `"detailed_logs_enabled": false`, decks/matches are empty.**
Arena isn't writing game data. Settings → Account → tick "Detailed Logs
(Plugin Support)" → fully restart Arena → `mtga-companion ingest` again.

**`sync-cards` fails to download, or the card table looks empty.**
Needs network access to `api.scryfall.com` / `data.scryfall.io`. Check
connectivity, then re-run with `--force` if it partially completed.

**`serve` starts but decks/collection are empty in the UI.**
Run `mtga-companion ingest` first (or start `serve` and wait — it tails
continuously, so the data appears as soon as Arena writes it, typically within
a few seconds of app launch).

**`scripts/sync_collection.py` reports validation below the threshold and
writes nothing.** Either the wrong memory region was found (rare), or you
haven't built enough decks yet for a confident cross-check — the validation
needs cards it can independently confirm you own. Run
`scripts/scan_memory.py` to see every candidate region's numbers, and try
again after building a couple more decks or opening the Collection screen in
Arena.

**`sudo: a password is required` / can't run the memory sync non-interactively.**
That's expected — `sudo` needs an interactive terminal. Run the command
directly in your own terminal rather than through a wrapper that can't prompt
for a password.

**MCP tools return data but it looks stale.** `get_collection`'s
`completeness`/`caveat` fields say whether you're looking at an exact memory
sync, an import, or inferred evidence, and how old a memory sync is. Re-run
`sync_collection.py` or `ingest` as needed — nothing here auto-refreshes
except the log tail while `serve` is running.

**Port 8765 already in use.** `mtga-companion serve --port 8888` (also update
the `claude mcp add` URL and your browser bookmark to match).

## Where things live

| What | Path |
|---|---|
| Our database | `~/.local/share/mtga_companion/db.sqlite` (override with `XDG_DATA_HOME`) |
| Scryfall cache | `~/.local/share/mtga_companion/scryfall-cache/` |
| Arena's log | `~/Library/Logs/Wizards Of The Coast/MTGA/Player.log` |
| Arena's card DB (read-only fallback source) | `.../MTGA/MTGA_Data/Downloads/Raw/Raw_CardDatabase_*.mtga` |

## Development

```sh
.venv/bin/python -m pytest tests/ -q
```

158 tests, no network or root required (the memory-sync and Scryfall-sync code
paths are exercised with synthetic data, not live calls).
