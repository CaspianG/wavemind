# Long-Term Memory Evidence Benchmark Design

## Goal

Build a reproducible benchmark layer that proves whether WaveMind is more useful than a plain vector store for long-running AI-agent memory.

The benchmark must move beyond static nearest-neighbor retrieval. It should measure whether a memory system can retrieve the right evidence from long histories while suppressing stale, corrected, expired, or cross-user facts.

Target proof:

- Agents remember relevant facts longer.
- Agents make fewer context mistakes from stale or conflicting facts.
- Personalization facts survive long conversations.
- Prompt context can be smaller because retrieval returns compact evidence.
- Retrieval latency stays acceptable for an agent loop.

## Scope

The first implementation is retrieval-only. It will not call an LLM and will not use an LLM judge.

This is intentional: evidence retrieval is cheaper, deterministic, and easier to compare across WaveMind, Chroma, and Qdrant. Once evidence quality is stable, an optional answer-quality layer can be added on top.

## Datasets

The benchmark runner should support two dataset styles.

1. Public long-term memory datasets

- LoCoMo-style long conversation memory datasets.
- LongMemEval-style long-term assistant memory datasets.
- LongMemEval-V2-style web-agent memory datasets when available.

2. Repository-local synthetic long-memory scenarios

These are not a replacement for public benchmarks. They are smoke tests and regression tests for dynamic behavior:

- preference repeated across sessions,
- user profile facts,
- correction of old facts,
- TTL expiration,
- namespace isolation,
- irrelevant filler history,
- ambiguous questions where stale facts should be suppressed.

## Data Model

Normalize datasets into a common evidence format:

```json
{
  "sessions": [
    {
      "id": "session-001",
      "turns": [
        {
          "role": "user",
          "text": "I moved from Berlin to Lisbon.",
          "timestamp": "2026-01-08T12:00:00Z"
        }
      ]
    }
  ],
  "queries": [
    {
      "id": "q-current-city",
      "text": "Where does the user live now?",
      "expected_evidence_ids": ["turn-017"],
      "forbidden_evidence_ids": ["turn-003"],
      "category": "correction"
    }
  ]
}
```

Every engine receives the same normalized memories, queries, embeddings, namespaces, timestamps, and metadata.

## Engines

WaveMind:

- Stores each memory with namespace, tags, timestamp, TTL, priority, and metadata.
- Uses vector candidates first.
- Applies dynamic memory policy for hotness, priority, TTL, and stale suppression.

Chroma static:

- Stores the same text and embeddings.
- Uses plain vector retrieval.
- Does not receive extra application-layer correction/TTL policy in the first baseline.

Chroma policy:

- Future stronger baseline.
- Uses metadata filters, deletes, and app-layer rules to simulate parts of WaveMind behavior.

Qdrant static:

- Stores the same text and embeddings.
- Uses plain vector retrieval.

Qdrant policy:

- Future stronger baseline with payload filters and app-layer rules.

## Metrics

Core retrieval metrics:

- `evidence_recall@k`: whether expected evidence appears in top-k.
- `evidence_precision@k`: how much returned evidence is useful.
- `mrr@k`: how high the first correct evidence appears.
- `precision@1`: whether the first result is correct.

Dynamic memory metrics:

- `stale_suppression`: forbidden stale evidence is absent from top-k.
- `correction_accuracy`: newer corrected fact beats older conflicting fact.
- `ttl_suppression`: expired memory is not returned.
- `namespace_isolation`: another user/project memory never leaks.
- `personalization_accuracy`: stable user preferences/profile facts are returned.

Agent-cost metrics:

- `context_tokens_returned`: estimated prompt tokens needed for retrieved evidence.
- `context_budget_saved`: reduction versus sending the whole recent history or a fixed RAG chunk budget.
- `avg_latency_ms` and `p95_latency_ms`.

## CLI

Add a runner shaped like:

```sh
python benchmarks/long_memory_evidence_benchmark.py \
  --dataset ./benchmarks/data/locomo \
  --format normalized \
  --engines wavemind chroma qdrant \
  --top-k 5 \
  --output benchmarks/long_memory_evidence_results.json
```

Also include a local deterministic smoke dataset:

```sh
python benchmarks/long_memory_evidence_benchmark.py \
  --dataset synthetic \
  --engines wavemind chroma \
  --top-k 5
```

## Outputs

The runner writes machine-readable JSON with:

- dataset name and format,
- engine list,
- embedding configuration,
- per-engine metrics,
- per-category metrics,
- per-query diagnostic rows,
- latency summary,
- context-token estimates.

README should show only committed, reproducible results. Planned datasets must stay clearly labeled as planned.

## Success Criteria

First milestone:

- Synthetic long-memory benchmark implemented and tested.
- WaveMind beats static Chroma on stale suppression, correction accuracy, namespace isolation, and personalization.
- The benchmark writes JSON and a Markdown table.

Second milestone:

- LoCoMo or LongMemEval adapter implemented.
- First public-dataset retrieval-only result committed.
- README shows WaveMind vs Chroma/Qdrant on evidence retrieval metrics.

Breakthrough target:

- On at least one public long-term memory benchmark, WaveMind improves dynamic-memory categories by 20-30 percentage points versus static vector-store retrieval, while keeping p95 retrieval latency under 100 ms for the benchmark scale.

## Non-Goals

- Do not claim public benchmark wins before results are committed.
- Do not compare different embedding models as if that proves memory-system quality.
- Do not require OpenAI API keys for the first benchmark.
- Do not make WaveMind look better by withholding metadata from competitors in future policy baselines.

## Testing

Unit tests should cover:

- normalized dataset loader,
- synthetic scenario generation,
- metric calculations,
- WaveMind runner,
- Chroma/Qdrant optional dependency behavior,
- CLI JSON output,
- README result consistency when chart data is updated.

## Implementation Order

1. Add normalized long-memory dataset types and metrics.
2. Add synthetic long-memory scenario builder.
3. Add WaveMind and Chroma static runners.
4. Add optional Qdrant static runner.
5. Add CLI output and tests.
6. Add JSON result and README table for synthetic proof.
7. Add public dataset adapter for LoCoMo or LongMemEval.
8. Add chart update after first public result.

