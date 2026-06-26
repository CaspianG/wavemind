from __future__ import annotations

import argparse
import bz2
import json
import random
import re
import statistics
import tempfile
import time
import urllib.request
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import WaveMind
from wavemind.encoders import create_text_encoder


TATOEBA_RU_URL = "https://downloads.tatoeba.org/exports/per_language/rus/rus_sentences.tsv.bz2"
USER_AGENT = "WaveMindBenchmark/0.1 (local integration benchmark)"


def download_tatoeba_ru() -> bytes:
    request = urllib.request.Request(
        TATOEBA_RU_URL,
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def tokenize(sentence: str) -> list[str]:
    return [
        word.lower().replace("ё", "е")
        for word in re.findall(r"[А-Яа-яЁё]{4,}", sentence)
    ]


def is_good_sentence(sentence: str) -> bool:
    sentence = re.sub(r"\s+", " ", sentence).strip()
    words = tokenize(sentence)
    cyrillic = re.findall(r"[А-Яа-яЁё]", sentence)
    return (
        30 <= len(sentence) <= 180
        and len(words) >= 4
        and len(cyrillic) >= 25
        and not re.search(r"https?://|@|[{}<>]", sentence)
    )


def load_sentences(seed: int, count: int) -> list[str]:
    raw = bz2.decompress(download_tatoeba_ru()).decode("utf-8", errors="replace")
    sentences = []
    seen = set()
    for line in raw.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        sentence = re.sub(r"\s+", " ", parts[2]).strip()
        key = sentence.lower()
        if key in seen or not is_good_sentence(sentence):
            continue
        seen.add(key)
        sentences.append(sentence)

    if len(sentences) < count:
        raise RuntimeError(f"Only {len(sentences)} usable Tatoeba sentences, need {count}")

    rng = random.Random(seed)
    return rng.sample(sentences, count)


def choose_query_words(sentences: list[str], query_count: int, seed: int) -> list[tuple[str, str]]:
    rng = random.Random(seed + 1000)
    df = Counter()
    tokens_by_sentence = {}
    for sentence in sentences:
        tokens = sorted(set(tokenize(sentence)))
        tokens_by_sentence[sentence] = tokens
        df.update(tokens)

    queries = []
    for sentence in rng.sample(sentences, query_count):
        tokens = tokens_by_sentence[sentence]
        unique = [token for token in tokens if df[token] == 1]
        candidates = unique or tokens
        word = max(candidates, key=lambda token: (len(token), token))
        queries.append((word, sentence))
    return queries


def run(sentence_count: int, query_count: int, seed: int, encoder_kind: str, index_kind: str) -> dict:
    sentences = load_sentences(seed=seed, count=sentence_count)
    queries = choose_query_words(sentences, query_count=query_count, seed=seed)
    encoder = create_text_encoder(kind=encoder_kind, vector_dim=384)

    with tempfile.TemporaryDirectory() as tmp:
        mind = WaveMind(
            db_path=Path(tmp) / "ru-tatoeba-benchmark.sqlite3",
            encoder=encoder,
            index_kind=index_kind,
            score_threshold=0.0,
            width=64,
            height=64,
            layers=3,
            evolve_on_feed=3,
        )
        try:
            for sentence in sentences:
                mind.remember(sentence, namespace="ru-tatoeba")

            latencies = []
            hit1 = 0
            hit3 = 0
            examples = []
            for word, expected in queries:
                started = time.perf_counter()
                results = mind.query(word, namespace="ru-tatoeba", top_k=3)
                latencies.append((time.perf_counter() - started) * 1000.0)
                texts = [result.text for result in results]
                if texts[:1] == [expected]:
                    hit1 += 1
                if expected in texts[:3]:
                    hit3 += 1
                if len(examples) < 5:
                    examples.append(
                        {
                            "query": word,
                            "expected": expected,
                            "top1": texts[0] if texts else None,
                            "hit@3": expected in texts[:3],
                        }
                    )
        finally:
            mind.store.close()

    return {
        "source": TATOEBA_RU_URL,
        "encoder": type(encoder).__name__,
        "encoder_kind": encoder_kind,
        "index": index_kind,
        "sentences": sentence_count,
        "queries": query_count,
        "precision_at_1": hit1 / query_count,
        "precision_at_3": hit3 / query_count,
        "avg_query_ms": statistics.mean(latencies),
        "p95_query_ms": sorted(latencies)[min(len(latencies) - 1, int(len(latencies) * 0.95))],
        "examples": examples,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sentences", type=int, default=200)
    parser.add_argument("--queries", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--encoder", choices=["hash", "sentence"], default="hash")
    parser.add_argument("--index", choices=["numpy", "faiss", "annoy", "pgvector"], default="numpy")
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.sentences, args.queries, args.seed, args.encoder, args.index),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
