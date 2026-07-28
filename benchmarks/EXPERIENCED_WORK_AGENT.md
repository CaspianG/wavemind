# Experienced Work Agent

Status: `pass`

Dataset `experienced-work-agent-v1-frozen-20260728`: 60 training trajectories, 30 frozen held-out tasks.

| engine | success | repeated error | median steps | median context | p95 |
|---|---:|---:|---:|---:|---:|
| Cold work agent | 0.0% | 100.0% | 4.0 | 0.0 | 28.50 ms |
| WaveMind Core | 16.7% | 83.3% | 4.0 | 60.0 | 33.85 ms |
| WaveMind Experience | 100.0% | 0.0% | 3.0 | 36.0 | 19.57 ms |

## Admission checks

- `pass` training-count: 60 (target: 60)
- `pass` held-out-count: 30 (target: 30)
- `pass` held-out-domain-balance: {'support_crm': 10, 'coding_repository': 10, 'enterprise_workflow': 10} (target: 10 per domain)
- `pass` task-success-uplift: 0.8333333333333334 (target: >= 0.15 absolute over WaveMind Core)
- `pass` repeated-error-reduction: 1.0 (target: >= 0.50 relative)
- `pass` tool-step-reduction: 0.25 (target: >= 0.25 relative)
- `pass` context-token-reduction: 0.4 (target: >= 0.35 relative)
- `pass` p95-latency: -0.42198785835167174 (target: <= 0.20 relative)
