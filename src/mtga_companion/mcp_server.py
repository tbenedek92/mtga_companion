"""MCP server exposing your Arena decks, matches and collection.

Runs over streamable HTTP bound to loopback. There is no authentication, so it
must never be bound to a routable address -- the data includes your account's
play history.

Tool descriptions carry the collection caveat deliberately: an agent that reads
a missing card as "not owned" will give bad deck advice, and the description is
the only place it reliably sees that warning before calling.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import cards as cards_mod
from . import collection as collection_mod
from . import deckbuilder as builder_mod
from . import paths, queries, store

log = logging.getLogger(__name__)

mcp = MCPServer(
    name="mtga-companion",
    instructions=(
        "Local MTG Arena companion. Exposes the player's decks, match history, "
        "card database and inferred collection.\n\n"
        "Important: Arena stopped reporting collection contents in 2021, so "
        "get_collection returns a LOWER BOUND derived from decks, drafts and "
        "games played -- not a complete list. A card absent from it may still "
        "be owned. Check the 'completeness' field before telling the user they "
        "cannot build something. Call status() first if results look empty."
    ),
)

_conn: sqlite3.Connection | None = None


def db() -> sqlite3.Connection:
    """Lazily open the shared connection used by both MCP tools and the web UI.

    Thread checking is off because the HTTP transport serves requests from a
    worker pool.
    """
    global _conn
    if _conn is None:
        _conn = store.connect(check_same_thread=False)
    return _conn


@mcp.tool()
def status() -> dict[str, Any]:
    """Health check: how much data is loaded and whether Arena logging is on.

    Call this first when other tools return nothing -- the usual cause is that
    'Detailed Logs (Plugin Support)' is off in Arena's Account settings, which
    makes Arena write no game data at all.
    """
    return queries.status(db())


@mcp.tool()
def list_decks(include_precon: bool = False) -> list[dict[str, Any]]:
    """List the player's decks with format, colors, size and last-played time.

    Arena ships roughly 108 starter and preconstructed decks alongside the
    player's own, so they are excluded unless include_precon is set.
    """
    return queries.list_decks(db(), include_precon=include_precon)


@mcp.tool()
def get_deck(deck_id: str) -> dict[str, Any]:
    """Get one deck's full mainboard and sideboard with resolved card data.

    Use the deck_id returned by list_decks.
    """
    deck = queries.get_deck(db(), deck_id)
    if deck is None:
        return {"error": f"No deck with id {deck_id!r}. Call list_decks for valid ids."}
    return deck


@mcp.tool()
def search_cards(
    query: str = "",
    owned_only: bool = False,
    colors: str | None = None,
    rarity: str | None = None,
    max_cmc: float | None = None,
    limit: int = 50,
    all_printings: bool = False,
) -> list[dict[str, Any]]:
    """Search Arena-legal cards by name or rules text.

    Args:
        query: Substring matched against card name and oracle text.
        owned_only: Restrict to cards with ownership evidence. Note this uses
            the incomplete lower-bound collection, so it can miss cards the
            player does own.
        colors: Color letters to require, e.g. "UB" for cards that are both.
        rarity: One of common, uncommon, rare, mythic.
        max_cmc: Maximum mana value.
        limit: Maximum rows to return.
        all_printings: Return one row per Arena printing instead of one per
            card name. Off by default because Arena has many grpIds per card.
    """
    return queries.search_cards(
        db(), query=query, owned_only=owned_only, colors=colors,
        rarity=rarity, max_cmc=max_cmc, limit=limit, all_printings=all_printings,
    )


@mcp.tool()
def get_collection(
    colors: str | None = None, rarity: str | None = None, limit: int = 500
) -> dict[str, Any]:
    """Cards the player is known to own.

    Returns a 'completeness' field that is either 'exact' (an exact collection
    CSV was imported) or 'lower_bound'. When it is 'lower_bound' the list is
    derived only from decks, draft picks and cards played, because Arena no
    longer reports collection contents. Do not tell the user they lack a card
    on the basis of its absence from a lower-bound result.
    """
    return collection_mod.get_collection(db(), colors=colors, rarity=rarity, limit=limit)


@mcp.tool()
def get_inventory() -> dict[str, Any]:
    """Wildcards, gold, gems and vault progress from the latest Arena snapshot."""
    inv = queries.get_inventory(db())
    if inv is None:
        return {"error": "No inventory captured yet.", "hint": "Call status()."}
    return inv


@mcp.tool()
def get_rank() -> dict[str, Any]:
    """Latest constructed and limited rank."""
    rank = queries.get_rank(db())
    if rank is None:
        return {"error": "No rank captured yet.", "hint": "Call status()."}
    return rank


@mcp.tool()
def get_match_history(limit: int = 20, deck_id: str | None = None) -> list[dict[str, Any]]:
    """Recent matches, newest first, optionally filtered to one deck."""
    return queries.get_match_history(db(), limit=limit, deck_id=deck_id)


@mcp.tool()
def get_deck_stats(deck_id: str) -> dict[str, Any]:
    """Win rate, mana curve, land count and color/type spread for one deck."""
    stats = queries.get_deck_stats(db(), deck_id)
    if stats is None:
        return {"error": f"No deck with id {deck_id!r}."}
    return stats


@mcp.tool()
def import_collection(path: str) -> dict[str, Any]:
    """Import an exact collection CSV, replacing any previous import.

    Expects a card-name column (Name / Card / Card Name) and a quantity column
    (Quantity / Qty / Count); an optional Set column disambiguates reprints.
    This upgrades get_collection from 'lower_bound' to 'exact'.
    """
    try:
        return collection_mod.import_collection(db(), path)
    except (FileNotFoundError, ValueError) as exc:
        return {"error": str(exc)}


@mcp.tool()
def refresh_cards(force: bool = False) -> dict[str, int]:
    """Re-sync the card database from Scryfall and Arena's local files.

    Runs at most once a day unless force is true. Needed after a new set drops.
    """
    return cards_mod.sync_all(db(), force=force)


# ---------------------------------------------------------------- deck builder


@mcp.tool()
def get_deck_candidates(
    format: str = "standard",
    colors: str | None = None,
    include_unowned: bool = False,
    limit: int = 400,
) -> dict[str, Any]:
    """Cards available to build a deck with, for a given format.

    Args:
        format: standard, alchemy, historic, timeless, pioneer, brawl,
            standardbrawl or historicbrawl.
        colors: Restrict to a colour identity, e.g. "R" or "UB".
        include_unowned: Also return legal cards the player does not own, each
            with owned=0, so you can propose upgrades. Check the wildcard cost
            with validate_deck before recommending one.
        limit: Maximum cards to return.

    Every entry carries `owned`, which is a LOWER BOUND -- Arena stopped
    reporting collection contents in 2021, so a card showing owned=0 may still
    be in the player's collection.
    """
    conn = db()
    try:
        pool = builder_mod.candidate_pool(
            conn, format, colors, owned_only=not include_unowned, limit=limit
        )
    except ValueError as exc:
        return {"error": str(exc)}
    inv = queries.get_inventory(conn) or {}
    return {
        "format": format,
        "colors": colors,
        "count": len(pool),
        "cards": pool,
        "wildcards_available": {
            "common": inv.get("wc_common"), "uncommon": inv.get("wc_uncommon"),
            "rare": inv.get("wc_rare"), "mythic": inv.get("wc_mythic"),
        },
        "caveat": (
            "Owned counts are a lower bound derived from decks the player built "
            "and cards granted while the tracker was running. Absence is not "
            "proof the player lacks a card."
        ),
    }


@mcp.tool()
def validate_deck(
    cards: list[dict[str, Any]],
    format: str = "standard",
    wildcard_budget: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Check a proposed decklist and report what it would cost to build.

    Args:
        cards: [{"name": "Lightning Strike", "quantity": 4, "board": "main"}, ...]
            board is "main", "sideboard" or "commander" and defaults to main.
        format: The format to check legality against.
        wildcard_budget: A self-imposed spending cap, e.g. {"rare": 1, "mythic": 0}
            to build using at most 1 rare and 0 mythic wildcards for this deck --
            distinct from `craftable_now` in wildcard_cost, which checks against
            actual stock. Omit for no budget constraint.

    Returns every problem at once (size, the four-copy limit counted by card
    NAME, format legality, unknown names) plus the wildcard cost measured
    against the player's actual stock, and -- if wildcard_budget was given --
    whether this build respects it. Call this before presenting a deck, and if
    `within_budget` is false, cut the cards named in `over_budget`'s rarities
    and try again rather than presenting an over-budget deck.
    """
    conn = db()
    try:
        result = builder_mod.validate_deck(conn, cards, format)
    except ValueError as exc:
        return {"error": str(exc)}
    result["wildcard_cost"] = builder_mod.wildcard_cost(conn, cards)
    result["wildcard_budget_check"] = builder_mod.check_wildcard_budget(
        result["wildcard_cost"], wildcard_budget
    )
    result["arena_export"] = builder_mod.to_arena_export(conn, cards)
    return result


