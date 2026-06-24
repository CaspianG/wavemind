from __future__ import annotations

import argparse
import json
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
    cache_encoder_for_dataset,
    run_chroma_static,
    run_qdrant_static,
    run_static_vector,
    run_wavemind,
)
from wavemind.encoders import create_text_encoder


SOURCE_URL = "https://github.com/xiaowu0162/LongMemEval"
DATA_URL = "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _samples(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "samples", "instances", "questions"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    raise ValueError("LongMemEval payload must be a JSON object or a list of objects")


def _question_id(sample: dict[str, Any], index: int) -> str:
    value = sample.get("question_id") or sample.get("id")
    if value not in (None, ""):
        return str(value)
    return f"question-{index:04d}"


def _turn_text(turn: Any) -> str:
    if isinstance(turn, str):
        return turn.strip()
    if not isinstance(turn, dict):
        return ""
    role = str(turn.get("role") or turn.get("speaker") or "").strip()
    content = str(turn.get("content") or turn.get("text") or turn.get("message") or "").strip()
    if role and content:
        return f"{role}: {content}"
    return content


def _session_text(session: Any, date: str | None) -> str:
    parts = [f"[{date}]" if date else ""]
    if isinstance(session, list):
        parts.extend(_turn_text(turn) for turn in session)
    else:
        parts.append(_turn_text(session))
    return "\n".join(part for part in parts if part).strip()


def _session_id(sample: dict[str, Any], offset: int) -> str:
    session_ids = sample.get("haystack_session_ids") or []
    if isinstance(session_ids, list) and offset < len(session_ids):
        value = session_ids[offset]
        if value not in (None, ""):
            return str(value)
    return f"session-{offset + 1:04d}"


def _session_date(sample: dict[str, Any], offset: int) -> str | None:
    dates = sample.get("haystack_dates") or []
    if isinstance(dates, list) and offset < len(dates):
        value = dates[offset]
        if value not in (None, ""):
            return str(value)
    return None


def _answer_session_ids(sample: dict[str, Any]) -> tuple[str, ...]:
    value = sample.get("answer_session_ids") or sample.get("evidence_session_ids") or []
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if item not in (None, ""))


def _is_abstention(sample: dict[str, Any], question_id: str) -> bool:
    question_type = str(sample.get("question_type") or "").lower()
    return question_id.endswith("_abs") or question_type == "abstention"


def _load_session_granularity(
    sample: dict[str, Any],
    question_id: str,
    namespace: str,
) -> tuple[list[LongMemory], tuple[str, ...]]:
    sessions = sample.get("haystack_sessions") or []
    answer_sessions = set(_answer_session_ids(sample))
    memories: list[LongMemory] = []
    expected: list[str] = []
    seen_sessions: dict[str, int] = {}
    if not isinstance(sessions, list):
        return memories, ()
    for offset, session in enumerate(sessions):
        session_id = _session_id(sample, offset)
        seen_sessions[session_id] = seen_sessions.get(session_id, 0) + 1
        unique_session_id = (
            session_id
            if seen_sessions[session_id] == 1
            else f"{session_id}#{seen_sessions[session_id]}"
        )
        date = _session_date(sample, offset)
        memory_id = f"{question_id}::{unique_session_id}"
        text = _session_text(session, date)
        if not text:
            continue
        memories.append(
            LongMemory(
                id=memory_id,
                text=text,
                namespace=namespace,
                tags=("longmemeval", "session"),
                timestamp=date,
            )
        )
        if session_id in answer_sessions:
            expected.append(memory_id)
    return memories, tuple(expected)


