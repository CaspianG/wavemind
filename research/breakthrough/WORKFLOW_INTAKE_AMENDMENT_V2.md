# Intake amendment 1.1: one incident field name, no outcome change

Date: 2026-09-07, after the first intake and **before any model scoring**.
The initial result is preserved in [runs/workflow_intake_v1/result.json](runs/workflow_intake_v1/result.json).
Its SHA-256 is `257252b0642cb9680efa2b0817d4dbb0d3f16b911b943c149ca0bbc5164a304b`.
The original script/protocol/tests at `3ce4cd7` remain unchanged.
The three preserved v1 output files have an explicit Git `-text` attribute,
so checkout cannot normalize their original line endings and invalidate the
byte-for-byte hashes. No raw archive or source-page HTML is added to Git.

## Evidence and authority for the correction

The controlling task supplied official local archives and provenance records.
Both archive hashes, both source-page snapshots, all extracted member hashes
and the complete original output were checked by a read-only replay. This
confirmed integrity, **not** enterprise schema acceptance: the original result
correctly has `schema_accepted: false` and an empty enterprise split.

The archived official UCI documentation describes field 33 as `close_code`,
an identifier for the resolution. The CSV header has `closed_code` at that
same position (zero-based 32), with the other 35 names in exactly the expected
order and no second competing close-code field. Their precise source hashes
are frozen in [workflow_intake_amendment_v2.json](workflow_intake_amendment_v2.json).

This supports treating the mismatch as a naming correction for the same field,
not a different outcome or task. It does not establish the data authors' intent
independently. The latest instruction explicitly authorizes a versioned naming
correction if the task remains the same; an interpretable alias does not make
the source unusable for incident-history reconciliation. No replacement is
selected merely to avoid this recorded failure.

## Only allowed semantic change

In an in-memory copy of protocol v1, replace `close_code` with `closed_code`
at its header position and in the future-sensitive-field list. No raw CSV is
rewritten. Keep the same archive, records, timestamp formats, missing markers,
source-row numbering, group keys, split seed/intervals and safety rules.
The wrapper verifies these are the only two changed values and that all frozen
v1 code bytes still match their original commit. The incident header must now
match exactly; no generic fuzzy mapping, column dropping or reordering is used.

SMS input/profile/split must remain exactly identical to the first audit.
The incident split did not exist before the schema failed; its first nonempty
manifest will follow the already frozen v1 entity/hash rule. It is not tuned
on incident outcomes. All original failures and receipt bytes remain present.

## Terms review is separate from schema repair

Both official page snapshots identify CC BY 4.0. The incident archive has no
additional bundled terms file. The SMS readme includes attribution/contact
requests, copyright, warranty/liability language and an indemnification clause.
The optional contact request is not an instruction to send a message; none
was sent. No terms were accepted through a browser and no data were uploaded.

The SMS readme is not UTF-8: the first inspection failed decoding; a subsequent
Latin-1 view preserved every byte and made the terms readable. A Windows
console encoding error during display was also corrected without changing the
archive. These are inspection-environment issues, not SMS record failures.

The agent can document and flag these texts; it cannot truthfully perform a
**human** terms review or give legal clearance. Because the controlling task
requires human terms review before baseline admission, both lanes remain
unadmitted until that prerequisite is actually recorded. Quality profiling
may continue locally on the user-supplied archives; no baseline scoring will
be smuggled into the audit.
