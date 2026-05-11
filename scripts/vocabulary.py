from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from services.common.paths import ProjectPaths
from services.vocabulary.store import VocabularyStore


Output = Callable[[str], None]


def main(argv: list[str] | None = None, *, output: Output = print) -> int:
    parser = argparse.ArgumentParser(description="Manage LocalFlow vocabulary and corrections.")
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to the LocalFlow SQLite database.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_term = subparsers.add_parser("add-term", help="Add or reinforce a vocabulary term.")
    add_term.add_argument("term")

    add_correction = subparsers.add_parser("add-correction", help="Add a spoken correction pair.")
    add_correction.add_argument("original")
    add_correction.add_argument("corrected")

    list_terms = subparsers.add_parser("list", help="List learned vocabulary and corrections.")
    list_terms.add_argument("--limit", type=int, default=20)

    args = parser.parse_args(argv)
    db_path = args.db or ProjectPaths.discover().db_dir / "localflow.db"
    store = VocabularyStore(db_path)

    if args.command == "add-term":
        store.add_word(args.term)
        output(f"Added vocabulary term: {args.term}")
        return 0

    if args.command == "add-correction":
        store.record_correction(args.original, args.corrected)
        output(f"Added correction: {args.original} -> {args.corrected}")
        return 0

    if args.command == "list":
        for term in store.formatter_hints(vocabulary_limit=args.limit, correction_limit=args.limit):
            output(term)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
