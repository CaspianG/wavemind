# Prior art and candidate selection, 2026-09-06

Status: targeted primary-source review, NOT an exhaustive novelty clearance.
Absence from these searches does not establish novelty. Papers' reported
results are their claims, not independently reproduced results of this project.
Patent documents are technical prior art here; no legal or freedom-to-operate
conclusion is made.

Search families: verified/causal/lifecycle agent memory; meta-learned memory;
Hamiltonian identifiability and Bayesian experimental design; amortized design;
quantum predictive memory; neural quantum error decoding; memory verification
and Hamiltonian-learning patents. Searches included 2026 publications and
backward references to mechanism foundations. URLs below were searched/opened;
access depth and gaps are explicit.

## Checkable novelty map

| Source and access | Already known | Consequence for our claim |
|---|---|---|
| [MemoryLACE, 2609.03201v1](https://arxiv.org/html/2609.03201v1), full HTML, Sep 2026 | Sparse supersession/contradiction/merge links, provenance and relation-aware evidence retrieval | Lifecycle plus provenance is not a new scientific mechanism. Its benchmarks include BEAM and StructMemEval. |
| [ALMA, 2602.07755v1](https://arxiv.org/html/2602.07755v1), full HTML; [official code](https://github.com/zksha/alma) | Searches executable memory designs and evaluates sequential tasks | An agent discovering memory architectures is already an active research method. |
| [MemAudit, 2605.23723](https://arxiv.org/abs/2605.23723), abstract | Counterfactual influence plus structural memory auditing | Removing harmful memories using causal attribution is not sufficient novelty. |
| [EARM, 2608.22767](https://arxiv.org/abs/2608.22767), abstract | Reuses learned query–memory relevance scores | Amortizing repeated memory decisions needs a stronger claim than caching scores. |
| [Graphiti official documentation](https://help.getzep.com/graphiti/getting-started/overview), page | Temporal graph, historical context, hybrid retrieval and invalidation | Compare to configured dynamic products, not a static vector store. |
| [Mem0 update documentation](https://docs.mem0.ai/core-concepts/memory-operations/update), page | Updating stored memory is a supported product operation | CRUD, updates and history are product requirements, not breakthrough evidence. |
| [Hamiltonian identifiability, 1809.02965](https://arxiv.org/abs/1809.02965), abstract | Identifiability tests via similarity and structure-preserving transformations | Memory cannot recover a parameter absent from all accessible observation distributions. |
| [Control-enhanced observability, 1102.2717](https://arxiv.org/abs/1102.2717), abstract | Discriminating controls can resolve otherwise limited observations | Adding a revealing control is known physics, not a new memory law. |
| [QInfer, 1610.00336](https://arxiv.org/abs/1610.00336), abstract; [official repository](https://github.com/QInfer/python-qinfer) | Sequential Bayesian inference and experimental design for quantum characterization | Strong comparator must retain posterior and cache likelihoods. Recomputing everything is an unfair baseline. |
| [DAD, 2103.02438v2](https://arxiv.org/abs/2103.02438v2), abstract; [official code](https://github.com/ae-foster/dad) | Amortizes sequential Bayesian design into a learned policy | Fast reused experiment policies are not novel by themselves. |
| [Observation geometry, 2608.10350](https://arxiv.org/abs/2608.10350), abstract | Uncertainty-aware multimodal Hamiltonian inference and adaptive design in NiPS3 | Identifiability-aware quantum discovery is already a current research direction. |
| [Evidential-bias adaptive design, 2608.16466](https://arxiv.org/abs/2608.16466), abstract | Recent alternatives to the EIG objective within adaptive design | EIG is not the only strong design criterion; later study must compare objectives. |
| [Occam's Quantum Razor, 1102.1994](https://arxiv.org/abs/1102.1994), abstract | Quantum states can reduce predictive model memory relative to optimal classical models | A classical NumPy simulation of density matrices does not inherit physical quantum memory savings. |
| [AlphaQubit, Nature 2024](https://www.nature.com/articles/s41586-024-08148-8), indexed primary text; full fetch blocked | Recurrent decoding learns from syndrome history | Persistent quantum decoder state is established. |
| [AlphaQubit 2, 2512.07737](https://arxiv.org/abs/2512.07737), abstract | Real-time neural QEC decoding and scalable code families | Compare against contemporary decoders and real latency, not only naive matching. |
| [EP4182858A1](https://patents.google.com/patent/EP4182858A1/en), description/abstract | Gradient-based quantum-assisted Hamiltonian estimation | Quantum-assisted parameter learning has patent prior art; no blanket originality claim. |
| [CN121960775A](https://patents.google.com/patent/CN121960775A/en), indexed claims/description | Identity, temporal and service-version checks before reusing dialogue cache | Scoped verified cache reuse itself has close patent art. |
| [US20250200392A1](https://patents.google.com/patent/US20250200392A1/en), indexed abstract/description | Verifying LLM outputs against structured facts | Verification plus language models is not a sufficient novelty claim. |

Benchmark protocol references: [LongMemEval](https://github.com/xiaowu0162/LongMemEval)
and [LongMemEval-V2](https://github.com/xiaowu0162/LongMemEval-V2) official pages.
Neither was executed or mined for test cases. MemoryLACE's cited BEAM and
StructMemEval are candidate *future* independent memory tasks, not evidence
already obtained. QInfer and DAD source SHAs must be pinned before any external
comparison. No fabricated pin or claimed external reproduction is provided.

## Five competing hypotheses

| ID | Precise proposed claim and mechanism | Falsifier and strongest baselines | Anticipated effect / cheap cost | Consumer and enterprise path |
|---|---|---|---|---|
| H1 | Scoped verification by itself prevents harmful transfer of a stored action after hidden environment change | Two observationally identical histories require different actions; compare Bayesian change-point detection and fresh diagnostic probe | Near-zero transfer errors; exact two-world counterexample costs seconds | Personal automations and changing enterprise APIs; shared label is insufficient evidence of unchanged dynamics |
| H2 | Counterfactual utility credit and automatic memory architecture search create a new continual-learning capability | Same-model ALMA, MemAudit, dynamic Graphiti/Mem0 and no-memory causal interventions explain gain | Desired >=10x fewer repeated failures; real evaluation needs models and new independent tasks | Learning reliable workflows; novelty overlaps heavily with existing work |
| H3 | Physical quantum predictive states give useful order-of-magnitude agent-memory savings | Optimal classical causal-state/compressed model plus encoding, decoding and error-correction costs erase advantage | Potential entropy separation; hardware requirement defeats cheap mass deployment today | Compression of recurring stochastic workloads; connection to ordinary assistant memory unproved |
| H4 | A cached Bayesian experiment decision plus a posterior-distance certificate preserves exact EIG choice while reducing decision p95 >=10x and exact score calls >=10x on unseen measurement histories | Fair vectorized cached-likelihood EIG; exact-posterior memoization; uncertified reuse ablation; weak naive baseline reported separately | Zero decision regret and >=10x compute saving; <=120 s NumPy experiment | Adaptive diagnostics on personal devices and repeated instrument calibration; end-user outcome still untested |
| H5 | Reusable syndrome-history representations yield a new accurate real-time quantum decoder | AlphaQubit 2, correlated matching, belief propagation, tensor-network/exact small-code decoder; cross-device noise | Desired new code family or >=10x logical error reduction at real-time latency; not feasible in this cheap phase | Fault-tolerant compute infrastructure, indirect mass benefit; no direct consumer workflow yet |

H2 is rejected as an unqualified novelty claim; H3's classical implementation
route is rejected as a quantum-advantage claim. H5 lacks a distinctive mechanism
and cheap competitive implementation. H1 has a likely identifiability obstruction.
H4 is selected for falsification, not declared novel or admitted.

## Decision matrix

Scores 0–4, larger is better; these are explicit judgments, not measured facts.
Weights: novelty .20, falsifiability .15, effect .15, reproducibility .10,
feasibility .15, safety .05, latency/cost .10, breadth .10. Novelty below 3
forbids scientific admission regardless of weighted total.

| Hypothesis | Novelty | Falsify | Effect | Reproduce | Feasible | Safe | Cost | Breadth | Weighted |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| H1 | 0 | 4 | 3 | 4 | 4 | 2 | 4 | 4 | 2.95 |
| H2 | 1 | 3 | 2 | 2 | 1 | 2 | 2 | 4 | 2.00 |
| H3 | 0 | 3 | 4 | 2 | 0 | 3 | 0 | 1 | 1.50 |
| H4 | 2 | 4 | 3 | 4 | 4 | 4 | 3 | 3 | 3.25 |
| H5 | 1 | 3 | 4 | 2 | 0 | 3 | 0 | 2 | 1.80 |

H4's residual question is whether its certificate gives a useful exact
computation–memory tradeoff under realistic posterior changes. Known entropy
continuity and memoization could fully explain it. Before promotion, search
certified computation reuse, Bayesian sufficient statistics, Lipschitz action
caching, adaptive submodularity and posterior robustness in depth. This first
review cannot establish exhaustive novelty, and its matrix admits no breakthrough.