def _load_turn_granularity(
    sample: dict[str, Any],
    question_id: str,
    namespace: str,
) -> tuple[list[LongMemory], tuple[str, ...]]:
    sessions = sample.get("haystack_sessions") or []
    answer_sessions = set(_answer_session_ids(sample))
    memories: list[LongMemory] = []
    expected: list[str] = []
    seen_sessions: dict[str, int] = {}
    if not isinstance(sessions, list):
        return memories, ()
    for session_offset, session in enumerate(sessions):
        session_id = _session_id(sample, session_offset)
        seen_sessions[session_id] = seen_sessions.get(session_id, 0) + 1
        unique_session_id = (
            session_id
            if seen_sessions[session_id] == 1
            else f"{session_id}#{seen_sessions[session_id]}"
        )
        date = _session_date(sample, session_offset)
        if not isinstance(session, list):
            session = [session]
        session_has_turn_labels = any(
            isinstance(turn, dict) and "has_answer" in turn
            for turn in session
        )
        for turn_offset, turn in enumerate(session, start=1):
            text = _turn_text(turn)
            if not text:
                continue
            memory_id = f"{question_id}::{unique_session_id}::turn-{turn_offset:04d}"
            if date:
                text = f"[{date}] {text}"
            memories.append(
                LongMemory(
                    id=memory_id,
                    text=text,
                    namespace=namespace,
                    tags=("longmemeval", "turn"),
                    timestamp=date,
                )
            )
            has_answer = isinstance(turn, dict) and bool(turn.get("has_answer"))
            if has_answer or (not session_has_turn_labels and session_id in answer_sessions):
                expected.append(memory_id)
    return memories, tuple(expected)


def load_longmemeval_dataset(
    path: str | Path,
    granularity: str = "session",
    limit_queries: int | None = None,
    include_abstention: bool = False,
) -> EvidenceDataset:
    raw_samples = _samples(_read_json(Path(path)))
    memories: list[LongMemory] = []
    queries: list[EvidenceQuery] = []
    loaders = {
        "session": _load_session_granularity,
        "turn": _load_turn_granularity,
    }
    if granularity not in loaders:
        raise ValueError("granularity must be either session or turn")

    seen_questions: dict[str, int] = {}
    for index, sample in enumerate(raw_samples, start=1):
        if limit_queries is not None and len(queries) >= limit_queries:
            break
        raw_question_id = _question_id(sample, index)
        seen_questions[raw_question_id] = seen_questions.get(raw_question_id, 0) + 1
        question_id = (
            raw_question_id
            if seen_questions[raw_question_id] == 1
            else f"{raw_question_id}#{seen_questions[raw_question_id]}"
        )
        question = str(sample.get("question") or "").strip()
        if not question:
            continue
        if _is_abstention(sample, question_id) and not include_abstention:
            continue
        namespace = f"longmemeval:{question_id}"
        sample_memories, expected = loaders[granularity](sample, question_id, namespace)
        if not expected and not include_abstention:
            continue
        memories.extend(sample_memories)
        queries.append(
            EvidenceQuery(
                id=question_id,
                text=question,
                namespace=namespace,
                expected_evidence_ids=expected,
                category=str(sample.get("question_type") or "general"),
            )
        )

    return EvidenceDataset(name=f"longmemeval-{granularity}", memories=memories, queries=queries)


def run_benchmark(
    dataset_path: str | Path,
    engines: Iterable[str],
    encoder_kind: str = "hash",
    granularity: str = "session",
    top_k: int = 5,
    limit_queries: int | None = None,
    include_abstention: bool = False,
) -> dict[str, Any]:
    dataset = load_longmemeval_dataset(
        dataset_path,
        granularity=granularity,
        limit_queries=limit_queries,
        include_abstention=include_abstention,
    )
    base_encoder = create_text_encoder(kind=encoder_kind, vector_dim=384)
    encoder = cache_encoder_for_dataset(dataset, base_encoder)
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
    return {
        "scenario": {
            "name": "longmemeval_evidence_retrieval",
            "dataset": str(dataset_path),
            "source_url": SOURCE_URL,
            "data_url": DATA_URL,
            "granularity": granularity,
            "memories": len(dataset.memories),
            "queries": len(dataset.queries),
            "top_k": top_k,
            "description": (
                "LongMemEval retrieval-only evidence benchmark. It indexes each "
                "question's long chat history and measures whether expected evidence "
                "sessions or turns are retrieved."
            ),
        },
        "embedding": {
            "kind": encoder_kind,
            "class": type(base_encoder).__name__,
            "cached": True,
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
    parser.add_argument("--granularity", choices=["session", "turn"], default="session")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit-queries", type=int, default=None)
    parser.add_argument("--include-abstention", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("benchmarks/longmemeval_evidence_results.json"))
    args = parser.parse_args()

    payload = run_benchmark(
        dataset_path=args.dataset,
        engines=args.engines,
        encoder_kind=args.encoder,
        granularity=args.granularity,
        top_k=args.top_k,
        limit_queries=args.limit_queries,
        include_abstention=args.include_abstention,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_table(payload)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
