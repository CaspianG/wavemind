# ADR 0001: Task-Native Evaluation Science

Status: accepted for implementation

Baseline source: `25e501b79b8210226bd577c926fc761db9936cc1`

## Context

WaveMind's previous quality recovery lane stopped after two bounded development
candidates failed. That lane also exposed a measurement defect: generative and
long-range tasks from MemoryAgentBench had been converted into literal evidence
retrieval labels. Twenty non-literal questions, including the complete
Long-Range Understanding category, were filtered while a universal category
gate still expected four improved categories. The result could not establish
generalization, and the unopened held-out split remains unopened.

The failure is preserved as historical evidence. It is not a license to weaken
quality thresholds or to tune on the failed rows.

## Decision

Evaluation is split into five independent layers:

1. lifecycle correctness: remember, update, forget, reflect, scope, provenance,
   and current state;
2. retrieval and evidence: relevant evidence, stale and contradictory evidence,
   forbidden evidence, and abstention;
3. answer quality: a pinned reader evaluated with the task's native scorer;
4. agent and workflow outcome: executable final state, repeated errors, tool
   calls, and stability across runs;
5. efficiency and safety: latency, context, cost proxy, storage, isolation,
   deletion, false-memory behavior, and provenance.

These layers are never collapsed into one synthetic accuracy. Each task family
declares primary and secondary metrics before a product run. Aggregate claims
use a preregistered Pareto analysis and non-inferiority margins.

The evaluation pipeline has separate versioned contracts for:

- dataset manifest;
- immutable protocol;
- task adapter;
- memory backend adapter;
- reader;
- scorer;
- run identity and environment;
- per-case evidence;
- aggregate report and admission.

Every run identity includes source SHA, evaluator version, dataset revision and
checksum, model and embedding revision, prompt hash, seed, and environment
fingerprint. Raw case outputs are uploaded as checksummed CI artifacts. Git
stores compact manifests, summaries, validators, and test fixtures only.

The memory backend receives an allowlisted query view. Gold answers, gold
evidence, task type, case identifiers, evaluator metadata, split labels, and
expected outcomes are not backend inputs.

## Native Scoring Rules

- MemoryAgentBench categories keep their published task semantics. Long-range
  or generated-answer rows are not converted into retrieval labels.
- LongMemEval evidence retrieval is measured only where gold evidence exists.
  Abstention rows remain in answer and safety evaluation.
- LongMemEval-V2 uses its memory-backend interface and native overall, static,
  dynamic, procedure, gotcha, latency, and LAFS views. A local open-weight run is
  labelled official-compatible, not an official leaderboard result.
- STATE-Bench Agent Learning uses executable final-state assertions, pass@1,
  pass^5, tool/turn/token measures, and a pinned judge only where native.
- MemOps measures operation-level remember, update, forget, reflect, composed
  transitions, target, scope, provenance, stale leakage, over-forgetting, and
  unsupported inference.

## Admission Order

Product behavior cannot be tuned until `evaluation-validity-admission` is
admitted. Validity must prove provenance, disjoint splits, native metrics,
positive and negative controls, expected control ordering, usable metric range,
power and MDE, paired clustered statistics, correction policy, judge
calibration, deterministic fingerprints, complete per-case evidence, backend
blinding, exact-SHA integrity, and preservation of Safe Product and Workspace
Experience admissions.

After validity admission, development data may be used for bounded hypotheses.
Validation and final rows remain unavailable for error analysis or parameter
selection. A heavy or GPU run requires a passed development gate and explicit
user permission.

## Consequences

This design produces a slower but defensible path to a quality claim. A task
that cannot pass validity is excluded from the claim with a recorded reason.
Synthetic controls can validate the evaluator, but cannot prove general model
quality. Historical failures remain visible and future public claims must map
to fresh exact-main artifacts.
