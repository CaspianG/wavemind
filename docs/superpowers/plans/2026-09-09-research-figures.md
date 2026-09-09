# Research Figures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish three evidence-backed research figures in the owner's approved light, dark-ink and orange style.

**Architecture:** One Python renderer consumes the existing, hash-verified figure data. It creates standalone HTML with inline SVG, then extracts portable SVGs using diagram-design's export procedure. Research Markdown embeds the SVGs; the existing conceptual cover remains unchanged except for its adjacent caption.

**Tech Stack:** Python standard library, existing NumPy evidence builder, pytest, existing Node Playwright with installed Chrome for local visual QA. No dependency installation.

**Spec:** `research/breakthrough/assets/FIGURE_CONTRACT.md`, style approved by the owner on 2026-09-09.

## Global Constraints

- Surface: Markdown in this repository, not a new dashboard or product website.
- Three figures, `doc-wide`, 1280 × 720, at least 40 px outer margin.
- English inside shared figures and Russian/English adjacent explanations.
- Paper `#f5f5f5`, ink `#2d3142`, muted `#4f5d75`, accent `#eb6c36`; Instrument Serif / Geist / Geist Mono with legible fallbacks.
- HTML source with inline SVG/CSS first, then derived SVG. No scripts, external images or fonts other than the approved Google Fonts stylesheet.
- Layout constants follow the 4 px grid. Numerical plot positions do not.
- Frozen scientific sources, protocols, data and `build_figure_data.py` must not change.
- Scientific advantage gate remains false. No hardware measurement or scientific novelty claim.
- No push, merge or external publication in implementation tasks.

## Task 1: Reproducible renderer and exports

**Files:**
- Create `research/breakthrough/assets/render_figures.py`.
- Extend `research/breakthrough/assets/test_render_figures.py` only for renderer behavior.
- Generate `sensing-model.html/.svg`, `pulse-comparison.html/.svg`, `drag3-waveform.html/.svg` in the same assets directory.
- Other documentation is owned by the coordinating agent; do not edit it.

**Interfaces:**
- Consume `build_figure_data.build() -> dict` and checked-in `figure-data.json`.
- Produce CLI `python research/breakthrough/assets/render_figures.py [--output-dir DIRECTORY] [--check]`.
- No arguments regenerate the six named files in the assets directory; `--check` verifies identical bytes without writing; `--output-dir` selects a directory for generation or comparison.

- [x] Write tests for CLI generation, XML accessibility, 8 bar values/lengths, all 771 control points and deterministic checked-in outputs.
- [x] Observe the first CLI test fail before implementation (2026-09-09): `1 failed`, renderer not yet present. Baseline outside the new renderer tests: `42 passed in 3.93s`.

- [x] Implement the minimal renderer. First verify the frozen input, fail explicitly if it differs, then render:

```python
data = json.loads((HERE / "figure-data.json").read_text(encoding="utf-8"))
if data != build():
    raise ValueError("Figure inputs differ from verified frozen evidence")
```

Use explicit pure helpers for text escaping and shared SVG/HTML framing. Keep it one focused renderer, not a new framework. Adapt upstream template and export procedure (MIT already present): `ct/work/diagram-design-20260908/skills/diagram-design/assets/template.html` and `references/export.md`.

Each SVG needs `role="img"`, unique slug-prefixed title/desc IDs, first-child title before defs, visible title/subtitle/source inside SVG, one defs block, `xmlns`, no `foreignObject`. Extract the first SVG from HTML, inject XML-escaped font import into existing defs, normalize rgba presentation attributes and transparent colors, prepend XML declaration. Check missing SVG/viewBox with explicit exceptions. Keep generated files deterministic, LF endings.

Figure 1: architecture schematic, four stages (weak oscillating field → three-level evolution with 64 pulses → six finite readout settings → information / total time), plus a dashed branch for unwanted third-level excitation. This is a model, not wiring or a built device. No named software architecture pattern fits. Use 4–5 nodes, 3–4 connectors; no gradients/shadows. 64 pulses, six readouts, common time 74.25 are protocol values. Keep arrows away from text, one highlighted control node at most.

