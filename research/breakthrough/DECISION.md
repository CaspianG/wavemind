# Milestone: reject H4-R1/R2 and universal H1; mission remains active

Date: 2026-09-06. Neither final gate is passed. No candidate is ready for an
expensive experiment. This is a negative research result, not a breakthrough.

## Frozen runs

| Experiment | Source SHA before execution | Result |
|---|---|---|
| H4-R1 posterior certificate | `5ee82f8ef4b5087e0c8a1a35ded6b3701a9ae9bd` | 3,456 decisions; zero disagreements; every decision recomputed |
| H4-R2 equivalent-channel quotient | `831c7d6ee26ae4507a821c3048ad56b1ddefa718` | 3,456 new decisions; zero disagreements; every decision recomputed |
| H1-R3 hidden sign change | `b12df277a475134249ce81451976dd1c80d411bd` | Exact two-world counterexample refutes scope-alone universal transfer |
| R4 optimal diagnostic baseline | `1428e8c6f7de4c899d2fec4fc67b4363fce14a79` | 315 exact rows; 45 depth-two comparisons with exhaustive policy enumeration; known baseline, not a novel mechanism |

R1 mean paired seed p95 speedups: x 0.470 [0.462, 0.477], z 0.487
[0.470, 0.512], tilted 0.467 [0.460, 0.473]. R2: 0.445 [0.430, 0.457],
0.449 [0.438, 0.458], and 0.465 [0.455, 0.478]. Values below 1 mean the
candidate is slower. The target was >=10 with >=90% fewer full score calls.
Both saved 0% of calls; this deterministic failure suffices for rejection
without relying on microsecond timing precision.

R2 reduced 78 channels to 40/40/39 for both methods. Symmetry duplicates do
not explain the entire failure: the sufficient entropy bound is too
conservative relative to the observed margins. R1's uncertified last-action
reuse changed the selected action 449/464/620 times, with positive maximum
information regret in each family. These are action disagreements, not
counts of wrong physical outcomes.

R3's X-readout distributions are identical in opposite-sign Hamiltonian worlds.
At pi/2, the correct correction actions are opposite. Any history-only rule
has at most 50% average sign-choice success under equal current-world priors.
A fresh Y diagnostic yields 100%, 98%, or 90% at readout errors 0, .02 or .1.
The matched classical hidden-bit problem has the same limitation. This is
known identifiability, not new physics or failure of all useful memory.

## Boundaries and integrity

All four are generated mathematical-model evaluations. There is no physical
or public held-out data result. X and z are symmetry-related and do not count
as independent task domains. Each family has 24 seed histories, not thousands
of independent physical experiments. R2 was explicitly informed by R1.
Timing intervals describe this machine and workload, not universal utility.

The reference is a vectorized, cached, exact finite-grid one-step EIG oracle.
QInfer's pinned `expected_information_gain` source was read; its expected
posterior-KL formulation is consistent with the independent mathematical form
in `verify_evidence.py`. QInfer, DAD and OptBayesExpt packages were not executed.
This is not a comparison with a Bayes-optimal multi-step policy.

Protocol/source hashes, likelihood hashes, full posteriors, actions, outcomes,
timing samples and receipts are in `runs/`. Each protocol and implementation
was committed before execution. Outcomes have not been replaced or retuned.
Protected v31 raw data and paid endpoints were untouched. Each run took seconds.

## R4: A Stronger Baseline, Not A Breakthrough

The diagnostic-witness idea overlaps established decision-region determination;
see [the reduction and primary sources](DIAGNOSTIC_REDUCTION.md). R4 implements
the exact finite-horizon Bayesian diagnostic policy with rational arithmetic.
It charges for every probe and uses the same calibrated model and prior for
all policies. In 15 of 45 parameter scenarios, allowing up to six adaptive
probes improves expected loss relative to an optimal at-most-one-probe policy.
The largest ratio is about 16.84, but this is an advantage of a known optimal
algorithm over a restricted baseline, not a new scientific result or product
speedup. The model is stationary, conditionally independent and generated;
there is no external task evidence or quantum hardware result.

The original receipt, 315 rows, and result remain unchanged in `runs/r4/`.
`verify_r4.py` checks their hashes against the preregistered source, replays
every exact result, independently enumerates all depth-two policies, and checks
the reported gains. No rerun overwrites the original evidence.

