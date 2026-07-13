from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prune_ghcr_versions.py"
SPEC = spec_from_file_location("prune_ghcr_versions", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_sha_only_versions_are_deletable() -> None:
    assert MODULE.should_delete(["sha-a5af202"])
    assert MODULE.should_delete(["sha-a5af202", "sha-deadbeef"])


def test_public_and_release_tags_are_protected() -> None:
    assert not MODULE.should_delete([])
    assert not MODULE.should_delete(["latest", "main", "sha-a5af202"])
    assert not MODULE.should_delete(["2.6.1", "2.6", "sha-a5af202"])
    assert not MODULE.should_delete(["custom"])


def test_container_workflow_does_not_publish_sha_tags() -> None:
    workflow = (ROOT / ".github" / "workflows" / "container.yml").read_text(
        encoding="utf-8"
    )

    assert "type=sha" not in workflow
    assert "type=raw,value=latest" in workflow
    assert "type=ref,event=branch" in workflow
    assert "type=semver,pattern={{version}}" in workflow


def test_retention_workflow_has_bounded_write_permissions() -> None:
    workflow = (ROOT / ".github" / "workflows" / "package-retention.yml").read_text(
        encoding="utf-8"
    )

    assert "packages: write" in workflow
    assert "contents: read" in workflow
    assert "scripts/prune_ghcr_versions.py" in workflow
    assert "--apply" in workflow
    assert "schedule:" in workflow
