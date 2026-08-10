from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.memory_os_ab_benchmark import CASES
from wavemind.evidence import (
    attach_artifact_integrity,
    canonical_json_bytes,
    sha256_bytes,
)
from wavemind.quality_leadership_admission import (
    QUALITY_LEADERSHIP_PROTOCOL_SCHEMA,
    QUALITY_LEADERSHIP_SPLIT_MANIFEST_SCHEMA,
    QUALITY_THRESHOLDS,
    quality_leadership_protocol_manifest,
)


MEMORY_AGENT_BENCH_DATASET = "ai-hyz/MemoryAgentBench"
MEMORY_AGENT_BENCH_API = (
    "https://huggingface.co/api/datasets/ai-hyz/MemoryAgentBench?blobs=true"
)
MEMORY_AGENT_BENCH_HF_URL = "https://huggingface.co/datasets/ai-hyz/MemoryAgentBench"
MEMORY_AGENT_BENCH_GITHUB_URL = "https://github.com/HUST-AI-HYZ/MemoryAgentBench"
MEMORY_AGENT_BENCH_GITHUB_REVISION = "455306dcabc3842526eb83cd4e225e5d486c5c5d"
MEMORY_AGENT_BENCH_PAPER = "https://arxiv.org/abs/2507.05257"

HELD_OUT_SPLITS = (
    "Accurate_Retrieval",
    "Test_Time_Learning",
    "Long_Range_Understanding",
    "Conflict_Resolution",
)
CANDIDATE2_LANE = "candidate2-memoryagentbench-balanced"
CANDIDATE2_DATASET_REVISION = "quality-leadership-freeze-v2-20260811"
CANDIDATE2_DEVELOPMENT_ROWS_PER_SPLIT = 2


