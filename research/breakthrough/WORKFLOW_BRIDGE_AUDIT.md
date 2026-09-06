# CSS recognition is not an automatic practical improvement

Date: 2026-09-07. Decision: reject the automatic quality-transfer claim.
Keep R6/R8 as a separate mathematical candidate, pending prior-art review and
independent scrutiny. Neither mission gate is satisfied.

## What was tested, and why

R8 accepts binary generators and a qubit count. It does not accept a noise
channel, device geometry, measurement circuit, decoder cost or workflow value.
The following control tests whether its correct CSS witness nevertheless
guarantees better (or at least equal) noise protection. It does not.

This is a **known analytical boundary control**, with the expected outcome
declared before execution, not a novel theorem or a risky discovery experiment.
It uses elementary repetition codes. The broader point is already established
in [The XZZX surface code, Results](https://doi.org/10.1038/s41467-021-22274-1):
local basis changes preserve code parameters but can change response to a fixed
biased noise channel. This control does not reproduce that paper's surface-code
thresholds or circuit results.

Frozen source before the control:
`496c7573140eb312384a7464d219345622932911`.
The [protocol](workflow_bridge_protocol.json) fixed the two inputs, exact
channels, optimal decoder class, expected fractions and stop rule. Four
preflight tests used separate one/two-qubit examples; all passed. The
[runner](workflow_bridge_control.py) confirms that its R8 solver and dense
checkers are byte-identical to the R8 frozen source.

## Exact result

Both input codes already have CSS form. Keeping the input unchanged is therefore
a legitimate baseline, not an unimplemented competitor. Frozen R8 returns H
on every site for these two inputs, exchanging their X and Z generators.
Both have full quantum parameters **[[3,1,1]]**, not [[3,1,3]]. The repetition
protection applies only to the restricted error type.

Per-site pure-Z noise is I with probability 99/100 and Z with probability
1/100. Errors on sites are independent. Syndrome measurement is perfect;
the decoder chooses the largest-probability stabilizer coset separately for
each syndrome. All 64 Pauli errors are enumerated, including zero-mass errors.
The same optimal decoder class is used before and after transformation.

| Input stabilizers | Fixed pure-Z failure before | Fixed pure-Z failure after R8 | After / before |
|---|---:|---:|---:|
| XXI, IXX | 149/500000 = 0.000298 | 7351/250000 = 0.029404 | 14702/149, about **98.67 times worse** |
| ZZI, IZZ | 7351/250000 = 0.029404 | 149/500000 = 0.000298 | 149/14702 |

The second row is the reverse known effect, **not a measured 98.67x workflow
gain**. Selecting only that row would hide the decisive adverse control.

Independent closed-form checks at p=1/100 are:

- For XXI, IXX: failure is 3p^2(1-p)+p^3 (two or three Z errors).
- For ZZI, IZZ: failure is 3p(1-p)^2+p^3 (odd Z parity).

With depolarizing noise I=99/100 and X=Y=Z=1/300, both codes before and after
have exactly the same failure **5569/281250**. When the pure-Z channel is
co-transformed along with the code (here becoming pure X), each original
failure is also preserved exactly. Dense row-action and CSS witness checks
passed, as did exact enumeration of code dimension and distance.

There are two inputs and five code/channel settings per input: 640 enumerated
Pauli-error records, not 640 independent workflows. Fractions are exact in
this specified model; statistical confidence intervals would not add evidence
about unmeasured real-world performance. No hardware, circuit, model/API or
external workflow was executed.

## Why these boundaries are structural

The following is standard covariance reasoning, not a claimed new proof.
Let U be a product of single-qubit Clifford gates and S a stabilizer group.
Conjugation maps S bijectively to USU†, preserves commutation and Pauli support
weight, and maps its normalizer and nontrivial logical cosets bijectively.
Thus n, k and minimum logical weight d are unchanged.

For a Pauli channel, optimal coset-decoding success with perfect syndrome is
the sum, over syndromes, of the largest coset probability. Co-transforming
the channel by U preserves those masses under the same bijection. An
independent depolarizing channel is itself invariant under any local Clifford
because all three nonidentity errors have the same probability at each site.
Consequently no automatic optimal-decoding improvement follows in that model.

A **physical change of code at fixed biased channel** is a different operation
from a **passive change of coordinates for both code and channel**. Only the
former can produce the unequal rows above. Neither statement covers circuit
noise, decoder runtime, connectivity, non-Pauli noise or a restricted decoder;
those need their own assumptions, baselines and measurements.

## Bridge to the unchanged mission

| Proposed link from recognition | Current evidence | Decision |
|---|---|---|
| More logical qubits or larger distance simply by local frame change | n,k,d invariance | Reject this automatic link. |
| Better optimal protection under independent depolarizing noise | Channel/coset covariance | Reject this automatic link. |
| No worse protection under a fixed biased Pauli channel | Exact adverse control above | Reject this guarantee for frozen R8. |
| Faster decoder or cheaper fault-tolerant circuit | No cost objective, implemented circuit or measured comparator | Open possibility, not evidence of benefit. |
| Useful subroutine for a QEC design/compiler workflow | Recognition candidate, but no owner-supplied task, measured bottleneck or external same-task package run | Plausible narrow research application only. |
| Better AI memory or indispensability in consumer and enterprise work | No implemented QEC-to-product path or real workflow outcomes | No established bridge; do not treat QEC audit counts as product progress. |

Repository check at parent `a15bcf093383dab1e99fee6b587cd817e8170589`:
`git diff a465ac0e3a5610cadcf07320fcd08bf6873158f3 HEAD -- wavemind pyproject.toml sdk/typescript`
had no differences. Searching `wavemind`, `sdk/typescript` and `website` for
`lc_scalar_components`, `lc_stitching` or `research[./]breakthrough` had no hits.
This establishes no current explicit integration in those inspected paths,
not impossibility of every future application or dynamic integration.

## Next action changed by this audit

Do not extend positive direct-sum corpora, tune CSS witnesses for the selected
toy channel, or present the favorable reverse control as progress toward the
mass-indispensability gate. A noise-aware conversion problem would be a
different task with substantial prior art, not a small repair proving the
current mission. Even an identity-on-already-CSS guard only fixes these inputs.

Keep the theorem candidate and its unsent review packet available for independent
criticism. For the practical track, first identify an actual consumer process
and an actual enterprise process, their owner-defined outcome and current
strong baseline. Those inputs have been requested but are not yet supplied.
Before another discovery experiment, select or reject a mechanism with a
causal path to those outcomes, and define its new assertion against prior art.
Local work can still inspect the diagnostic/mechanism literature and derive
boundaries; it cannot invent independent participants, expert endorsement,
error budgets or a real-world 10x win.

## Preserved evidence

- [Start receipt](runs/workflow_bridge/receipt_start.json),
  [result](runs/workflow_bridge/result.json), [raw records](runs/workflow_bridge/raw.jsonl).
- Raw bytes: 54011; SHA-256
  `4f6d5056b8ad0f83cfb5dfb9fe96e2269b4d36d86d0d9aa319e8ebb6338b1f81`.
- [Read-only verifier](verify_workflow_bridge.py) replays every case and checks
  current and frozen source hashes, R8 pins, raw hash and result fields.
- [Post-run tamper controls](test_workflow_bridge_evidence.py) require rejection
  of altered raw bytes and an invented novelty claim.

```sh
python research/breakthrough/verify_workflow_bridge.py
python -m pytest -q research/breakthrough
```

For a new execution, use a clean checkout at the frozen SHA and run
`python research/breakthrough/workflow_bridge_control.py --output NEW_DIRECTORY`.
An existing output directory is rejected. Original R1–R8 sources and outcomes
are unchanged. Both full gates remain false.

Post-run verification: 56 research tests passed, including raw-byte and false
novelty tamper rejection; Ruff passed. These are software/evidence checks,
not independent investigators or real workflow measurements.
