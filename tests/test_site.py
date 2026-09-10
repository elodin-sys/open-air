import base64
import hashlib
import subprocess
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest
import yaml
from PIL import Image

from openair.site.build import (
    OUTPUT_MARKER,
    PUBLISHED_ASSETS,
    THREEVIEW_PREVIEW_ASSET,
    SiteBuildError,
    _rewrite_report,
    _threeview_preview,
    _validate_local_links,
    build_site,
)
from openair.theme import REPORT_CSS


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_COMMIT = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=REPO_ROOT,
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()


def _report_with_embedded_threeview() -> str:
    image = Image.new("RGB", (9, 3), "white")
    for x, color in (
        (0, (255, 0, 0)),
        (3, (0, 128, 0)),
        (6, (0, 0, 255)),
    ):
        image.paste(color, (x, 0, x + 3, 3))
    encoded = BytesIO()
    image.save(encoded, format="PNG")
    payload = base64.b64encode(encoded.getvalue()).decode("ascii")
    return (
        '<!doctype html><div class="brand">open-air · concept review</div>'
        '<h3>Exported-aircraft three-view</h3>'
        f'<img src="data:image/png;base64,{payload}">'
    )


def test_shared_theme_retains_the_published_report_css():
    assert (
        hashlib.sha256(REPORT_CSS.encode()).hexdigest()
        == "30de258207dc6f4441a86d3c0c7c09edfa542bf91227fe009ba9577d6534a0f0"
    )


def test_site_build_publishes_every_design_review(tmp_path: Path):
    output = tmp_path / "_site"
    views = build_site(
        repo_root=REPO_ROOT,
        output_dir=output,
        commit=BUILD_COMMIT,
        generated_at=datetime(2026, 9, 10, 16, 30, tzinfo=timezone.utc),
    )

    report_slugs = {
        path.parent.name
        for path in (REPO_ROOT / "results").glob("*/report.html")
    }
    assert {view["slug"] for view in views} == report_slugs
    assert sum(bool(view["featured"]) for view in views) == 1
    assert (output / OUTPUT_MARKER).is_file()
    assert (output / ".nojekyll").is_file()
    assert (output / "404.html").is_file()

    index = (output / "index.html").read_text(encoding="utf-8")
    assert REPORT_CSS in index
    assert "Aircraft concepts, engineered in the open." in index
    assert "Evidence, not claims" in index
    assert "Built from <a href=" in index
    assert "baseline_vs_optimized.png" not in index
    assert index.count(f"/{THREEVIEW_PREVIEW_ASSET}") == len(views) + 1
    assert "optimized 2.56 m span" in index
    assert "2.65 m span" not in index
    assert "source 65f48ec9" not in index
    for slug in report_slugs:
        assert f'href="designs/{slug}/"' in index
        published = output / "designs" / slug
        assert (published / "index.html").is_file()
        preview = published / THREEVIEW_PREVIEW_ASSET
        assert preview.is_file()
        with Image.open(preview) as image:
            assert image.size == (1200, 600)
        for asset in PUBLISHED_ASSETS:
            assert (published / asset).is_file()

    dolphin = (
        output / "designs" / "atomrc-dolphin-v1-1" / "index.html"
    ).read_text(encoding="utf-8")
    assert "../../docs/" not in dolphin
    assert (
        f"https://github.com/elodin-sys/open-air/blob/{BUILD_COMMIT}/"
        "docs/guidebook/00-qa-workflow.md"
    ) in dolphin
    assert '<div class="brand"><a href="../../"' in dolphin
    assert "const meshPayload =" in dolphin

    holdout = (
        output / "designs" / "openair-x8-capstone" / "index.html"
    ).read_text(encoding="utf-8")
    assert "Publication-only historical artifact" in holdout
    assert "designs/openair-x8-capstone/design.yaml" not in holdout
    assert "results/openair-x8-capstone/optimized/design.yaml" not in holdout


def test_threeview_preview_retains_top_and_side_columns_only():
    preview = _threeview_preview(
        _report_with_embedded_threeview(),
        slug="demo",
    )

    with Image.open(BytesIO(preview)) as image:
        assert image.size == (6, 3)
        assert image.getpixel((1, 1)) == (255, 0, 0)
        assert image.getpixel((4, 1)) == (0, 128, 0)
        assert all(
            image.getpixel((x, y)) != (0, 0, 255)
            for x in range(image.width)
            for y in range(image.height)
        )