## R5: Full-LC Certificates For The Public PBB Catalog

The subsequent QEC direction produced a bounded candidate result: 357 exact
linear impossibility certificates and 11 explicit local-Clifford-to-CSS
witnesses for all 368 records in a pinned public catalog. A separate dense
implementation verified every certificate. Runtime for construction, search,
verification and the restricted 36-pattern baseline was 19.7693 seconds.
The prediction of additional hidden CSS codes was rejected; the prediction
of at least 95% certified coverage was confirmed. Neither full-mission gate
passes. The conjugated-projector idea has substantial prior-art overlap.

See [the R5 report](LC_PROJECTOR_R5_RESULTS.md) for the preregistration, preserved
metadata failure, source SHA, all raw certificates, primary sources and claim
limits. The existing diagnostic negatives remain intact. The next local step
is R5 prior-art resolution and a preregistered independent-family falsifier,
not a product relaunch or a claim of invented quantum error correction.

## R6: Polynomial Candidate, With A Specific Remaining Falsifier

The next derivation uses closure of the local endomorphism algebra: for a
trace-one map T, I+T^2+T is a central mask selecting its rank-one sites.
A cover by at most dimension+1 such maps can be partitioned and stitched.
This removes R5's residual enumeration in the candidate theorem and implementation;
it is not an independent expert endorsement or novelty clearance.

The preregistered run at `90579911ad56ae2ef85e0c6f96c5c86d98cec178` completed
34,047 cases, including all labelled graph states through six qubits and 180
other constructed codes. All certificates and source hashes were audited;
33,951 exact-oracle/known-construction comparisons and 48 proper-code direct
Clifford enumerations had no disagreement. R6 resolved 29 cases left unresolved
by our old R5 limit; no external best-solver superiority follows from that.

Crucially, every positive case in the main corpus already had a good initial
particular solution. The multi-mask stitching branch only has a small unit
control. The immediate next falsifier must exercise adversarial affine frames
on nontrivial positive codes. Preserve this coverage gap rather than quietly
counting it as tested. See [the full R6 report](LC_STITCHING_R6_RESULTS.md).

## Earlier Diagnostic Research Decision (superseded as the immediate next step)

The following diagnostic direction was proposed after R3. R4 and its prior-art
review now establish the required baseline; they do not establish a new mechanism.
Do not relabel the diagnostic reduction or its 16.84x toy-model ratio as novelty.

Stop tuning H4 on these histories. Investigate whether a small set of fresh
diagnostic interventions can certify transport of a learned procedure under
a specified class of latent changes with a new sample-complexity/capability
boundary. Compare against active diagnosis, Bayesian ACRONYM, safe transfer
and system identification. This is an open question, not a new mechanism yet.

First derive assumptions and a lower bound, then review closest methods and
formulate an assertion they do not imply. An assumption that directly reveals
the hidden state cannot establish a new capability. The next minimal local
comparison should use an optimal adaptive diagnostic policy and charge every
probe to both methods; only a survivor earns a new independent external task.

Source baselines are pinned in `baseline_pins.json`. The GitHub connector
resolved the shell-network obstacle for read-only source access. No external
action is needed for the next mathematical/prior-art cycle. Expensive testing
is currently unjustified because all implemented candidates were rejected.

## Product gates: prepared, unmeasured

Consumer target: personal-device diagnosis and reversible repair after
configuration changes. Enterprise target: instrument/API diagnosis and safe
calibration or repair across versions. Both require independently collected
workflow data, externally defined success, held-out changes and the existing
troubleshooting system as baseline.

Measure resolved tasks, repeated failures, diagnostic interactions, total cost
per successful resolution, p50/p95 delay, unsafe actions, rollback success,
recovery time, throughput and setup by someone other than the author. Require
>=10x improvement in a preregistered resource/outcome at preserved quality and
safety, or a previously impossible capability, in both real workflows. Set
error budgets with workflow owners before collection. No such participants,
enterprise access or independent expert review are currently supplied.

Measure switching cost as migration/integration effort and lost useful
procedures, with export and rollback available; deliberate lock-in is not
indispensability. All real product outcomes and unit economics are unmeasured.
