"""JSON API handlers, exercised through a real Starlette app.

The routes are registered on an MCPServer via custom_route, so these tests
build one the same way `serve()` does rather than calling the handlers
directly -- that way a routing or serialisation mistake is caught too.
"""

from __future__ import annotations

import pytest
from mcp.server.mcpserver import MCPServer
from starlette.testclient import TestClient

from mtga_companion import store, web


@pytest.fixture
def client(tmp_path):
    # Same settings the server uses: TestClient dispatches on another thread.
    conn = store.connect(tmp_path / "web.sqlite", check_same_thread=False)
    conn.executemany(
        "INSERT INTO cards (arena_id, name, mana_cost, cmc, colors, color_identity,"
        " type_line, rarity, set_code, collector_number, image_uri, legalities, source)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'scryfall')",
        [
            (1, "Lightning Bolt", "{R}", 1, "R", "R", "Instant", "rare", "sta", "42",
             "https://img/bolt.jpg", '{"standard":"legal"}'),
            (2, "Mountain", "", 0, "", "", "Basic Land — Mountain", "basic", "m19", "1",
             "https://img/mtn.jpg", '{"standard":"legal"}'),
        ],
    )
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, colors, deck_kind) "
        "VALUES ('d1','Burn','Standard','R','player')"
    )
    conn.execute(
        "INSERT INTO decks (deck_id, name, deck_kind) VALUES ('p1','Precon','precon')"
    )
    conn.executemany(
        "INSERT INTO deck_cards (deck_id, arena_id, quantity, board) VALUES (?,?,?,'main')",
        [("d1", 1, 4), ("d1", 2, 20)],
    )
    conn.execute(
        "INSERT INTO card_ownership (arena_id, source, quantity, confidence) "
        "VALUES (1,'deck',4,'lower_bound')"
    )
    conn.execute(
        "INSERT INTO inventory (captured_at, gold, gems, wc_common, wc_uncommon,"
        " wc_rare, wc_mythic) VALUES ('2026-01-01',250,100,20,26,5,6)"
    )
    conn.commit()

    mcp = MCPServer(name="test")
    web.register(mcp, lambda: conn)
    with TestClient(mcp.streamable_http_app()) as c:
        yield c
    conn.close()


def test_index_and_static_are_served(client):
    assert client.get("/").status_code == 200
    assert "MTGA" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_static_path_traversal_is_blocked(client):
    """`path` comes from the URL and must not escape the static directory."""
    for attempt in ("../store.py", "..%2Fstore.py", "../../../etc/passwd"):
        assert client.get(f"/static/{attempt}").status_code == 404


def test_decks_excludes_precons_by_default(client):
    assert [d["name"] for d in client.get("/api/decks").json()] == ["Burn"]
    both = client.get("/api/decks?include_precon=1").json()
    assert {d["name"] for d in both} == {"Burn", "Precon"}


def test_deck_detail_carries_stats_and_export(client):
    deck = client.get("/api/decks/d1").json()
    assert deck["name"] == "Burn"
    assert deck["stats"]["lands"] == 20
    assert "4 Lightning Bolt (STA) 42" in deck["arena_export"]


def test_deck_cards_include_images(client):
    """The image grid is the default view; a missing column empties it."""
    cards = client.get("/api/decks/d1").json()["mainboard"]
    assert all(c["image_uri"] for c in cards)


def test_missing_deck_is_404(client):
    assert client.get("/api/decks/nope").status_code == 404


def test_cards_search_annotates_ownership(client):
    data = client.get("/api/cards?q=Lightning").json()
    assert data["count"] == 1
    assert data["cards"][0]["owned"] == 4


def test_collection_reports_completeness(client):
    data = client.get("/api/collection").json()
    assert data["completeness"] == "lower_bound"
    assert "LOWER BOUND" in data["caveat"]


def test_summary_is_one_round_trip_for_the_dashboard(client):
    data = client.get("/api/summary").json()
    assert data["decks"] == 1
    assert data["inventory"]["wc_mythic"] == 6
    assert data["owned_by_rarity"] == {"rare": 1}


def test_brief_includes_real_wildcards_and_pool_size(client):
    data = client.get("/api/brief?format=standard&colors=R&strategy=fast").json()
    assert data["wildcards"]["mythic"] == 6
    assert "fast" in data["brief"]
    assert "save_suggested_deck" in data["brief"]
    assert "LOWER BOUND" in data["brief"]


