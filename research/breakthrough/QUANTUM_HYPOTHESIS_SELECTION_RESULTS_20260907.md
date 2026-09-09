# QEC hypothesis selection: none admitted

Date/cutoff: 2026-09-07. Rules were frozen before searching in
[`QUANTUM_HYPOTHESIS_SELECTION_GATE_20260907.md`](QUANTUM_HYPOTHESIS_SELECTION_GATE_20260907.md),
commit `32088860824ff3c6127599b6d4649debeb6e7d8c` (parent `1558f08`).
Three candidates, eight of twelve allowed targeted queries; no experiment,
package installation, max call, hardware run or product modification.

**Decision: select none.** These are useful unresolved tasks, not three new
inventions. The proposed objectives below lack a justified new mechanism.
No criterion was relaxed to produce a winner. This bounded search does not
prove that the problems are impossible or that no novel solution exists.

## A. Causal adaptation to noise drift at fixed total cost

**Task.** Surface-code memory: input is the circuit, initial calibration and
syndrome prefix through round t; output is the logical correction at a fixed
decision delay. Future syndromes and true simulated error probabilities are
unavailable to the adaptive decoder. Can adaptation reduce logical errors
without increasing total calibration, training and decoding cost?

**Closest primary work.** [Bhardwaj et al., v1, 2025](https://arxiv.org/html/2511.09491v1),
sections III.1–III.3 and IV.5, already provide sliding, iterative and relative
windows. Equation 11's estimate at t uses an additional cycle; comparisons
must align information and delay. Their surface-code decoding demonstration
uses distance three and X stabilizers, not a general full-Pauli guarantee.
[QAdapt, v1, 2026](https://arxiv.org/html/2607.28422v1), sections 3–4 and
limitations, already combines neural pre-decoding, matching and continual
adaptation. It explicitly lacks end-to-end component timing and some
controlled adaptation comparisons. A causal, cost-matched advantage is an
audit-inferred target, not a new theorem asserted by either paper.

**Minimum claim worth testing.** A specified causal update rule achieves at
least 20% lower logical error at non-increased total cost against the best
matched static, window-adaptive and neural-adaptive controls on a frozen
drift family. No such distinct update rule or invariant was established here;
adding rolling statistics, adaptive weights or EWC is not new enough.

**Cheapest lethal falsifier, not run.** First audit timestamps: any use of
future syndrome information kills the causal claim. Then use a stationary
control and abrupt/oscillating drift near the estimator's window limit with
paired distance-three shots. Freeze drift parameters, delay, uncertainty and
cost accounting before scoring. An adverse result can reject the chosen
claim; a small pass cannot establish rare-event protection.

**Baselines/access and value.** Stim plus PyMatching are public; the exact
adaptive comparators' source/version equivalence was not established in this
bounded pass. Reduced recalibration and logical failures would directly
benefit a QEC control pipeline, not automatically a consumer application.
**No-go: G2 fails; G3/G4 remain unknown.**

## B. Safe commit buffers for weighted streaming decoding

**Task.** Fixed surface-code decoding graph with positive heterogeneous edge
growth times and an arriving syndrome prefix; output is an irreversible
committed correction and a computable sufficient buffer bound. Does a local
invariant support weighting without leaving unannihilated committed defects?

**Closest primary work.** [Snowflake, v3, March 2026](https://arxiv.org/html/2406.01701v3),
sections 3, 4.3–4.4 and 6, already reuses overlapping-window work. Proposition
2 gives the unweighted buffer bound 2 floor(d/2). Its guarantee concerns
annihilation of committed defects, not correctness of every logical decision.
The weighted-edges discussion explicitly identifies a configurable buffer
bound as nontrivial. Its distributed timesteps are not measured CPU latency,
and mean throughput is not a hard deadline guarantee.

**Minimum claim worth testing.** An explicit weighted growth/commit invariant
gives a sufficient bound and permits at least 2x lower total decoding latency
than a conservative weighted streaming baseline at non-inferior logical
error. Neither the invariant nor a justified comparison bound was derived.
Weighted union-find plus a dynamic window, by itself, is only a combination.

**Cheapest lethal falsifier, not run.** On a distance-three graph, place an
isolated defect behind slow edges and advance successive syndrome prefixes.
One unannihilated defect entering the committed region refutes a proposed
sufficient bound. Enumerate a small fixed set of positive integer weights
before any performance test; do not enumerate all large-code syndromes.
Without a bound/formula, executable cost and termination remain unknown.

**Baselines/access and value.** Public localuf supplies the author's simulator
and decoder source; weighted matching in PyMatching provides an accuracy
control, not an equivalent streaming deadline guarantee. Version metadata
below establishes availability, not compatibility or reproduced results.
Lower decoder delay/buffering would directly affect feed-forward and decoder
resources. No FPGA or hardware speedup is claimed. **No-go: G2/G4 unknown.**

## C. Tight bounded-cluster certificates for the gross BB code

**Task.** The [[144,12,12]] bivariate-bicycle code, independent X-only
code-capacity noise, known priors and measured syndrome; return a winning
logical class with sound probability bounds, or abstain. All 2^12 classes in
that sector must be covered; this is not the full joint Pauli problem.

**Closest primary work.** [Certified decoding of quantum LDPC codes, v1,
August 2026](https://arxiv.org/html/2608.25545v1), sections 7.4–7.6, 8.5 and 9,
already combines interval bounds, class pruning and certification. Its
paired-bootstrap results are asymptotic, unlike deterministic interval
separation under the specified noise model. The authors report loose
mini-bucket bounds breaking 49/60 previously correct gross-code decisions
when used for ranking, and explicitly call for tighter bounded-cluster
bounds. Code, scripts and raw results are available upon request, not as an
identified public release in the reviewed source. Results were not reproduced.

**Minimum claim worth testing.** A genuinely new shared-coset bound at cluster
width at most 20 retains soundness and the baseline's certification coverage
at half its total cost on a frozen syndrome sample. No concrete new bound
was obtained; composing existing mini-bucket bounds with fallback is not it.

**Cheapest lethal falsifier, not run.** Exhaustively compute exact class
probabilities for a small CSS control: one bound excluding the truth, or one
incorrect certified winner, kills soundness. This does not validate gross-code
coverage or cost. The missing formula and comparison implementation prevent
a credible <=2-hour execution plan.

**Baselines/access and value.** Public ldpc exposes BP+OSD and BP+LSD;
[localized statistics decoding](https://www.nature.com/articles/s41467-025-63214-7)
already uses reliability-guided local clusters and reused elimination.
These cannot substitute for the unavailable exact certification comparator.
Sound abstention could support decoder validation and selective expensive
decoding; model-relative optimality is not noise-model robustness.
**No-go: G2/G4 unknown, G3 fails.** No outreach is initiated.

## Access evidence and fixed decision

Public source-distribution listings were inspected, not merely repository
home pages. Nothing was downloaded or executed. Licenses below are package
metadata, not a completed dependency/license audit:

| Package | Identified source release | Listed license | Primary listing |
|---|---|---|---|
| Stim | 1.16.0; 2026-05-22; stim-1.16.0.tar.gz | Apache 2 | [PyPI](https://pypi.org/project/stim/1.16.0/) |
| PyMatching | 2.4.0; 2026-05-22; pymatching-2.4.0.tar.gz | Apache 2 | [PyPI](https://pypi.org/project/PyMatching/2.4.0/) |
| localuf | 3.4.4; 2026-02-12; localuf-3.4.4.tar.gz | MIT | [PyPI](https://pypi.org/project/localuf/3.4.4/) |
| ldpc | 2.4.1; 2025-12-08; ldpc-2.4.1.tar.gz | MIT | [PyPI](https://pypi.org/project/ldpc/2.4.1/) |

G1 exact supported task; G2 new mechanism; G3 public reproducibility; G4
bounded lethal test; G5 direct value target; G6 separation from old results.
G5 pass means a qualifying *target*, never an observed benefit. G4 is unknown
because a sketch of a cheap falsifier is not a verified execution plan for
an unspecified mechanism. Under the frozen rule, unknown means no-go.

| Candidate | G1 | G2 | G3 | G4 | G5 | G6 | Decision |
|---|---|---|---|---|---|---|---|
| A: causal adaptation | pass | fail | unknown | unknown | pass | pass | no-go |
| B: weighted commit bound | pass | unknown | pass | unknown | pass | pass | no-go |
| C: gross-code certification | pass | unknown | fail | unknown | pass | pass | no-go |

Search stopped without filling the remaining budget. Closest prior art found
is not a claim of exhaustive SOTA coverage. Method/result/limitation sections
were read; search-only leads were not treated as reviewed evidence.

The eight targeted queries, in order, were:

1. quantum error correction decoder 2026 correlated noise model mismatch open source real time decoding limitations
2. quantum LDPC decoding 2025 2026 latency belief propagation localized statistics decoding open source
3. surface code streaming decoder 2025 2026 burst errors real time worst case latency open source
4. site:arxiv.org quantum error correction noise drift adaptive decoder 2026 syndrome calibration
5. site:arxiv.org "Certified Decoding of Quantum LDPC Codes"
6. site:arxiv.org "Snowflake" decoder burst
7. "Snowflake" "weighted" decoder 2026 buffer
8. "causal" "noise" "syndrome" estimation 2026 quantum decoder

No candidate advances to implementation or a max packet. R8 remains
not novelty-admitted; neither mission gate changes. SMS/incident baselines
remain on hold for actual human terms review. This selection supplies no
approval and does not substitute literature objectives for measured outcomes.
