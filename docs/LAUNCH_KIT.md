# WaveMind Launch Kit

This is the canonical public-message kit. It keeps the explanation, proof, and
claim boundaries consistent across GitHub, the product site, demos, and posts.

<!-- product-status:start -->
> WaveMind is the trust layer that lets agents learn from completed work without silently learning incorrect behavior.
>
> Canonical machine status: `docs/data/product-status.json`.

| Product truth | Status | Evidence |
|---|---|---|
| Public release | `v2.14.0`; runtime source `e93954d40285` | PyPI package `wavemind` and `ghcr.io/caspiang/wavemind:2.14.0` |
| Current release | `v2.14.0` at `e93954d40285`; `published` | Upgrade admission `admitted_19_of_19`; GitHub Release, PyPI, and GHCR verified |
| Safe Product snapshot | `historical`, 18/18 checks at `92c539d0a069` | [`benchmarks/safe_product_admission_results.json`](../benchmarks/safe_product_admission_results.json) |
| Current-source admission | Required per exact source SHA | [`.github/workflows/safe-product.yml`](../.github/workflows/safe-product.yml) |
| TypeScript SDK | `@wavemind/http`, repository-local; npm claim disabled | Repository package only |

> Only an admitted exact-SHA workflow artifact may describe the current source as admitted.
<!-- product-status:end -->

## Positioning

### Category

Verified experience infrastructure for AI agents.

### One Sentence

WaveMind lets agents learn from independently verified work through compact,
cited Experience Packets with scope, correction, and rollback.

### Plain-Language Explanation

Most agent memory saves what the agent saw. WaveMind carries forward what
independent evidence says worked. A test, tool, operator, or downstream system
verifies the outcome before a procedure can be promoted. The next run gets the
useful procedure with its source and boundaries, not a dump of old context.

### The Breakthrough

The shift is from **memory as accumulated context** to **memory as governed,
proof-carrying experience**.

```text
trace -> independent verification -> shadow candidate
      -> cited Experience Packet -> better next run
      -> explainable diff -> correction or rollback
```

This is not a claim that a model can verify itself. Verification must come from
outside the generating model: tests, tool state, operators, or downstream
effects.

## Message Hierarchy

Use these points in this order:

1. Agents repeat costly tool-work mistakes because raw context does not prove
   what worked.
2. WaveMind verifies outcomes before promoting reusable experience.
3. Every packet carries provenance, scope, corrections, and rollback.
4. The product is local-first and works across Python, HTTP, MCP, TypeScript,
   and common agent frameworks.
5. Public claims are tied to checked artifacts, including failed experiments.

Adaptive recall, TTL, hotness, graph signals, and vector backends are important
capabilities, but they support the verified-experience story rather than replace
it.

## Proof Points

| Proof | Result | Boundary |
|---|---|---|
| Verified Experience Runtime | Success `20% -> 100%`, repeated errors `-100%`, context `-39.2%` | Frozen local 150-task, three-domain slice |
| Memory safety | 375 attacks contained; zero cross-namespace leakage; benign acceptance `100%` | Frozen attack suite |
| v32 exact selector | 240/240 exact matches across three repeats; p95 speedup `9.72-10.09x` | Disk-backed synthetic, performance-only protocol |
| v31 LongMemEval | Failed quality admission remains published | No generalized quality-uplift claim |
| Distribution | PyPI, GitHub Release, and public GHCR image verified for `v2.14.0` | Release source `e93954d40285` |

Evidence links:

- [Why WaveMind](WHY_WAVEMIND.md)
- Public methodology and launch evidence: `docs/BENCHMARK_BRIEF.md`
- [Verified Experience admission](../benchmarks/VERIFIED_EXPERIENCE_ADMISSION.md)
- [Memory safety admission](../benchmarks/MEMORY_SAFETY_ADMISSION.md)
- [v32 selector validation](../benchmarks/scientific_performance_v32_validation_results.json)
- [v31 failed scientific admission](../benchmarks/scientific_v31_admission_outcome.json)
- [Known limitations](KNOWN_LIMITATIONS.md)

## What To Say Clearly

- WaveMind complements vector indexes; it governs memory and experience around
  candidate retrieval.
