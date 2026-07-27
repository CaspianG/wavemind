from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_GUIDES = [
    ROOT / "README.md",
    ROOT / "docs" / "SCALE_AND_PRODUCTION.md",
    ROOT / "docs" / "MULTIMODAL_AND_STORAGE.md",
    ROOT / "docs" / "INTEGRATIONS.md",
    ROOT / "docs" / "BENCHMARKS.md",
]


def test_readme_is_an_entrypoint_with_stable_navigation():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert len(readme.splitlines()) < 1000
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
        assert guide.relative_to(ROOT).as_posix() in readme


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
