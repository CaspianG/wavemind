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
| preflight | `action_required` |
| required artifact | `benchmarks/external_http_active_active_results.json` |

## Required Evidence

| requirement | status | artifact | evidence |
|---|---|---|---|
| External HTTP active-active regions | `action_required` | `benchmarks/external_http_active_active_results.json` | no checked-in external HTTP active-active region result |

## Preflight

| status | required env | missing env | evidence |
|---|---|---|---|
| `action_required` | `WAVEMIND_ACTIVE_ACTIVE_REGIONS, WAVEMIND_ACTIVE_ACTIVE_REGIONS_MANIFEST_JSON` | `WAVEMIND_ACTIVE_ACTIVE_REGIONS, WAVEMIND_ACTIVE_ACTIVE_REGIONS_MANIFEST_JSON` | 0 URLs configured |

## Issues

- external_http_active_active is not admitted: strict_status=action_required
- missing artifact

## Next Actions

- Do not admit multi-region production traffic yet; run the external active-active workflow against real regions first.
- `gh workflow run external-http-active-active.yml -f regions="us-east=https://wm-us.example.com,eu-west=https://wm-eu.example.com,ap-south=https://wm-ap.example.com" -f namespace_count=16 -f p99_slo_ms=1500 -f fail_on_slo=true -f commit_results=true`
