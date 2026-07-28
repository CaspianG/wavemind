# WaveMind Documentation

Use this page as the map from first recall to production evidence. Start with
the smallest path that solves your problem; move into scale, operations, and
benchmarks only when the deployment requires them.

## Start Here

| Goal | Guide |
|---|---|
| Install and recall the first memory | [Quick Start](../README.md#quick-start) |
| See the product UI | [WaveMind Studio](../README.md#wavemind-studio) |
| Embed WaveMind in Python or HTTP | [Examples in the README](../README.md#python-example) |
| Choose a real application pattern | [Use Cases](USE_CASES.md) |
| Migrate local Chroma memory | [Chroma Migration](CHROMA_MIGRATION.md) |

## Build With WaveMind

| Area | Guide |
|---|---|
| LangChain, LangGraph, LlamaIndex, CrewAI, AutoGen, and custom loops | [Framework Integrations](INTEGRATIONS.md) |
| Connect any MCP-compatible agent | [MCP Integration](MCP.md) |
| Hash, sentence-transformer, FAISS, pgvector, Qdrant, Annoy, and quantized indexes | [Embeddings And Index Backends](INDEX_BACKENDS.md) |
| Structured payloads, multimodal contracts, storage, backup, and HTTP API | [Multimodal, Storage, And API](MULTIMODAL_AND_STORAGE.md) |
| Metrics, traces, dashboards, and alerts | [Observability](OBSERVABILITY.md) |

## Operate And Scale

| Area | Guide |
|---|---|
| Scale plans, replication, Kubernetes, Redis, Memory OS, and production gates | [Scale And Production](SCALE_AND_PRODUCTION.md) |
| Current limits and locked claims | [Known Limitations And Claim Boundaries](KNOWN_LIMITATIONS.md) |
| Release validation and publishing | [Release Process](RELEASE.md) |
| Security reporting and supported use | [Security](../SECURITY.md) / [Support](../SUPPORT.md) |

## Evidence

| Evidence | Guide |
|---|---|
| Current methods, artifacts, and interpretation rules | [Benchmark Guide](BENCHMARKS.md) |
| Short public methodology | [Benchmark Brief](BENCHMARK_BRIEF.md) |
| Adaptive agent-memory admission | [13/13 Admission Report](../benchmarks/AGENT_MEMORY_ADVANTAGE_ADMISSION.md) |
| Live checked-in status | [Living Benchmark Dashboard](https://caspiang.github.io/wavemind/) |
| Release history | [Changelog](../CHANGELOG.md) |

Public claims must trace to checked JSON artifacts. Local, loopback, planned,
and production evidence remain separate on purpose.

## Direction And Contribution

| Area | Guide |
|---|---|
| Product direction and evidence gates | [Roadmap](ROADMAP.md) |
| Launch positioning and claim boundaries | [Launch Kit](LAUNCH_KIT.md) |
| Development workflow | [Contributing](../CONTRIBUTING.md) |
| Community expectations | [Code Of Conduct](../CODE_OF_CONDUCT.md) |

The root [README](../README.md) remains the product entrypoint. This page is the
navigation layer for readers who need more depth.
