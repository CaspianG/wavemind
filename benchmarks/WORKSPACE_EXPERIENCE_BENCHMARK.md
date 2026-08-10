# Workspace Experience Historical Checksum-Selection Experiment

- Status: `failed`
- Split: `heldout`
- Manifest: `workspace-experience-v3-checksum-selection-historical-20260810`
- Manifest SHA-256: `4f4d9c5f5dca3b0d4349a9e2d8b3af9768b8a603a924085bdd8c37f2076d6cf6`
- Claim boundary: Historical failed checksum-selection experiment only. Task success uses source_sha256_check over pinned files, not reproduced workflow, test, CI, or environment outcomes. This artifact must not satisfy Goal 7 real-work admission.

This artifact is historical failed evidence only. It is not real-work benchmark proof because task success is based on source checksum selection, not on reproduced workflow, test, CI, or environment outcomes.

| Metric | Value | Gate |
|---|---:|---:|
| Task success lift | 1.67 pp | >= 15 pp |
| Known-error reduction | 0.053 | >= 0.50 |
| Context reduction | 0.807 | >= 0.30 |
| False procedure injection | 0.000 | <= 0.01 |
| Mandatory event capture | 1.000 | >= 0.99 |
| Cross-client parity | 1.000 | 1.00 |
| Packet p95 | 41.33 ms | <= 100 ms |
| Packet p99 | 42.01 ms | <= 250 ms |
| Clean onboarding | 1.96 s | <= 300 s |
