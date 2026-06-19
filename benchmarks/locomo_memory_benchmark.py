from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.long_memory_evidence_benchmark import (
    EvidenceDataset,
    EvidenceQuery,
    LongMemory,
    run_chroma_static,
    run_qdrant_static,
    run_static_vector,
    run_wavemind,
)
from wavemind.encoders import create_text_encoder


SOURCE_URL = "https://github.com/snap-research/locomo"
SESSION_RE = re.compile(r"^session_(\d+)$")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _samples(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "samples", "conversations"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    raise ValueError("LoCoMo payload must be a JSON object or a list of objects")


def _sample_id(sample: dict[str, Any], index: int) -> str:
    for key in ("sample_id", "conversation_id", "id"):
        value = sample.get(key)
        if value not in (None, ""):
            return str(value)
    return f"sample-{index:04d}"


def _conversation(sample: dict[str, Any]) -> Any:
    for key in ("conversation", "conversations", "dialogue", "dialog"):
        if key in sample:
            return sample[key]
    raise ValueError("LoCoMo sample is missing a conversation field")


def _qa_items(sample: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("qa", "qas", "questions", "qa_pairs"):
        value = sample.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _session_keys(conversation: dict[str, Any]) -> list[str]:
    keys = [key for key, value in conversation.items() if SESSION_RE.match(key) and isinstance(value, list)]
    return sorted(keys, key=lambda key: int(SESSION_RE.match(key).group(1)))  # type: ignore[union-attr]


def _speaker_name(conversation: dict[str, Any], speaker: str) -> str:
    value = conversation.get(speaker)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return speaker


def _turn_text(turn: dict[str, Any], speaker: str, date: str | None) -> str:
    text = str(
        turn.get("text")
        or turn.get("content")
        or turn.get("message")
        or turn.get("utterance")
        or ""
    ).strip()
    caption = str(turn.get("blip_caption") or turn.get("caption") or "").strip()
    parts = []
    if date:
        parts.append(f"[{date}]")
    if text:
        parts.append(f"{speaker}: {text}")
    if caption:
        parts.append(f"Image caption: {caption}")
    return " ".join(parts).strip()


def _turn_id(turn: dict[str, Any], session_key: str, offset: int) -> str:
    for key in ("dia_id", "dialog_id", "turn_id", "id"):
        value = turn.get(key)
        if value not in (None, ""):
            return str(value)
    return f"{session_key}:{offset}"


def _iter_turns(sample_id: str, conversation: Any) -> Iterable[LongMemory]:
    if isinstance(conversation, list):
        for offset, turn in enumerate(conversation, start=1):
            if not isinstance(turn, dict):
                continue
            raw_speaker = str(turn.get("speaker") or turn.get("role") or "speaker")
            text = _turn_text(turn, raw_speaker, None)
            if not text:
                continue
            dia_id = _turn_id(turn, "conversation", offset)
            yield LongMemory(
                id=f"{sample_id}::{dia_id}",
                text=text,
                namespace=f"locomo:{sample_id}",
                tags=("locomo", "turn"),
            )
        return

    if not isinstance(conversation, dict):
        raise ValueError("LoCoMo conversation must be a dict or a list")

    for session_key in _session_keys(conversation):
        date = conversation.get(f"{session_key}_date_time")
        date_text = str(date).strip() if date not in (None, "") else None
        turns = conversation.get(session_key, [])
        for offset, turn in enumerate(turns, start=1):
            if not isinstance(turn, dict):
                continue
            raw_speaker = str(turn.get("speaker") or turn.get("role") or "speaker")
            speaker = _speaker_name(conversation, raw_speaker)
            text = _turn_text(turn, speaker, date_text)
            if not text:
                continue
            dia_id = _turn_id(turn, session_key, offset)
            yield LongMemory(
                id=f"{sample_id}::{dia_id}",
                text=text,
                namespace=f"locomo:{sample_id}",
                tags=("locomo", session_key),
                timestamp=date_text,
            )


def _evidence_ids(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        ids: list[str] = []
        for item in value:
            if isinstance(item, str):
                ids.append(item)
            elif isinstance(item, dict):
                for key in ("dia_id", "dialog_id", "turn_id", "id"):
                    candidate = item.get(key)
                    if candidate not in (None, ""):
                        ids.append(str(candidate))
                        break
        return tuple(ids)
    return ()


def _qa_question(item: dict[str, Any]) -> str:
    return str(item.get("question") or item.get("query") or "").strip()


def load_locomo_dataset(
    path: str | Path,
    limit_samples: int | None = None,
    limit_queries: int | None = None,
    include_answerless: bool = False,
) -> EvidenceDataset:
    root = Path(path)
    raw_samples = _samples(_read_json(root))
    if limit_samples is not None:
        raw_samples = raw_samples[:limit_samples]

    memories: list[LongMemory] = []
    queries: list[EvidenceQuery] = []
    query_count = 0

    for sample_index, sample in enumerate(raw_samples, start=1):
        sid = _sample_id(sample, sample_index)
        namespace = f"locomo:{sid}"
        sample_memories = list(_iter_turns(sid, _conversation(sample)))
        known_ids = {memory.id for memory in sample_memories}
        memories.extend(sample_memories)

        for qa_index, qa in enumerate(_qa_items(sample), start=1):
            if limit_queries is not None and query_count >= limit_queries:
                break
            question = _qa_question(qa)
            if not question:
                continue
            raw_evidence = _evidence_ids(
                qa.get("evidence")
                or qa.get("evidences")
                or qa.get("evidence_ids")
                or qa.get("evidence_id")
            )
            evidence = tuple(
                f"{sid}::{evidence_id}"
                for evidence_id in raw_evidence
                if f"{sid}::{evidence_id}" in known_ids
            )
            if not evidence and not include_answerless:
                continue

            queries.append(
                EvidenceQuery(
                    id=f"{sid}::qa_{qa_index:04d}",
                    text=question,
                    namespace=namespace,
                    expected_evidence_ids=evidence,
                    category=str(qa.get("category") or qa.get("type") or "general"),
                )
            )
            query_count += 1

    return EvidenceDataset(name="locomo", memories=memories, queries=queries)


def run_benchmark(
    dataset_path: str | Path,
    engines: Iterable[str],
    encoder_kind: str = "hash",
    top_k: int = 5,
    limit_samples: int | None = None,
    limit_queries: int | None = None,
) -> dict[str, Any]:
    dataset = load_locomo_dataset(
        dataset_path,
        limit_samples=limit_samples,
        limit_queries=limit_queries,
    )
    encoder = create_text_encoder(kind=encoder_kind, vector_dim=384)
    runners = {
        "wavemind": run_wavemind,
        "static": run_static_vector,
        "static-vector": run_static_vector,
        "chroma": run_chroma_static,
        "chroma-static": run_chroma_static,
        "qdrant": run_qdrant_static,
        "qdrant-static": run_qdrant_static,
    }

    results = []
    for engine in engines:
        key = engine.lower()
        if key not in runners:
            raise ValueError(f"Unknown engine: {engine}")
        results.append(asdict(runners[key](dataset, encoder, top_k)))

    conversations = len({memory.namespace for memory in dataset.memories})
    return {
        "scenario": {
            "name": "locomo_evidence_retrieval",
            "dataset": str(dataset_path),
            "source_url": SOURCE_URL,
            "conversations": conversations,
            "memories": len(dataset.memories),
            "queries": len(dataset.queries),
            "top_k": top_k,
            "description": (
                "LoCoMo retrieval-only evidence benchmark. It uses conversation turns as "
                "memories and QA evidence dialog ids as relevance labels."
            ),
        },
        "embedding": {
            "kind": encoder_kind,
            "class": type(encoder).__name__,
            "vector_dim": getattr(encoder, "vector_dim", None),
            "note": "All engines receive embeddings from the same WaveMind encoder.",
        },
        "results": results,
    }


def print_table(payload: dict[str, Any]) -> None:
    top_k = payload["scenario"]["top_k"]
    print(f"| engine | evidence recall@{top_k} | precision@1 | MRR@{top_k} | avg latency |")
    print("|---|---:|---:|---:|---:|")
    for result in payload["results"]:
        print(
            f"| {result['engine']} | "
            f"{result['evidence_recall_at_k']:.3f} | "
            f"{result['precision_at_1']:.3f} | "
            f"{result['mrr_at_k']:.3f} | "
            f"{result['avg_latency_ms']:.2f} ms |"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument(
        "--engines",
        nargs="+",
        choices=["wavemind", "static", "static-vector", "chroma", "chroma-static", "qdrant", "qdrant-static"],
        default=["wavemind", "static"],
    )
    parser.add_argument("--encoder", choices=["hash", "sentence"], default="hash")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit-samples", type=int, default=None)
    parser.add_argument("--limit-queries", type=int, default=None)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/locomo_evidence_results.json"))
    args = parser.parse_args()

    payload = run_benchmark(
        dataset_path=args.dataset,
        engines=args.engines,
        encoder_kind=args.encoder,
        top_k=args.top_k,
        limit_samples=args.limit_samples,
        limit_queries=args.limit_queries,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_table(payload)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
