# Quality Leadership Admission

Status: **blocked**
Source SHA: `be873e720fe3a9eba4b73566efb56e1c488c5f77`
Protocol: `quality-leadership-v1-20260810`
Rows: **11/22 implemented**, 9 blocked, 2 required-current, 0 failed

| Row | Status | Artifact | Test |
|---|---:|---|---|
| `source-sha-exact` | `implemented` | `git rev-parse HEAD` | `tests/test_quality_leadership_admission.py` |
| `goal4-failure-preserved` | `implemented` | `benchmarks/goal4_quality_experiment_results.json` | `tests/test_goal4_quality_experiment.py` |
| `protocol-snapshot-current` | `implemented` | `benchmarks/quality_leadership_protocol.json` | `tests/test_quality_leadership_admission.py` |
| `protocol-frozen-before-heldout` | `blocked` | `benchmarks/quality_leadership_protocol.json` | `tests/test_quality_leadership_admission.py` |
| `safe-product-current` | `required_current` | `benchmarks/safe_product_admission_results.json` | `.github/workflows/safe-product.yml` |
| `workspace-experience-current` | `required_current` | `benchmarks/workspace_experience_admission_results.json` | `.github/workflows/safe-product.yml` |
| `results-artifact-current` | `implemented` | `benchmarks/quality_leadership_results.json` | `tests/test_quality_leadership_admission.py` |
| `development-go-no-go` | `blocked` | `benchmarks/quality_leadership_results.json` | `tests/test_quality_leadership_admission.py` |
| `heldout-opened-once` | `blocked` | `benchmarks/quality_leadership_results.json` | `tests/test_quality_leadership_admission.py` |
| `longmemeval-v2-quality` | `blocked` | `benchmarks/quality_leadership_results.json` | `tests/test_quality_leadership_admission.py` |
| `memory-os-uplift-over-core` | `implemented` | `benchmarks/quality_leadership_results.json` | `tests/test_quality_leadership_admission.py` |
| `category-improvements` | `blocked` | `benchmarks/quality_leadership_results.json` | `tests/test_quality_leadership_admission.py` |
| `context-reduction` | `implemented` | `benchmarks/quality_leadership_results.json` | `tests/test_quality_leadership_admission.py` |
| `stale-contradiction-control` | `implemented` | `benchmarks/quality_leadership_results.json` | `tests/test_quality_leadership_admission.py` |
| `latency-budget` | `implemented` | `benchmarks/quality_leadership_results.json` | `tests/test_quality_leadership_admission.py` |
| `locomo-longmemeval-dynamic-categories` | `blocked` | `benchmarks/quality_leadership_results.json` | `tests/test_quality_leadership_admission.py` |
| `real-local-competitors` | `implemented` | `benchmarks/quality_leadership_results.json` | `tests/test_quality_leadership_admission.py` |
| `backend-recall-loss` | `blocked` | `benchmarks/quality_leadership_results.json` | `tests/test_quality_leadership_admission.py` |
| `five-run-confidence-intervals` | `implemented` | `benchmarks/quality_leadership_results.json` | `tests/test_quality_leadership_admission.py` |
| `verdict-fingerprint-stability` | `blocked` | `benchmarks/quality_leadership_results.json` | `tests/test_quality_leadership_admission.py` |
| `per-query-artifact` | `implemented` | `benchmarks/quality_leadership_per_query.jsonl` | `tests/test_quality_leadership_admission.py` |
| `public-claims-fresh` | `blocked` | `README.md / docs/ROADMAP.md / docs/BENCHMARK_BRIEF.md` | `tests/test_quality_leadership_admission.py` |

## Next Actions

- Freeze a new independent quality-leadership development/held-out protocol before tuning.
- Run a bounded development benchmark and stop unless the go/no-go gate passes.
- Use exact-current CI artifacts for Safe Product and Workspace Experience on the final SHA.
- Open the new held-out split exactly once only after protocol freeze and dev go/no-go.

## Claim Boundary

Quality leadership is blocked until a new frozen protocol, bounded development gate, single untouched held-out run, real local competitors, current Safe Product and Workspace Experience evidence, and exact-main CI evidence all pass. The historical Goal 4 failure remains public.
