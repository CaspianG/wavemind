# Official workflow intake: replay passes, baseline admission remains closed

As of 2026-09-07, the locally supplied official UCI archives have been fully
profiled without training, scoring, network access or changes to raw records.
This is data-quality evidence, not evidence of a scientific breakthrough or
consumer/enterprise usefulness. Both mission gates remain false.

## Evidence and preserved failure

The first audit correctly rejected the incident header: the saved UCI
description says `close_code`, but the CSV has `closed_code` in the same field
position. Before a second run, [amendment v2](WORKFLOW_INTAKE_AMENDMENT_V2.md)
was frozen at `a2f23fd3b38cce136b656d0f88e2b375e22fa1ed`. It changes only that
name in the schema and future-sensitive-field list. Source, rows, task,
normalization, partition seed and thresholds are unchanged. This is consistent
with a naming typo; author intent was not independently confirmed.

The first [result](runs/workflow_intake_v1/result.json), SMS split and empty
incident split are preserved byte for byte. Its result SHA256 remains
`257252b0642cb9680efa2b0817d4dbb0d3f16b911b943c149ca0bbc5164a304b`.
Original CRLF bytes initially triggered Git's trailing-whitespace check.
The exact archived path now declares CR-at-EOL whitespace and disables text
conversion; evidence bytes were not normalized to make the check green.

The amended [result](runs/workflow_intake_v2/result.json) SHA256 is
`db94535609f88b60f68acc82e608cfb386f72990d7b7d8397394de333a7c24cd`.
The SMS profile and manifest are exactly identical to the first run.
SMS split SHA256: `afe7bb594ec196af36150b92807e711d6728e73abf37d4f24905eb5f38a75ec8`.
Incident split SHA256: `b624174e8f9dedc4115117ed4d1b5a17b9747509924c2fcb4fa40588059a014f`.
No raw archive, message body or person identifier is committed.

## Profile and quality verdict

| Lane / unit | Rows | Groups | Train / development / evaluation rows |
| --- | ---: | ---: | --- |
| SMS / labeled physical line | 5,574 | 5,159 normalized messages | 3,883 / 844 / 847 |
| Incidents / update record | 141,712 | 24,918 incident IDs | 98,778 / 21,582 / 21,352 |

All rows are covered exactly once by the manifests; whole groups never cross
partitions. Hash intervals are 70/15/15, not exact row quotas. Neither lane
supports an inferred chronological split or cross-version schema-drift claim.

| Finding | Evidence / denominator | Severity and required handling |
| --- | --- | --- |
| SMS exact and normalized duplicates | 403 and 415 excess rows / 5,574 | Major: retain raw rows; group split is mandatory, row independence is not established. |
| SMS digit-template leakage | 4 templates, 12 rows across partitions | Blocking for semantic-generalization scoring: freeze a leakage-safe evaluation-subset rule before any model scores; never rebalance the existing manifest. |
| SMS labels | 4,827 ham / 747 spam; no conflicts, malformed or empty records | Class imbalance must be reported. No sender/time provenance means no future-distribution claim. |
| Incident outcome enrichment | `closed_at` later than update in 116,726 / 141,712 records; `resolved_at` later in 87,471 / 138,571 records with valid resolved time | Blocking for online prediction: outcome values cannot be treated as observable at update time. Reconciliation may concern visible supplied prefixes only, not reconstructed real history. |
| Incident chronology inconsistencies | 5 updates before opening; 1 timestamp regression in 1 incident; 4 counter regressions in 4 incidents | Major: do not silently sort/repair. Define deterministic visible-record semantics before baseline execution. Source timezone is unknown. |
| Incident missingness | `sys_created_at` 53,076 / 141,712 (37.45%); `assigned_to` 27,496 (19.40%); `cmdb_ci` 141,267 (99.69%); `caused_by` 141,689 (99.98%) | Major for tasks depending on these fields. Preserve missing markers; audit field eligibility rather than invent values. All column/partition counts are in the receipt. |
| Incident state vocabulary | 5 train records have an unrecognized hashed state; zero malformed integer/date/boolean values | Major if interpreting state transitions: unknown state must remain explicit, not silently mapped. |
| Incident duplicates/conflicts | 0 exact duplicate excess; 0 distinct rows sharing equal event key | These particular checks pass; absence of these conflicts does not establish true chronology. |

Monthly counts/state balance, all-column missingness by partition, naive date
ranges and input-member hashes are recorded in the full result. Profile-only
inspection of development/evaluation data has occurred; no model outcome was
seen. This is not an untouched-dataset claim.

## Terms review and admission decision

Both local source-page snapshots label the datasets CC BY 4.0. The archive
hashes match the controller-supplied provenance, whose retrieval time is
2026-09-07T13:10:18Z. This confirms local custody consistency, not independent
authentication of the download. Earlier network/browser denials remain in the
history; local supplied files did not authorize a browser workaround.

The agent read the SMS bundled README, including its full license/disclaimer
section. Alongside free-use wording it retains copyright, disclaims warranty,
limits liability and includes indemnity/hold-harmless wording. A request to cite
the work and notify authors was not treated as an instruction to send anything.
The incident archive contains only CSV, with no bundled terms file. Attribution
records remain in [the original protocol](workflow_intake_protocol.json).

**Actual human terms review is pending for both lanes.** The agent's inspection
is not legal clearance or a substitute for the human review explicitly required
by the task. A human must review the saved source pages and SMS README and
record approval or rejection for the planned local research use. This is not
a finding that the datasets are prohibited or that a replacement is necessary.

Decision: archival/profile intake accepted under the narrow header amendment;
both baseline admissions remain false. Next: human terms decision, then freeze
SMS leakage handling and incident visible-prefix semantics with cheap baseline
definitions before any training/scoring. No new dataset selected, no max run,
paid endpoint, release, merge or external publication occurred in this audit.

## Reproduction and QA

From the research worktree, with the supplied ignored input directory present:

```powershell
python research/breakthrough/workflow_intake_v2.py --archive-dir data/workflow_intake_20260907 --output research/breakthrough/runs/workflow_intake_v2 --verify
python research/breakthrough/workflow_intake_independent_qa.py --archive-dir data/workflow_intake_20260907 --run-dir research/breakthrough/runs/workflow_intake_v2
python -m pytest research/breakthrough -q
```

Full frozen v2 replay passed. [Independent pandas QA](runs/workflow_intake_v2/independent_qa.json)
passed 336 assertions/check groups, including every entity's partition and row
membership, duplicates, labels, template leakage, all-column/partition missingness,
valid dates, future dates, regressions and equal-key conflicts. It does not import
the original profiler, but shares the same input files and investigator; it is
not external replication. Bundled Python 3.12.14 / pandas 3.0.1 were used.

The complete research test suite passed: **82 tests + 5 subtests, 0 failures**
in 19.77 seconds. These are software tests, not model accuracy.
The [v2 companion notebook](workflow_intake_v2_review.ipynb) is executed through
standard Python sequential cell replay; Jupyter/nbclient/kernel execution is
unavailable and is not claimed. The original v1 notebook remains historical.

Data Analytics quality and validation workflows required the separate
denominators, independent recalculation and explicit admission hold above.
