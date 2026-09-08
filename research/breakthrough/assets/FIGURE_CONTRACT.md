# Figure contract: quantum sensing v1–v3

Status: data and editorial contract prepared; first-project diagram-design
style selection awaits the repository owner's answer. Do not treat a
preselected UI option as submitted approval or write a project profile marker
without consent.

## Shared contract

Audience: interested non-specialist first, technical reviewer second.
Surface: Markdown in this repository, not a new dashboard or product website.
Proposed footprint: `doc-wide`, 1280 × 720, at least 40 px outer margin,
large readable labels, English inside shared figures and Russian/English
adjacent explanations. Each figure answers one question.

Use the requested diagram-design workflow: HTML source with inline SVG/CSS
first, then derived SVG and PNG. Accessible SVG title and description,
descriptive Markdown alt text, visible source and simulation boundary.
Fonts must actually load before export; report any fallback honestly.
No generated bitmap contains plotted data or exact labels.

Proposed visual direction, not yet selected: neutral paper, dark ink, one
orange focal element, Instrument Serif / Geist / Geist Mono. Other valid
choices offered are the existing WaveMind palette or user-provided tokens.
Layout constants follow the 4 px grid. Numerical plot positions do not:
rounding their coordinates to a decorative grid would change the data.

## 1. What the model measures

- Question: how does a weak field become an information score?
- Type: architecture schematic, four stages plus one unwanted-level branch.
- Story: controlled three-level evolution is followed by six finite readout
  settings and a common total-time denominator.
- Labels: weak oscillating field, 64 controlled pulses, six readout settings,
  information per total time; unwanted third-level excitation is a distinct
  path, not a real device component.
- Source: `sensing_rs/PULSE_V3_THEORY.md`, `protocol_v3.json`, `pulse_v3.py`.
- Omitted: full matrix elements and all calibration settings; link the frozen
  theory. It must not look like a manufactured sensor or its wiring diagram.
- Encoding: direct labels; solid/dashed edges distinguish meaning, not color
  alone. No quantitative position or bar length in this schematic.

## 2. Minimum information rate by pulse shape

- Question: does shaping benefit only RS, or also strong known controls?
- Type: grouped horizontal bars, four shapes × two sequences = eight bars.
- Quantity: minimum of `fi_rate` across 9 × 1024 v3 grid points, model units.
- Source: `sensing_rs/runs/pulse_v3/results.json`, each `screen` row and
  matching `screen_{wave}_{sequence}.npz`.
- Inclusion rule: RS and the best minimum among non-RS known sequences for
  each shape. The selected best is RXY8 in all four groups. No outcome is
  silently removed: all 36 combinations remain linked in the complete JSON.
- Encoding: common linear axis starting at zero, explicit sequence labels,
  no minimum pixel width that exaggerates FAST_RECT/RS. Orange can highlight
  only the current DRAG3/RS candidate; direct text identifies every method.
- Takeaway for caption: shaping improves RS, but DRAG3/RS is 0.9834 times the
  best known minimum, below the frozen 2.0-times advantage threshold.
- Uncertainty: deterministic finite grid with synthetic parameters; RXY8 is
  a mean over 32 fixed phase realizations sharing one budget. Its seed error
  at the worst point is not a confidence interval for a global minimum.
- Cost note: DRAG3 uses 47.47% more RF energy than RECT plus level control;
  all methods have the same caps/menu, not identical consumed energy.

## 3. Components of the fixed DRAG3 pulse

- Question: what did the mechanism actually change inside an impulse?
- Type: three directly labeled lines, X(t), Y(t) and d(t).
- Quantity: amplitudes in model units vs local time u/tau in [0, 0.25].
- Source: analytical `waveform('DRAG3', t)` in frozen `pulse_v3.py`.
- Sampling: 257 fixed evenly spaced points, straight polyline connections,
  no spline smoothing, no synthetic decorative wave. This deliberately
  exceeds a business chart's suggested point count to retain a scientific
  waveform's extrema and sign changes. Three series only.
- Encoding: common signed linear axis with visible zero, distinct dash
  patterns and direct component labels. One accent series at most.
- Interpretation boundary: these are commanded shapes, not oscilloscope
  measurements; d(t) is additional physical control, not free software.
- Omitted: phase coding of all 64 pulses and finite readout tail, documented
  in the linked full protocol. This figure does not prove leakage reduction.

## QA before handoff

1. Verify run manifests and source hashes before loading any plotted value.
2. Check values, denominator, selection rule, zero/bounds and all labels
   against the frozen data. Never transfer the v2 continuous guarantee to v3.
3. Run upstream self-check and geometry checks after inspecting the scripts.
4. Inspect actual PNG exports and the final Markdown at normal reader size;
   check clipped labels, font loading, contrasts and grayscale interpretation.
5. Preserve HTML sources, export provenance and upstream MIT attribution.
6. Re-run figure-data checks after future scientific updates; do not manually
   edit a chart to make a research gate appear passed.
