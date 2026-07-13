# WaveMind Remote Memory OS Worker Soak

This preflight only validates a production-like remote topology contract. It does not admit Memory OS until the remote worker soak itself passes.

Status: `action_required`

## Checks

| check | result | evidence |
|---|---|---|
| `worker-endpoints` | `action_required` | workers=0, distinct_netlocs=0 |
| `non-loopback-workers` | `action_required` | remote=False |
| `worker-transport` | `action_required` | https=False, allow_insecure=False |
| `remote-redis` | `action_required` | configured=False, environment=missing |
| `redis-transport` | `action_required` | rediss=False, allow_insecure=False |
| `admin-auth` | `action_required` | api_key_present=False |

## Handoff

- GitHub environment: `memory-os-production-evidence`
- Workflow: `.github/workflows/memory-os-remote-soak.yml`
- Dispatch: `gh workflow run memory-os-remote-soak.yml --ref main`
