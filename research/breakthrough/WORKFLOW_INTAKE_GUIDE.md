# Public workflow intake: frozen checks and access history

## Current update — 2026-09-07

The controller has supplied local official archives and provenance. The first
schema failure is preserved, and a frozen header-only amendment has passed
full replay and independent pandas QA. See [actual results and admission
hold](WORKFLOW_INTAKE_V2_RESULTS.md) and the [current notebook](workflow_intake_v2_review.ipynb).
Both baselines remain unadmitted pending actual human terms review and frozen
leakage-safe evaluation semantics. The access-denial account and original
preflight/notebook observations below are historical, not the current intake state.

The task is a data-quality/reproducibility audit, not training or scoring.
The primary deliverables are repository protocol, checker, tests, split
manifests when actual data arrive, and a companion notebook. No workbook,
dashboard, model endpoint or cloud publication is part of this task.

## What is frozen before real data

[workflow_intake_protocol.json](workflow_intake_protocol.json) specifies
sources, schema, bounded archive handling, normalization and deterministic
70/15/15 hash intervals by whole entity. These are expected approximate shares,
not guaranteed row counts. SMS groups ignore labels; incident groups contain
the entire incident. No target-aware rebalancing is allowed after the intake.

[workflow_intake_audit.py](workflow_intake_audit.py) is deliberately offline.
It cannot fetch data, upload anything, train a classifier or score a candidate.
It reads bounded ZIP members in memory and never extracts member paths. Missing
inputs and schema/license problems remain visible; a green parser test is not
permission to score or evidence that real data passed.

## Access and provenance prerequisite

Terminal socket requests to the official UCI source pages failed under the
environment's network permissions. Browser Use then explicitly denied access
to `archive.ics.uci.edu` because permission was declined. This is an access
decision, not an observed dataset failure. No mirrors, other browser surfaces,
alternate hostnames, proxies or connectors were used to get those archives.
No replacement dataset is justified solely by this access denial.

After authorized download or user upload, keep raw files in the ignored
`data/public-workflow-intake/` directory, not under tracked `research/runs`.
For each lane provide:

- `sms.zip` / `incidents.zip`: the unchanged official archive;
- `sms.source.html` / `incidents.source.html`: the official dataset page
  snapshot showing the archive link and current license;
- `sms.provenance.json` / `incidents.provenance.json`: source page, actual
  official archive URL, UTC retrieval time, method, archive SHA-256, source
  snapshot SHA-256, and license identifier `CC-BY-4.0`.

Archive URLs are intentionally not guessed from a naming pattern. They must
appear in the supplied official page snapshot. A local provenance file and
checksums record custody; they are not independent authentication of an
untrusted uploader. Any uncertainty about origin must remain disclosed.

If the data owner supplies only archives, first record that receipt honestly.
Do not invent HTTP status, retrieval time or a missing source-page snapshot.
Resolve missing provenance before calling the intake accepted.

## Run and inspect

After freezing a clean commit and assembling verified inputs:

```sh
python research/breakthrough/workflow_intake_audit.py --archive-dir data/public-workflow-intake --output research/breakthrough/runs/workflow_intake_unique
```

Use a fresh output directory. Preserve all failures. The runner records source
hashes and the exact split manifests, plus aggregate results without message
bodies or person identifiers. It always leaves baseline admission false:
license terms and quality findings need review before a separately frozen
baseline experiment. Unknown schema/version drift is not reported as zero.

The companion [notebook](workflow_intake_review.ipynb) displays the protocol,
recorded access status and optional real-data results. In this environment the
Jupyter kernel/nbclient packages are absent. Its cells are checked and replayed
sequentially with standard Python, not claimed to have run in Jupyter. To verify
the notebook in a Jupyter-enabled environment, run:

```sh
python -m jupyter nbconvert --execute --to notebook --inplace research/breakthrough/workflow_intake_review.ipynb
```

## Baseline boundary

No real-data profile, immutable data-dependent split, class balance, leakage
count or schema-change result exists until the archives pass intake. Synthetic
unit fixtures test the checker only; they are not substitutes for those data.
After intake, inspect findings first and freeze a baseline protocol before
training/scoring. Strong SMS classifiers and conventional incremental incident
state tables remain required comparisons. No paid call is authorized.

The Data Quality skill shaped the separate missingness, duplicate, leakage and
time checks. Spreadsheet research guidance requires intact raw observations and
explicit unknown values; no input rows are rewritten here. Computer Use rules
require stopping the denied browser path. The Jupyter skill supplies the
inspectable companion, with its execution limitation stated explicitly.

## Local validation, not a data-quality result

Fifteen synthetic security/parser unit tests passed under bundled Python
3.12.14 (latest repeat: 0.024 s). The complete research suite passed 76 tests
and five subtests in 18.80 s under the research test environment. Ruff passed.
Three notebook code cells replayed in standard Python; no Jupyter kernel ran.
Actual archive downloads, data-dependent split hashes, training and scoring
remain absent. The authoritative access record is
[workflow_intake_status.json](workflow_intake_status.json).
