"""Browser UI and its JSON API, mounted on the MCP server's own app.

`MCPServer.custom_route` registers Starlette routes on the same application that
serves `/mcp`, so one `mtga-companion serve` gives both a browsable UI and the
agent endpoint from a single process and database connection.

Handlers here are deliberately thin: everything they return comes from
`queries`, `collection` or `deckbuilder`, so the UI and an agent see the same
data computed the same way. Loopback only, unauthenticated -- same posture as
the MCP endpoint, and for the same reason: the data is the player's account
history and it must not be bound to a routable address.
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from . import collection as collection_mod
from . import deckbuilder, queries

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def _int(request: Request, name: str, default: int | None) -> int | None:
    try:
        return int(request.query_params.get(name, default))
    except (TypeError, ValueError):
        return default


def _float_or_none(request: Request, name: str) -> float | None:
    raw = request.query_params.get(name)
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _flag(request: Request, name: str) -> bool:
    return request.query_params.get(name, "").lower() in ("1", "true", "yes")


def _param(request: Request, name: str) -> str | None:
    value = request.query_params.get(name)
    return value or None


def register(mcp: Any, db: Callable[[], Any]) -> None:
    """Attach the UI and API routes to an MCPServer instance.

    `db` is passed in rather than imported so the web layer shares the MCP
    server's connection instead of opening a second one against the same file.
    """

    def ok(payload: Any) -> JSONResponse:
        return JSONResponse(payload)

    # ---------------------------------------------------------------- pages

    @mcp.custom_route("/", methods=["GET"])
    async def index(request: Request) -> Response:
        return FileResponse(STATIC_DIR / "index.html")

    @mcp.custom_route("/static/{path:path}", methods=["GET"])
    async def static_files(request: Request) -> Response:
        name = request.path_params["path"]
        target = (STATIC_DIR / name).resolve()
        # Contain the path: `name` comes from the URL and must not escape.
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            return Response("Not found", status_code=404)
        media_type, _ = mimetypes.guess_type(target.name)
        return FileResponse(target, media_type=media_type)

    # ------------------------------------------------------------------ api

    @mcp.custom_route("/api/status", methods=["GET"])
    async def api_status(request: Request) -> Response:
        return ok(queries.status(db()))

    @mcp.custom_route("/api/decks", methods=["GET"])
    async def api_decks(request: Request) -> Response:
        return ok(queries.list_decks(db(), include_precon=_flag(request, "include_precon")))

    @mcp.custom_route("/api/decks/{deck_id}", methods=["GET"])
    async def api_deck(request: Request) -> Response:
        conn = db()
        deck_id = request.path_params["deck_id"]
        deck = queries.get_deck(conn, deck_id)
        if deck is None:
            return JSONResponse({"error": "deck not found"}, status_code=404)
        deck["stats"] = queries.get_deck_stats(conn, deck_id)
        deck["arena_export"] = deckbuilder.to_arena_export(
            conn, deckbuilder.deck_to_cards(conn, deck_id)
        )
        return ok(deck)

    @mcp.custom_route("/api/decks/{deck_id}/notes", methods=["POST"])
    async def api_deck_notes(request: Request) -> Response:
        """Set description/playstyle/comments/recommendations on a deck.

        Player- or agent-written; never touched by log ingestion. Only fields
        present in the body are changed -- send an empty string to clear one.
        """
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "expected a JSON body"}, status_code=400)
        try:
            updated = queries.update_deck_notes(
                db(), request.path_params["deck_id"],
                description=body.get("description"),
                playstyle=body.get("playstyle"),
                comments=body.get("comments"),
                recommendations=body.get("recommendations"),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return ok(updated)

    @mcp.custom_route("/api/cards", methods=["GET"])
    async def api_cards(request: Request) -> Response:
        conn = db()
        cards = queries.search_cards(
            conn,
            query=request.query_params.get("q", ""),
            owned_only=_flag(request, "owned_only"),
            colors=_param(request, "colors"),
            rarity=_param(request, "rarity"),
            max_cmc=_float_or_none(request, "max_cmc"),
            limit=_int(request, "limit", 60),
            all_printings=_flag(request, "all_printings"),
        )
        # Annotate ownership so the UI can badge each card without a second call.
        owned = deckbuilder.owned_by_name(conn)
        for card in cards:
            card["owned"] = owned.get(card["name"], 0)
        return ok({"cards": cards, "count": len(cards)})

    @mcp.custom_route("/api/collection", methods=["GET"])
    async def api_collection(request: Request) -> Response:
        return ok(
            collection_mod.get_collection(
                db(),
                colors=_param(request, "colors"),
                rarity=_param(request, "rarity"),
                limit=_int(request, "limit", 500),
            )
        )

    @mcp.custom_route("/api/inventory", methods=["GET"])
    async def api_inventory(request: Request) -> Response:
        return ok(queries.get_inventory(db()) or {})

    @mcp.custom_route("/api/rank", methods=["GET"])
    async def api_rank(request: Request) -> Response:
        return ok(queries.get_rank(db()) or {})

    @mcp.custom_route("/api/matches", methods=["GET"])
    async def api_matches(request: Request) -> Response:
        matches = queries.get_match_history(
            db(),
            limit=_int(request, "limit", 20),
            deck_id=_param(request, "deck_id"),
        )
        return ok({"matches": matches, "count": len(matches)})

    @mcp.custom_route("/api/matches/{match_id}/plays", methods=["GET"])
    async def api_match_plays(request: Request) -> Response:
        plays = queries.get_match_plays(db(), request.path_params["match_id"])
        return ok({"plays": plays, "count": len(plays)})

    @mcp.custom_route("/api/matches/{match_id}/combat", methods=["GET"])
    async def api_match_combat(request: Request) -> Response:
        combat = queries.get_match_combat(db(), request.path_params["match_id"])
        return ok({"combat": combat, "count": len(combat)})

    @mcp.custom_route("/api/summary", methods=["GET"])
    async def api_summary(request: Request) -> Response:
        """Everything the dashboard needs, in one round trip."""
        conn = db()
        rarity_counts = dict(
            conn.execute(
                "SELECT c.rarity, COUNT(DISTINCT c.name) FROM card_ownership o "
                "JOIN cards c ON c.arena_id = o.arena_id GROUP BY c.rarity"
            ).fetchall()
        )
        by_source = dict(
            conn.execute(
                "SELECT source, COUNT(DISTINCT arena_id) FROM card_ownership "
                "GROUP BY source"
            ).fetchall()
        )
        return ok({
            "status": queries.status(conn),
            "inventory": queries.get_inventory(conn) or {},
            "rank": queries.get_rank(conn) or {},
            "decks": len(queries.list_decks(conn)),
            "owned_by_rarity": rarity_counts,
            "owned_by_source": by_source,
            "owned_total": sum(rarity_counts.values()),
        })

    # -------------------------------------------------------- deck builder

    @mcp.custom_route("/api/formats", methods=["GET"])
    async def api_formats(request: Request) -> Response:
        return ok(sorted(deckbuilder.FORMATS))

    @mcp.custom_route("/api/suggestions", methods=["GET"])
    async def api_suggestions(request: Request) -> Response:
        return ok(deckbuilder.list_suggestions(db(), limit=_int(request, "limit", 20)))

    @mcp.custom_route("/api/suggestions/{suggestion_id}", methods=["GET"])
    async def api_suggestion(request: Request) -> Response:
        try:
            key = int(request.path_params["suggestion_id"])
        except ValueError:
            return JSONResponse({"error": "bad id"}, status_code=400)
        found = deckbuilder.get_suggestion(db(), key)
        if found is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return ok(found)

    @mcp.custom_route("/api/suggestions/{suggestion_id}/notes", methods=["POST"])
    async def api_suggestion_notes(request: Request) -> Response:
        """Set description/playstyle/comments/recommendations on a saved
        suggestion, without touching its decklist."""
        try:
            key = int(request.path_params["suggestion_id"])
        except ValueError:
            return JSONResponse({"error": "bad id"}, status_code=400)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "expected a JSON body"}, status_code=400)
        try:
            updated = deckbuilder.update_suggestion_notes(
                db(), key,
                description=body.get("description"), playstyle=body.get("playstyle"),
                comments=body.get("comments"), recommendations=body.get("recommendations"),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return ok(updated)

    @mcp.custom_route("/api/duplicate-deck", methods=["POST"])
    async def api_duplicate_deck(request: Request) -> Response:
        """Clone a real deck or a saved suggestion into a new suggestion."""
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "expected a JSON body"}, status_code=400)
        new_name = (body.get("new_name") or "").strip()
        if not new_name:
            return JSONResponse({"error": "'new_name' is required"}, status_code=400)
        try:
            saved = deckbuilder.duplicate_deck(
                db(), new_name,
                deck_id=body.get("deck_id"), suggestion_id=body.get("suggestion_id"),
                fmt=body.get("format"),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return ok(saved)

    @mcp.custom_route("/api/import-deck", methods=["POST"])
    async def api_import_deck(request: Request) -> Response:
        """Paste an Arena-format decklist to save it, without going through
        an agent at all -- for a list found elsewhere, or a recommendation an
        agent gave in chat without calling the MCP tools directly."""
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "expected a JSON body"}, status_code=400)

        text = (body.get("text") or "").strip()
        name = (body.get("name") or "").strip()
        if not text or not name:
            return JSONResponse(
                {"error": "both 'text' and 'name' are required"}, status_code=400
            )
        try:
            saved = deckbuilder.import_deck(
                db(), text, name,
                fmt=body.get("format", "standard"),
                rationale=body.get("rationale"),
                based_on_deck=body.get("based_on_deck"),
                description=body.get("description"), playstyle=body.get("playstyle"),
                comments=body.get("comments"), recommendations=body.get("recommendations"),
                suggestion_id=body.get("suggestion_id"),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return ok(saved)

    @mcp.custom_route("/api/brief", methods=["GET"])
    async def api_brief(request: Request) -> Response:
        """The deck-building brief to hand an agent.

        The GUI does not call a model. It assembles the constraints -- format,
        colors, the player's real wildcard stock, and an optional wildcard
        spending budget -- so the agent has them without the player retyping
        anything.
        """
        conn = db()
        fmt = request.query_params.get("format", "standard")
        colors = _param(request, "colors")
        strategy = request.query_params.get("strategy", "").strip()
        budget = {
            rarity: _int(request, f"max_{rarity}", None)
            for rarity in ("common", "uncommon", "rare", "mythic")
        }
        budget = {k: v for k, v in budget.items() if v is not None}
        try:
            pool_size = deckbuilder.candidate_pool_size(conn, fmt, colors)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        inv = queries.get_inventory(conn) or {}
        wildcards = {
            "common": inv.get("wc_common"), "uncommon": inv.get("wc_uncommon"),
            "rare": inv.get("wc_rare"), "mythic": inv.get("wc_mythic"),
        }
        has_exact = conn.execute(
            "SELECT 1 FROM card_ownership WHERE source IN ('import', 'memory') LIMIT 1"
        ).fetchone()
        lines = [
            f"Build me a {fmt} deck" + (f" in {colors}" if colors else "") + ".",
            "",
            f"Use the mtga MCP server. My wildcard stock is {wildcards}.",
            f"I have {pool_size} known-owned {fmt}-legal cards to work with.",
        ]
        if budget:
            lines.append(
                f"Wildcard budget for this deck: at most {budget}. Call "
                "validate_deck with wildcard_budget=" + repr(budget) + " and "
                "don't present or save anything where within_budget is false."
            )
        lines += [
            "",
            "Steps:",
            f"1. Call get_deck_candidates(format='{fmt}'"
            + (f", colors='{colors}'" if colors else "") + ") for my pool.",
            "2. Build a deck preferring cards I already own.",
            "3. You may suggest upgrades I don't own, but call validate_deck to "
            "check legality" + (", budget," if budget else "") + " and the "
            "wildcard cost of each.",
            "4. Finish by calling save_suggested_deck so it appears in my app. "
            "Give me its arena_export text verbatim -- it pastes directly into "
            "Arena's deck importer.",
            "",
            (
                "Note: my collection was read from Arena's own memory (or an "
                "exact import), so the pool above is complete, not a guess."
                if has_exact else
                "Note: my collection is a LOWER BOUND (Arena stopped reporting "
                "collection contents in 2021). A card missing from the pool may "
                "still be owned - do not tell me I lack something on that basis."
            ),
        ]
        if strategy:
            lines[1:1] = ["", f"What I want: {strategy}"]
        return ok({
            "brief": "\n".join(lines),
            "format": fmt,
            "colors": colors,
            "pool_size": pool_size,
            "wildcards": wildcards,
            "wildcard_budget": budget or None,
        })

    @mcp.custom_route("/api/decks/{deck_id}/improve-brief", methods=["GET"])
    async def api_deck_improve_brief(request: Request) -> Response:
        """The deck-improvement brief for one existing deck, to hand an agent.

        Mirrors /api/brief, but starts FROM a deck the player already has
        instead of a blank format/colors pair.
        """
        conn = db()
        deck_id = request.path_params["deck_id"]
        deck = queries.get_deck(conn, deck_id)
        if deck is None:
            return JSONResponse({"error": f"No deck with id {deck_id!r}."}, status_code=404)

        focus = request.query_params.get("focus", "").strip()
        budget = {
            rarity: _int(request, f"max_{rarity}", None)
            for rarity in ("common", "uncommon", "rare", "mythic")
        }
        budget = {k: v for k, v in budget.items() if v is not None}
        budget_line = (
            f"\n\nIf you propose a revised build, keep it within a wildcard "
            f"budget of at most {budget}: pass this dict as wildcard_budget to "
            "validate_deck, and if within_budget comes back false, cut cards "
            "from the rarities named in over_budget before saving."
            if budget else ""
        )
        fmt = deck.get("format") or "standard"
        colors = deck.get("colors") or ""
        lines = [
            f"Analyze and suggest improvements for my deck {deck['name']!r} "
            f"(deck_id={deck_id!r}).",
        ]
        if focus:
            lines.append(f"What I want to focus on: {focus}.")
        lines += [
            "",
            "Use the mtga MCP server.",
            f"1. Call get_deck({deck_id!r}) and get_deck_stats({deck_id!r}) to "
            "see its current build, win rate, mana curve and color/type spread.",
            f"2. Call get_deck_candidates(format={fmt!r}"
            + (f", colors={colors!r}" if colors else "") + ", include_unowned=True) "
            "for cards that could replace weak slots.",
            "3. Call validate_deck on anything you propose." + budget_line,
            "",
            "Then either call update_deck_notes(...) with a short recommendation, "
            f"or save_suggested_deck(..., based_on_deck={deck_id!r}) with a full "
            "revised decklist -- whichever fits how much needs to change.",
            "",
            "My collection is a LOWER BOUND (Arena stopped reporting collection "
            "contents in 2021) -- do not tell me I lack a card merely because "
            "it's absent from the pool.",
        ]
        return ok({
            "brief": "\n".join(lines),
            "deck_id": deck_id,
            "deck_name": deck["name"],
            "format": fmt,
            "colors": colors,
            "wildcard_budget": budget or None,
        })

    log.info("Web UI registered at / (API under /api)")
