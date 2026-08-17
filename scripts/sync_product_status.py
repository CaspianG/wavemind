from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / "docs" / "data" / "product-status.json"
START = "<!-- product-status:start -->"
END = "<!-- product-status:end -->"
TARGETS = (
    ROOT / "README.md",
    ROOT / "docs" / "ROADMAP.md",
    ROOT / "docs" / "LAUNCH_KIT.md",
)


def load_status() -> dict:
    return json.loads(STATUS_PATH.read_text(encoding="utf-8"))


def render_status(status: dict, *, docs_path: bool) -> str:
    candidate = status["stable_release"]
    release = status["public_release"]
    release_candidate = status["release_candidate"]
    safe = status["safe_product"]
    artifact = (
        "../" + safe["artifact"] if docs_path else safe["artifact"]
    )
    workflow = (
        "../" + safe["current_claim_source"]
        if docs_path
        else safe["current_claim_source"]
    )
    if candidate["publication_status"] == "published":
        release_state = (
            f"| Current release | `v{candidate['version']}` at "
            f"`{candidate['source_sha'][:12]}`; `published` | Upgrade admission "
            f"`{release_candidate['upgrade_admission']}`; GitHub Release, PyPI, "
            "and GHCR verified |"
        )
    else:
        release_state = (
            f"| Release candidate | `v{candidate['version']}` at "
            f"`{candidate['source_sha'][:12]}`; "
            f"`{release_candidate['publication_status']}` until its tag exists | "
            f"Upgrade admission `{release_candidate['upgrade_admission']}`; "
            "tag-only release workflow |"
        )
    return "\n".join(
        (
            START,
            f"> {status['category_statement']}",
            ">",
            f"> Canonical machine status: `{STATUS_PATH.relative_to(ROOT).as_posix()}`.",
            "",
            "| Product truth | Status | Evidence |",
            "|---|---|---|",
            f"| Public release | `v{release['version']}`; runtime source `{release['source_sha'][:12]}` | PyPI package `{release['python_package']}` and `{release['container']}` |",
            release_state,
            f"| Safe Product snapshot | `{safe['checked_in_status']}`, {safe['checked_in_checks_passed']}/{safe['checked_in_checks_total']} checks at `{safe['checked_in_source_sha'][:12]}` | [`{safe['artifact']}`]({artifact}) |",
            f"| Current-source admission | Required per exact source SHA | [`{safe['current_claim_source']}`]({workflow}) |",
            f"| TypeScript SDK | `{status['typescript']['package_name']}`, {status['typescript']['distribution']}; npm claim disabled | Repository package only |",
            "",
            f"> {safe['current_claim_rule']}",
            END,
        )
    )


def replace_block(text: str, block: str) -> str:
    pattern = re.compile(
        re.escape(START) + r".*?" + re.escape(END),
        flags=re.DOTALL,
    )
    if pattern.search(text) is None:
        raise ValueError("product status markers are missing")
    return pattern.sub(block, text, count=1)


def _quoted_version(path: Path, pattern: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"version not found in {path.relative_to(ROOT)}")
    return match.group(1)


def consistency_errors(status: dict) -> list[str]:
    expected = status["stable_release"]["version"]
    package = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    observed = {
        "pyproject.toml": package["project"]["version"],
        "wavemind/__init__.py": _quoted_version(
            ROOT / "wavemind" / "__init__.py",
            r'__version__\s*=\s*"([^"]+)"',
        ),
        "deploy/helm/wavemind/Chart.yaml": _quoted_version(
            ROOT / "deploy" / "helm" / "wavemind" / "Chart.yaml",
            r'appVersion:\s*"([^"]+)"',
        ),
        "deploy/helm/wavemind/values.yaml": _quoted_version(
            ROOT / "deploy" / "helm" / "wavemind" / "values.yaml",
            r'tag:\s*"([^"]+)"',
        ),
    }
    errors = [
        f"{path} has {version}, expected {expected}"
        for path, version in observed.items()
        if version != expected
    ]
    typescript = json.loads(
        (ROOT / "sdk" / "typescript" / "package.json").read_text(encoding="utf-8")
    )
    if typescript["name"] != status["typescript"]["package_name"]:
        errors.append("TypeScript package name differs from product status")
    if status["typescript"]["npm_published"] is not False:
        errors.append("npm publication claim must remain disabled until verified")
    publication_status = status["stable_release"].get("publication_status")
    if publication_status not in {"unpublished_candidate", "published"}:
        errors.append("stable release publication status is invalid")
    if publication_status == "published":
        if status["public_release"].get("version") != expected:
            errors.append("public release must equal the published stable release")
        if status["public_release"].get("source_sha") != status["stable_release"].get(
            "source_sha"
        ):
            errors.append("public and stable release source SHAs must match")
        if status["release_candidate"].get("publication_status") != "published":
            errors.append("release candidate status must record publication")
        if status["release_candidate"].get("blocker") is not None:
            errors.append("published release must not retain a blocker")
    elif status["public_release"].get("version") == expected:
        errors.append("public release must not equal the unpublished source candidate")
    for target in TARGETS:
        expected_block = render_status(
            status,
            docs_path=target.parent == ROOT / "docs",
        )
        text = target.read_text(encoding="utf-8")
        if expected_block not in text:
            errors.append(f"{target.relative_to(ROOT)} product status block is stale")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.write and not args.check:
        parser.error("choose --write or --check")
    status = load_status()
    if args.write:
        for target in TARGETS:
            block = render_status(
                status,
                docs_path=target.parent == ROOT / "docs",
            )
            text = target.read_text(encoding="utf-8")
            target.write_text(replace_block(text, block), encoding="utf-8")
    errors = consistency_errors(status)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 2
    print("Product status is synchronized.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