@mcp.tool()
def save_suggested_deck(
    name: str,
    cards: list[dict[str, Any]],
    format: str = "standard",
    rationale: str | None = None,
    based_on_deck: str | None = None,
    wildcard_budget: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Save a finished deck so it appears in the player's app.

    Call this last, once validate_deck confirms the deck is legal and (if a
    budget was set) within it. The response includes `arena_export` -- give
    that text to the player directly; it pastes straight into Arena's deck
    importer, so they don't need the app open to use what you built.

    Args:
        name: A short name for the deck.
        cards: Same shape as validate_deck.
        format: The format the deck is built for.
        rationale: Why this build -- shown to the player under the deck name.
        based_on_deck: deck_id, if this is a revision of an existing deck.
        wildcard_budget: Same as validate_deck's -- re-checked and stored so
            the player's app can show whether the saved deck respects it.
    """
    try:
        return builder_mod.save_suggestion(
            db(), name, format, cards, rationale, based_on_deck, wildcard_budget
        )
    except ValueError as exc:
        return {"error": str(exc)}


@mcp.tool()
def import_deck(
    text: str,
    name: str,
    format: str = "standard",
    rationale: str | None = None,
    based_on_deck: str | None = None,
) -> dict[str, Any]:
    """Parse an Arena-format decklist and save it, same as save_suggested_deck.

    Use this when you (or the player) have a decklist as plain text rather
    than a structured `cards` list -- e.g. a list pasted from a website, or one
    you wrote out yourself instead of calling get_deck_candidates first.

    Args:
        text: Arena-importable decklist text, e.g.:
            Deck
            4 Lightning Bolt (STA) 42
            20 Mountain

            Sideboard
            2 Negate
        name: A short name for the deck.
        format: The format the deck is built for.
        rationale: Why this build. Defaults to "Imported decklist".
        based_on_deck: deck_id, if this is a revision of an existing deck.
    """
    try:
        return builder_mod.import_deck(
            db(), text, name, format, rationale, based_on_deck
        )
    except ValueError as exc:
        return {"error": str(exc)}


@mcp.tool()
def export_deck_arena(deck_id: str) -> dict[str, Any]:
    """Arena-importable text for one of the player's existing decks."""
    conn = db()
    if queries.get_deck(conn, deck_id) is None:
        return {"error": f"No deck with id {deck_id!r}."}
    return {
        "deck_id": deck_id,
        "arena_export": builder_mod.to_arena_export(
            conn, builder_mod.deck_to_cards(conn, deck_id)
        ),
    }


@mcp.prompt(
    name="build_deck",
    description="Build an MTG Arena deck from the player's own collection.",
)
def build_deck_prompt(
    format: str = "standard",
    colors: str = "",
    strategy: str = "",
    max_rare_wildcards: int | None = None,
    max_mythic_wildcards: int | None = None,
    max_uncommon_wildcards: int | None = None,
    max_common_wildcards: int | None = None,
) -> str:
    """The deck-building brief, with the player's real constraints filled in.

    The max_*_wildcards args set a spending budget for THIS deck -- separate
    from wildcard stock, which get_deck_candidates already reports. Use these
    when the player wants to keep a build cheap even though they could afford
    more, e.g. "at most 1 rare wildcard".
    """
    conn = db()
    inv = queries.get_inventory(conn) or {}
    wildcards = {
        "common": inv.get("wc_common"), "uncommon": inv.get("wc_uncommon"),
        "rare": inv.get("wc_rare"), "mythic": inv.get("wc_mythic"),
    }
    budget = {
        rarity: cap for rarity, cap in (
            ("common", max_common_wildcards), ("uncommon", max_uncommon_wildcards),
            ("rare", max_rare_wildcards), ("mythic", max_mythic_wildcards),
        ) if cap is not None
    }
    budget_line = (
        f"\n\nWildcard budget for this deck: at most {budget}. Pass this same "
        "dict as wildcard_budget to validate_deck -- if within_budget comes back "
        "false, cut cards from the rarities named in over_budget and re-check "
        "before saving. Do not present or save a deck that exceeds this budget."
        if budget else ""
    )
    return (
        f"Build a {format} deck"
        + (f" in {colors}" if colors else "")
        + (f" that is {strategy}" if strategy else "")
        + ".\n\n"
        f"The player's wildcard stock is {wildcards}."
        f"{budget_line}\n\n"
        "1. Call get_deck_candidates to see what they own.\n"
        "2. Prefer cards they already own. You may propose upgrades they do "
        "not own, but say what each costs in wildcards.\n"
        "3. Call validate_deck to confirm legality, cost, and budget.\n"
        "4. Call save_suggested_deck so the deck appears in their app. Its "
        "response includes arena_export -- give that text to the player "
        "verbatim; it pastes directly into Arena's deck importer.\n\n"
        "Their collection is a LOWER BOUND: Arena stopped reporting collection "
        "contents in 2021. Do not tell them they lack a card merely because it "
        "is absent from the pool."
    )


@mcp.resource("mtga://decks/{deck_id}")
def deck_resource(deck_id: str) -> dict[str, Any]:
    """A single deck as a resource."""
    return queries.get_deck(db(), deck_id) or {"error": "not found"}


@mcp.resource("mtga://cards/{arena_id}")
def card_resource(arena_id: str) -> dict[str, Any]:
    """A single card by its Arena grpId."""
    try:
        key = int(arena_id)
    except ValueError:
        return {"error": f"arena_id must be an integer, got {arena_id!r}"}
    return cards_mod.get_card(db(), key) or {"error": "not found"}


def serve(host: str = "127.0.0.1", port: int = 8765, web_ui: bool = True) -> None:
    """Run the MCP server, and by default the browser UI alongside it.

    Both are mounted on one Starlette app, so a single process serves the UI at
    `/` and the agent endpoint at `/mcp`. Loopback only -- do not expose this.
    """
    if web_ui:
        from . import web

        web.register(mcp, db)
        log.info("Web UI:     http://%s:%d/", host, port)
    log.info("MCP server: http://%s:%d/mcp", host, port)
    mcp.run("streamable-http", host=host, port=port)
