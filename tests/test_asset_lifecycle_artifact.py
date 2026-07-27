from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "benchmarks" / "asset_lifecycle_results.json"
REQUIRED_CHECKS = {
    "object_store_pass",
    "filesystem_pass",
    "ingest_pass",
    "checksum_pass",
    "reload_pass",
    "persistence_pass",
    "namespace_isolation_pass",
    "ttl_pass",
    "physical_delete_pass",
    "tombstone_pass",
    "backup_restore_pass",
    "orphan_cleanup_pass",
}


def test_asset_lifecycle_artifact_is_real_minio_evidence_with_locked_scope():
    payload = json.loads(ARTIFACT.read_text(encoding="utf-8"))

    assert payload["schema"] == "wavemind.asset-lifecycle-evidence.v1"
    assert payload["status"] == "pass"
    assert re.fullmatch(r"[0-9a-f]{40}", payload["source_ref"])
    assert payload["fixture"] == {
        "kind": "lifecycle-only",
        "public_asset_count": 0,
        "multimodal_query_count": 0,
        "eligible_for_multimodal_quality_admission": False,
    }
    assert "does not prove multimodal encoder quality" in payload["claim_boundary"]
    assert payload["filesystem"]["status"] == "pass"
    assert payload["s3_compatible"]["status"] == "pass"
    assert payload["s3_compatible"]["backend"] == "minio"
    assert payload["s3_compatible"]["teardown_pass"] is True
    assert re.fullmatch(
        r"(?:minio/minio@)?sha256:[0-9a-f]{64}",
        payload["s3_compatible"]["container_image"],
    )
    assert REQUIRED_CHECKS <= payload["lifecycle"].keys()
    assert all(payload["lifecycle"][name] is True for name in REQUIRED_CHECKS)
    assert "wavemind-local-secret" not in ARTIFACT.read_text(encoding="utf-8")
