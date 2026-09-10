"""Command-line entry point for the static design-review site."""

from __future__ import annotations

import argparse
from pathlib import Path

from openair.site.build import (
    DEFAULT_REPO_ROOT,
    DEFAULT_REPO_URL,
    SiteBuildError,
    build_site,
)


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m openair.site")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser(
        "build",
        help="build and validate the GitHub Pages artifact",
    )
    build.add_argument(
        "--out",
        type=Path,
        required=True,
        help="destination directory (replaced if it exists)",
    )
    build.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help="open-air repository root",
    )
    build.add_argument(
        "--manifest",
        type=Path,
        help="design manifest (defaults to site/designs.yaml)",
    )
    build.add_argument(
        "--repo-url",
        default=DEFAULT_REPO_URL,
        help="public GitHub repository URL",
    )
    build.add_argument(
        "--commit",
        help="source revision for immutable repository links",
    )
    args = parser.parse_args()

    if args.command == "build":
        try:
            designs = build_site(
                repo_root=args.repo_root,
                output_dir=args.out,
                manifest_path=args.manifest,
                repo_url=args.repo_url,
                commit=args.commit,
            )
        except SiteBuildError as exc:
            parser.error(str(exc))
        print(f"built {args.out} with {len(designs)} design reviews")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
