# Changelog

Notable user-facing and operational changes are recorded here. Git tags,
GitHub Releases, checked evidence artifacts, and package versions remain the
authoritative release sources.

## Unreleased

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
| [v2.8.0](https://github.com/CaspianG/wavemind/releases/tag/v2.8.0) | 2026-07-28 | Adaptive multimodal agent memory and MCP |
| [v2.7.0](https://github.com/CaspianG/wavemind/releases/tag/v2.7.0) | 2026-07-27 | Multimodal lifecycle and public presentation |
| [v2.6.3](https://github.com/CaspianG/wavemind/releases/tag/v2.6.3) | 2026-07-27 | Production Memory OS release |
| [v2.6.2](https://github.com/CaspianG/wavemind/releases/tag/v2.6.2) | 2026-07-17 | Full release notes and artifacts |
| [v2.6.1](https://github.com/CaspianG/wavemind/releases/tag/v2.6.1) | 2026-07-13 | Full release notes and artifacts |
| [v2.6.0](https://github.com/CaspianG/wavemind/releases/tag/v2.6.0) | 2026-07-13 | Full release notes and artifacts |
| [v2.5.0](https://github.com/CaspianG/wavemind/releases/tag/v2.5.0) | 2026-07-13 | Full release notes and artifacts |

See the complete [release archive](https://github.com/CaspianG/wavemind/releases)
for earlier versions and attached evidence bundles.

[2.8.0]: https://github.com/CaspianG/wavemind/compare/v2.7.0...v2.8.0
[2.7.0]: https://github.com/CaspianG/wavemind/compare/v2.6.3...v2.7.0
[2.6.3]: https://github.com/CaspianG/wavemind/compare/v2.6.2...v2.6.3
