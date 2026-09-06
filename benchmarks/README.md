# WaveMind Benchmark Directory

This directory is an evidence ledger, not a collection of interchangeable
demo results. It intentionally keeps protocols, implementations, raw records,
admission decisions, and failed experiments together so public claims remain
auditable.

## Start With These Files

| Need | Read first |
|---|---|
| Current evidence overview | [`../docs/BENCHMARKS.md`](../docs/BENCHMARKS.md) |
| Short public interpretation | [`../docs/BENCHMARK_BRIEF.md`](../docs/BENCHMARK_BRIEF.md) |
| Verified agent-experience proof | [`VERIFIED_EXPERIENCE_ADMISSION.md`](VERIFIED_EXPERIENCE_ADMISSION.md) |
| Safe-product snapshot | [`SAFE_PRODUCT_ADMISSION.md`](SAFE_PRODUCT_ADMISSION.md) |
| Scientific-memory status | [`SCIENTIFIC_MEMORY_ADMISSION.md`](SCIENTIFIC_MEMORY_ADMISSION.md) and [`scientific_v31_admission_outcome.json`](scientific_v31_admission_outcome.json) |
| v32 selector performance | [`scientific_performance_v32_validation_results.json`](scientific_performance_v32_validation_results.json) |
| Machine-readable public index | [`../docs/data/leaderboard-status.json`](../docs/data/leaderboard-status.json) |
| Known claim boundaries | [`../docs/KNOWN_LIMITATIONS.md`](../docs/KNOWN_LIMITATIONS.md) |

## How The Files Fit Together

| File pattern | Meaning |
|---|---|
| `*_benchmark.py`, `*_smoke.py` | Workload or operational evidence runner |
| `*_protocol_*.json` | Frozen inputs, thresholds, and evaluation rules |
| `*_raw.jsonl` | Per-case records retained for audit and recomputation |
| `*_results.json` | Machine-readable output for one declared run |
| `*_admission.py` | Gate that evaluates evidence against fixed requirements |
| `*_ADMISSION.md` or `*_OUTCOME.md` | Human-readable rendering of a machine verdict |
| `*_manifest*.json` | Integrity, dataset, source, or execution inventory |
| `*_failure*.json` | Preserved failed run or infrastructure diagnosis |

The versioned `scientific_*` files record a real research sequence. A later
version does not erase an earlier failure, and performance evidence does not
silently become quality evidence.

## Verdict Vocabulary

| Verdict | Meaning |
|---|---|
| `admitted` / `pass` | Every declared requirement passed for the artifact's exact protocol and source. |
| `blocked` | Evidence required for the public claim is absent or not current. This is a valid, fail-closed result. |
| `failed_experiment` / `failed` | The measured hypothesis or admission threshold did not pass. Keep and cite the result honestly. |
| `historical` | The artifact is valid for its recorded source SHA, not for the current repository tip. |
| `planned` | No measured result exists yet. It must not be described as a win. |

## Evidence Rules

1. Freeze the protocol before the final run.
2. Record source revision, environment, dependencies, dataset identity, and
   execution command.
3. Keep raw case-level output when the protocol requires it.
4. Generate summaries from machine results instead of copying numbers by hand.
5. Separate local, loopback, synthetic, remote, and production evidence.
6. Preserve negative, failed, and blocked outcomes.
7. Run the artifact audit before presenting a result publicly.
8. Never treat an exact-SHA result as proof for a later source revision.

## Common Validation Commands

The complete workflow is defined in `.github/workflows/full-check.yml` and
`.github/workflows/safe-product.yml`. Useful local checks include:

```sh
python benchmarks/validate_benchmark_artifacts.py --max-age-days 8
python benchmarks/render_leaderboard_status.py
python benchmarks/render_benchmark_dashboard.py --output docs/benchmark-dashboard.html
pytest -q tests/test_benchmark_artifact_audit.py tests/test_benchmark_workflow.py
```

Some external benchmark runs require explicitly downloaded upstream datasets,
services, credentials, or hardware. Their runner must fail clearly or report a
skipped/blocked profile; it must not replace missing external evidence with a
local result carrying the same claim.

## Adding Evidence

Before adding a new public row, document:

- the question being tested;
- dataset and immutable split identity;
- baseline systems and versions;
- quality, latency, cost, and safety metrics relevant to the claim;
- the exact command and source SHA;
- known limitations and what the result does not prove.

See [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for the development workflow and
[`../docs/REPOSITORY_GUIDE.md`](../docs/REPOSITORY_GUIDE.md) for the full
repository map.
