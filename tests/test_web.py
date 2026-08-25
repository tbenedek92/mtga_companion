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
