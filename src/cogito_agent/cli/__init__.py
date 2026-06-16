import argparse
import sys

from cogito_agent.storage import Database


def _run_migrate(args: argparse.Namespace) -> None:
    db = Database(args.db_path)
    db.initialize()
    applied = db.migrate()
    if applied:
        for v in applied:
            print(f"Applied migration v{v}")
    else:
        print("Already up to date.")
    db.close()


def _run_chat(args: argparse.Namespace) -> None:
    from .chat import run_cli
    run_cli(db_path=args.db_path)


def run_cli() -> None:
    parser = argparse.ArgumentParser(
        prog="cogito",
        description="Cogito-Agent: Local-first personal Agent runtime",
    )

    sub = parser.add_subparsers(dest="command", help="Available commands")

    migrate_parser = sub.add_parser("migrate", help="Initialize or migrate the database")
    migrate_parser.set_defaults(db_path=":memory:")
    migrate_parser.add_argument(
        "--db", dest="db_path",
        help="SQLite database path (default: :memory:)",
    )

    chat_parser = sub.add_parser("chat", help="Start an interactive chat session")
    chat_parser.set_defaults(db_path=":memory:")
    chat_parser.add_argument(
        "--db", dest="db_path",
        help="SQLite database path (default: :memory:)",
    )

    args = parser.parse_args()

    if args.command == "migrate":
        _run_migrate(argparse.Namespace(db_path=args.db_path))
    elif args.command == "chat":
        _run_chat(argparse.Namespace(db_path=args.db_path))
    else:
        parser.print_help()
        sys.exit(1)


__all__ = [
    "run_cli",
]
