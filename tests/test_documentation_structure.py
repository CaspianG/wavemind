from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_GUIDES = [
    ROOT / "README.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "README.md",
    ROOT / "docs" / "INDEX_BACKENDS.md",
    ROOT / "docs" / "KNOWN_LIMITATIONS.md",
    ROOT / "docs" / "SCALE_AND_PRODUCTION.md",
    ROOT / "docs" / "MULTIMODAL_AND_STORAGE.md",
    ROOT / "docs" / "INTEGRATIONS.md",
    ROOT / "docs" / "BENCHMARKS.md",
]


def test_readme_is_an_entrypoint_with_stable_navigation():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert len(readme.splitlines()) < 700
    for heading in (
        "## Quick Start",
        "## HTTP API",
        "## LangChain Memory",
        "## Benchmark",
        "## Known Limitations",
        "## Contributing",
    ):
        assert heading in readme

    for guide in PUBLIC_GUIDES[1:]:
        assert guide.exists()

    for entrypoint in (
        "CHANGELOG.md",
        "docs/README.md",
        "docs/INDEX_BACKENDS.md",
        "docs/KNOWN_LIMITATIONS.md",
    ):
        assert entrypoint in readme

    for asset in (
        ROOT / "docs" / "assets" / "wavemind-social-preview.png",
        ROOT / "docs" / "assets" / "wavemind-studio.png",
    ):
        assert asset.exists()
        assert asset.stat().st_size > 10_000


def test_public_guide_local_links_resolve():
    broken: list[str] = []

    for guide in PUBLIC_GUIDES:
        text = guide.read_text(encoding="utf-8")
        for match in re.finditer(r"\]\(([^)]+)\)", text):
            raw_target = match.group(1).strip()
            target = raw_target.split("#", 1)[0].strip("<>")
            if not target or re.match(r"^(?:https?://|mailto:|data:)", target):
                continue
            if not (guide.parent / target).resolve().exists():
                broken.append(f"{guide.relative_to(ROOT)} -> {raw_target}")

    assert broken == []


def test_public_guide_local_heading_links_resolve():
    broken: list[str] = []

    for guide in PUBLIC_GUIDES:
        text = guide.read_text(encoding="utf-8")
        targets = re.findall(r"\]\(([^)]+)\)", text)
        targets.extend(re.findall(r'href="([^"]+)"', text))
        for raw_target in targets:
            if raw_target.startswith(("http://", "https://", "mailto:", "data:")):
                continue
            path_part, separator, fragment = raw_target.strip("<>").partition("#")
            if not separator or not fragment:
                continue
            target_path = (guide.parent / path_part).resolve() if path_part else guide
            if not target_path.exists() or target_path.suffix.lower() != ".md":
                continue
            headings = _github_heading_ids(target_path.read_text(encoding="utf-8"))
            if fragment not in headings:
                broken.append(f"{guide.relative_to(ROOT)} -> {raw_target}")

    assert broken == []


def _github_heading_ids(markdown: str) -> set[str]:
    identifiers: set[str] = set()
    counts: dict[str, int] = {}
    for match in re.finditer(r"^#{1,6}\s+(.+?)\s*$", markdown, flags=re.MULTILINE):
        heading = re.sub(r"<[^>]+>", "", match.group(1)).lower()
        base = re.sub(r"[^\w\s-]", "", heading)
        base = re.sub(r"\s", "-", base)
        count = counts.get(base, 0)
        identifier = base if count == 0 else f"{base}-{count}"
        counts[base] = count + 1
        identifiers.add(identifier)
    return identifiers


def test_community_files_and_dependency_updates_are_configured():
    code_of_conduct = (ROOT / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8")
    pull_request_template = (
        ROOT / ".github" / "pull_request_template.md"
    ).read_text(encoding="utf-8")
    dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")

    assert "Contributor Covenant" in code_of_conduct
    assert "## Validation" in pull_request_template
    assert "Public claims link to reproducible checked-in evidence" in pull_request_template
    for ecosystem in ("pip", "github-actions", "docker"):
        assert f"package-ecosystem: {ecosystem}" in dependabot
