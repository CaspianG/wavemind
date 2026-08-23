# ADR 0002: Proof-Carrying Causal Memory

Status: preregistered; not admitted

## Decision

WaveField, the existing associative graph, Memory OS, vector retrieval, and the
current combined pipeline remain unchanged as baselines at
`c30205ed389057bc695488655a3f8650ba8e5277`. The scientific core is a separate
candidate path and cannot replace the public architecture until frozen
admission passes.

The source of truth is a typed, append-only event stream. Folding that stream
produces memory state at sequence `t`:

`S_t = fold(E_1, ..., E_t)`.

Every event contains its predecessor digest. Memory values are typed as facts,
state transitions, procedures, constraints, or failed strategies. Each value
declares preconditions, effects, applicability, a validity interval,
provenance, token cost, latency cost, and safety risk. Promotion, demotion,
revocation, and rollback are explicit events rather than silent mutations.

## Proof-Carrying Experience

Using memory produces an influence receipt before the outcome is known. A
receipt binds the task and case, attributed memory IDs, context digest, action
digest, and optional safe-canary arm. A receipt changes production utility only
when a test, tool, environment, or operator verifier supplies immutable
evidence and paired treatment/control outcomes. Agent self-assessment is
recorded as rejected verification and carries zero production influence.

Falsified experience contributes non-positive evidence. A false verified
promotion blocks promotion. Counterevidence can demote or revoke a memory, and
rollback remains visible in the hash-chained event stream.

## Causal utility candidate

For memory `m`, each independently verified paired replay yields

`d_i(m) = attribution_i(m) * (outcome_with_memory_i - outcome_without_memory_i)`.

The controller uses a paired cluster bootstrap, clustered by official case ID,
to estimate the mean treatment effect and its frozen 95% confidence interval.
Production promotion requires at least three verified pairs,
`LCB95(d(m)) > 0`, and zero false verified promotions. Forgetting requires
`UCB95(d(m)) < 0`; time decay alone is not causal forgetting. If positive
utility is unproven, the controller abstains.

Selection maximizes positive risk-adjusted lower-bound utility while enforcing
applicability, validity, token, latency, and safety constraints. The returned
set is minimal in the sense that no memory with non-positive incremental
risk-adjusted lower-bound utility is included.

## Evidence-constrained graph candidate

For binary selection variables `x_i`, the frozen energy is:

`E(x) = sum_i x_i[-r_i - 0.20 log(1+e_i) + 0.50 c_i - 1.00 l_i + 0.25 w_i] - 0.10 sum_ij a_ij x_i x_j + 0.50 sum_ij k_ij x_i x_j`.

Here `r` is relevance, `e` independent evidence count, `c` counterevidence
count, `l` the causal utility lower bound, `w` confidence-interval width, `a`
positive association, and `k` conflict. Eligibility requires evidence,
positive causal lower bound, and no counterevidence. The exact minimum-energy
subset under the token budget is selected; non-negative best energy means
abstention.

The optional hybrid only applies this graph to memories already promoted by
the causal controller. It adds no tunable parameter after preregistration.

## Evaluation contract

The machine-readable contract is
`benchmarks/scientific_memory_protocol_v1.json`. It freezes baselines,
candidates, equations, official benchmark families, common model/prompt/
embedding/seed/token/hardware controls, ablations, thresholds, three-run
reproducibility, raw-row retention, and a single allowed full LongMemEval-V2
run after the development gate.

Development and validation may be bounded. Held-out cases cannot be used for
tuning. Mem0 OSS, LangGraph, Chroma, and Qdrant rows must execute the real local
packages and record exact versions; local imitations are invalid.

If no preregistered candidate passes every gate, the terminal result is
`failed_experiment`. Thresholds are not relaxed, negative rows remain public,
and the architecture is not described as revolutionary or state of the art.
