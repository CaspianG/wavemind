# Workspace Experience Admission Matrix

- Status: `blocked`
- Source SHA: `8214d58f8a6e7671c3da9980d3512ca1634f51d5`
- Protocol: `workspace-experience-v1-frozen-20260810`
- Protocol SHA-256: `fa2ebc36799b44ff54e74120da7dab3a475d40461a4963872069f5905beeb590`

| Row | Status | Artifact | Test |
|---|---|---|---|
| `baseline-gap-audit` | `implemented` | `benchmarks/workspace_experience_admission_matrix.json` | `tests/test_workspace_experience_admission.py` |
| `workspace-identity-isolation` | `implemented` | `tests/test_workspace_experience.py` | `tests/test_workspace_experience.py` |
| `provider-neutral-capture-contract` | `implemented` | `tests/test_workspace_experience.py` | `tests/test_workspace_experience.py` |
| `verified-runbook-compiler` | `implemented` | `wavemind/workspace_experience.py` | `tests/test_workspace_experience.py` |
| `human-review-control` | `implemented` | `wavemind/workspace_experience.py` | `tests/test_workspace_experience.py` |
| `cross-agent-portability` | `implemented` | `wavemind/workspace_experience.py` | `tests/test_workspace_experience.py` |
| `useful-experience-packet` | `implemented` | `wavemind/workspace_experience.py` | `tests/test_workspace_experience.py` |
| `workspace-onboarding` | `implemented` | `docs/WORKSPACE_EXPERIENCE_QUICKSTART.md` | `tests/test_workspace_experience.py` |
| `historical-v3-checksum-selection-experiment` | `failed` | `benchmarks/workspace_experience_benchmark_results.json` | `tests/test_workspace_experience_benchmark.py` |
| `frozen-real-work-benchmark-v4` | `failed` | `benchmarks/workspace_experience_v4_manifest.json` | `tests/test_workspace_experience_v4_benchmark.py` |
| `frozen-real-work-benchmark-v5` | `missing` | `benchmarks/workspace_experience_v5_benchmark_results.json` | `tests/test_workspace_experience_v5_benchmark.py` |
| `workspace-experience-admission` | `blocked` | `benchmarks/workspace_experience_admission_results.json` | `tests/test_workspace_experience_admission.py` |
| `safe-product-regression` | `required_current` | `benchmarks/safe_product_admission_results.json` | `.github/workflows/safe-product.yml` |

## Claim Boundary

This matrix is a Goal 7 gap audit, not final production admission.