def test_brief_rejects_an_unknown_format(client):
    assert client.get("/api/brief?format=nonsense").status_code == 400


def test_suggestions_endpoints(client):
    assert client.get("/api/suggestions").json() == []
    assert client.get("/api/suggestions/1").status_code == 404
    assert client.get("/api/suggestions/notanumber").status_code == 400


def test_cards_owned_only_filters_to_owned(client):
    all_cards = client.get("/api/cards?q=&limit=10").json()["count"]
    owned_cards = client.get("/api/cards?owned_only=1").json()
    assert owned_cards["count"] < all_cards
    assert all(c["owned"] > 0 for c in owned_cards["cards"])


def test_brief_includes_wildcard_budget_when_given(client):
    data = client.get("/api/brief?format=standard&max_rare=1&max_mythic=0").json()
    assert data["wildcard_budget"] == {"rare": 1, "mythic": 0}
    assert "validate_deck with wildcard_budget" in data["brief"]


def test_brief_omits_budget_language_when_not_given(client):
    data = client.get("/api/brief?format=standard").json()
    assert data["wildcard_budget"] is None
    assert "wildcard_budget=" not in data["brief"]


def test_import_deck_saves_and_is_listed(client):
    res = client.post("/api/import-deck", json={
        "name": "Pasted List", "text": "Deck\n4 Lightning Bolt\n56 Mountain\n",
        "format": "standard",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Pasted List"
    assert "arena_export" in body

    listed = client.get("/api/suggestions").json()
    assert any(s["name"] == "Pasted List" for s in listed)


def test_import_deck_requires_name_and_text(client):
    assert client.post("/api/import-deck", json={"text": "4 Lightning Bolt"}).status_code == 400
    assert client.post("/api/import-deck", json={"name": "X"}).status_code == 400
    assert client.post("/api/import-deck", json={}).status_code == 400


def test_import_deck_rejects_unparseable_text(client):
    res = client.post("/api/import-deck", json={"name": "X", "text": "nothing here"})
    assert res.status_code == 400
    assert "Could not parse" in res.json()["error"]


def test_import_deck_rejects_non_json_body(client):
    res = client.post(
        "/api/import-deck", content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 400


def test_deck_notes_endpoint_updates_and_returns_the_deck(client):
    res = client.post("/api/decks/d1/notes", json={
        "playstyle": "Aggro", "description": "Cheap and fast.",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["playstyle"] == "Aggro"
    assert body["description"] == "Cheap and fast."

    # Confirm it's the same data the deck detail endpoint would show.
    deck = client.get("/api/decks/d1").json()
    assert deck["playstyle"] == "Aggro"


def test_deck_notes_partial_update_preserves_other_fields(client):
    client.post("/api/decks/d1/notes", json={"comments": "First"})
    client.post("/api/decks/d1/notes", json={"playstyle": "Control"})
    deck = client.get("/api/decks/d1").json()
    assert deck["comments"] == "First"
    assert deck["playstyle"] == "Control"


def test_deck_notes_requires_at_least_one_field(client):
    res = client.post("/api/decks/d1/notes", json={})
    assert res.status_code == 400


def test_deck_notes_unknown_deck_is_400(client):
    res = client.post("/api/decks/nope/notes", json={"comments": "x"})
    assert res.status_code == 400


def test_deck_notes_rejects_non_json_body(client):
    res = client.post(
        "/api/decks/d1/notes", content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 400


def test_suggestion_notes_endpoint_updates_and_returns_the_suggestion(client):
    saved = client.post("/api/import-deck", json={
        "name": "V1", "text": "Deck\n4 Lightning Bolt\n56 Mountain\n",
        "format": "standard",
    }).json()

    res = client.post(f"/api/suggestions/{saved['suggestion_id']}/notes", json={
        "playstyle": "Aggro", "description": "Cheap and fast.",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["playstyle"] == "Aggro"
    assert body["description"] == "Cheap and fast."

    fetched = client.get(f"/api/suggestions/{saved['suggestion_id']}").json()
    assert fetched["playstyle"] == "Aggro"


def test_suggestion_notes_partial_update_preserves_other_fields(client):
    saved = client.post("/api/import-deck", json={
        "name": "V1", "text": "Deck\n60 Mountain\n", "format": "standard",
    }).json()
    sid = saved["suggestion_id"]

    client.post(f"/api/suggestions/{sid}/notes", json={"comments": "First"})
    client.post(f"/api/suggestions/{sid}/notes", json={"playstyle": "Control"})
    fetched = client.get(f"/api/suggestions/{sid}").json()
    assert fetched["comments"] == "First"
    assert fetched["playstyle"] == "Control"


def test_suggestion_notes_requires_at_least_one_field(client):
    saved = client.post("/api/import-deck", json={
        "name": "V1", "text": "Deck\n60 Mountain\n", "format": "standard",
    }).json()
    res = client.post(f"/api/suggestions/{saved['suggestion_id']}/notes", json={})
    assert res.status_code == 400


def test_suggestion_notes_unknown_id_is_400(client):
    res = client.post("/api/suggestions/999/notes", json={"comments": "x"})
    assert res.status_code == 400


def test_suggestion_notes_bad_id_is_400(client):
    res = client.post("/api/suggestions/notanumber/notes", json={"comments": "x"})
    assert res.status_code == 400


def test_suggestion_notes_rejects_non_json_body(client):
    saved = client.post("/api/import-deck", json={
        "name": "V1", "text": "Deck\n60 Mountain\n", "format": "standard",
    }).json()
    res = client.post(
        f"/api/suggestions/{saved['suggestion_id']}/notes",
        content=b"not json", headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 400


def test_import_deck_with_suggestion_id_revises_in_place(client):
    first = client.post("/api/import-deck", json={
        "name": "V1", "text": "Deck\n60 Mountain\n", "format": "standard",
    }).json()
    second = client.post("/api/import-deck", json={
        "name": "V2", "text": "Deck\n4 Lightning Bolt\n56 Mountain\n",
        "format": "standard", "suggestion_id": first["suggestion_id"],
    }).json()
    assert second["suggestion_id"] == first["suggestion_id"]
    assert len(client.get("/api/suggestions").json()) == 1


def test_duplicate_deck_from_real_deck(client):
    res = client.post("/api/duplicate-deck", json={"new_name": "Burn Variant", "deck_id": "d1"})
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Burn Variant"

    suggestions = client.get("/api/suggestions").json()
    assert any(s["name"] == "Burn Variant" for s in suggestions)


def test_duplicate_deck_from_suggestion(client):
    saved = client.post("/api/import-deck", json={
        "name": "Base", "text": "Deck\n60 Mountain\n", "format": "standard",
    }).json()
    res = client.post("/api/duplicate-deck", json={
        "new_name": "Base Fork", "suggestion_id": saved["suggestion_id"],
    })
    assert res.status_code == 200
    assert res.json()["suggestion_id"] != saved["suggestion_id"]


def test_duplicate_deck_requires_new_name(client):
    res = client.post("/api/duplicate-deck", json={"deck_id": "d1"})
    assert res.status_code == 400


def test_duplicate_deck_requires_exactly_one_source(client):
    res = client.post("/api/duplicate-deck", json={"new_name": "X"})
    assert res.status_code == 400


def test_duplicate_deck_rejects_non_json_body(client):
    res = client.post(
        "/api/duplicate-deck", content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 400


def test_deck_improve_brief_includes_deck_and_steps(client):
    data = client.get("/api/decks/d1/improve-brief").json()
    assert data["deck_id"] == "d1"
    assert data["deck_name"] == "Burn"
    assert "d1" in data["brief"]
    assert "update_deck_notes" in data["brief"]
    assert "save_suggested_deck" in data["brief"]


def test_deck_improve_brief_includes_focus_when_given(client):
    data = client.get("/api/decks/d1/improve-brief?focus=beat+control").json()
    assert "beat control" in data["brief"]


def test_deck_improve_brief_includes_wildcard_budget_when_given(client):
    data = client.get("/api/decks/d1/improve-brief?max_rare=1&max_mythic=0").json()
    assert data["wildcard_budget"] == {"rare": 1, "mythic": 0}
    assert "wildcard_budget" in data["brief"]


def test_deck_improve_brief_omits_budget_language_when_not_given(client):
    data = client.get("/api/decks/d1/improve-brief").json()
    assert data["wildcard_budget"] is None


def test_deck_improve_brief_unknown_deck_is_404(client):
    res = client.get("/api/decks/nope/improve-brief")
    assert res.status_code == 404
