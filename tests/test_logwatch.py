"""Tailer behaviour, especially the cases Arena actually produces."""

from __future__ import annotations

import pytest

from mtga_companion import logwatch, store


@pytest.fixture
def conn(tmp_path):
    c = store.connect(tmp_path / "test.sqlite")
    yield c
    c.close()


def test_reads_all_complete_lines(tmp_path, conn):
    log = tmp_path / "Player.log"
    log.write_text("alpha\nbeta\ngamma\n")

    assert list(logwatch.iter_lines(conn, log)) == ["alpha", "beta", "gamma"]


def test_second_read_returns_only_new_lines(tmp_path, conn):
    log = tmp_path / "Player.log"
    log.write_text("one\n")
    assert list(logwatch.iter_lines(conn, log)) == ["one"]

    # Nothing new yet.
    assert list(logwatch.iter_lines(conn, log)) == []

    with log.open("a") as fh:
        fh.write("two\n")
    assert list(logwatch.iter_lines(conn, log)) == ["two"]


def test_partial_trailing_line_is_held_back(tmp_path, conn):
    """The game writes while we read; a half-written line must not be emitted."""
    log = tmp_path / "Player.log"
    log.write_text("complete\npar")

    assert list(logwatch.iter_lines(conn, log)) == ["complete"]

    # Once the line is finished it comes through whole, not as a fragment.
    with log.open("a") as fh:
        fh.write("tial\n")
    assert list(logwatch.iter_lines(conn, log)) == ["partial"]


def test_truncation_rereads_from_start(tmp_path, conn):
    """Arena rewrites Player.log on launch; we must not sit at a stale offset."""
    log = tmp_path / "Player.log"
    log.write_text("old session line one\nold session line two\n")
    assert len(list(logwatch.iter_lines(conn, log))) == 2

    # New Arena launch: shorter file, entirely different content.
    log.write_text("new\n")
    assert list(logwatch.iter_lines(conn, log)) == ["new"]


def test_missing_file_is_not_an_error(tmp_path, conn):
    assert list(logwatch.iter_lines(conn, tmp_path / "nope.log")) == []


def test_cursor_persists_across_connections(tmp_path):
    db = tmp_path / "test.sqlite"
    log = tmp_path / "Player.log"
    log.write_text("first\n")

    c1 = store.connect(db)
    assert list(logwatch.iter_lines(c1, log)) == ["first"]
    c1.close()

    with log.open("a") as fh:
        fh.write("second\n")

    c2 = store.connect(db)
    assert list(logwatch.iter_lines(c2, log)) == ["second"]
    c2.close()


def test_invalid_utf8_does_not_crash(tmp_path, conn):
    log = tmp_path / "Player.log"
    log.write_bytes(b"good line\n\xff\xfe bad bytes\n")

    lines = list(logwatch.iter_lines(conn, log))
    assert lines[0] == "good line"
    assert len(lines) == 2
