from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_ID = "operation-routed-target-state-agent-v31"
CANDIDATE_SOURCE_SHA = "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
PROTOCOL_DIGEST = "bc1f895bdf8bd30027bcc17f1c3a375099c8ee442681382c56ba57fa7580793b"
MODEL_DIGEST = "f974a74358d62a017b37c6f424fcdf2744ca02926c4f952513ddf474b2fa5091"
FINAL_UNIT_IDS = (
    "Long_Range_Understanding:0069:c7f1535f7238600e",
    "Long_Range_Understanding:0070:8a93d4cd5cbd681e",
    "Long_Range_Understanding:0072:893a573e50a0f0ec",
    "Long_Range_Understanding:0076:3448e84ad791bded",
    "Long_Range_Understanding:0077:d3fa1ef5e2ffc10b",
    "Long_Range_Understanding:0078:ef8ee769eeaaf621",
    "Long_Range_Understanding:0083:db96042a8a5aa313",
    "Long_Range_Understanding:0085:a348120f6cdda6a0",
    "Long_Range_Understanding:0088:4f8eeff8019e736b",
    "Long_Range_Understanding:0098:b8164c32e0eba3df",
)


def _base_module():
    path = ROOT / "benchmarks" / "scientific_mab_v19_final.py"
    spec = importlib.util.spec_from_file_location(
        "wavemind_scientific_mab_v31_final_base", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load isolated v31 MAB final runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.CANDIDATE_ID = CANDIDATE_ID
    module.CANDIDATE_SOURCE_SHA = CANDIDATE_SOURCE_SHA
    module.PROTOCOL_DIGEST = PROTOCOL_DIGEST
    module.MODEL_DIGEST = MODEL_DIGEST
    module.FINAL_UNIT_IDS = FINAL_UNIT_IDS
    return module


def run(args: argparse.Namespace) -> dict[str, Any]:
    base = _base_module()
    artifact = base.run(args)
    from wavemind.evidence import attach_artifact_integrity, validate_artifact_integrity

    if validate_artifact_integrity(artifact):
        raise RuntimeError("intermediate v31 MAB final artifact integrity failed")
    artifact.pop("integrity", None)
    artifact.update(
        {
            "schema": "wavemind.memoryagentbench_final.v31",
            "candidate_id": CANDIDATE_ID,
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "protocol_digest": PROTOCOL_DIGEST,
            "claim_boundary": (
                "MAB final arm only; full v31 admission remains incomplete until "
                "every later frozen arm passes."
            ),
        }
    )
    artifact = attach_artifact_integrity(artifact)
    args.artifact.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return artifact


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return _base_module().parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    artifact = run(parse_args(argv))
    print(
        json.dumps(
            {
                "status": artifact["status"],
                "paired_cluster_bootstrap": artifact["paired_cluster_bootstrap"],
                "gate_checks": artifact["gate_checks"],
            },
            indent=2,
        )
    )
    return 0 if artifact["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
