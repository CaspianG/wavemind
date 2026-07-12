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
| `action_required` | `WAVEMIND_CLOUD_RUN_PROJECT_ID, WAVEMIND_CLOUD_RUN_REGION, WAVEMIND_CLOUD_RUN_SERVICE, WAVEMIND_GCP_WORKLOAD_IDENTITY_PROVIDER, WAVEMIND_GCP_SERVICE_ACCOUNT, WAVEMIND_API_KEY` | `WAVEMIND_CLOUD_RUN_PROJECT_ID, WAVEMIND_CLOUD_RUN_REGION, WAVEMIND_CLOUD_RUN_SERVICE, WAVEMIND_GCP_WORKLOAD_IDENTITY_PROVIDER, WAVEMIND_GCP_SERVICE_ACCOUNT, WAVEMIND_API_KEY` | project missing, region missing, service missing, OIDC missing |

## Issues

- serverless_remote_telemetry is not admitted: strict_status=action_required
- serverless_remote_telemetry artifact does not satisfy requested rollout: requested_evidence_status=action_required
- missing artifact

## Next Actions

- Do not admit managed/serverless production traffic yet; run the remote telemetry workflow against deployed nodes first.
- `gh workflow run managed-serverless-cloud-run.yml --ref main -f project_id="$WAVEMIND_CLOUD_RUN_PROJECT_ID" -f region="$WAVEMIND_CLOUD_RUN_REGION" -f service_name="$WAVEMIND_CLOUD_RUN_SERVICE"`
