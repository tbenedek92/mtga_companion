"""Command line entry points."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading

from . import cards, collection, logwatch, paths, queries, store


def _log_setup(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _warn_if_logging_disabled() -> bool:
    """Report Arena's logging state. Returns True if game data can be read."""
    state = paths.detailed_logs_enabled()
    if state is True:
        return True
    log = logging.getLogger("mtga_companion")
    if state is False:
        log.warning(
            "Arena has Detailed Logs DISABLED - the log contains no game data. "
            "Enable Settings -> Account -> 'Detailed Logs (Plugin Support)' and "
            "restart Arena. Card data still works; decks and matches will not."
        )
    else:
        log.warning("Could not read %s - is Arena installed?", paths.PLAYER_LOG)
    return False


def cmd_status(args) -> int:
    conn = store.connect()
    print(json.dumps(queries.status(conn), indent=2))
    return 0


def cmd_sync_cards(args) -> int:
    conn = store.connect()
    print(json.dumps(cards.sync_all(conn, force=args.force), indent=2))
    return 0


def cmd_ingest(args) -> int:
    _warn_if_logging_disabled()
    conn = store.connect()
    from .parse import LogParser

    # One parser instance for the whole pass: response payloads arrive on the
    # line after their header, so parsing is stateful across lines.
    parser = LogParser(conn)
    seen = logwatch.catch_up(conn, parser.feed)
    conn.commit()
    collection.rebuild_inferred(conn)
    print(json.dumps({"lines_read": seen, **queries.status(conn)}, indent=2))
    return 0


def cmd_import_collection(args) -> int:
    conn = store.connect()
    try:
        print(json.dumps(collection.import_collection(conn, args.path), indent=2))
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_serve(args) -> int:
    _warn_if_logging_disabled()
    conn = store.connect()
    if conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0:
        logging.getLogger("mtga_companion").info("Card table empty; syncing first")
        cards.sync_all(conn)
    conn.close()

    if not args.no_tail:
        threading.Thread(
            target=_tail_forever, name="log-tailer", daemon=True
        ).start()

    from . import mcp_server

    mcp_server.serve(host=args.host, port=args.port, web_ui=not args.no_web)
    return 0


def _tail_forever() -> None:
    """Ingest log lines in the background while the server answers queries."""
    log = logging.getLogger("mtga_companion.tail")
    conn = store.connect()
    from .parse import LogParser

    parser = LogParser(conn)
    pending = 0

    def handler(line: str) -> None:
        nonlocal pending
        if parser.feed(line):
            pending += 1

    def on_idle() -> None:
        nonlocal pending
        if pending:
            conn.commit()
            collection.rebuild_inferred(conn)
            log.info("Ingested %d new events", pending)
            pending = 0

    logwatch.follow(conn, handler, on_idle=on_idle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mtga-companion",
        description="Local MTG Arena companion: reads your Arena log and serves "
        "decks, matches and collection over MCP.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="show what data is loaded")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("sync-cards", help="refresh the card database")
    p.add_argument("--force", action="store_true", help="ignore the daily cache")
    p.set_defaults(func=cmd_sync_cards)

    p = sub.add_parser("ingest", help="read new log lines once and exit")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("import-collection", help="import an exact collection CSV")
    p.add_argument("path")
    p.set_defaults(func=cmd_import_collection)

    p = sub.add_parser("serve", help="run the web UI + MCP server, tailing the log")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-tail", action="store_true", help="serve without ingesting")
    p.add_argument("--no-web", action="store_true", help="serve MCP only, no browser UI")
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    _log_setup(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
