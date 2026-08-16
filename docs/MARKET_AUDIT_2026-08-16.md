# WaveMind Market and Product Audit

**Date:** 2026-08-16  
**Decision horizon:** now, 6, 12, and 18 months  
**Repository reviewed:** `CaspianG/wavemind` through `e7a688b5eaeeb00c34bf740c79e287ee02f25cce`  
**Claim rule:** repository evidence is historical unless an exact-SHA workflow artifact says otherwise.

## Executive decision

WaveMind should not compete as a generic memory store. That surface is already
crowded and easy to copy. Its defensible product is a **verified experience
layer for agents that repeat consequential work**:

> trace -> independent verification -> scoped Experience Packet -> better next
> run -> explainable outcome diff -> rollback

The flagship job is: **stop a coding, support, or operations agent from
repeating a previously verified tool-work mistake without injecting an unsafe
or stale procedure.**

The next P0 is **exact-current, task-native competitive admission**. WaveMind
already demonstrates the product loop in controlled fixtures, but it has not
yet earned a general switching claim. The P0 must compare Core and Verified
Experience with the strongest runnable local alternatives under identical
datasets, prompts, readers, embeddings, token budgets, seeds, and hardware.

The first P0 engineering slice is merged in
[PR #100](https://github.com/CaspianG/wavemind/pull/100): a real LangGraph
`InMemoryStore` adapter with namespace and provenance controls. It is labeled
`LangGraph BaseStore`, not LangMem, because it does not measure memory
formation or prompt optimization.

## Method and evidence boundary

This audit used:

- the current repository, checked artifacts, tests, release workflows, README,
  roadmap, and product site;
- official product documentation and official repositories for competitor
  capabilities and active-project signals;
- current public package state checked on 2026-08-16;
- no estimated revenue, customer count, or market size without primary data.

Public PyPI still reports `wavemind 2.12.1`. Version `2.13.0` is an admitted
source candidate, not a public release, until tag `v2.13.0` exists on
`a23283123eb37b187a755db7ab4c4776555198d8` and the tag-only release workflow
publishes and verifies GitHub Release, PyPI, and GHCR.

## Strategic hypothesis

**Verdict: supported, with medium confidence.**

The market is converging on persistent context, semantic/episodic/procedural
memory, and graph-based retrieval. WaveMind is most differentiated where
memory becomes a governed lifecycle: independent evidence, provenance,
applicability boundaries, correction, forgetting, promotion, explanation, and
rollback. This is valuable when a wrong learned procedure can repeatedly
change code, customer records, or production systems.

The hypothesis is falsified if teams consistently prefer ungoverned memory
because review and verification cost more than repeated mistakes, or if
framework-native stores add equivalent verification, promotion, explanation,
and rollback with lower integration cost.

## Competitor matrix

| Product | Current documented position | Strongest differentiator | Lifecycle and governance | Verifiable adoption signal | WaveMind response |
|---|---|---|---|---|---|
| [Mem0](https://docs.mem0.ai/platform/overview) | Managed and OSS memory with extraction, retrieval, categories, graph/entity features, and platform governance | Low-friction memory formation and managed operations | Platform audit/governance exists; V3 emphasizes ADD-only extraction and multi-signal retrieval | Active official OSS repository plus a managed platform and migration path | Do not imitate generic add/search. Prove safer correction, verified procedure promotion, and rollback. |
| [Zep / Graphiti](https://help.getzep.com/zep-vs-graphiti) | Temporal knowledge graph for agent context; Graphiti is OSS, Zep is the managed Context Lake | Bi-temporal facts, entities, edges, and episodes | Temporal invalidation is structurally strong; managed governance belongs to Zep | Active OSS Graphiti and a separate managed product | Treat temporal truth as a serious baseline. Differentiate on independently verified procedural experience and outcome diffs. |
| [Letta](https://docs.letta.com/guides/core-concepts/memory/memory-blocks) | Stateful agents with always-visible, agent-editable and shareable memory blocks | Agent-managed context and explicit memory hierarchy | Blocks can be read-only/shared; agent self-editing is a core interaction | Active official framework and extensive product documentation | Win when self-editing is too risky: evidence-gated promotion, scope, and rollback before reuse. |
| [LangMem / LangGraph](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/) | Semantic, episodic, and procedural memory with hot-path/background formation, managers, and prompt optimization | Native fit for LangGraph agents and background memory formation | BaseStore provides namespaces; governance depends on application design | Official LangChain project and direct framework distribution | Maintain first-class integration, benchmark the real BaseStore, then add a genuine LangMem formation baseline rather than a renamed imitation. |
| [Cognee](https://github.com/topoteretes/cognee) | Graph/vector ingestion and memory control plane | Data ingestion into a connected graph/vector representation | Shared-memory and feedback concepts are visible; exact governance varies by deployment | Active official OSS repository | Avoid a graph-feature race. Emphasize verified action procedures, deletion/rollback evidence, and compact runtime packets. |
| Framework-native vector/RAG | Embeddings plus local or service vector search | Lowest switching cost and broad ecosystem support | Usually application-defined TTL, correction, provenance, and deletion | Already present in most agent stacks | WaveMind must remain additive: sit above Qdrant, pgvector, FAISS, or Chroma and prove net task value. |

Important caveat: Mem0's platform migration documents entity linking in place of
its earlier platform graph model, while its
[OSS graph documentation](https://docs.mem0.ai/open-source/features/graph-memory)
still describes graph backends. The audit treats platform and OSS capabilities
separately.

## User and JTBD matrix

Ratings are directional (`low`, `medium`, `high`) and represent adoption
propensity, not a price quote.

| Segment | Job to be done | Frequency / severity | Existing solution | Why switch to WaveMind | Switching cost / time to value | Willingness to adopt or pay | Confidence |
|---|---|---|---|---|---|---|---|
| Coding agents | Reuse a verified fix, repository convention, or tool procedure without repeating a failed edit/build/test loop | High / high on active repositories | Context files, chat history, vector memory, framework stores | Cited procedure, repository/environment boundary, measurable next-run diff, rollback | Medium; <5 minutes for demo, days for production instrumentation | High when repeated failures consume developer time or cause unsafe edits | Medium-high |
| Support / CRM agents | Apply the latest verified resolution and policy while suppressing stale customer or policy state | High / high | CRM notes, RAG, vendor memory, playbooks | Corrections, TTL, namespace isolation, human/test verification, auditable deletion | Medium; one workflow and one verifier can pilot in days | High for regulated or high-volume queues; medium elsewhere | Medium |
| Browser / operations agents | Reuse successful navigation, API, or runbook steps without replaying obsolete state | Medium-high / very high for production actions | Runbooks, traces, browser history, workflow engines | Environment-scoped packet, external-state verification, rollback and failure evidence | Medium-high because tools and verifiers must be instrumented | High where a wrong action has operational cost | Medium |
| Agent-platform teams | Give multiple agent runtimes one portable, governed experience contract | Medium / high platform leverage | Custom event stores, LangGraph/LangMem, vendor memory APIs | Local-first source of truth, provider parity, portable packet, policy layer above existing retrieval | High; requires platform integration, but avoids building governance primitives | High if one layer replaces multiple bespoke implementations | Medium |
| Private / regulated workflows | Learn from work while preserving provenance, residency, approval, deletion, and auditability | Medium / very high | Private RAG, case-management systems, manual approval | Local-first operation, namespaces, explicit promotion, deletion and rollback evidence | High; security and legal review dominate | Potentially high, but only after independent security/compliance evidence | Low-medium |

### Beachhead

Start with **coding and support/operations tool workflows that repeat at least
weekly, have an objective verifier, and have a visible cost of repetition**.
These workflows make the loop measurable without requiring WaveMind to replace
the team's model, agent framework, or vector database.

## Current gap map

| Area | Current strength | Gap | User consequence | Required acceptance |
|---|---|---|---|---|
| Verified loop | Trace, external verification, shadow/promotion, Experience Packet, replay and rollback primitives exist | Public proof remains concentrated in controlled fixtures | Buyers cannot infer general workflow lift | Positive paired task result on independent public tasks with frozen splits |
| Competitive proof | Real Mem0 and Hindsight LoCoMo rows exist; LangGraph BaseStore adapter is merged | Existing LoCoMo artifact is historical; no same-SHA LangGraph/strong-current matrix | Switching claim is weaker than product breadth | Exact-SHA artifact with current versions, shared protocol and explicit non-equivalence notes |
| Five-minute value | Starter and runnable verified-experience example exist | The first useful loop is split across README, example, Studio, and evidence pages | A new user may see memory storage before the differentiated product moment | One command/path reaches cold run, verification, packet, replay, diff and rollback in <5 minutes |
| Explanation | Provenance and packet state are inspectable | Success/error/context/cost diff is not the primary user-facing output everywhere | Value is harder to defend to operators and buyers | Stable machine-readable and human-readable before/after diff |
| Governance | Namespace isolation, audit, deletion, backup and rollback are strong | SSO, policy-as-code, independent compliance and deletion proofs are incomplete | Regulated buyers face long review | Independent pilot/security evidence before regulated claims |
| Distribution | Python, HTTP, MCP, TypeScript repository package and provider adapters exist | npm remains unpublished; Connect is not yet a simple opt-in product | Cross-agent setup still costs engineering time | Do not build Connect until competitive task lift is admitted |
| Release truth | Upgrade candidate passed 19/19 exact-SHA admission | `v2.13.0` tag, GitHub Release, PyPI and GHCR publication are missing | Users cannot install the completed upgrade release | Create exact tag, publish, then verify clean wheel and image installs |

## Flagship loop acceptance

The flagship loop is admitted only when one public workflow demonstrates all
of the following on an exact source SHA:

1. a cold run fails or incurs a measurable avoidable cost;
2. the trace records tool calls, environment, outcome, and source identity;
3. a test, operator, or external state independently verifies the outcome;
4. an Experience Packet remains shadowed until its declared evidence threshold;
5. a held-out next run receives a compact cited packet and improves;
6. the report shows paired task success, repeated errors, context tokens, cost,
   and latency;
7. applicability boundaries and provenance are visible;
8. rollback removes the packet's behavioral effect and preserves audit history.

## 0 / 6 / 12 / 18 month forecast

Probabilities are judgmental forecasts, not measured market shares.

| Horizon | Forecast | Probability | Evidence and assumptions | Falsification signal | Confidence |
|---|---|---:|---|---|---|
| Now | Agent teams continue adding memory, but default to framework-native stores unless risk or repeated-work cost is explicit | 80% | Every major competitor offers add/search or native agent memory; switching cost favors incumbents | Teams adopt third-party governance layers without requiring task evidence | High |
| 6 months | Buyers ask for outcome-level proof and lower context cost, not retrieval-only recall | 70% | Agent evaluation is moving toward stateful tasks and workflow outcomes; WaveMind's own failed LongMemEval uplift shows retrieval is insufficient | Procurement and developer discussions remain focused only on vector recall | Medium-high |
| 12 months | Provenance, correction, deletion and policy controls become table stakes for enterprise agent memory | 65% | Managed competitors already expose governance/audit concepts; agent actions raise operational risk | Enterprise products keep opaque self-editing memory without customer demand for controls | Medium |
| 18 months | A portable experience contract across models and agent frameworks becomes valuable, but only if it preserves framework-native ergonomics | 55% | Provider fragmentation creates portability pain; LangGraph/Letta integration gravity remains strong | One framework becomes dominant enough that portability has little value | Medium-low |
| 18 months | Verified procedural experience becomes a distinct category from generic long-term memory | 45% | The trace-to-verified-reuse loop addresses a real governance gap | Native platforms ship equivalent verification, scope, diff and rollback before WaveMind earns pilots | Low-medium |

## Decision matrix

Scores are 1 (weak) to 5 (strong). Cost and risk are reverse-scored: 5 means
low cost or low risk. Weighted score = pain 25%, demand 20%, differentiation
20%, adoption 15%, measurable acceptance 10%, cost 5%, risk 5%.

| Candidate | Pain | Demand | Differentiation | Adoption | Acceptance | Cost | Risk | Weighted / 5 | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Exact-current task-native competitive admission | 5 | 5 | 4 | 4 | 5 | 4 | 4 | **4.55** | **P0 now** |
| Unified five-minute trace-to-packet command | 5 | 4 | 5 | 5 | 5 | 3 | 4 | **4.65** | Flagship UX immediately after proof gate; reuse current primitives |
| Studio Learning Inbox | 4 | 3 | 5 | 4 | 4 | 3 | 3 | **3.90** | Next after a pilot validates review demand |
| Zero-config WaveMind Connect | 3 | 3 | 4 | 4 | 3 | 2 | 2 | **3.25** | Defer until task lift is admitted |
| New modalities, storage engines, Kubernetes, multi-region, or 100M work | 2 | 2 | 1 | 2 | 2 | 1 | 1 | **1.65** | No new work without demand evidence |

The five-minute workflow scores slightly higher as a product surface, but most
of its primitives and demo already exist. The blocking uncertainty is whether
the product improves independent work against credible alternatives. Therefore
competitive admission is the next implementation P0; the unified command is
the next UX slice once that proof exists.

## P0: exact-current competitive admission

### Protocol

- Freeze development, validation, and final splits before tuning.
- Use the same tasks, prompts, reader, embeddings where architecturally
  comparable, token budgets, seeds, hardware profile, and top-k.
- Compare WaveMind Core, WaveMind Verified Experience, static Chroma/Qdrant,
  current Mem0 OSS, and real LangGraph BaseStore. Add LangMem formation only
  when its native workflow is implemented; never rename BaseStore as LangMem.
- Record package versions, source revisions, dataset hashes, inputs, per-case
  outputs, environment, latency, context and cost.
- Keep proprietary services as explicit `skipped`, never silently simulated.

### Admission

1. exact source SHA and source manifest match the tested tree;
2. every mandatory baseline completed with no imitation;
3. positive paired lift has a lower 95% confidence bound above zero on one
   task/workflow family;
4. lifecycle safety is non-inferior for stale, corrected, forgotten, and
   cross-namespace cases;
5. WaveMind is on the Pareto frontier and beats the strongest fully comparable
   local baseline on at least two of quality, context/cost, and latency while
   staying inside the third-axis budget;
6. failures and blocked rows remain public;
7. the final split remains unopened until the development gate passes.

## Public roadmap

| Horizon | Outcome | Release boundary |
|---|---|---|
| 0 months | Publish and verify `v2.13.0`; complete exact-current LangGraph and Mem0 competitive artifacts | Tag, PyPI, GHCR and clean-install verification; no false public-release row |
| 0-6 months | Admit one independent task-native flagship loop; unify the five-minute cold-run -> packet -> replay -> diff -> rollback path | Positive paired lift, safety non-inferiority, Pareto gate, exact-SHA evidence |
| 6-12 months | Run design-partner pilots; build Studio Learning Inbox only if review/rollback usage is observed | Pilot retention, repeated-work savings, operator review and rollback evidence |
| 12-18 months | Add policy-as-code and portable cross-client experience only after pilots validate demand | Zero namespace leakage, deletion proof, provider parity and measurable workflow benefit |

## Explicit no-go list

- No generic “best memory”, “SOTA”, or universal leadership claim.
- No new modality, storage engine, Kubernetes, multi-region, serverless, or
  100M initiative without a user-backed decision record.
- No hidden failed benchmark, weakened threshold, or repeated final-split
  tuning.
- No WaveMind Connect expansion before a generalizable task-value gate.
- No claim that a BaseStore retrieval baseline measures LangMem formation.

## Sources

- [WaveMind repository](https://github.com/CaspianG/wavemind)
- [Mem0 Platform overview](https://docs.mem0.ai/platform/overview)
- [Mem0 V2 to V3 migration](https://docs.mem0.ai/migration/platform-v2-to-v3)
- [Mem0 OSS graph memory](https://docs.mem0.ai/open-source/features/graph-memory)
- [Zep vs Graphiti](https://help.getzep.com/zep-vs-graphiti)
- [Graphiti overview](https://help.getzep.com/graph-overview)
- [Letta memory blocks](https://docs.letta.com/guides/core-concepts/memory/memory-blocks)
- [Letta context hierarchy](https://docs.letta.com/guides/core-concepts/memory/context-hierarchy)
- [LangMem conceptual guide](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/)
- [LangGraph persistence and BaseStore](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Cognee official repository](https://github.com/topoteretes/cognee)

## Limitations

This is a product decision report, not a market-size study. It does not claim
verified competitor customer counts, revenue, hosted throughput, or answer
quality. The checked LoCoMo comparison is retrieval-only and uses non-equivalent
native embedding/ingest paths for some systems. Current public package and
release state can change after the report date.

