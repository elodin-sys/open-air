from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from openair.designer.generator import generate_design_studio
from openair.designer.server import (
    ConceptWorkspace,
    WorkspaceError,
    serve_workspace,
)


def _static_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m openair.designer",
        description=(
            "Create/edit a concept workspace, or generate the offline Design Studio."
        ),
        epilog=(
            "Workspace modes:\n"
            "  python -m openair.designer new <concept> --open\n"
            "  python -m openair.designer <concept> --open\n"
            "  python -m openair.designer edit <concept> --open"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "concept",
        nargs="?",
        help="Concept name, concept folder, or design YAML (default: template)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output HTML path (default: beside the concept design)",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the generated studio in the default browser",
    )
    return parser


def _workspace_parser(action: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"python -m openair.designer {action}",
        description=(
            "Create a new source concept with Design Studio."
            if action == "new"
            else "Edit an existing source concept with Design Studio."
        ),
    )
    parser.add_argument("concept", help="Bare concept name or designs/<name>")
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the local Design Studio in the default browser",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Localhost port (default: choose an available port)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] in {"new", "edit"}:
        action = raw.pop(0)
        parser = _workspace_parser(action)
        args = parser.parse_args(raw)
        try:
            workspace = (
                ConceptWorkspace.new(args.concept)
                if action == "new"
                else ConceptWorkspace.edit(args.concept)
            )
        except (WorkspaceError, FileNotFoundError) as exc:
            parser.error(str(exc))
        try:
            serve_workspace(
                workspace,
                port=args.port,
                open_browser=args.open,
            )
        except ValueError as exc:
            parser.error(str(exc))
        return

    parser = _static_parser()
    args = parser.parse_args(raw)
    if args.open and args.output is None and args.concept is not None:
        try:
            workspace = ConceptWorkspace.edit(args.concept)
        except (WorkspaceError, FileNotFoundError):
            pass
        else:
            serve_workspace(workspace, port=0, open_browser=True)
            return
    target = generate_design_studio(args.concept, output=args.output)
    print(f"wrote {target}")
    if args.open:
        webbrowser.open(target.as_uri())


if __name__ == "__main__":
    main()
