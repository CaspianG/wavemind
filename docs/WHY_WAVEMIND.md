# Why WaveMind

## The One-Minute Explanation

Most agent memory systems save conversation fragments and retrieve similar
text later. That helps an agent remember, but it does not tell the agent
whether a past action was correct, whether the environment has changed, or
whether the same procedure is safe here.

WaveMind adds a trust lifecycle around memory:

1. Capture what the agent did and the conditions around it.
2. Let a test, tool, operator, or downstream system verify the outcome.
3. Keep the candidate procedure in shadow until the required evidence exists.
4. Reuse it as a compact, cited Experience Packet only inside its valid scope.
5. Preserve corrections, supersession, deletion, and rollback.

In short, WaveMind turns **completed work into governed experience**. It helps
an agent improve without treating its own confident output as proof.

## Why This Is Different

The important distinction is not another embedding model or vector database.
It is the unit that crosses from one run to the next.

| Typical retained context | WaveMind Experience Packet |
|---|---|
| A fragment that happened before | A procedure tied to a verified outcome |
| Similarity is the main retrieval signal | Scope, freshness, conflict, and evidence govern reuse |
| The source may be hidden in a long transcript | Provenance and citations travel with the advice |
| Corrections accumulate beside old instructions | Supersession and conflict handling are explicit |
| Removing learned behavior is ad hoc | Inspection, deletion, and rollback are part of the lifecycle |

Vector indexes still do what they are good at: finding candidates. WaveMind
governs what becomes durable memory, what is eligible for reuse, and when the
system should abstain.

## A Concrete Example

Imagine an agent that repeatedly exports records from an API. On its first
attempt it forgets a pagination cursor and silently returns an incomplete file.

- The failed result is preserved, not learned as a successful recipe.
- A later run uses the cursor and an independent row-count check verifies the
  complete export.
- Repeated verified outcomes promote a procedure scoped to that API and
  environment.
- The next agent receives the cursor rule together with its evidence and scope.
- If the API changes, the procedure can be superseded or rolled back without
  erasing the audit trail.

The runnable local version is
[`examples/verified_experience_runtime.py`](../examples/verified_experience_runtime.py).

## What Version 2.14 Adds

WaveMind 2.14 joins the product lifecycle to a proof-carrying scientific memory
core:

- typed memory definitions instead of loosely interpreted records;
- deterministic reconciliation when evidence conflicts or arrives in a
  different order;
- provenance and applicability boundaries that remain attached to memory;
- frozen protocols, execution receipts, integrity manifests, and preserved
  failed outcomes;
- bounded exact-selection adapters whose optimized result can be checked
  against a reference selector.

This matters because faster retrieval is not useful if an optimization quietly
changes which memory is selected. The v32 disk-backed performance validation
matched the reference selector on all 240 frozen synthetic queries in each of
three repeats. Its indexed p95 was `0.151-0.156 s`, a `9.72-10.09x` p95 speedup
on that declared workload.

## What The Evidence Proves

| Question | Current evidence | Boundary |
|---|---|---|
| Can verified experience improve the next run in the frozen runtime slice? | Success rose from `20%` to `100%`, repeated errors fell by `100%`, and context fell by `39.2%` across 150 stateful tasks. | Controlled local coding, support, and operations scenarios; not universal task uplift. |
| Does the safety gate contain hostile memory input? | 375 attacks were contained with zero cross-namespace leakage and 100% benign acceptance. | The frozen attack suite, not every possible attack. |
| Can the v32 selector preserve exact behavior while accelerating selection? | 240/240 exact matches across three repeats with `9.72-10.09x` p95 speedup. | Performance-only, disk-backed synthetic protocol. |
| Did the official v31 LongMemEval experiment prove quality uplift? | No. The admission failed and the failed outcome remains published. | No generalized LongMemEval quality claim is made. |

Primary artifacts:

- [Verified Experience admission](../benchmarks/VERIFIED_EXPERIENCE_ADMISSION.md)
- [Memory safety admission](../benchmarks/MEMORY_SAFETY_ADMISSION.md)
- [v32 selector validation](../benchmarks/scientific_performance_v32_validation_results.json)
- [v31 failed scientific admission](../benchmarks/scientific_v31_admission_outcome.json)
- [Known limitations and locked claims](KNOWN_LIMITATIONS.md)

## What WaveMind Does Not Claim

WaveMind does not claim that:

- a model's self-evaluation is independent verification;
- one frozen benchmark proves universal agent improvement;
- the v32 performance result proves LongMemEval quality uplift;
- WaveMind should replace every vector database;
- remote multi-region, managed-serverless, or 100M-scale operation is admitted
  without the required external evidence.

Failed and blocked outcomes are part of the public record. They are not hidden
or relabeled as wins.

## Where To Start

To see the differentiated product loop locally:

```sh
python -m pip install wavemind
python examples/verified_experience_runtime.py
```

For a generated starter:

```sh
wavemind init my-agent --template python
cd my-agent
python app.py
```

Then choose the next path:

- [Verified Experience Runtime](VERIFIED_EXPERIENCE_RUNTIME.md) for lifecycle
  and integration details;
- [Quick Start](../README.md#quick-start) for basic memory operations;
- [Documentation map](README.md) for deployment and framework guides;
- [Benchmark directory map](../benchmarks/README.md) for evidence provenance;
- [Repository guide](REPOSITORY_GUIDE.md) for contributors.
