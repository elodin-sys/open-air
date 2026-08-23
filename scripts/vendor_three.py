#!/usr/bin/env python3
"""Vendor a pinned, offline Three.js + OrbitControls browser bundle."""

from __future__ import annotations

import argparse
import hashlib
import re
import urllib.request
from pathlib import Path

VERSION = "0.170.0"
BASE_URL = f"https://unpkg.com/three@{VERSION}/"
SOURCES = {
    "three": (
        "build/three.module.min.js",
        "08fd7545d13d2c7fb65ab691530a802dafefd638596501854f267d0fb13c39e7",
    ),
    "orbit": (
        "examples/jsm/controls/OrbitControls.js",
        "80efaadea4f8a636a65fb0bd08bfef62f3d93a0bb94e2e7500f23176c5c07f4e",
    ),
    "license": (
        "LICENSE",
        "4c40a1ef62450b857c3b2aaf294936304cd552d965fbcd9d32d4c5bcf4ba4454",
    ),
}
ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = ROOT / "src/openair/designer/assets/vendor"
BUNDLE_PATH = VENDOR_DIR / "three.classic.min.js"
LICENSE_PATH = VENDOR_DIR / "THREE_LICENSE.txt"


def _download(relative: str, expected_sha256: str) -> str:
    request = urllib.request.Request(
        BASE_URL + relative,
        headers={"User-Agent": "open-air-vendor-script/1"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise RuntimeError(
            f"{relative}: expected SHA-256 {expected_sha256}, got {digest}"
        )
    return raw.decode("utf-8")


def _classic_three(module_source: str) -> str:
    match = re.search(r"export\{([^{}]+)\};?\s*$", module_source)
    if match is None:
        raise RuntimeError("Three.js module export block was not found")
    properties: list[str] = []
    for entry in match.group(1).split(","):
        entry = entry.strip()
        if " as " in entry:
            local, exported = entry.split(" as ", 1)
        else:
            local = exported = entry
        properties.append(f"{exported!r}:{local}")
    body = module_source[: match.start()]
    return (
        "(function(global){'use strict';\n"
        + body
        + "\nglobal.THREE={"
        + ",".join(properties)
        + "};\n})(window);\n"
    )


def _classic_orbit(module_source: str) -> str:
    import_match = re.search(
        r"^\s*import\s*\{([^}]+)\}\s*from\s*['\"]three['\"];\s*",
        module_source,
    )
    if import_match is None:
        raise RuntimeError("OrbitControls Three.js import block was not found")
    imports: list[str] = []
    for entry in import_match.group(1).split(","):
        entry = entry.strip()
        if " as " in entry:
            source, local = entry.split(" as ", 1)
            imports.append(f"{source}:{local}")
        else:
            imports.append(entry)
    body = module_source[import_match.end() :]
    export_match = re.search(
        r"\s*export\s*\{\s*OrbitControls\s*\};?\s*$",
        body,
    )
    if export_match is None:
        raise RuntimeError("OrbitControls export block was not found")
    body = body[: export_match.start()]
    return (
        "(function(THREE){'use strict';\nconst {"
        + ",".join(imports)
        + "}=THREE;\n"
        + body
        + "\nTHREE.OrbitControls=OrbitControls;\n})(window.THREE);\n"
    )


def _license_comment(license_text: str) -> str:
    if "*/" in license_text:
        raise RuntimeError("Three.js license cannot be embedded safely")
    lines = "\n".join(
        f" * {line}" if line else " *" for line in license_text.splitlines()
    )
    return f"/*!\n * Three.js {VERSION} + OrbitControls\n{lines}\n */\n"


def build_bundle() -> tuple[str, str]:
    three = _download(*SOURCES["three"])
    orbit = _download(*SOURCES["orbit"])
    license_text = _download(*SOURCES["license"])
    bundle = (
        _license_comment(license_text) + _classic_three(three) + _classic_orbit(orbit)
    )
    if re.search(r"(^|\n)\s*(import|export)\s", bundle):
        raise RuntimeError("ES module syntax remains in generated classic bundle")
    if "</script" in bundle.lower() or "<!--" in bundle:
        raise RuntimeError("generated bundle contains an unsafe inline-script token")
    return bundle, license_text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify committed files match regenerated pinned assets",
    )
    args = parser.parse_args()
    bundle, license_text = build_bundle()
    if args.check:
        if (
            not BUNDLE_PATH.is_file()
            or BUNDLE_PATH.read_text(encoding="utf-8") != bundle
            or not LICENSE_PATH.is_file()
            or LICENSE_PATH.read_text(encoding="utf-8") != license_text
        ):
            raise SystemExit("vendored Three.js assets are stale")
        print(f"Three.js {VERSION} vendored assets are current")
        return 0

    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    BUNDLE_PATH.write_text(bundle, encoding="utf-8")
    LICENSE_PATH.write_text(license_text, encoding="utf-8")
    print(f"wrote {BUNDLE_PATH.relative_to(ROOT)} ({len(bundle):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
