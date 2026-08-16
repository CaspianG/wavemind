# Changelog

Notable user-facing and operational changes are recorded here. Git tags,
GitHub Releases, checked evidence artifacts, and package versions remain the
authoritative release sources.

## 2.13.0 - Unreleased candidate (prepared 2026-08-16)

- Added the `wavemind upgrade` command for verified one-command Python and
  Docker Compose upgrades, with dry-run and machine-readable output.
- Added exclusive locking, durable journals, checksummed backups, explicit
  core and experience schema ledgers, staged migrations, and logical parity
  checks before activation.
- Added automatic recovery and fail-closed rollback for interrupted installs,
  failed health checks, configuration changes, and container recreation.
- Added exact-SHA admission across Ubuntu and Windows on Python 3.11-3.13,
  real N-2/N-1 package upgrades, and Docker Compose upgrade/rollback evidence.
- Added the operational upgrade guide, including offline artifact verification,
  preflight requirements, rollback behavior, and recovery procedures.

Candidate source: `a23283123eb37b187a755db7ab4c4776555198d8`.
Publication remains blocked until tag `v2.13.0` triggers and verifies GitHub
Release, PyPI, and GHCR.

## [2.12.1] - 2026-08-10

- Added exact-current Workspace Experience admission to the Safe Product
  workflow, producing JSON, Markdown, manifest, and operational evidence
  artifacts for the current source SHA.
- Preserved frozen v5 real-work quality evidence as immutable historical
  quality proof while adding a freshness gate for quality-critical files.
- Added current operational replay evidence for server-side workspace registry,
  namespace authorization, restart persistence, and HTTP cross-client packet
  retrieval.
- Redacted operational benchmark CLI stdout so evidence JSON stays in the
  artifact file without logging secret-bearing payloads.

