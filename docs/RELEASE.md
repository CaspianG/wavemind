# Release Process

WaveMind uses Git tags for releases.

## Checklist

1. Make sure `main` is green in GitHub Actions.
2. Update the version in `pyproject.toml`, `wavemind/__init__.py`,
   `deploy/helm/wavemind/Chart.yaml`, `deploy/helm/wavemind/values.yaml`,
   `docker-compose.yml`, `deploy/remote/inventory.example.json`,
   `deploy/serverless/wavemind-serverless.sample.json`, and
   `deploy/cloud/gcp-remote-active-active/terraform.tfvars.example`.
3. Run local checks:

```sh
pytest -q
python -m build
python -m twine check dist/*
wavemind release-claims --write-artifacts --fail-on-blocked
wavemind scale-gap --write-artifacts
wavemind production-admission --target-memories 100000000 --engine qdrant-sharded-service --allow-plan-only --write-artifacts
```

On Windows PowerShell:

```powershell
pytest -q
python -m build
python -m twine check dist\*
wavemind release-claims --write-artifacts --fail-on-blocked
wavemind scale-gap --write-artifacts
wavemind production-admission --target-memories 100000000 --engine qdrant-sharded-service --allow-plan-only --write-artifacts
```

4. Commit the version bump.
5. Confirm release notes categories and labels:

```sh
git diff -- .github/release.yml .github/labels.yml
```

6. Create and push a tag:

```sh
git tag vX.Y.Z
git push origin main --tags
```

## Automation

- `.github/workflows/release.yml` creates a GitHub Release and uploads built
  artifacts for tags that match `v*`. It verifies that the tag matches the
  package version and uploads the release claims manifest and production
  evidence bundle.
- `.github/release.yml` groups generated release notes into production,
  indexing, integrations, and documentation sections.
- `.github/workflows/publish.yml` independently verifies the tag, benchmark
  freshness, production readiness, and release claims before publishing to
  PyPI through trusted publishing. It has one trigger, the release tag push,
  so a GitHub Release event cannot start a duplicate upload.

## Cadence

- Publish one release for a coherent user-facing change set, not one release
  per commit.
- Use a minor version for backward-compatible features and a patch version for
  focused fixes to already released behavior.
- Keep published tags and PyPI versions immutable. Correct mistakes with a new
  version instead of deleting release history.
- Prefer release notes that explain user impact, migration concerns, evidence,
  and known limits over a raw commit list.

## Rules

- Do not publish a release with failing tests.
- Do not publish a release when `wavemind release-claims --fail-on-blocked`
  reports `release_blocked`.
- Do not claim 10M/50M/100M production scale unless
  `wavemind scale-gap --fail-on-action-required` passes or the release notes
  explicitly say the remaining rows are plan-only.
- Do not route production traffic to a named large-N deployment unless
  `wavemind production-admission --target-memories ... --engine ... --fail-on-blocked`
  admits that exact target/engine pair.
- Do not add benchmark claims to release notes unless the result JSON is
  committed under `benchmarks/`.
- If the release changes public benchmark numbers, update README and
  `benchmarks/BENCHMARK_REPORT.md` before tagging.
- `core_release_ready` is acceptable for a library release: it means core
  readiness and artifact audit pass, while strict remote/large-N production
  claims remain locked. `full_production_claims_ready` is required only when
  release notes claim strict remote, managed-serverless, 50M, or 100M
  production scale.
