# Breakthrough research — local investigation resumed, not achieved

This is the research entry point for the mission started on 2026-09-06.
The released WaveMind product is an input to the investigation, not evidence
that a scientific breakthrough has happened.

Both gates remain required: a novel, independently reproducible scientific
capability and an order-of-magnitude or previously impossible improvement in
real consumer and enterprise workflows. External expert scrutiny is required
before calling any result a breakthrough. A local experiment cannot close
either gate.

- [Что сделано и почему это ещё не доказанный прорыв — без жаргона](PLAIN_LANGUAGE_RU.md)
- [Bounded QEC hypothesis selection: three candidates, none admitted](QUANTUM_HYPOTHESIS_SELECTION_RESULTS_20260907.md)
- [Selection criteria frozen before the literature search](QUANTUM_HYPOTHESIS_SELECTION_GATE_20260907.md)
- [Current scientific decision gate: exact residual claim, proof and falsifiers](SCIENTIFIC_DECISION_GATE.md)
- [Decision-gate results: full replay, physical negatives, no novelty clearance](SCIENTIFIC_DECISION_RESULTS.md)
- [Frozen public-workflow selection and measurement contract](PUBLIC_WORKFLOW_SELECTION_PROTOCOL.md)
- [Selected public consumer/enterprise workflows and rejected-source ledger](PUBLIC_WORKFLOW_SELECTION.md)
- [Actual UCI intake results: preserved failure, amended replay, quality and terms hold](WORKFLOW_INTAKE_V2_RESULTS.md)
- [Frozen intake guide, access history and companion notebook](WORKFLOW_INTAKE_GUIDE.md)
- [Compact R8 handoff: exact claim and remaining prior-art questions](R8_NEXT_GATE_BRIEF.md)
- [Starting state and instruction audit](STATE_AND_AUDIT.md)
- [Primary-source novelty map and decision matrix](NOVELTY_REVIEW.md)
- [Frozen first experiment](protocol_r1.json)
- [Mechanism and proof boundary](MECHANISM.md)
- [Results and next decision](DECISION.md)
- [External baseline source pins](baseline_pins.json)
- [Diagnostic reduction and exact R4 baseline](DIAGNOSTIC_REDUCTION.md)
- [R5 full local-Clifford criterion and proof boundary](LC_PROJECTOR.md)
- [R5 complete 368-code audit, results and plain Russian explanation](LC_PROJECTOR_R5_RESULTS.md)
- [R6 polynomial stitching candidate and proof](LC_STITCHING.md)
- [R6 34,047-case falsifier, limitations and plain Russian report](LC_STITCHING_R6_RESULTS.md)
- [R7 adversarial affine-frame protocol and assumptions](LC_ADVERSARIAL_FRAMES.md)
- [R7 384-case multi-piece audit, ablations and limits](LC_ADVERSARIAL_R7_RESULTS.md)
- [Theorem-level prior-art applicability audit and refuted shortcut](PRIOR_ART_THEOREM_AUDIT.md)
- [Independent review request — unsent draft](EXPERT_REVIEW_PACKET.md)
- [R8 scalar-component simplification and known foundation](LC_SCALAR_COMPONENTS.md)
- [R8 complete small-subspace falsifier and narrowed novelty boundary](LC_SCALAR_R8_RESULTS.md)
- [Workflow bridge audit: correct CSS conversion can worsen fixed-noise protection](WORKFLOW_BRIDGE_AUDIT.md)
- [Safe-transfer prior-art audit: known mechanisms and incompatible guarantee targets](SAFE_TRANSPORT_PRIOR_ART_AUDIT.md)
- [Historical learned-structure triage and external requirements](LEARNED_TRANSPORT_TRIAGE.md)

The subsequent instruction authorizes autonomous selection of public licensed
consumer and enterprise workflows. Missing owner-selected tasks no longer
blocks local research. Independent review and real-workflow validation remain
required for the full gates; the earlier paused posture is historical.

Results are recorded after execution, including rejection. No released runtime
is changed by this experiment. No paid API, judge, simulator, quantum hardware,
or LongMemEval execution is authorized by these local runners.

## Reproduce or audit

Python and NumPy suffice (`numpy==2.5.2` was used). Audit stored evidence:

```sh
python research/breakthrough/verify_evidence.py
python research/breakthrough/verify_r4.py
python research/breakthrough/verify_r5.py
python research/breakthrough/verify_r6.py
python research/breakthrough/verify_r7.py
python research/breakthrough/verify_prior_art_applicability.py
python research/breakthrough/verify_r8.py
python research/breakthrough/verify_workflow_bridge.py
python research/breakthrough/decision_gate_falsifier.py --verify research/breakthrough/runs/decision_gate
```

For reproduction, create a clean detached checkout at the run's source SHA
in `DECISION.md` (or the linked R5/R6/R7/R8 reports), then invoke its `experiment_r1.py`,
`experiment_r2.py`, `experiment_r3.py`, `experiment_r4.py`, `experiment_r5.py`, `experiment_r6.py`, `experiment_r7.py` or `experiment_r8.py`
with `--output` pointing to a new directory. Runners reject
existing output directories and tracked uncommitted changes. Preserve original
outcomes and record the reproducer's own environment and timing uncertainty.
