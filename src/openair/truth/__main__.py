"""Command line interface for the truth-validation corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openair.paths import configure_runtime
from openair.truth.corpus import fetch_case, load_registry
from openair.truth.holdout import authorize_holdout
from openair.truth.runner import (
    generate_envelope,
    run_case,
    score_case,
    validate_corpus,
)


def _case_ids(value: str) -> list[str]:
    if value == "all":
        return [entry.id for entry in load_registry().cases if entry.status == "active"]
    return [value]


def main() -> None:
    configure_runtime()
    parser = argparse.ArgumentParser(prog="python -m openair.truth")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("fetch", "run", "score"):
        child = commands.add_parser(name)
        child.add_argument("case", help="case id or 'all'")
    report = commands.add_parser("report")
    report.add_argument(
        "--output",
        type=Path,
        default=None,
        help="output markdown (default: docs/validation-envelope.md)",
    )
    commands.add_parser("validate")
    authorize = commands.add_parser("authorize")
    authorize.add_argument("case", help="class-A validation case id")
    authorize.add_argument("attempt", help="unique one-shot attempt id")
    args = parser.parse_args()

    if args.command == "fetch":
        for case_id in _case_ids(args.case):
            paths = fetch_case(case_id)
            print(f"{case_id}: {len(paths)} pinned download(s)")
    elif args.command == "run":
        for case_id in _case_ids(args.case):
            _payload, path = run_case(case_id)
            print(f"wrote {path}")
    elif args.command == "score":
        for case_id in _case_ids(args.case):
            score, path = score_case(case_id)
            print(f"wrote {path} ({score.status})")
    elif args.command == "report":
        print(f"wrote {generate_envelope(args.output)}")
    elif args.command == "validate":
        print(json.dumps(validate_corpus(), indent=2))
    elif args.command == "authorize":
        print(json.dumps(authorize_holdout(args.case, args.attempt), indent=2))


if __name__ == "__main__":
    main()
