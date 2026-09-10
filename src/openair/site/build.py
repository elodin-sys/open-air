"""Build the static GitHub Pages artifact from committed design previews."""

from __future__ import annotations

import base64
import binascii
import html
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import yaml
from PIL import Image, UnidentifiedImageError

from openair.site.templates import render_404, render_index


DEFAULT_REPO_URL = "https://github.com/elodin-sys/open-air"
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
PUBLISHED_ASSETS = (
    "executive_brief.pdf",
    "baseline_vs_optimized.png",
    "cg_np_balance.png",
)
THREEVIEW_PREVIEW_ASSET = "optimized-threeview.png"
OUTPUT_MARKER = ".openair-generated-site"
ALLOWED_KINDS = {"reproduction", "inspiration", "sealed holdout"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
REVISION_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
REPO_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
DOC_LINK_RE = re.compile(r"""href=(["'])(\.\./\.\./docs/[^"']+)\1""")
THREEVIEW_IMAGE_RE = re.compile(
    r'<h3>Exported-aircraft three-view</h3>'
    r'<img src="data:image/png;base64,([^"]+)"'
)
REPORT_BRAND = '<div class="brand">open-air · concept review</div>'
REPORT_BRAND_LINK = (
    '<div class="brand"><a href="../../" '
    'style="color:inherit;text-decoration:none">open-air · concept review</a></div>'
)
REPORT_EXECUTIVE_MARKER = '<section id="executive"><div class="wrap">'
HISTORICAL_PATH_META = (
    '<p class="meta">Concept source: designs/openair-x8-capstone/design.yaml'
    "<br>Optimized spec: results/openair-x8-capstone/optimized/design.yaml</p>"
)
HISTORICAL_PATH_REPLACEMENT = (
    '<p class="meta"><b>Publication-only historical artifact:</b> no source '
    "or optimized YAML was committed with this sealed report; the paths named "
    "by the original generator are unavailable.</p>"
)
HISTORICAL_NOTICE = """<section style="padding:24px 0"><div class="wrap">
  <div class="card" style="border-left:6px solid var(--orange)">
    <div class="eyebrow">Historical artifact notice</div>
    <h3>Frozen report; publication-only context</h3>
    <p>This 2026-08-22 report is retained as sealed historical evidence. Its original generator claimed concept-source and optimized-spec paths that were never committed and cannot be regenerated under the current schema. Read the embedded results in that historical context; this notice does not reopen or alter the holdout evidence.</p>
  </div>
</div></section>

"""
REGULAR_GIT_MODES = {"100644", "100755"}


class SiteBuildError(ValueError):
    """Raised when the publishable preview set violates the site contract."""


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id:
            self.ids.add(element_id)
        if tag == "a" and attributes.get("name"):
            self.ids.add(attributes["name"])
        for name, value in attrs:
            if name in {"href", "src"} and value:
                self.links.append(value)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SiteBuildError(f"cannot read YAML {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SiteBuildError(f"{path} must contain a YAML mapping")
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SiteBuildError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SiteBuildError(f"{path} must contain a JSON object")
    return payload


def _git_tree(
    repo_root: Path,
    commit: str,
) -> dict[str, tuple[str, str]]:
    try:
        raw = subprocess.run(
            [
                "git",
                "ls-tree",
                "-r",
                "-z",
                "--full-tree",
                commit,
                "--",
                "results",
                "designs",
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SiteBuildError(
            f"cannot inspect publish inputs at Git revision {commit}"
        ) from exc

    tracked: dict[str, tuple[str, str]] = {}
    for record in raw.split("\0"):
        if not record:
            continue
        try:
            metadata, relative = record.split("\t", 1)
            mode, object_type, blob = metadata.split()
        except ValueError as exc:
            raise SiteBuildError(f"cannot parse Git tree record {record!r}") from exc
        if object_type != "blob":
            raise SiteBuildError(
                f"publish input is not a Git blob at {commit}: {relative}"
            )
        tracked[PurePosixPath(relative).as_posix()] = (mode, blob)
    return tracked


def _require_tracked_regular(
    path: Path,
    *,
    repo_root: Path,
    tracked: dict[str, tuple[str, str]],
    expected_root: Path,
) -> None:
    try:
        relative = path.relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise SiteBuildError(f"publish input escapes repository: {path}") from exc
    record = tracked.get(relative)
    if record is None:
        raise SiteBuildError(
            f"publish input is not tracked at the build revision: {relative}"
        )
    mode, indexed_blob = record
    if mode not in REGULAR_GIT_MODES:
        raise SiteBuildError(
            f"publish input is not a regular Git blob: {relative} (mode {mode})"
        )

    current = repo_root
    for part in Path(relative).parts:
        current /= part
        if current.is_symlink():
            raise SiteBuildError(f"publish input traverses a symlink: {relative}")
    if not path.is_file():
        raise SiteBuildError(f"tracked publish input is missing: {relative}")
    resolved = path.resolve()
    if not resolved.is_relative_to(repo_root) or not resolved.is_relative_to(
        expected_root.resolve()
    ):
        raise SiteBuildError(f"publish input escapes its design directory: {relative}")

    try:
        working_blob = subprocess.run(
            ["git", "hash-object", "--", relative],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SiteBuildError(f"cannot hash publish input {relative}") from exc
    if working_blob != indexed_blob:
        raise SiteBuildError(
            f"publish input differs from the build revision: {relative}"
        )


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    payload = _read_yaml(path)
    raw_designs = payload.get("designs")
    if not isinstance(raw_designs, list) or not raw_designs:
        raise SiteBuildError(f"{path} must define a non-empty designs list")

    required = {"slug", "title", "summary", "kind"}
    allowed = required | {"featured"}
    designs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_designs):
        where = f"{path}: designs[{index}]"
        if not isinstance(raw, dict):
            raise SiteBuildError(f"{where} must be a mapping")
        missing = required - raw.keys()
        extra = raw.keys() - allowed
        if missing:
            raise SiteBuildError(f"{where} is missing {sorted(missing)}")
        if extra:
            raise SiteBuildError(f"{where} has unsupported fields {sorted(extra)}")

        slug = raw["slug"]
        if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
            raise SiteBuildError(f"{where}.slug must be a safe lowercase slug")
        if slug in seen:
            raise SiteBuildError(f"{path} contains duplicate slug {slug!r}")
        seen.add(slug)

        for field in ("title", "summary", "kind"):
            if not isinstance(raw[field], str) or not raw[field].strip():
                raise SiteBuildError(f"{where}.{field} must be non-empty text")
        if raw["kind"] not in ALLOWED_KINDS:
            raise SiteBuildError(
                f"{where}.kind must be one of {sorted(ALLOWED_KINDS)}"
            )
        if "featured" in raw and not isinstance(raw["featured"], bool):
            raise SiteBuildError(f"{where}.featured must be true or false")

        designs.append(
            {
                "slug": slug,
                "title": raw["title"].strip(),
                "summary": raw["summary"].strip(),
                "kind": raw["kind"],
                "featured": bool(raw.get("featured", False)),
            }
        )

    featured = [design["slug"] for design in designs if design["featured"]]
    if len(featured) != 1:
        raise SiteBuildError(
            f"{path} must mark exactly one design featured; found {featured}"
        )
    return designs


def _discover_reports(
    repo_root: Path,
    tracked: dict[str, tuple[str, str]],
) -> dict[str, Path]:
    reports: dict[str, Path] = {}
    for relative in sorted(tracked):
        parts = PurePosixPath(relative).parts
        if (
            len(parts) == 3
            and parts[0] == "results"
            and parts[2] == "report.html"
        ):
            reports[parts[1]] = repo_root / relative
    return reports


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _run_date(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return f"{parsed.day} {parsed.strftime('%b %Y')}"


def _design_view(
    design: dict[str, Any],
    *,
    repo_root: Path,
    tracked: dict[str, tuple[str, str]],
) -> dict[str, Any]:
    slug = design["slug"]
    source_path = repo_root / "designs" / slug / "design.yaml"
    treatment: str | None = None
    span_m: float | None = None
    length_m: float | None = None
    if source_path.is_file():
        _require_tracked_regular(
            source_path,
            repo_root=repo_root,
            tracked=tracked,
            expected_root=source_path.parent,
        )
        source = _read_yaml(source_path)
        sketch = source.get("sketch")
        if isinstance(sketch, dict) and isinstance(sketch.get("treatment"), str):
            treatment = sketch["treatment"]

    if design["kind"] != "sealed holdout" and treatment != design["kind"]:
        raise SiteBuildError(
            f"{slug}: manifest kind {design['kind']!r} does not match "
            f"design.yaml sketch.treatment {treatment!r}"
        )
    if design["kind"] == "sealed holdout" and source_path.exists():
        raise SiteBuildError(
            f"{slug}: sealed holdout entries must not have a mutable design source"
        )

    package_dir = (
        repo_root / "results" / slug / "optimized" / "elodin_package"
    )
    model_path = package_dir / "elodin_model.json"
    credibility: str | None = None
    created_at: str | None = None
    source_commit: str | None = None
    pipeline_run_id: str | None = None
    if model_path.is_file():
        _require_tracked_regular(
            model_path,
            repo_root=repo_root,
            tracked=tracked,
            expected_root=package_dir,
        )
        model = _read_json(model_path)
        if model.get("concept") != slug or model.get("phase") != "optimized":
            raise SiteBuildError(
                f"{slug}: Elodin package identity/phase does not match its path"
            )
        reference_geometry = model.get("reference_geometry")
        if isinstance(reference_geometry, dict):
            span_m = _as_float(reference_geometry.get("span_m"))
            fuselage = reference_geometry.get("fuselage")
            if isinstance(fuselage, dict):
                length_m = _as_float(fuselage.get("length_m"))
        if isinstance(model.get("credibility"), str):
            credibility = model["credibility"]
        if isinstance(model.get("created_at"), str):
            created_at = model["created_at"]
        provenance = model.get("provenance")
        if isinstance(provenance, dict):
            if isinstance(provenance.get("source_git_commit"), str):
                source_commit = provenance["source_git_commit"]
            if isinstance(provenance.get("pipeline_run_id"), str):
                pipeline_run_id = provenance["pipeline_run_id"]

    return {
        **design,
        "kind_key": design["kind"],
        "kind": design["kind"].title(),
        "treatment": treatment,
        "span_m": span_m,
        "length_m": length_m,
        "credibility": credibility,
        "created_at": created_at,
        "run_date": _run_date(created_at),
        "source_git_commit": source_commit,
        "pipeline_run_id": pipeline_run_id,
        "has_package": model_path.is_file(),
    }


def _validate_publish_set(
    designs: list[dict[str, Any]],
    reports: dict[str, Path],
    *,
    repo_root: Path,
    results_root: Path,
    tracked: dict[str, tuple[str, str]],
) -> None:
    manifest_slugs = {design["slug"] for design in designs}
    report_slugs = set(reports)
    if manifest_slugs != report_slugs:
        missing_manifest = sorted(report_slugs - manifest_slugs)
        missing_report = sorted(manifest_slugs - report_slugs)
        details: list[str] = []
        if missing_manifest:
            details.append(f"reports without manifest entries: {missing_manifest}")
        if missing_report:
            details.append(f"manifest entries without reports: {missing_report}")
        raise SiteBuildError("; ".join(details))

    for slug in sorted(report_slugs):
        design_root = results_root / slug
        _require_tracked_regular(
            reports[slug],
            repo_root=repo_root,
            tracked=tracked,
            expected_root=design_root,
        )
        for asset in PUBLISHED_ASSETS:
            _require_tracked_regular(
                design_root / asset,
                repo_root=repo_root,
                tracked=tracked,
                expected_root=design_root,
            )


def _rewrite_report(
    document: str,
    *,
    repo_url: str,
    commit: str,
    slug: str,
    historical: bool,
) -> str:
    def docs_link(match: re.Match[str]) -> str:
        parsed = urlsplit(html.unescape(match.group(2)))
        relative_path = parsed.path.removeprefix("../../docs/")
        doc_path = PurePosixPath(unquote(relative_path))
        if doc_path.is_absolute() or ".." in doc_path.parts:
            raise SiteBuildError(f"{slug}: unsafe documentation link {doc_path}")
        target = (
            f"{repo_url}/blob/{quote(commit, safe='')}/docs/"
            f"{quote(doc_path.as_posix(), safe='/')}"
        )
        if parsed.query:
            target += f"?{parsed.query}"
        if parsed.fragment:
            target += f"#{parsed.fragment}"
        return (
            f"href={match.group(1)}{html.escape(target, quote=True)}"
            f"{match.group(1)}"
        )

    rewritten = DOC_LINK_RE.sub(docs_link, document)
    if "../../docs/" in rewritten:
        raise SiteBuildError(f"{slug}: unresolved repository documentation link")
    if REPORT_BRAND not in rewritten:
        raise SiteBuildError(f"{slug}: report topbar brand marker is missing")
    rewritten = rewritten.replace(REPORT_BRAND, REPORT_BRAND_LINK, 1)
    if historical:
        if (
            REPORT_EXECUTIVE_MARKER not in rewritten
            or HISTORICAL_PATH_META not in rewritten
        ):
            raise SiteBuildError(
                f"{slug}: historical report publication markers are missing"
            )
        rewritten = rewritten.replace(
            REPORT_EXECUTIVE_MARKER,
            HISTORICAL_NOTICE + REPORT_EXECUTIVE_MARKER,
            1,
        )
        rewritten = rewritten.replace(
            HISTORICAL_PATH_META,
            HISTORICAL_PATH_REPLACEMENT,
            1,
        )
    return rewritten


def _threeview_preview(document: str, *, slug: str) -> bytes:
    match = THREEVIEW_IMAGE_RE.search(document)
    if match is None:
        raise SiteBuildError(
            f"{slug}: report has no embedded optimized three-view image"
        )
    try:
        source = base64.b64decode(match.group(1), validate=True)
        with Image.open(BytesIO(source)) as image:
            image.load()
            width, height = image.size
            if image.format != "PNG" or not (2.5 <= width / height <= 3.5):
                raise SiteBuildError(
                    f"{slug}: embedded three-view has unexpected format or "
                    f"dimensions ({image.format}, {width}x{height})"
                )
            # The report figure has three equal columns: top, side, front.
            # Retaining top + side produces a legible 2:1 publishing image
            # without depending on ignored stage artifacts.
            preview = image.crop((0, 0, 2 * width // 3, height))
            output = BytesIO()
            preview.save(output, format="PNG", optimize=True)
            return output.getvalue()
    except (binascii.Error, UnidentifiedImageError, OSError) as exc:
        raise SiteBuildError(
            f"{slug}: embedded optimized three-view is not a valid PNG"
        ) from exc


def _copy_design(
    design: dict[str, Any],
    report_path: Path,
    *,
    results_root: Path,
    output_root: Path,
    repo_url: str,
    commit: str,
) -> None:
    slug = design["slug"]
    destination = output_root / "designs" / slug
    destination.mkdir(parents=True, exist_ok=True)
    report = report_path.read_text(encoding="utf-8")
    (destination / THREEVIEW_PREVIEW_ASSET).write_bytes(
        _threeview_preview(report, slug=slug)
    )
    (destination / "index.html").write_text(
        _rewrite_report(
            report,
            repo_url=repo_url,
            commit=commit,
            slug=slug,
            historical=design["kind_key"] == "sealed holdout",
        ),
        encoding="utf-8",
    )
    for asset in PUBLISHED_ASSETS:
        shutil.copy2(results_root / slug / asset, destination / asset)


def _validate_local_links(output_root: Path) -> None:
    root = output_root.resolve()
    errors: list[str] = []
    documents: dict[Path, _LinkCollector] = {}

    def parsed_document(path: Path) -> _LinkCollector:
        if path not in documents:
            collector = _LinkCollector()
            collector.feed(path.read_text(encoding="utf-8"))
            documents[path] = collector
        return documents[path]

    for html_path in sorted(output_root.rglob("*.html")):
        collector = parsed_document(html_path)
        for link in collector.links:
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc:
                continue
            if parsed.path.startswith("/"):
                errors.append(
                    f"{html_path.relative_to(output_root)}: root-absolute link {link!r}"
                )
                continue
            target = (
                (html_path.parent / unquote(parsed.path)).resolve()
                if parsed.path
                else html_path.resolve()
            )
            if not target.is_relative_to(root):
                errors.append(
                    f"{html_path.relative_to(output_root)}: link escapes site {link!r}"
                )
                continue
            if target.is_dir():
                target = target / "index.html"
            if not target.is_file():
                errors.append(
                    f"{html_path.relative_to(output_root)}: missing target {link!r}"
                )
                continue
            if parsed.fragment and target.suffix.lower() in {".html", ".htm"}:
                fragment = unquote(parsed.fragment)
                if fragment not in parsed_document(target).ids:
                    errors.append(
                        f"{html_path.relative_to(output_root)}: missing fragment "
                        f"{fragment!r} in {link!r}"
                    )
    if errors:
        raise SiteBuildError("broken generated links:\n" + "\n".join(errors))


def _resolve_commit(repo_root: Path, commit: str | None) -> str:
    candidate = commit or os.environ.get("GITHUB_SHA")
    if not candidate:
        try:
            candidate = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise SiteBuildError(
                "cannot resolve build commit; pass --commit explicitly"
            ) from exc
    if not REVISION_RE.fullmatch(candidate):
        raise SiteBuildError(
            f"build commit must be a 7–64 character hexadecimal revision: {candidate!r}"
        )
    return candidate


def _validate_repo_url(repo_url: str) -> str:
    candidate = repo_url.rstrip("/")
    parsed = urlsplit(candidate)
    path_parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or len(path_parts) != 2
        or any(not REPO_PART_RE.fullmatch(part) for part in path_parts)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise SiteBuildError(
            f"repository URL must be a plain HTTPS URL: {repo_url!r}"
        )
    return candidate


def _prepare_output(output_dir: Path, repo_root: Path) -> None:
    if (
        output_dir == repo_root
        or output_dir == Path(output_dir.anchor)
        or output_dir in repo_root.parents
    ):
        raise SiteBuildError(f"refusing to replace unsafe output directory {output_dir}")
    if output_dir.exists():
        if not output_dir.is_dir():
            raise SiteBuildError(f"output path is not a directory: {output_dir}")
        if any(output_dir.iterdir()) and not (output_dir / OUTPUT_MARKER).is_file():
            raise SiteBuildError(
                f"refusing to replace unrecognized non-empty directory {output_dir}"
            )
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    (output_dir / OUTPUT_MARKER).write_text(
        "Generated by python -m openair.site; safe to replace.\n",
        encoding="utf-8",
    )


def build_site(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    output_dir: Path,
    manifest_path: Path | None = None,
    repo_url: str = DEFAULT_REPO_URL,
    commit: str | None = None,
    generated_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Build and validate a complete static publishing directory."""
    repo_root = repo_root.resolve()
    output_dir = output_dir.resolve()
    manifest_path = (
        manifest_path.resolve()
        if manifest_path is not None
        else repo_root / "site" / "designs.yaml"
    )
    repo_url = _validate_repo_url(repo_url)
    build_commit = _resolve_commit(repo_root, commit)

    designs = _load_manifest(manifest_path)
    results_root = repo_root / "results"
    tracked = _git_tree(repo_root, build_commit)
    reports = _discover_reports(repo_root, tracked)
    _validate_publish_set(
        designs,
        reports,
        repo_root=repo_root,
        results_root=results_root,
        tracked=tracked,
    )
    views = [
        _design_view(design, repo_root=repo_root, tracked=tracked)
        for design in designs
    ]

    _prepare_output(output_dir, repo_root)

    timestamp = generated_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    generated_label = (
        f"Published {timestamp.day} {timestamp.strftime('%b %Y')} "
        f"at {timestamp.strftime('%H:%M')} UTC"
    )

    for design in views:
        _copy_design(
            design,
            reports[design["slug"]],
            results_root=results_root,
            output_root=output_dir,
            repo_url=repo_url,
            commit=build_commit,
        )
    (output_dir / "index.html").write_text(
        render_index(
            views,
            repo_url=repo_url,
            commit=build_commit,
            generated_at=generated_label,
        ),
        encoding="utf-8",
    )
    (output_dir / "404.html").write_text(
        render_404(repo_url=repo_url),
        encoding="utf-8",
    )
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")
    _validate_local_links(output_dir)
    return views
