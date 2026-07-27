# Changelog

Notable user-facing and operational changes are recorded here. Git tags,
GitHub Releases, checked evidence artifacts, and package versions remain the
authoritative release sources.

## Unreleased

- Hardened multimodal admission so descriptor, metadata, and precomputed-vector
  paths cannot be presented as real encoder evidence.
- Improved the public repository entrypoint, documentation navigation, package
  metadata, and benchmark dashboard without changing evidence thresholds.
- Added namespace-bound filesystem and S3-compatible multimodal asset
  lifecycles with checksummed reload, TTL cleanup, physical deletion,
  tombstones, backup/restore, provenance, and orphan cleanup.

## [2.6.3] - 2026-07-27

- Shipped the SQLite concurrency fix used by background Memory OS workers.
- Recorded verified remote Redis/worker soak evidence and preserved the
  admitted Production Memory OS gate.
- Hardened hot and cold latency sampling, transient DNS retry handling,
  Kubernetes evidence validation, and agent-impact baselines.
- Added the aggregate `required / full-check` CI status.
- Added Code of Conduct, pull request template, Dependabot configuration, and
  focused technical guides.

Release: [WaveMind v2.6.3](https://github.com/CaspianG/wavemind/releases/tag/v2.6.3)

## Recent Releases

| Version | Published | Notes |
|---|---|---|
| [v2.6.2](https://github.com/CaspianG/wavemind/releases/tag/v2.6.2) | 2026-07-17 | Full release notes and artifacts |
| [v2.6.1](https://github.com/CaspianG/wavemind/releases/tag/v2.6.1) | 2026-07-13 | Full release notes and artifacts |
| [v2.6.0](https://github.com/CaspianG/wavemind/releases/tag/v2.6.0) | 2026-07-13 | Full release notes and artifacts |
| [v2.5.0](https://github.com/CaspianG/wavemind/releases/tag/v2.5.0) | 2026-07-13 | Full release notes and artifacts |

See the complete [release archive](https://github.com/CaspianG/wavemind/releases)
for earlier versions and attached evidence bundles.

[2.6.3]: https://github.com/CaspianG/wavemind/compare/v2.6.2...v2.6.3
