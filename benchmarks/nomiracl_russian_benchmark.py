from __future__ import annotations

import argparse
import gzip
import json
import sys
import urllib.request
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.open_retrieval_benchmark import (
    RetrievalDataset,
    RetrievalDocument,
    RetrievalQuery,
    print_table,
    run_chroma,
    run_qdrant,
    run_wavemind,
)
from wavemind.encoders import create_text_encoder


SOURCE_URL = "https://huggingface.co/datasets/miracl/nomiracl"
PAPER_URL = "https://aclanthology.org/2024.findings-emnlp.730/"
BASE_URL = "https://huggingface.co/datasets/miracl/nomiracl/resolve/main/data/russian"
DEFAULT_DATASET_DIR = Path("benchmarks/data/nomiracl-russian")


def download_nomiracl_russian(dataset_dir: str | Path = DEFAULT_DATASET_DIR) -> Path:
    root = Path(dataset_dir)
    files = (
        "corpus.jsonl.gz",
        "qrels/dev.relevant.tsv",
        "qrels/test.relevant.tsv",
        "topics/dev.relevant.tsv",
        "topics/test.relevant.tsv",
    )
    for relative in files:
        destination = root / relative
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        url = f"{BASE_URL}/{relative}"
        urllib.request.urlretrieve(url, destination)
    return root


def _read_topics(path: Path) -> list[RetrievalQuery]:
    queries: list[RetrievalQuery] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) != 2:
                raise ValueError(f"Invalid NoMIRACL topic row at {path}:{line_number}")
            queries.append(RetrievalQuery(id=parts[0], text=parts[1]))
    return queries


def _read_qrels(path: Path) -> dict[str, dict[str, float]]:
    qrels: dict[str, dict[str, float]] = {}
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 4:
                raise ValueError(f"Invalid NoMIRACL qrels row at {path}:{line_number}")
            query_id, _, document_id, score = parts[:4]
            relevance = float(score)
            if relevance > 0:
                qrels.setdefault(query_id, {})[document_id] = relevance
    return qrels


def _read_corpus(path: Path, allowed_ids: set[str] | None = None) -> list[RetrievalDocument]:
    documents: list[RetrievalDocument] = []
    seen_ids: set[str] = set()
    with gzip.open(path, "rt", encoding="utf-8-sig") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid NoMIRACL corpus JSON at {path}:{line_number}") from exc
            docid = str(row.get("docid") or row.get("id") or "")
            if not docid:
                raise ValueError(f"Missing NoMIRACL docid at {path}:{line_number}")
            if allowed_ids is not None and docid not in allowed_ids:
                continue
            if docid in seen_ids:
                continue
            seen_ids.add(docid)
            title = str(row.get("title") or "").strip()
            text = str(row.get("text") or "").strip()
            combined = f"{title}\n{text}".strip() if title else text
            documents.append(RetrievalDocument(id=docid, text=combined))
    return documents


def load_nomiracl_russian_dataset(
    dataset_dir: str | Path,
    split: str = "test",
    limit_queries: int | None = None,
    limit_corpus: int | None = None,
) -> RetrievalDataset:
    root = Path(dataset_dir)
    topics_path = root / "topics" / f"{split}.relevant.tsv"
    qrels_path = root / "qrels" / f"{split}.relevant.tsv"
    corpus_path = root / "corpus.jsonl.gz"
    for path in (topics_path, qrels_path, corpus_path):
        if not path.exists():
            raise FileNotFoundError(f"Missing NoMIRACL Russian file: {path}")

    qrels = _read_qrels(qrels_path)
    queries = [query for query in _read_topics(topics_path) if query.id in qrels]
    if limit_queries is not None:
        queries = queries[:limit_queries]
    selected_query_ids = {query.id for query in queries}
    qrels = {query_id: docs for query_id, docs in qrels.items() if query_id in selected_query_ids}
    required_doc_ids = {doc_id for docs in qrels.values() for doc_id in docs}
    documents = _read_corpus(corpus_path)
    if limit_corpus is not None and limit_corpus > 0:
        selected: list[RetrievalDocument] = []
        selected_ids: set[str] = set()
        for document in documents:
            if document.id in required_doc_ids:
                selected.append(document)
                selected_ids.add(document.id)
        for document in documents:
            if len(selected) >= limit_corpus:
                break
            if document.id not in selected_ids:
                selected.append(document)
                selected_ids.add(document.id)
        documents = selected
    document_ids = {document.id for document in documents}
    qrels = {
        query.id: {doc_id: score for doc_id, score in qrels.get(query.id, {}).items() if doc_id in document_ids}
        for query in queries
    }
    queries = [query for query in queries if qrels.get(query.id)]
    return RetrievalDataset(
        name=f"nomiracl-russian-{split}.relevant",
        documents=documents,
        queries=queries,
        qrels=qrels,
    )


def run_benchmark(
    dataset_dir: str | Path,
    engines: Iterable[str],
    split: str = "test",
    encoder_kind: str = "hash",
    top_k: int = 10,
    limit_queries: int | None = None,
    limit_corpus: int | None = None,
) -> dict:
    dataset = load_nomiracl_russian_dataset(
        dataset_dir=dataset_dir,
        split=split,
        limit_queries=limit_queries,
        limit_corpus=limit_corpus,
    )
    encoder = create_text_encoder(kind=encoder_kind, vector_dim=384)
    runners = {"wavemind": run_wavemind, "chroma": run_chroma, "qdrant": run_qdrant}
    results = []
    for engine in engines:
        key = engine.lower()
        if key not in runners:
            raise ValueError(f"Unknown engine: {engine}")
        results.append(runners[key](dataset, encoder, top_k).__dict__)
    return {
        "scenario": {
            "name": "nomiracl_russian_relevant_retrieval",
            "dataset": dataset.name,
            "source_url": SOURCE_URL,
            "paper_url": PAPER_URL,
            "documents": len(dataset.documents),
            "queries": len(dataset.queries),
            "limit_queries": limit_queries,
            "limit_corpus": limit_corpus,
            "split": split,
            "top_k": top_k,
            "description": (
                "NoMIRACL Russian relevant-subset retrieval over human-annotated "
                "top-k passages. This is a compact multilingual relevance benchmark, "
                "not a full-corpus MIRACL run."
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--split", choices=["dev", "test"], default="test")
    parser.add_argument("--engines", nargs="+", choices=["wavemind", "chroma", "qdrant"], default=["wavemind"])
    parser.add_argument("--encoder", choices=["hash", "sentence"], default="hash")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--limit-queries", type=int, default=None)
    parser.add_argument("--limit-corpus", type=int, default=None)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/nomiracl_russian_results.json"))
    args = parser.parse_args()
    if args.download:
        download_nomiracl_russian(args.dataset)
    payload = run_benchmark(
        dataset_dir=args.dataset,
        engines=args.engines,
        split=args.split,
        encoder_kind=args.encoder,
        top_k=args.top_k,
        limit_queries=args.limit_queries,
        limit_corpus=args.limit_corpus,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_table(payload)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
