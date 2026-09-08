# Sensing research handoff — not a breakthrough or device release

2026-09-08. Prepared locally; not sent to anyone. No laboratory, reviewer,
participant, customer or partner is represented as enrolled.

## Current decision

v1 derived a first-order leakage bound but its selected binary readout had
eight counterexamples to uniform sensitivity. v2 removes those eight blind
spots in a more explicit readout/noise model. Its matched-budget screen
fails against randomized XY8. v3 then tests known pulse-local compensation
under common caps and waveform choices. DRAG3 improves the RS grid minimum
12.37-fold over RECT/RS on the same new grid, but DRAG3/RXY8 remains stronger.
The added RF energy and physical longitudinal channel are reported, not free.
This is a useful research testbed, not an admitted superior sensing protocol.

Entry points: [v1 derivation](THEORY.md), [v1 adverse evidence](RESULTS_RU.md),
[v2 protocol](protocol_v2.json), [v2 derivation](READOUT_V2_THEORY.md),
[v2 result](RESULTS_V2_RU.md), [v3 protocol](protocol_v3.json),
[v3 mechanism](PULSE_V3_THEORY.md), [current result](RESULTS_V3_RU.md).

## Questions for an independent theory reviewer

1. Does the arbitrary-input, first-derivative leakage bound in THEORY.md
   follow with the stated pulse times, sign convention and boundary term?
   Is the precise result already a direct consequence of published pulse
   constructions? RS polynomial bounds themselves are known.
2. Does the mixed-propagator derivative bound used to bound six-component
   readout curvature hold for every detuning under the fixed Hamiltonian?
   Check all factors of 2π and the contribution during analysis pulses.
3. What would be needed to replace the declared floating endpoint allowance
   with a rigorous interval enclosure? Current covers are conditional,
   not interval-arithmetic certificates.
4. Does the v3 convention implement the cited leading DRAG terms correctly,
   including both driven transitions and `d(t) diag(0,1,2)`? What platform
   can actually supply that added control within measured bandwidth limits?
5. Is there a distinct, feasible mechanism left that could beat known
   controls under a fair resource contract? Neither multi-basis readout
   alone nor the frozen DRAG3/RS combination has demonstrated that advantage.

Agreement from the same author or another test in this repository does not
count as an independent review. No scientific-priority verdict is requested
on the basis of a search returning no exact match.

## Reproduce locally

Use a clean checkout containing the archived runs and unchanged frozen
sources. Python 3.13.2 and NumPy 2.5.2 were used; SciPy is not required.
Pytest is required only for the tests. No network or hardware is contacted.

```sh
python -m pytest research/breakthrough/sensing_rs -q -p no:cacheprovider
python research/breakthrough/sensing_rs/experiment_v3.py --output /NEW/EMPTY/PARENT/pulse-v3-replay
python research/breakthrough/sensing_rs/verify_v3_replay.py /NEW/EMPTY/PARENT/pulse-v3-replay --check-git
```

Expected v3 outcome: 36 combinations, 9,216 grid points each, numerical gate
true, combination advantage false, mission complete false. The fresh local
replay matched 228 arrays and one scientific JSON record; 43 archived files
matched Git blobs byte for byte. Frozen v3 source:
`cd73cd5028bfa6820039e96c29c1f00e000b4aa6`.

For the preserved v2 experiment:

```sh
python research/breakthrough/sensing_rs/experiment_v2.py --output /NEW/EMPTY/PARENT/readout-replay
python research/breakthrough/sensing_rs/verify_v2_replay.py /NEW/EMPTY/PARENT/readout-replay --check-git
```

Replace the placeholder with a new local path. The output directory itself
must not exist. The runner refuses tracked uncommitted changes and never
overwrites an evidence directory. Frozen experiment source:
`66550207872d662e059d6b43bf29b0c4ee6c9edc`; later commits add evidence and
verifiers, not changed experimental parameters. Git ownership errors on a
shared Windows installation should be handled for this verified checkout
only, not with a global wildcard trust setting.

Expected scientific outcome: eight repaired roots, nine complete
conditional detuning covers, advantage gate false, mission complete false.
The repeat must preserve the failed gate. Source and payload digests are
in each run's provenance and checksums manifests. Focused sensing software
tests currently number 35 across v1–v3; test count is not a scientific
success criterion. The historical v2 validation record retains its original
24-test count and is not rewritten as if v3 existed at that time.

## Inputs required before an equipment experiment can be designed

- A specified physical sensor and independently measured levels, couplings,
  drive selectivity and usable frequency range. The three-level ladder
  cannot simply be relabeled a complete NV-center model.
- Preparation fidelity, timing limits, phase-switching/transient errors,
  photon statistics and registration overhead. Simulated probabilities
  0.10/0.07 and 10τ overhead must be replaced by measurements.
- Noise spectrum, drift and parameter-estimation uncertainty. Check whether
  signal changes can be distinguished from changes in calibration. Current
  single-parameter FI assumes the calibration values are known.
- Signal frequency/phase and amplitude range, or an explicit acquisition
  protocol with its time cost if they are unknown.
- A laboratory-approved benign field/current reference and independent
  reference readings. The dimensionless schedule is not a device driver.

No equipment purchase, paid remote execution, risky battery experiment,
disabling of protection, or external message is authorized by this packet.
Lab-specific operating and safety procedures belong to the qualified operator.

## Practical falsifier before a consumer/enterprise claim

Choose one concrete inspection task and freeze it before viewing results:
what constitutes a defect, who labels it independently, what errors matter,
what the ordinary non-quantum baseline is, and which objects are held out.
Separate repeated readings of one object from genuinely new objects.

Evaluate detection/estimation errors, total time per object, calibration
time, cost, failure handling and operator burden under the same conditions.
Compare the quantum device, strong known pulse controls and the ordinary
inspection method. An improved FI score alone does not pass this test.
The mission's order-of-magnitude or previously impossible real-workflow
criterion remains a prospective requirement, not a result or sales claim.

## Stop / continue rule

Keep the readout and pulse shaping as validated components of the local
model, within their stated numerical limits. Do not retune v2 or v3 on their
test outcomes and overwrite the failed evidence. A follow-up is a
new, predeclared hypothesis with a stated physical mechanism, prior-art
distinction and a new comparison including shaped RXY8. Physical and mass-use
claims require the measurements above; local theoretical work need not wait
for hardware, but must not claim that hardware validation has happened.
