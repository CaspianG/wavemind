# Milestone: reject H4-R1/R2 and universal H1; mission remains active

Date: 2026-09-06. Neither final gate is passed. No candidate is ready for an
expensive experiment. This is a negative research result, not a breakthrough.

## Frozen runs

| Experiment | Source SHA before execution | Result |
|---|---|---|
| H4-R1 posterior certificate | `5ee82f8ef4b5087e0c8a1a35ded6b3701a9ae9bd` | 3,456 decisions; zero disagreements; every decision recomputed |
| H4-R2 equivalent-channel quotient | `831c7d6ee26ae4507a821c3048ad56b1ddefa718` | 3,456 new decisions; zero disagreements; every decision recomputed |
| H1-R3 hidden sign change | `b12df277a475134249ce81451976dd1c80d411bd` | Exact two-world counterexample refutes scope-alone universal transfer |

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

All three are generated mathematical-model evaluations. There is no physical
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

## Next decision

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
