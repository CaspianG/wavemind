from __future__ import annotations

import json

from wavemind.evidence import attach_artifact_integrity, file_sha256
from wavemind.scientific_development_evidence import build_development_evidence
from wavemind.scientific_protocol import protocol_digest


GRAPH = "evidence-constrained-associative-graph-v1"
CAUSAL = "causal-utility-controller-v1"


def _candidate(candidate_id, raw_path, *, memops):
    common = {
        "phase": "bounded-development",
        "admission_eligible": False,
        "candidate_id": candidate_id,
        "source_sha": "a" * 40,
        "case_count": 4 if not memops else 2,
        "paired_effect": {
            "values": [0.0, 0.0, 0.0, 0.0] if not memops else [-1.0, 0.0],
            "mean": 0.0 if not memops else -0.5,
        },
        "production_case_count": 0,
        "promoted_memory_ids": [],
        "false_verified_promotions": 0,
    }
    if memops:
        common.update(
            {
                "case_ids": ["A04_forget_q1", "A04_forget_q2"],
                "raw_output": {
                    "path": str(raw_path),
                    "sha256": file_sha256(raw_path),
                },
            }
        )
    else:
        common["raw_results"] = {
            "path": str(raw_path),
            "sha256": file_sha256(raw_path),
        }
    return attach_artifact_integrity(common)


def test_development_evidence_fails_closed_on_zero_lcb_and_one_subject(
    tmp_path,
    monkeypatch,
):
    mab_raw = tmp_path / "mab.jsonl"
    mab_raw.write_text(
        "".join(
            json.dumps(
                {
                    "case_id": f"context-{context}:q{query}",
                    "paired_effect": 0.0,
                }
            )
            + "\n"
            for context in (1, 2)
            for query in (1, 2)
        ),
        encoding="utf-8",
    )
    memops_raw = tmp_path / "memops.jsonl"
    memops_raw.write_text("{}\n{}\n", encoding="utf-8")
    protocol = {"schema": "test-protocol"}
    protocol["protocol_digest"] = protocol_digest(protocol)
    monkeypatch.setattr(
        "wavemind.scientific_development_evidence.validate_prepared_state_bench_artifact",
        lambda unused: [],
    )

    payload = build_development_evidence(
        source_sha="b" * 40,
        protocol=protocol,
        mab_artifacts={
            candidate: _candidate(candidate, mab_raw, memops=False)
            for candidate in (GRAPH, CAUSAL)
        },
        mab_raw_paths={candidate: mab_raw for candidate in (GRAPH, CAUSAL)},
        memops_artifacts={
            candidate: _candidate(candidate, memops_raw, memops=True)
            for candidate in (GRAPH, CAUSAL)
        },
        state_bench_artifact={
            "status": "prepared_waiting_for_credentials",
            "source_sha": "c" * 40,
            "credentials": {"official_execution_succeeded": False},
        },
    )

    assert payload["status"] == "failed_experiment"
    for candidate in (GRAPH, CAUSAL):
        evidence = payload["candidates"][candidate]
        assert evidence["advance_to_validation"] is False
        assert (
            evidence["memoryagentbench"]["paired_cluster_bootstrap"]["ci_lower"] == 0.0
        )
        assert evidence["memops"]["independent_cluster_count"] == 1
    assert payload["longmemeval_v2"]["full_451_run_executed"] is False
