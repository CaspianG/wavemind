# WaveMind Production Admission

This is the deployment-facing admission gate. It answers whether a
requested production scale is backed by passing strict evidence, or still
limited to a plan-only run contract.

| metric | value |
|---|---:|
| status | `plan_only` |
| admitted | `False` |
| deployment | `production` |
| engine | `qdrant-sharded-service` |
| target memories | `100000000` |
| required profiles | `qdrant-sharded-100m` |
| blocking issues | `1` |
| strict evidence | `action_required` |
| scale gap | `action_required` |

## Required Evidence

| profile | strict | scale gap | artifact | nearest baseline | missing env |
|---|---|---|---|---:|---|
| qdrant-sharded-100m | `action_required` | `blocked_by_env` | `benchmarks/production_streaming_load_qdrant_sharded_100m_results.json` | 1000000 | `WAVEMIND_REMOTE_SCALE_INVENTORY_JSON, WAVEMIND_REMOTE_SCALE_SSH_PRIVATE_KEY, WAVEMIND_REMOTE_SCALE_SSH_KNOWN_HOSTS, WAVEMIND_REMOTE_SCALE_QDRANT_API_KEY` |

## Issues

- qdrant-sharded-100m is not admitted: strict_status=action_required, scale_gap_status=blocked_by_env

## Next Actions

- Do not admit production traffic yet; run the listed strict-evidence job first.
- `gh workflow run remote-qdrant-100m-lab.yml --ref main -f action=evidence -f runner_label=self-hosted-large`
