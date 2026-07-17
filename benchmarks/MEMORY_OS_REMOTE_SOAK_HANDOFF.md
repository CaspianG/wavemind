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

- Secret scope: `repository_actions_secrets`
- Workflow: `.github/workflows/memory-os-remote-soak.yml`
- Dispatch: `gh workflow run memory-os-remote-soak.yml --ref main -f cycles=500 -f contenders=4`
- Minimum duration: `21600` seconds
- Minimum worker cycles: `500`
- Every worker must expose `WAVEMIND_COMMIT_SHA` matching the tested commit.