@pytest.mark.parametrize("mode", ["missing_manifest", "missing_report"])
def test_site_build_fails_closed_on_manifest_report_mismatch(
    tmp_path: Path,
    mode: str,
):
    manifest = yaml.safe_load(
        (REPO_ROOT / "site" / "designs.yaml").read_text(encoding="utf-8")
    )
    if mode == "missing_manifest":
        manifest["designs"].pop()
        expected = "reports without manifest entries"
    else:
        manifest["designs"].append(
            {
                "slug": "not-a-published-design",
                "title": "Missing report",
                "summary": "Contract fixture.",
                "kind": "reproduction",
            }
        )
        expected = "manifest entries without reports"
    manifest_path = tmp_path / "designs.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest), encoding="utf-8")

    with pytest.raises(SiteBuildError, match=expected):
        build_site(
            repo_root=REPO_ROOT,
            output_dir=tmp_path / "_site",
            manifest_path=manifest_path,
            commit=BUILD_COMMIT,
        )


def test_generated_link_check_rejects_missing_local_target(tmp_path: Path):
    output = tmp_path / "_site"
    output.mkdir()
    (output / "index.html").write_text(
        '<!doctype html><a href="designs/missing/">Missing</a>',
        encoding="utf-8",
    )

    with pytest.raises(SiteBuildError, match="missing target"):
        _validate_local_links(output)


def test_generated_link_check_validates_same_and_cross_page_fragments(
    tmp_path: Path,
):
    output = tmp_path / "_site"
    output.mkdir()
    index = output / "index.html"
    details = output / "details.html"
    index.write_text(
        '<!doctype html><main id="top"><a href="#top">Top</a>'
        '<a href="details.html#evidence">Evidence</a></main>',
        encoding="utf-8",
    )
    details.write_text(
        '<!doctype html><h1 id="evidence">Evidence</h1>',
        encoding="utf-8",
    )
    _validate_local_links(output)

    details.write_text("<!doctype html><h1>Evidence</h1>", encoding="utf-8")
    with pytest.raises(SiteBuildError, match="missing fragment 'evidence'"):
        _validate_local_links(output)


def test_report_docs_rewrite_preserves_query_and_fragment():
    document = (
        '<div class="brand">open-air · concept review</div>'
        '<a href="../../docs/guidebook/00-qa-workflow.md?plain=1&amp;view=raw#geometry">'
        "Workflow</a>"
    )

    rewritten = _rewrite_report(
        document,
        repo_url="https://github.com/elodin-sys/open-air",
        commit=BUILD_COMMIT,
        slug="demo",
        historical=False,
    )

    assert (
        f"https://github.com/elodin-sys/open-air/blob/{BUILD_COMMIT}/"
        "docs/guidebook/00-qa-workflow.md?plain=1&amp;view=raw#geometry"
    ) in rewritten


def test_site_build_does_not_replace_an_unrecognized_directory(tmp_path: Path):
    output = tmp_path / "_site"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("do not delete", encoding="utf-8")

    with pytest.raises(SiteBuildError, match="unrecognized non-empty directory"):
        build_site(
            repo_root=REPO_ROOT,
            output_dir=output,
            commit=BUILD_COMMIT,
        )

    assert sentinel.read_text(encoding="utf-8") == "do not delete"


def test_site_build_uses_revision_tree_and_rejects_worktree_symlinks(
    tmp_path: Path,
):
    repo = tmp_path / "repo"
    design = repo / "designs" / "demo"
    results = repo / "results" / "demo"
    design.mkdir(parents=True)
    results.mkdir(parents=True)
    (design / "design.yaml").write_text(
        "name: demo\nsketch:\n  treatment: reproduction\n",
        encoding="utf-8",
    )
    (results / "report.html").write_text(
        _report_with_embedded_threeview(),
        encoding="utf-8",
    )
    for asset in PUBLISHED_ASSETS:
        (results / asset).write_bytes(b"preview")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "designs", "results"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=open-air tests",
            "-c",
            "user.email=tests@open-air.invalid",
            "commit",
            "-qm",
            "site fixture",
        ],
        cwd=repo,
        check=True,
    )
    fixture_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    untracked = repo / "results" / "untracked"
    untracked.mkdir()
    (untracked / "report.html").write_text(
        _report_with_embedded_threeview(),
        encoding="utf-8",
    )
    for asset in PUBLISHED_ASSETS:
        (untracked / asset).write_bytes(b"untracked")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    image = results / "baseline_vs_optimized.png"
    manifest = tmp_path / "designs.yaml"
    manifest.write_text(
        "designs:\n"
        "  - slug: demo\n"
        "    title: Demo\n"
        "    summary: Tracked-file fixture.\n"
        "    kind: reproduction\n"
        "    featured: true\n",
        encoding="utf-8",
    )

    views = build_site(
        repo_root=repo,
        output_dir=tmp_path / "_site",
        manifest_path=manifest,
        commit=fixture_commit,
    )
    assert [view["slug"] for view in views] == ["demo"]

    image.unlink()
    image.symlink_to(outside)
    with pytest.raises(SiteBuildError, match="traverses a symlink"):
        build_site(
            repo_root=repo,
            output_dir=tmp_path / "_site",
            manifest_path=manifest,
            commit=fixture_commit,
        )