Figure 2: eight individually labeled horizontal categories, in source order, RS then best-known RXY8 for each waveform. This preserves four comparisons without a grouped legend or violating the upstream two-group limit. Label RS_prefix as RS but retain full method ID in data attributes. Orange only for DRAG3/RS; other bars dark/muted. Minima are over 9,216 finite-grid settings, not continuous guarantees. RXY8 averages 32 retained phase realizations sharing one budget; no error bars misrepresenting seed error as a global-minimum confidence interval. Complete 36-combination result remains linked by Markdown. Use:

```python
x = 352
width = minimum_rate / 0.016 * 760
y = 196 + row_index * 48
height = 24
```

Axis 0–0.016, ticks every 0.004; value labels outside bar ends, no minimum-width clamp. Add `data-method` and exact `data-value` to each bar. FAST_RECT/RS is legitimately subpixel: its explicit number must remain visible. Takeaway title should accurately say shaping helps both methods; caption/footer must retain negative gate and model boundary. 98.34% is candidate/best, not accuracy or pass rate. Do not plot the 2.0 threshold as an unrelated FI value.

Figure 3: three scientific polylines, all 257 supplied samples each, no spline or rounding to design grid. X primary drive, Y derivative quadrature, d longitudinal level control. Signed shared axes, distinct solid/dashed patterns and legend/direct labels, orange on X only; every label dark. Use:

```python
x = 112 + time / 0.25 * 1088
y = 544 - (amplitude + 8) / 36 * 360
```

Plot bounds x112..1200, y184..544, time 0..0.25 tau, amplitude -8..28 inverse tau. Visible zero; `data-component` on each polyline, numerical serialization accurate within 1e-9 pixels. Caption: commanded controls, not measured traces. Additional d control is not free software; equal caps are not equal consumed energy. Record actual 47.47% extra RF cost in adjacent Markdown, not a fabricated curve.

- [x] Run `python -m pytest research/breakthrough/assets/test_render_figures.py -q -p no:cacheprovider`, `python research/breakthrough/assets/render_figures.py --check`, `python research/breakthrough/assets/build_figure_data.py --check`.
- [x] Run inspected upstream `self_check.py` and `verify-geometry.py` on all three HTML files. These are structural checks, not visual or scientific proof.
- [x] Self-review, commit only the renderer, its test and six generated files. Do not stage coordinating-agent docs. Report exact tests/output and any visual uncertainty. Controller performs actual Chrome/font/README QA and independent code review before publication.

## Verification record — 2026-09-09

Renderer commit `493b82e`: seven renderer tests pass, frozen figure inputs match,
all six exports match, upstream self-checks pass and geometry has zero findings.
Independent task review approved spec compliance and code quality. The controller
visually checked all three embedded figures and RU/EN desktop/mobile guides.
The combined sensing, figure and document checks passed all 53 tests.

At `037b51d`, the configured product suite passed 1415 tests with zero failures,
16 skips and one existing MCP/Pydantic warning. The initial README-length and
README-digest failures were resolved without changing the guards; the validity
admission remains blocked (15 of 16 checks), not admitted. Ruff passes.
The presentation QA JSON records commands, limitations and final-review status.
No package build, GitHub CI, push, merge or release is claimed by this record.

Final review cleanup `33295c5` makes small tag labels dark, removes unused SVG
markers and adds exact ordered bar/row-geometry regressions. Nine renderer
tests pass; the combined sensing/figure/document suite now passes 55 tests.
All three figures and four language/viewport previews passed Chrome QA again;
the changed model SVG was visually reinspected. Numerical evidence is unchanged.
The single scoped re-review confirmed all three findings addressed and no new
breakage. Publication approval remains pending; the existing worktree is kept.
