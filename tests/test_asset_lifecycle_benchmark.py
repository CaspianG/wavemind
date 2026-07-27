from __future__ import annotations

from benchmarks.asset_lifecycle_benchmark import (
    SCHEMA,
    run_asset_lifecycle_benchmark,
)


def test_asset_lifecycle_benchmark_keeps_filesystem_proof_separate_from_minio():
    result = run_asset_lifecycle_benchmark(
        s3_config=None,
        source_ref="a" * 40,
    )

    assert result["schema"] == SCHEMA
    assert result["status"] == "contract_pass"
    assert result["source_ref"] == "a" * 40
    assert result["fixture"]["eligible_for_multimodal_quality_admission"] is False
    assert result["filesystem"]["status"] == "pass"
    assert result["s3_compatible"]["status"] == "skipped"
    assert result["lifecycle"]["filesystem_pass"] is True
    assert result["lifecycle"]["object_store_pass"] is False
    assert all(result["filesystem"]["checks"].values())