def fetch_memory_agent_bench_metadata() -> dict[str, Any]:
    with urllib.request.urlopen(MEMORY_AGENT_BENCH_API, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def build_frozen_protocol(
    *,
    root: str | Path = PROJECT_ROOT,
    memory_agent_metadata: Mapping[str, Any],
    lane: str = "v1",
) -> dict[str, Any]:
    base = quality_leadership_protocol_manifest(root=root)
    hf_revision = str(memory_agent_metadata.get("sha") or "")
    if not hf_revision:
        raise ValueError("MemoryAgentBench metadata is missing the Hugging Face revision SHA")

    if lane == "v1":
        development_split = _development_split()
        held_out_split = _memory_agent_bench_held_out_split(
            memory_agent_metadata,
            hf_revision=hf_revision,
        )
        revision = "quality-leadership-freeze-v1-20260810"
        dataset_revisions = {
            "development": "wavemind-controlled-sequential-memory-os-v1",
            "held_out_huggingface": hf_revision,
            "held_out_github": MEMORY_AGENT_BENCH_GITHUB_REVISION,
        }
        claim_boundary = (
            "The development split is a local controlled diagnostic. The held-out "
            "split is reserved from MemoryAgentBench using public metadata only; "
            "parquet rows are not opened by this freeze step."
        )
        protocol_boundary = (
            "This frozen quality-leadership protocol reserves an independent "
            "MemoryAgentBench held-out source before row-level inspection. It "
            "authorizes development work only; no public quality claim is allowed "
            "until development, held-out, competitor, Safe Product, and Workspace "
            "Experience admission rows pass on exact-main evidence."
        )
    elif lane == CANDIDATE2_LANE:
        development_split, held_out_split = _memory_agent_bench_candidate2_split_pair(
            memory_agent_metadata,
            hf_revision=hf_revision,
        )
        revision = CANDIDATE2_DATASET_REVISION
        dataset_revisions = {
            "development_huggingface": hf_revision,
            "development_github": MEMORY_AGENT_BENCH_GITHUB_REVISION,
            "held_out_huggingface": hf_revision,
            "held_out_github": MEMORY_AGENT_BENCH_GITHUB_REVISION,
        }
        claim_boundary = (
            "Candidate 2 is preregistered from MemoryAgentBench metadata only. "
            "Development row contents may be opened later for bounded tuning; "
            "held-out rows remain unopened and disjoint by row fingerprint."
        )
        protocol_boundary = (
            "This candidate-2 quality-leadership protocol replaces the failed "
            "local v1 development split with a public MemoryAgentBench-balanced "
            "development split while keeping a disjoint unopened held-out split. "
            "It authorizes bounded development only; no public claim is allowed "
            "until all quality, competitor, Safe Product, and Workspace Experience "
            "admission rows pass on exact-main evidence."
        )
    else:
        raise ValueError(f"unsupported quality leadership freeze lane: {lane}")

    frozen_dataset = {
        "schema": QUALITY_LEADERSHIP_SPLIT_MANIFEST_SCHEMA,
        "state": "frozen_before_heldout",
        "revision": revision,
        "lane": lane,
        "development_split": development_split,
        "held_out_split": held_out_split,
        "development_split_sha256": _split_digest(development_split),
        "held_out_split_sha256": _split_digest(held_out_split),
        "development_gate_design_analysis": _development_gate_design_analysis(
            development_split
        ),
        "held_out_viewed": False,
        "licenses": {
            "development": "MIT",
            "held_out": "MIT",
        },
        "dataset_revisions": dataset_revisions,
        "claim_boundary": claim_boundary,
    }
    payload = {
        **base,
        "schema": QUALITY_LEADERSHIP_PROTOCOL_SCHEMA,
        "status": "frozen_before_heldout",
        "new_quality_dataset": frozen_dataset,
        "claim_boundary": protocol_boundary,
    }
    return attach_artifact_integrity(payload)


def _development_split() -> dict[str, Any]:
    categories: dict[str, int] = {}
    fingerprints: list[str] = []
    for case in CASES:
        categories[case.category] = categories.get(case.category, 0) + 1
        fingerprints.append(
            "wavemind-dev:"
            + sha256_bytes(canonical_json_bytes(asdict(case)))[:24]
        )
    return {
        "id": "wavemind-controlled-sequential-memory-os-v1",
        "role": "development",
        "view_status": "viewed_development_only",
        "case_count": len(CASES),
        "categories": categories,
        "primary_sources": [
            {
                "name": "WaveMind controlled sequential Memory OS diagnostic",
                "path": "benchmarks/memory_os_ab_benchmark.py",
                "license": "MIT",
                "revision": "repository-source-manifest",
            }
        ],
        "case_fingerprints": sorted(fingerprints),
        "leakage_controls": [
            "development split is allowed for tuning",
            "old Goal 4 full451 and untouched419 are not part of this split",
        ],
    }


def _development_gate_design_analysis(split: Mapping[str, Any]) -> dict[str, Any]:
    categories = split.get("categories")
    category_count = len(categories) if isinstance(categories, Mapping) else 0
    target = QUALITY_THRESHOLDS["improved_categories_min"]
    return {
        "target_improved_categories": target,
        "development_category_count": category_count,
        "spare_category_count": max(0, category_count - target),
        "requires_runtime_ceiling_check": True,
        "ceiling_risk": (
            "no_spare_categories_for_strict_lift_gate"
            if category_count <= target
            else "has_spare_categories"
        ),
        "claim_boundary": (
            "The split manifest alone cannot prove every category is improvable "
            "over Core. Bounded development evidence must still show an "
            "improvement ceiling at or above the category threshold before "
            "held-out execution is allowed."
        ),
    }


def _memory_agent_bench_held_out_split(
    metadata: Mapping[str, Any],
    *,
    hf_revision: str,
) -> dict[str, Any]:
    split_rows, file_manifest = _memory_agent_bench_manifest(metadata)
    categories = {split: split_rows[split] for split in HELD_OUT_SPLITS}
    fingerprints = [
        f"memoryagentbench:{hf_revision}:{split}:row:{index:04d}"
        for split in HELD_OUT_SPLITS
        for index in range(split_rows[split])
    ]
    return {
        "id": "memoryagentbench-reserved-heldout-v1",
        "role": "held_out",
        "view_status": "unopened",
        "case_count": len(fingerprints),
        "categories": categories,
        "primary_sources": [
            {
                "name": "MemoryAgentBench",
                "huggingface_dataset": MEMORY_AGENT_BENCH_DATASET,
                "huggingface_url": MEMORY_AGENT_BENCH_HF_URL,
                "huggingface_revision": hf_revision,
                "github_url": MEMORY_AGENT_BENCH_GITHUB_URL,
                "github_revision": MEMORY_AGENT_BENCH_GITHUB_REVISION,
                "paper": MEMORY_AGENT_BENCH_PAPER,
                "license": "MIT",
                "files": file_manifest,
            }
        ],
        "case_fingerprints": fingerprints,
        "leakage_controls": [
            "held-out rows are reserved by split metadata only",
            "parquet row contents are not opened during protocol freeze",
            "old Goal 4 full451 and untouched419 are excluded",
        ],
    }


def _memory_agent_bench_candidate2_split_pair(
    metadata: Mapping[str, Any],
    *,
    hf_revision: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    split_rows, file_manifest = _memory_agent_bench_manifest(metadata)
    development_fingerprints: list[str] = []
    held_out_fingerprints: list[str] = []
    development_categories: dict[str, int] = {}
    held_out_categories: dict[str, int] = {}
    for split in HELD_OUT_SPLITS:
        row_count = split_rows[split]
        development_count = min(CANDIDATE2_DEVELOPMENT_ROWS_PER_SPLIT, row_count)
        development_categories[split] = development_count
        held_out_categories[split] = row_count - development_count
        for index in range(row_count):
            fingerprint = f"memoryagentbench:{hf_revision}:{split}:row:{index:04d}"
            if index < development_count:
                development_fingerprints.append(fingerprint)
            else:
                held_out_fingerprints.append(fingerprint)
    source = {
        "name": "MemoryAgentBench",
        "huggingface_dataset": MEMORY_AGENT_BENCH_DATASET,
        "huggingface_url": MEMORY_AGENT_BENCH_HF_URL,
        "huggingface_revision": hf_revision,
        "github_url": MEMORY_AGENT_BENCH_GITHUB_URL,
        "github_revision": MEMORY_AGENT_BENCH_GITHUB_REVISION,
        "paper": MEMORY_AGENT_BENCH_PAPER,
        "license": "MIT",
        "files": file_manifest,
    }
    development_split = {
        "id": "memoryagentbench-balanced-development-v2",
        "role": "development",
        "view_status": "reserved_unopened_until_bounded_development",
        "case_count": len(development_fingerprints),
        "categories": development_categories,
        "primary_sources": [source],
        "case_fingerprints": development_fingerprints,
        "leakage_controls": [
            "development rows are selected by preregistered row index before row access",
            "row contents are not opened during protocol freeze",
            "old Goal 4 full451 and untouched419 are excluded",
            "failed v1 controlled split fingerprints are excluded",
        ],
    }
    held_out_split = {
        "id": "memoryagentbench-balanced-heldout-v2",
        "role": "held_out",
        "view_status": "unopened",
        "case_count": len(held_out_fingerprints),
        "categories": held_out_categories,
        "primary_sources": [source],
        "case_fingerprints": held_out_fingerprints,
        "leakage_controls": [
            "held-out rows are disjoint from development by row index",
            "held-out parquet row contents are not opened during protocol freeze",
            "old Goal 4 full451 and untouched419 are excluded",
            "failed v1 controlled split fingerprints are excluded",
        ],
    }
    return development_split, held_out_split


def _memory_agent_bench_manifest(
    metadata: Mapping[str, Any],
) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    card = metadata.get("cardData")
    if not isinstance(card, Mapping):
        raise ValueError("MemoryAgentBench metadata is missing cardData")
    if str(card.get("license") or "").lower() != "mit":
        raise ValueError("MemoryAgentBench license must be MIT for this freeze")
    dataset_info = card.get("dataset_info")
    if not isinstance(dataset_info, Mapping):
        raise ValueError("MemoryAgentBench metadata is missing dataset_info")
    split_rows = {
        str(row.get("name")): int(row.get("num_examples") or 0)
        for row in dataset_info.get("splits") or []
        if isinstance(row, Mapping)
    }
    missing = [split for split in HELD_OUT_SPLITS if split_rows.get(split, 0) <= 0]
    if missing:
        raise ValueError(f"MemoryAgentBench splits are missing row counts: {missing}")

    siblings = metadata.get("siblings")
    if not isinstance(siblings, list):
        raise ValueError("MemoryAgentBench metadata is missing file siblings")
    file_manifest = _file_manifest(siblings)
    missing_files = [
        f"data/{split}-00000-of-00001.parquet"
        for split in HELD_OUT_SPLITS
        if f"data/{split}-00000-of-00001.parquet" not in file_manifest
    ]
    if missing_files:
        raise ValueError(f"MemoryAgentBench files are missing: {missing_files}")
    return split_rows, file_manifest


def _file_manifest(siblings: list[Any]) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    for row in siblings:
        if not isinstance(row, Mapping):
            continue
        filename = str(row.get("rfilename") or "")
        if not filename:
            continue
        item: dict[str, Any] = {
            "size": int(row.get("size") or 0),
            "blob_id": row.get("blobId"),
        }
        lfs = row.get("lfs")
        if isinstance(lfs, Mapping):
            item["lfs_sha256"] = lfs.get("sha256")
            item["lfs_size"] = int(lfs.get("size") or 0)
        if filename.startswith("data/") and "lfs_sha256" not in item:
            raise ValueError(f"MemoryAgentBench data file has no LFS SHA: {filename}")
        files[filename] = item
    return files


def _split_digest(split: Mapping[str, Any]) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                key: value
                for key, value in split.items()
                if key not in {"sha256", "digest", "generated_at"}
            }
        )
    )


def _git_revision() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    ).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/quality_leadership_protocol.json"),
    )
    parser.add_argument("--metadata-json", type=Path)
    parser.add_argument("--expected-source-sha")
    parser.add_argument(
        "--lane",
        choices=("v1", CANDIDATE2_LANE),
        default="v1",
    )
    args = parser.parse_args()

    metadata = (
        json.loads(args.metadata_json.read_text(encoding="utf-8"))
        if args.metadata_json
        else fetch_memory_agent_bench_metadata()
    )
    payload = build_frozen_protocol(
        root=PROJECT_ROOT,
        memory_agent_metadata=metadata,
        lane=args.lane,
    )
    if args.expected_source_sha and payload.get("source_sha") != args.expected_source_sha:
        raise SystemExit(
            "source SHA mismatch: "
            f"{payload.get('source_sha')} != {args.expected_source_sha}"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": args.output.as_posix(), "source_sha": _git_revision()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