Release: [WaveMind v2.12.1](https://github.com/CaspianG/wavemind/releases/tag/v2.12.1)

## [2.12.0] - 2026-08-10

- Added Verified Workspace Experience for coding and work agents: stable
  workspace identity, isolated workspace namespaces, provider-neutral event
  capture, cited Experience Packets, and cross-client replay.
- Added human-controlled runbook review with candidate diff, approve, reject,
  edit-and-approve, rollback, protected deletion, provenance, and portable
  checksummed bundles.
- Added exact-source workspace-experience admission with a frozen three-repo
  held-out benchmark, positive task-success lift, context reduction, zero
  workspace leakage, and cross-surface parity checks.
- Hardened the HTTP workspace surface with server-side workspace registry
  resolution, configured base-root containment, symlink escape protection, and
  namespace authorization before workspace data access.
- Added local workspace onboarding commands, diagnostics, and documentation for
  keyless Python, HTTP, MCP, Docker, and TypeScript repository-local flows.

Release: [WaveMind v2.12.0](https://github.com/CaspianG/wavemind/releases/tag/v2.12.0)

## [2.11.0] - 2026-08-09

- Added exact-source Safe Product admission with signed manifests, frozen
  independent retrieval controls, and explicit current-versus-historical
  evidence boundaries.
- Made API, Docker, Kubernetes, operator, and serverless entrypoints safe by
  default, with fail-closed public binding, authenticated identities, and
  tenant/namespace isolation.
- Added durable Core and Verified Experience persistence across container
  recreation, coordinated backup/restore, rollback, and idempotent retry
  verification.
- Added production abstention and adversarial negative controls, recording
  zero false-memory injections across 60 frozen irrelevant queries while
  preserving 1.0 recall@1 on the frozen positive set.
- Added executable Python, MCP, Docker, and repository-local TypeScript
  onboarding, plus Python 3.10-3.13, Windows, container, and CodeQL coverage.

Release: [WaveMind v2.11.0](https://github.com/CaspianG/wavemind/releases/tag/v2.11.0)

## [2.10.0] - 2026-08-03

- Added the Verified Agent Experience Runtime with independent outcome
  verification, evidence-gated promotion, selective cited intervention,
  rollback, and shared Python/HTTP/provider/MCP/TypeScript contracts.
- Added Studio inspection for run timelines, tool outcomes, candidate evidence,
  intervention decisions, conflicts, and rollback controls.
- Added a frozen 150-task, three-domain, five-repeat local admission benchmark
  and a read-only STATE-Bench Agent Learning adapter with official train-split
  protocol validation.
- Kept the failed Goal 4 quality experiment explicit while allowing the living
  leaderboard to publish a valid blocked verdict instead of failing the page
  refresh.

Release: [WaveMind v2.10.0](https://github.com/CaspianG/wavemind/releases/tag/v2.10.0)

## [2.9.0] - 2026-07-30

- Added `wavemind init` starter projects for Python, TypeScript, MCP, and
  Docker, plus `wavemind doctor` runtime and Experience Packet diagnostics.
- Added a strict `memory-safety-admission` gate with 375 attacks, structural
  taint cases, benign controls, tenant isolation, and rollback/provenance proof.
- Completed the TypeScript HTTP memory lifecycle with feedback, explanation,
  forgetting, cancellation, concurrency, and mutation-safe retry behavior.
- Added strict cross-provider integration admission for Python, OpenAI Agents,
  Anthropic, MCP, LangGraph, HTTP, portable bundles, Mem0 imports, and a clean
  packed TypeScript SDK install against a live API.
- Hardened LongMemEval-V2 with official per-question haystacks, isolated A/B
  stores, crash-safe checkpoints, and a blocked public gate when uplift or
  latency evidence is insufficient.
- Added the Experienced Work Agent runtime, which compiles guarded experience
  records into tool plans and learns only from verified trajectories.
- Added a frozen 60/30 coding, support, and enterprise benchmark plus a strict
  12-check quality admission and weekly evidence refresh.

Release: [WaveMind v2.9.0](https://github.com/CaspianG/wavemind/releases/tag/v2.9.0)

## [2.8.0] - 2026-07-28

- Added a durable MCP memory server with remember, recall, feedback, forget,
  inspection, provenance, explanation, and namespace-management operations.
- Added direct Memory OS execution evidence for full LoCoMo, LongMemEval-S,
  and LongMemEval-V2 Small, plus a strict 13/13 agent-memory advantage gate.
- Added paired controlled evidence showing higher task success, zero stale
  errors, and lower p95 retrieval latency for Memory OS on the declared local
  protocol, while retaining explicit public-benchmark limitations.
- Preserved the admitted six-hour Production Memory OS soak and the admitted
  1,000-asset multimodal lifecycle and retrieval evidence.

Release: [WaveMind v2.8.0](https://github.com/CaspianG/wavemind/releases/tag/v2.8.0)

## [2.7.0] - 2026-07-27

- Hardened multimodal admission so descriptor, metadata, and precomputed-vector
  paths cannot be presented as real encoder evidence.
- Improved the public repository entrypoint, documentation navigation, package
  metadata, and benchmark dashboard without changing evidence thresholds.
- Added namespace-bound filesystem and S3-compatible multimodal asset
  lifecycles with checksummed reload, TTL cleanup, physical deletion,
  tombstones, backup/restore, provenance, and orphan cleanup.

Release: [WaveMind v2.7.0](https://github.com/CaspianG/wavemind/releases/tag/v2.7.0)

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
| `v2.13.0` candidate (unpublished) | prepared 2026-08-16 | Verified one-command Python and Docker Compose upgrades with rollback; tag required |
| [v2.12.1](https://github.com/CaspianG/wavemind/releases/tag/v2.12.1) | 2026-08-10 | Exact-current Workspace Experience admission and release evidence |
| [v2.12.0](https://github.com/CaspianG/wavemind/releases/tag/v2.12.0) | 2026-08-10 | Verified Workspace Experience and secure workspace HTTP isolation |
| [v2.11.0](https://github.com/CaspianG/wavemind/releases/tag/v2.11.0) | 2026-08-09 | Safe Trusted Product foundation and secure service runtimes |
| [v2.10.0](https://github.com/CaspianG/wavemind/releases/tag/v2.10.0) | 2026-08-03 | Verified Agent Experience Runtime and honest quality evidence |
| [v2.9.0](https://github.com/CaspianG/wavemind/releases/tag/v2.9.0) | 2026-07-30 | Trusted agent experience, safety, portability, and SDKs |
| [v2.8.0](https://github.com/CaspianG/wavemind/releases/tag/v2.8.0) | 2026-07-28 | Adaptive multimodal agent memory and MCP |
| [v2.7.0](https://github.com/CaspianG/wavemind/releases/tag/v2.7.0) | 2026-07-27 | Multimodal lifecycle and public presentation |
| [v2.6.3](https://github.com/CaspianG/wavemind/releases/tag/v2.6.3) | 2026-07-27 | Production Memory OS release |
| [v2.6.2](https://github.com/CaspianG/wavemind/releases/tag/v2.6.2) | 2026-07-17 | Full release notes and artifacts |
| [v2.6.1](https://github.com/CaspianG/wavemind/releases/tag/v2.6.1) | 2026-07-13 | Full release notes and artifacts |
| [v2.6.0](https://github.com/CaspianG/wavemind/releases/tag/v2.6.0) | 2026-07-13 | Full release notes and artifacts |
| [v2.5.0](https://github.com/CaspianG/wavemind/releases/tag/v2.5.0) | 2026-07-13 | Full release notes and artifacts |

See the complete [release archive](https://github.com/CaspianG/wavemind/releases)
for earlier versions and attached evidence bundles.

[2.12.1]: https://github.com/CaspianG/wavemind/compare/v2.12.0...v2.12.1
[2.12.0]: https://github.com/CaspianG/wavemind/compare/v2.11.0...v2.12.0
[2.11.0]: https://github.com/CaspianG/wavemind/compare/v2.10.0...v2.11.0
[2.10.0]: https://github.com/CaspianG/wavemind/compare/v2.9.0...v2.10.0
[2.9.0]: https://github.com/CaspianG/wavemind/compare/v2.8.0...v2.9.0
[2.8.0]: https://github.com/CaspianG/wavemind/compare/v2.7.0...v2.8.0
[2.7.0]: https://github.com/CaspianG/wavemind/compare/v2.6.3...v2.7.0
[2.6.3]: https://github.com/CaspianG/wavemind/compare/v2.6.2...v2.6.3

