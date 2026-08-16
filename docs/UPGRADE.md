# Safe Upgrade Guide

`wavemind upgrade` updates a supported local Python installation or Docker
Compose deployment while treating Core memory, Verified Experience, config,
and object-store references as persistent user state.

> The command is release-ready only when the exact release SHA has a passing
> `upgrade-admission` artifact. Until the next release is published, use the
> command from the candidate branch only for validation.

## What the command protects

Before activation, WaveMind acquires an exclusive lock, checks versions, disk
space, active WaveMind processes, and SQLite writers, verifies release
identity and checksums, and creates a checksummed backup. The backup includes:

- the Core SQLite database;
- the Verified Experience SQLite database;
- every path supplied with `--config`;
- every path supplied with `--object-store-manifest`;
- the Compose environment file in Docker Compose mode.

Migrations run on staged SQLite copies. The live files change only after both
copies pass schema and logical-parity checks. The journal at
`.wavemind/upgrade/journal.json` makes an interrupted command recoverable and
idempotent.

## Python installation

Preview the upgrade without changing package or user data:

```sh
wavemind upgrade --dry-run --json
```

Upgrade to the latest published release:

```sh
wavemind upgrade --json
```

Choose an exact version and explicit database locations:

```sh
wavemind --db ./state/wavemind.sqlite3 upgrade \
  --experience-db ./state/wavemind-experience.sqlite3 \
  --to 2.13.0 \
  --config ./config/wavemind.json \
  --object-store-manifest ./state/objects.json \
  --json
```

Downgrades fail closed. A deliberate downgrade must name the target and include
`--allow-downgrade`:

```sh
wavemind upgrade --to 2.12.1 --allow-downgrade --json
```

## Fully offline wheel upgrade

On a connected machine, download both the target wheel and the currently
installed wheel. Copy them and their SHA-256 digests into the offline
environment. For example:

```sh
python -m pip download --only-binary=:all: --no-deps \
  wavemind==2.13.0 wavemind==2.12.1 --dest ./upgrade-artifacts
sha256sum ./upgrade-artifacts/wavemind-*.whl
```

Then run without a package-index request:

```sh
wavemind upgrade \
  --artifact ./upgrade-artifacts/wavemind-2.13.0-py3-none-any.whl \
  --expected-sha256 <target-wheel-sha256> \
  --current-artifact ./upgrade-artifacts/wavemind-2.12.1-py3-none-any.whl \
  --current-expected-sha256 <current-wheel-sha256> \
  --json
```

Both digests are mandatory. The current wheel is the verified package rollback
source if target installation or health verification fails.

## Docker Compose

Run the command from a directory whose `docker-compose.yml` defines the
`wavemind` service. Auto mode selects Docker Compose and preserves `.env`:

```sh
wavemind upgrade --to 2.13.0 --json
```

For a non-default file or service, be explicit:

```sh
wavemind upgrade \
  --mode docker-compose \
  --compose-file ./deploy/docker-compose.yml \
  --compose-env-file ./deploy/.env \
  --compose-service wavemind \
  --to 2.13.0 \
  --expected-image-digest sha256:<digest> \
  --json
```

WaveMind pins the current image for rollback, pulls and verifies the target,
stops the service, checks both SQLite writers, backs up state, updates only
`WAVEMIND_IMAGE`, and performs a real `--force-recreate --wait`. Health checks
inside the recreated container verify the running version and both databases.

## Backup, interruption, and rollback

Successful non-dry-run reports include `backup_path` and `journal_path`.
Backups default to `.wavemind/backups` and contain a manifest with the target
paths, sizes, and SHA-256 digests. Keep the reported archive until the upgraded
deployment has passed its own application checks.

Any installation, migration, activation, or health failure automatically:

1. verifies and restores the backup;
2. restores the previous Python wheel or pinned container image;
3. recreates and health-checks the previous container when applicable;
4. compares both databases, config, and object manifests with the pre-upgrade
   state;
5. records `rolled_back` only after rollback parity passes.

If the process or host stops mid-upgrade, run the same command again. Before
starting a new operation it verifies the journal's backup digest and completes
recovery. Do not delete the journal, artifact cache, rollback image, or backup
while recovery is pending.

## Exit status and JSON output

Use `--json` for automation. A successful upgrade or dry-run exits `0` and
prints one report. A blocked or failed operation exits `4` and reports
`{"status":"blocked","error":"..."}`. Treat every nonzero exit as a failed
deployment step even when automatic rollback succeeds.

## Troubleshooting

| Error | Required action |
|---|---|
| `another WaveMind upgrade is running` | Wait for the recorded PID. Remove no lock while that process is alive. |
| `active writer detected` | Stop the application or worker writing that exact SQLite database, then retry. |
| `WaveMind state is open in another process` | Stop the listed WaveMind/Python process and retry. Docker Desktop itself is not enumerated. |
| `insufficient disk space` | Free the reported number of bytes on the volume containing the upgrade state directory. |
| `checksum mismatch` | Discard the artifact and obtain it again from the named trusted release source. |
| `unsupported` or `newer than supported` schema | Use a compatible WaveMind release; do not edit the migration ledger. |
| `rollback archive checksum does not match the journal` | Preserve the archive and journal for investigation. Do not force activation. |
| `rollback_failed` | Keep the backup, journal, rollback wheel/image, and logs. Fix the reported package/container cause and rerun the identical command so recovery executes first. |

The command currently supports SQLite-backed local Python and Docker Compose
deployments. It does not claim PostgreSQL, Helm, Kubernetes, multi-node, or
remote storage-engine upgrades.
