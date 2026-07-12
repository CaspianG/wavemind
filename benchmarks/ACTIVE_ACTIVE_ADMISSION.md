# WaveMind Active-Active Admission

This is the deployment-facing gate for remote multi-region active-active
rollouts. It admits production traffic only when real external HTTP
regions have passed convergence, tombstone, final-noop, and p99 SLO
evidence. Local loopback profiles stay useful for development, but do
not unlock this gate.

| metric | value |
|---|---:|
| status | `plan_only` |
| admitted | `False` |
| deployment | `production` |
| min regions | `3` |
| namespace count | `16` |
| p99 SLO ms | `1500.0` |
| strict evidence | `action_required` |
| requested evidence | `action_required` |
| preflight | `action_required` |
| required artifact | `benchmarks/external_http_active_active_results.json` |

## Required Evidence

| requirement | status | artifact | evidence |
|---|---|---|---|
| External HTTP active-active regions with physical failure recovery | `action_required` | `benchmarks/external_http_active_active_results.json` | transport: no checked-in external HTTP active-active region result; failure recovery: no remote physical region failure and recovery artifact |

## Requested Evidence

| status | min regions | namespace count | p99 SLO ms | evidence |
|---|---:|---:|---:|---|
| `action_required` | `3` | `16` | `1500.0` | no checked-in external HTTP active-active region result |

## Preflight

| status | required env | missing env | evidence |
|---|---|---|---|
| `action_required` | `WAVEMIND_REMOTE_LAB_INVENTORY_JSON, WAVEMIND_REMOTE_SSH_PRIVATE_KEY, WAVEMIND_REMOTE_SSH_KNOWN_HOSTS, WAVEMIND_REMOTE_API_KEY, WAVEMIND_REMOTE_POSTGRES_PASSWORD` | `WAVEMIND_REMOTE_LAB_INVENTORY_JSON, WAVEMIND_REMOTE_SSH_PRIVATE_KEY, WAVEMIND_REMOTE_SSH_KNOWN_HOSTS, WAVEMIND_REMOTE_API_KEY, WAVEMIND_REMOTE_POSTGRES_PASSWORD` | remote production inventory is not configured |

## Issues

- external_http_active_active is not admitted: strict_status=action_required
- external_http_active_active artifact does not satisfy requested rollout: requested_evidence_status=action_required
- missing artifact
- failure drill: missing remote region failure drill artifact

## Next Actions

- Do not admit multi-region production traffic yet; run the remote production lab against three independently attested regions and ingest both evidence artifacts.
- `gh workflow run remote-production-lab.yml -f action=evidence -f namespace_count=16`
