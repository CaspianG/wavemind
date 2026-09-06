# Starting state and targeted instruction audit

Date: 2026-09-06. Product base: `a465ac0e3a5610cadcf07320fcd08bf6873158f3`.
Work proceeds on `research/breakthrough-falsification-20260906` in an isolated
worktree. The base checkout was clean. Earlier CI reported 7/7 successful
workflows; this is engineering verification, not scientific admission.

## Evidence already available

- `benchmarks/scientific_performance_v32_validation_results.json`: exact
  selector agreement, 240 comparisons per repeat across three repeats,
  9.72–10.09x p95 speedup. Synthetic disk-backed performance evidence only.
- `benchmarks/scientific_v31_admission_outcome.json`: failed combined admission.
  Its aggregate reports +0.1086474501 accuracy difference, but only three
  improving categories, 70.71 s memory-query p95 against 1 s, and two metrics
  not operationally measurable under its preregistration. Saying "no measured
  uplift" would be inaccurate; saying "passed admission" would also be false.
- `scientific-memory-admission/README.md`: older v1 controllers failed (MAB
  zero effect; MemOps -0.400). This older record says the one-shot was untouched
  at that time; the later v31 record says its full run was consumed and failed.
  We do not assume a fresh unused one-shot exists now.
- Local verified-experience and attack-suite results remain bounded local
  evidence. No independent mass-indispensability result is present.

Only aggregate outcome/protocol files were read. Protected held-out questions,
answers and per-question v31 results were not opened for this work.

## Resources and external dependencies

Python 3.13.2 and NumPy 2.5.2 are available. SciPy is not installed in the
existing venv; the first experiment needs only NumPy. Shell access to GitHub
failed on port 443 under this turn's network restrictions. Web research can
read primary-source pages; a browser-readable page is not an executable,
SHA-pinned external baseline or measured physical dataset.

Follow-up: the read-only GitHub connector subsequently resolved QInfer and DAD
commit pins (see `baseline_pins.json`) and returned the QInfer EIG source.
Thus shell-network failure does not block source review. No external baseline
package or laboratory data has been executed; that distinction still applies.

No credentials were read or endpoints invoked. Physical device measurements,
independent external reproduction, consumer participants and an enterprise
pilot are absent from this phase. They become requirements for later gates,
not excuses to skip a local falsifier.

## Instruction audit

Checked the ancestor AGENTS.md locations between C:/ and the working project,
and searched the selected repository including hidden files for AGENTS.md and
SKILL.md (excluding dependencies and .git). No project-local instruction files
were found. `agents/` contains executable benchmark code, not agent directions.
There are no project-local duplicated instructions to remove.

The bundled OpenAI Docs skill was read for the requested model-guide check.
Its docs-first sequence is narrower than the scientific task; no extra route
reference was needed. Other installed skills are outside this repository and
were not mass-edited. Their displayed descriptions contain broad triggers and
some mandatory prerequisites, but changing installed plugins without testing
their actual workflows would not be a targeted project improvement.

[Official GPT-6 Astra guide](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6-astra)
was fetched: apply autonomous follow-through, task-relevant instruction review,
and proportionate validation here. [Eric Provencher's linked post](https://x.com/pvncher/status/2095991462416490862?s=46)
did not load through the web tool. Its text is not treated as read; the specific
audit criteria supplied in the mission are used directly. No cosmetic rewrite
or new blanket instruction file was introduced.
