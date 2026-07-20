# WaveMind Remote Memory OS Worker Soak

This evidence combines direct remote worker HTTP concurrency with lease and job-receipt semantics against the same non-loopback Redis. It admits only this tested worker topology.

Status: `pass`

## Checks

| check | result | evidence |
|---|---|---|
| `remote-topology` | `pass` | preflight=pass |
| `worker-health` | `pass` | healthy=2/2 |
| `worker-version` | `pass` | versions=['2.6.2'] |
| `worker-commit` | `pass` | expected=23edad3b172fe0480e3b49640071c1930304c665, commits=['23edad3b172fe0480e3b49640071c1930304c665'] |
| `worker-plan` | `pass` | safe=2/2, hot=2/2 |
| `remote-redis-semantics` | `pass` | status=pass, environment=remote_redis |
| `soak-duration` | `pass` | duration_seconds=21600.119, required=21600.000 |
| `worker-cycles` | `pass` | completed=500, required=500 |
| `cross-worker-single-flight` | `pass` | completed=500, cycles=500 |
| `cross-worker-retry` | `pass` | duplicate_retries=500, cycles=500 |
| `error-rate` | `pass` | failures=0, attempts=2500, rate=0.000000 |
| `lock-safety` | `pass` | lock_breach_count=0 |
| `duplicate-mutation-safety` | `pass` | duplicate_mutation_count=0 |
| `state-integrity` | `pass` | state_corruption_count=0 |
| `no-in-doubt-jobs` | `pass` | errors=0 |
| `cleanup` | `pass` | seeded=2 |

## Handoff

- Secret scope: `repository_actions_secrets`
- Workflow: `.github/workflows/memory-os-remote-soak.yml`
- Dispatch: `gh workflow run memory-os-remote-soak.yml --ref main -f cycles=500 -f contenders=4`
- Minimum duration: `21600` seconds
- Minimum worker cycles: `500`
- Every worker must expose `WAVEMIND_COMMIT_SHA` matching the tested commit.
