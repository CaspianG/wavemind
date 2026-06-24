# Long-Term Memory Evidence Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a retrieval-only long-term memory evidence benchmark that compares WaveMind against static vector-store baselines on dynamic memory behavior.

**Architecture:** Add one focused benchmark runner under `benchmarks/` with normalized scenario types, synthetic long-memory data, metric calculation, WaveMind runner, optional Chroma/Qdrant runners, CLI output, and README/result updates. The first benchmark is deterministic and local, so it can run without network or API keys.

**Tech Stack:** Python stdlib, WaveMind core API, optional `chromadb`, optional `qdrant-client`, pytest tests for CI, JSON results for README/chart consumption.

---

### Task 1: Tests for Normalized Dataset and Metrics

**Files:**
- Create: `tests/test_long_memory_evidence_benchmark.py`
- Create: `benchmarks/long_memory_evidence_benchmark.py`

- [ ] **Step 1: Write failing tests**

```python
def test_synthetic_long_memory_scenario_contains_dynamic_categories():
    from benchmarks.long_memory_evidence_benchmark import build_synthetic_dataset

    dataset = build_synthetic_dataset(memory_count=120)
    categories = {query.category for query in dataset.queries}

    assert len(dataset.memories) == 120
    assert {"profile", "personalization", "correction", "ttl", "namespace"}.issubset(categories)
    assert any(memory.ttl_seconds == 0 for memory in dataset.memories)
    assert any(query.forbidden_evidence_ids for query in dataset.queries)
```

```python
def test_metrics_reward_expected_evidence_and_stale_suppression():
    from benchmarks.long_memory_evidence_benchmark import EvidenceQuery, compute_evidence_metrics

    queries = [
        EvidenceQuery(id="q1", text="current city", namespace="user-a", expected_evidence_ids=("new_city",), forbidden_evidence_ids=("old_city",), category="correction"),
        EvidenceQuery(id="q2", text="expired token", namespace="user-a", expected_evidence_ids=(), forbidden_evidence_ids=("expired_token",), category="ttl"),
    ]
    metrics = compute_evidence_metrics(
        queries=queries,
        rankings={"q1": ["new_city", "old_city"], "q2": ["active_token"]},
        returned_texts={"q1": ["The user lives in Lisbon.", "The user lived in Berlin."], "q2": ["The valid token is green-772."]},
        latencies_ms=[2.0, 4.0],
        full_context_tokens=100,
        top_k=2,
        engine="unit",
    )

    assert metrics.evidence_recall_at_k == 1.0
    assert metrics.precision_at_1 == 1.0
    assert metrics.stale_suppression == 0.5
    assert metrics.category_success["correction"] == 1.0
    assert metrics.category_success["ttl"] == 1.0
    assert metrics.avg_latency_ms == 3.0
    assert metrics.context_budget_saved > 0.0
```

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_long_memory_evidence_benchmark.py -q`

Expected: FAIL because `benchmarks.long_memory_evidence_benchmark` does not exist.

- [ ] **Step 3: Implement dataclasses, synthetic dataset, and metric function**

Add `LongMemory`, `EvidenceQuery`, `EvidenceDataset`, `EvidenceMetrics`, `build_synthetic_dataset()`, and `compute_evidence_metrics()`.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python -m pytest tests/test_long_memory_evidence_benchmark.py -q`

Expected: PASS in CI/dev env. If local pytest is unavailable, run `python -m py_compile benchmarks/long_memory_evidence_benchmark.py tests/test_long_memory_evidence_benchmark.py`.

### Task 2: Runner and CLI

**Files:**
- Modify: `benchmarks/long_memory_evidence_benchmark.py`
- Modify: `tests/test_long_memory_evidence_benchmark.py`

- [ ] **Step 1: Write failing CLI test**

```python
def test_long_memory_cli_writes_json_for_wavemind(tmp_path):
    output = tmp_path / "long-memory-result.json"
    subprocess.run([...], check=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["scenario"]["name"] == "long_memory_evidence"
    assert payload["results"][0]["engine"] == "WaveMind"
    assert "context_budget_saved" in payload["results"][0]
```

- [ ] **Step 2: Implement `run_wavemind()`, optional static baselines, `run_benchmark()`, and CLI**

WaveMind must store each memory with namespace, tags, ttl, metadata evidence id, and priority. Static baselines should use identical embeddings when optional packages are installed.

- [ ] **Step 3: Run smoke command**

Run: `python benchmarks/long_memory_evidence_benchmark.py --dataset synthetic --engines wavemind --memories 120 --top-k 5 --output benchmarks/long_memory_evidence_results.json`

Expected: writes JSON and prints a Markdown table.

### Task 3: Results and README

**Files:**
- Create: `benchmarks/long_memory_evidence_results.json`
- Modify: `README.md`
- Modify: `benchmarks/benchmark_registry.py`
- Modify: `benchmarks/benchmark_matrix_results.json`

- [ ] **Step 1: Generate synthetic result JSON**

Run the CLI with WaveMind and available baselines. If Chroma/Qdrant are unavailable locally, include WaveMind-only JSON and document optional baseline commands.

- [ ] **Step 2: Update README**

Add a compact table under Benchmark showing long-term memory evidence metrics and a clear note that public LoCoMo/LongMemEval results are still pending.

- [ ] **Step 3: Update benchmark matrix**

Add `long_memory_evidence_synthetic` as implemented and keep LoCoMo/LongMemEval as planned until public results exist.

- [ ] **Step 4: Verify**

Run `python -m py_compile benchmarks/long_memory_evidence_benchmark.py` and the CLI smoke command. Run pytest when available.
