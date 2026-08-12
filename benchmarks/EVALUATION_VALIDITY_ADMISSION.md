# Evaluation Validity Admission

Status: **blocked**

Source SHA: `68e1bd0c0fb13e24f618a96c5f79b5d446bcc8cb`

Rows: `10/16` implemented

| Row | Status | Requirement |
|---|---|---|
| `dataset-provenance` | `implemented` | Dataset revisions, licenses, and checksums are pinned. |
| `split-isolation` | `blocked` | Dev, validation, and final splits have zero row, conversation, trajectory, or derived-fingerprint overlap. |
| `native-metric-mapping` | `implemented` | Every task uses its native scorer and semantic coercion is rejected. |
| `positive-controls` | `implemented` | Oracle evidence or correct-state controls are executed. |
| `negative-controls` | `implemented` | Random, no-memory, stale, wrong-namespace, and deleted-evidence controls are executed. |
| `control-ordering` | `implemented` | Oracle is above a strong valid baseline, which is above random and no-memory; poison affects only its safety target. |
| `metric-range` | `blocked` | Primary metrics have no floor or ceiling that makes preregistered improvement impossible. |
| `power-and-mde` | `blocked` | Sample size, minimum detectable effect, and cluster unit are preregistered per primary metric. |
| `paired-clustered-statistics` | `blocked` | Paired confidence intervals cluster by conversation, task, or trajectory. |
| `multiple-comparison-policy` | `implemented` | Multiple primary comparisons use the preregistered Holm correction. |
| `judge-calibration` | `blocked` | Every required LLM judge is pinned, calibrated, and has inter-run agreement evidence. |
| `deterministic-verdict` | `implemented` | Three deterministic repeats produce one verdict fingerprint. |
| `per-case-completeness` | `implemented` | Raw evidence includes every pass, failure, error, and skipped row. |
| `backend-blinding` | `implemented` | Backend input excludes gold, IDs, task type, split, and evaluator metadata. |
| `exact-sha-integrity` | `implemented` | Admission is tied to the exact source SHA and a current source manifest. |
| `safety-admissions-preserved` | `blocked` | Safe Product and Workspace Experience are admitted on the same exact SHA. |

> Measurement-validity admission only. Product tuning, benchmark quality, generalization, leaderboard, and production claims remain prohibited until admitted.
