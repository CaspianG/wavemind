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
already obtained. QInfer and DAD source SHAs were subsequently pinned in
`baseline_pins.json` through the GitHub connector before any external
comparison. No external package execution or reproduction is claimed.

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

## Follow-up after R1 (before R2)

[Bayesian ACRONYM Tuning, TQC 2019](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.TQC.2019.7)
explicitly reuses information across nearby control settings with a Lipschitz
assumption. This is close prior art for any broad "certified information reuse
in quantum control" claim, although it is not the same posterior/EIG cache.
[NIST OptBayesExpt](https://pages.nist.gov/optbayesexpt/) supplies another mature
adaptive-design comparator. Both primary pages were read. Novelty remains
unestablished; a fresh name cannot resolve the overlap.

R1 found zero certified reuse on 3,456 decisions. Tilted-axis margins were
at numerical zero; x/z had positive but small margins and still failed.
R2 removes equivalent channels for both candidate and baseline and uses new
seeds/grid/times. Its purpose is to rule out symmetry degeneracy as the sole
explanation of R1 failure, not to reset the original failed result.

## R5 follow-up: full-LC recognition audit, novelty still unresolved

The [R5 proof](LC_PROJECTOR.md) reduces full local-Clifford-to-CSS recognition
to site-dependent rank-one endomorphisms; inconsistent trace-one linear
constraints give short impossibility certificates. This is not claimed as a
polynomial-time complete method: consistent systems may require exponential
residual enumeration.

The [catalog audit](LC_PROJECTOR_R5_RESULTS.md) produced and independently
checked 357 full-LC negative certificates and 11 witnesses. This strengthens
the restricted-family accounting in [the PBB paper](https://arxiv.org/html/2606.02418v1#A6)
on this fixed corpus, without discovering an additional CSS-equivalent code.

The underlying algebraic ideas have close predecessors: the known CSS rank
test in [Cross–Vandeth](https://arxiv.org/html/2501.17447v1#S7.SS2), projection
invariance in [Dasu–Burton](https://arxiv.org/html/2507.10519v1#S3), and the
conjugated, site-dependent idempotent in [Albert's Appendix F.2](https://arxiv.org/html/2608.05688v1#A6.SS2).
The last source was examined in detail after R5 was frozen and is a material
novelty warning, not an external validation. Its stated lemma starts with two
CSS-form spaces; our experiment starts with an arbitrary stabilizer and asks
if a CSS frame exists. Whether the certificate formulation or the completed
catalog audit adds a publishable new result is still an open review question.

Next: check equivalence with existing algebraic recognition methods, then
preregister a different-family stress test and compare against an executed
strong general solver. Do not present the familiar projection construction,
a one-corpus success, or an unexecuted upstream package as a scientific gate.

## R6: determinant-mask stitching candidate

[The R6 derivation](LC_STITCHING.md) proposes using the central mask
I+T^2+T for trace-one local maps T. A cover of sites by at most d+1 candidates
is partitioned inside the preserving algebra to produce a rank-one projector.
This gives a candidate polynomial-time recognition algorithm, not just a
small residual-enumeration trick. Its complete proof and assumptions are
available for scrutiny; no independent expert has reviewed them.

An essential additional comparator is [Van den Nest et al. / Bouchet](https://arxiv.org/pdf/quant-ph/0405023):
polynomial-time local Clifford equivalence of two specified stabilizer states
already exists, with linear equations plus a polynomial-size search for the
quadratic constraints. Our target is arbitrary-rank stabilizers and existence
of any CSS frame. The distinction must be assessed against the actual older
theorems, not used to assume novelty. The brief primary paper was read,
including its stated O(n^4) algorithm and its attribution to Bouchet.

R6 passed its 34,047-instance finite test, but the result is narrower than
"every part of the construction is exercised": the initial particular map
already worked in every positive main-corpus instance. The multi-mask branch
only has a small unit control. The next adversarial-affine-frame falsifier
is therefore necessary; see [the evidence and gap](LC_STITCHING_R6_RESULTS.md).
Neither passing the finite test nor giving the proposed lemma a new name
establishes priority, a quantum hardware gain or mass indispensability.

## After R7: branch tested; classical algebra overlap still a live falsifier

[R7](LC_ADVERSARIAL_R7_RESULTS.md) now tests the multi-mask positive branch
on 384 constructed frames, including 96 guaranteed hard cases. It leaves
the historical R6 coverage statement unchanged and gives no novelty clearance.

The primary [Rains preprint, *Nonbinary quantum codes*](https://arxiv.org/pdf/quant-ph/9703048)
was inspected at the "Linear codes" section, printed pp. 5–7, including
Theorems 4 and 6. It uses a common coordinate transformation and relates a
split algebra's idempotents to the CSS decomposition. This confirms that
algebraic invariance and splitting by complementary projectors are prior art.
The inspected statement is not the site-dependent recognition algorithm
claimed in R6. That distinction is an unresolved comparison, not proof of
priority; the whole literature and all later implications were not checked.

The rechecked [Dasu–Burton §4](https://arxiv.org/html/2507.10519v1#S4)
explicitly restricts its classification to the same single-qubit Clifford
on every site. Next compare R6's actual input/output and complexity with
Bouchet/Van den Nest and general finite-algebra idempotent methods; reject or
narrow novelty if it follows from them. An implemented ablation is not a
substitute for an executed strong external comparator on the same task.

## Theorem-level follow-up and review packet

The [applicability audit](PRIOR_ART_THEOREM_AUDIT.md) adds a directly matching
open-complexity statement from *Quantum XYZ Stabilizer Codes*, and separates
it from the known pairwise, uniform-frame and generic-idempotent problems.
Two source examples were exhaustively reproduced, with their expected
answers already visible; an exact F4 counterexample refutes the shortcut from
arbitrary nonzero idempotents to the required rank-one witness. Neither check
refutes the cited external theorems or establishes novelty.

The generic finite-algebra reduction remains unresolved. The proof and
specific requests for criticism are assembled in an
[unsent independent-review packet](EXPERT_REVIEW_PACKET.md). No investigator
has reviewed or received it. Scientific and workflow gates remain false.
