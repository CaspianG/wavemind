from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_product_site_has_no_manus_runtime_dependencies():
    website = ROOT / "website"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in website.rglob("*")
        if path.is_file() and path.suffix in {".ts", ".tsx", ".css", ".html", ".json"}
    )

    assert "manus-storage" not in source
    assert "sonner" not in source
    assert "framer-motion" not in source
    assert 'from "express"' not in source
    assert (website / "public" / "wavemind-studio.png").stat().st_size > 0


def test_evidence_page_only_references_checked_in_artifacts():
    evidence_source = (ROOT / "website" / "src" / "Evidence.tsx").read_text(
        encoding="utf-8"
    )
    filenames = re.findall(r'file: "([^"]+\.json)"', evidence_source)

    assert len(filenames) >= 7
    assert len(filenames) == len(set(filenames))
    for filename in filenames:
        assert (ROOT / "benchmarks" / filename).is_file(), filename


def test_pages_deploy_is_independent_from_weekly_benchmark_refresh():
    pages = (ROOT / ".github" / "workflows" / "pages.yml").read_text(
        encoding="utf-8"
    )
    benchmark = (
        ROOT / ".github" / "workflows" / "benchmark-leaderboard.yml"
    ).read_text(encoding="utf-8")

    assert "actions/deploy-pages@v5" in pages
    assert "website/dist/data/leaderboard-status.json" in pages
    assert "find benchmarks" in pages
    assert "if: ${{ false }}" in benchmark
    assert "pages: write" not in benchmark
    assert "id-token: write" not in benchmark