- Independently verified outcomes, not model confidence, control promotion.
- An admitted result applies only to its declared protocol, source, and scope.
- Failed and blocked experiments remain visible.
- SQLite is the default local source of truth; production integrations are
  optional and explicitly configured.

## What Not To Claim

- Do not claim universal agent improvement or human-level memory.
- Do not describe the v32 selector result as LongMemEval quality evidence.
- Do not describe a historical artifact as proof for the current source SHA.
- Do not claim remote multi-region, managed-serverless, or 100M-scale admission
  without the required external evidence.
- Do not claim that WaveMind replaces Chroma, Qdrant, pgvector, or every vector
  database.
- Do not describe a model's self-score as independent verification.

## Audience Versions

### Developer

WaveMind stops an agent from blindly relearning the same tool workflow. It
captures a trace, accepts an independent outcome, promotes a procedure only
after evidence, and returns a cited packet on the next run. Start with:

```sh
python -m pip install wavemind
python examples/verified_experience_runtime.py
```

### Platform Team

WaveMind provides one provider-neutral contract for capture, verification,
promotion, selective injection, audit, correction, deletion, and rollback
across Python, HTTP, MCP, TypeScript, and agent frameworks.

### Operator Or Risk Owner

WaveMind keeps learned procedures inspectable and reversible. It records who or
what verified an outcome, where the procedure applies, what superseded it, and
how it was removed or rolled back.

### Investor Or Design Partner

WaveMind is an open-source experience-governance layer between raw context and
agent action. The wedge is repeated consequential tool work where a verified
procedure can improve the next run without creating opaque, irreversible
behavior.

## Ready-To-Use Copy

### GitHub Description

Verified experience for AI agents: independently checked, scoped, cited, and
reversible.

### Show HN Title

Show HN: WaveMind – agents learn from verified work, not raw history

### Short Launch Post

I built WaveMind because agent memory usually preserves what happened, not what
was proven to work.

WaveMind captures tool work, waits for an independent test, operator, tool, or
downstream state to verify the outcome, and promotes only a bounded procedure.
The next run receives a compact Experience Packet with provenance, scope,
corrections, and rollback.

The v2.14 release also adds a proof-carrying scientific memory core and frozen
experimental records. The v32 selector matched the reference on 240/240 frozen
synthetic queries across three repeats with a `9.72-10.09x` p95 speedup. The
official v31 LongMemEval quality experiment failed, and that result remains
public; v32 is performance evidence only.

```sh
python -m pip install wavemind
python examples/verified_experience_runtime.py
```

Repository: https://github.com/CaspianG/wavemind

### 30-Second Spoken Version

> Ordinary agent memory saves similar text. WaveMind saves verified experience.
> It waits for an independent outcome, promotes only a scoped procedure, and
> gives the next run a cited packet with a rollback path. That lets an agent
> improve from completed work without quietly turning its own mistakes into
> rules.

## Objection Handling

### Is This Just A Vector Database?

No. A vector index can find candidates. WaveMind governs whether a memory or
procedure is eligible for reuse, including evidence, scope, corrections,
freshness, namespace isolation, deletion, and rollback.

### Does The Agent Verify Itself?

No. A candidate can be recorded from the agent trace, but promotion requires an
independent verifier such as a test, tool result, operator, or downstream state.

### Does The Benchmark Prove General Intelligence?

No. Each result applies to the named frozen workload. The repository publishes
claim boundaries and failed outcomes precisely to prevent that extrapolation.

### Is It Production Ready?

The local-first core, public package, container, API, safety controls, and
upgrade path have automated evidence. Remote multi-region, managed-serverless,
and 100M service claims remain gated until external evidence exists.

Additional offline examples remain available at
`examples/customer_support_memory.py` and
`examples/research_notebook_memory.py`.

## Publication Checklist

Before publishing or updating public copy:

1. Confirm the latest release and source SHA.
2. Run `python scripts/sync_product_status.py --check`.
3. Link every number to its exact JSON or admission report.
4. State whether evidence is local, synthetic, remote, historical, or current.
5. Keep failed and blocked outcomes in view.
6. Test the install and differentiated demo from a clean environment.
7. Confirm the required GitHub check and security scans are green.

For Russian copy, use [RU Launch Posts](RU_LAUNCH_POSTS.md). For the runnable
walkthrough, use [Demo Script](DEMO_SCRIPT.md).
