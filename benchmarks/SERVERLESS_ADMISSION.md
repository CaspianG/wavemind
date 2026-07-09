# WaveMind Serverless Admission

This is the deployment-facing gate for managed/serverless production
rollouts. It admits production traffic only when deployed HTTP API
nodes have produced remote telemetry for p99 latency, cold-start
budget, error rate, and scale-out capacity. Loopback telemetry stays
useful for development, but does not unlock this gate.

| metric | value |
|---|---:|
| status | `plan_only` |
| admitted | `False` |
| deployment | `production` |
| target RPS | `3200.0` |
| target p99 ms | `500.0` |
| max scale | `256` |
| cold-start budget ms | `1500.0` |
| strict evidence | `action_required` |
| requested evidence | `action_required` |
| preflight | `action_required` |
| required artifact | `deploy/serverless/observed-telemetry.remote.json` |

## Required Evidence

| requirement | status | artifact | evidence |
|---|---|---|---|
| Managed/serverless remote telemetry | `action_required` | `deploy/serverless/observed-telemetry.remote.json` | missing remote serverless telemetry |

## Requested Evidence

| status | target RPS | target p99 ms | max scale | cold-start budget ms | evidence |
|---|---:|---:|---:|---:|---|
| `action_required` | `3200.0` | `500.0` | `256` | `1500.0` | missing remote serverless telemetry |

## Preflight

| status | required env | missing env | evidence |
|---|---|---|---|
| `action_required` | `WAVEMIND_SERVERLESS_NODES` | `WAVEMIND_SERVERLESS_NODES` | 0 node URLs configured |

## Issues

- serverless_remote_telemetry is not admitted: strict_status=action_required
- serverless_remote_telemetry artifact does not satisfy requested rollout: requested_evidence_status=action_required
- missing artifact

## Next Actions

- Do not admit managed/serverless production traffic yet; run the remote telemetry workflow against deployed nodes first.
- `gh workflow run serverless-observed-telemetry.yml -f nodes="https://wm-a.example.com,https://wm-b.example.com" -f seed_mode=first -f commit_results=true`
