"""Deterministic hashes for binding generated evidence to model source."""

from __future__ import annotations

import hashlib
from pathlib import Path

from openair.paths import SRC_ROOT


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(
    directory: Path,
    *,
    include_suffixes: set[str] | None = None,
) -> str:
    """Hash relative file names and bytes without following symlinks."""
    digest = hashlib.sha256()
    files = (
        item
        for item in directory.rglob("*")
        if item.is_file()
        and (include_suffixes is None or item.suffix.lower() in include_suffixes)
    )
    for path in sorted(files):
        if path.is_symlink():
            raise ValueError(f"provenance input may not be a symlink: {path}")
        relative = path.relative_to(directory).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def model_source_sha256() -> str:
    return sha256_tree(SRC_ROOT / "openair", include_suffixes={".py"})
