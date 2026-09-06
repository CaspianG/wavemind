# Breakthrough research — active, not achieved

This is the research entry point for the mission started on 2026-09-06.
The released WaveMind product is an input to the investigation, not evidence
that a scientific breakthrough has happened.

Both gates remain required: a novel, independently reproducible scientific
capability and an order-of-magnitude or previously impossible improvement in
real consumer and enterprise workflows. External expert scrutiny is required
before calling any result a breakthrough. A local experiment cannot close
either gate.

- [Что сделано и почему это ещё не доказанный прорыв — без жаргона](PLAIN_LANGUAGE_RU.md)
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
```

For reproduction, create a clean detached checkout at the run's source SHA
in `DECISION.md` (or the linked R5/R6/R7 reports), then invoke its `experiment_r1.py`,
`experiment_r2.py`, `experiment_r3.py`, `experiment_r4.py`, `experiment_r5.py`, `experiment_r6.py` or `experiment_r7.py`
with `--output` pointing to a new directory. Runners reject
existing output directories and tracked uncommitted changes. Preserve original
outcomes and record the reproducer's own environment and timing uncertainty.
