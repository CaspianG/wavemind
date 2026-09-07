# Two authentic-data workflow lanes selected; no performance result yet

Selection date: 2026-09-07. The criteria and KPI contract were frozen at
`2995104` **before** the source search. This is a bounded source/measurement
decision, not a model evaluation, live pilot, or claim of indispensability.
The source pages were read; archives have not yet been downloaded or profiled.
All counts below are source-reported, not locally verified record counts.

## Consumer lane: read-only SMS spam suggestions

Select [UCI SMS Spam Collection](https://www.archive.ics.uci.edu/dataset/228/sms%2Bspam%2Bcollection),
Almeida and Hidalgo (2011), DOI [10.24432/C5CC84](https://doi.org/10.24432/C5CC84).
The repository lists CC BY 4.0, 5,574 labelled messages and a small downloadable
text archive. The collection combines actual volunteered/reported messages
and earlier corpora; it is not chronological and is not a current population
sample. Its historical labels can support a bounded offline spam-suggestion
check, not a present-day guarantee or automatically hiding people's messages.

Task: suggest spam/legitimate/abstain for a held-out message without contacting
senders, opening embedded links, moving messages or accessing a real inbox.
Report verified completion, spam recall and legitimate-message false-positive
rate, with full confusion counts. These are labels, not an LLM judge. Treat
annotation ambiguity as a documented limitation, not absolute external truth.

Strong comparators to freeze before execution: word-count multinomial Naive
Bayes, character-feature linear classifier, exact-content cache plus the
strongest development-selected classifier, and deterministic no-cache
inference. Cheap existing classifiers may leave no meaningful cost advantage
for a memory layer. No model has been trained or scored in this selection pass.

Split policy: group normalized exact duplicates before assigning development
or evaluation; never allow the same message in both. Freeze normalization and
seed before loading labels for selection. Do not infer chronology from file
order, invent task histories, or present duplicate hits as semantic transfer.
Audit inconsistent labels within duplicate groups and corpus-source leakage.

Privacy: retain raw records only in a local ignored intake directory; do not
print message bodies, phone numbers or embedded URLs in reports. No uploads,
external model calls or republication. Review the included readme and current
license for compatibility before accepting the archive; record any discrepancy.

## Enterprise lane: incident-history reconciliation

Select [UCI Incident management process enriched event log](https://archive.ics.uci.edu/dataset/498/incident%2Bmanagement%2Bprocess%2Benriched%2Bevent%2Blog),
Amaral, Fantinato and Peres (2018), DOI [10.24432/C57S4H](https://doi.org/10.24432/C57S4H).
The source lists CC BY 4.0 and an anonymized ServiceNow audit log from an IT
company: 141,712 events, 24,918 incidents, 36 attributes, a 2.3 MB compressed
download. Text fields are excluded. Identical visible rows can represent
distinct events; missing values mean unknown, not false or zero.

Task: reconstruct the observable incident state at successive recorded
updates and answer a read-only status/history query without omitting updates,
silently deduplicating events or carrying a previous state past a new update.
This tests an actual incident-management record workflow, not autonomous
resolution or an invented enterprise deployment.

Primary oracle: batch reconstruction of the same frozen visible event prefix;
compare exact incident/version/state outputs with an incremental implementation.
Report unresolved timestamp/order ties, missing state and contradictory rows.
The batch oracle checks consistency with this dataset, not the hidden original
ServiceNow database. Do not assume historical enriched attributes were actually
available at event time. A feature-availability audit must precede any predictive
task; resolution/closure fields must not leak into an earlier prediction.

Strong comparators: independent batch group-by, keyed incremental state table
with explicit event/version invalidation, and query caching over that table.
A memory candidate needs a concrete additional mechanism before comparison;
merely remembering the last incident state is a conventional incremental view.
No corporate SLA improvement or resolution-time reduction is asserted.

Split policy: keep whole incident identifiers in one partition. Preserve
original row order and all duplicates, then audit timestamp/update-counter
ordering before deciding what can be treated as an event stream. Freeze the
selection rule before reading outcome distributions. Exclude personal-role
identifiers from displayed outputs even though the source is anonymized.

## Source-selection ledger

| Lane / source considered | Selection outcome and reason |
|---|---|
| Consumer: Open Library | Deferred. [Operator guidance](https://openlibrary.org/developers/api) supports low-volume book lookup and ordinary caching; [catalog terms](https://openlibrary.org/help/faq/using) describe public-domain/CC0 catalog data. A JSON probe was rejected by the browsing tool; usable machine-readable intake was not demonstrated. No retry through another tool and no bulk scrape. |
| Consumer: UCI SMS | Selected for bounded offline intake, subject to archive/readme verification. Objective labels, small download, explicit repository license. |
| Enterprise: USAspending | Deferred. [API documentation](https://api.usaspending.gov/docs/endpoints) exposes public unauthenticated data, but this pass did not establish a controlling data-reuse license. This is an unresolved check, not a claim that the data are prohibited. |
| Enterprise: Find a Tender | Deferred. The attempted documentation endpoint returned HTTP 403 and terms retrieval failed. Not retried or bypassed. |
| Enterprise: UCI incident log | Selected for bounded offline intake, subject to archive and event-order checks. Authentic operational provenance and explicit repository license. |

Two consumer and three enterprise source families were considered, within
the preregistered cap. Selection was based on access, provenance, license and
oracle feasibility, not on a candidate's measured advantage. Search-result
snippets from GitHub were not opened; private account data were not accessed.

## Next cheap experiment: intake integrity, not a leaderboard

Before download, freeze a small read-only intake script/protocol which:

1. Records the exact official archive URL obtained from each source page,
   one download per source, UTC timestamp, SHA-256 and HTTP response status.
   Limits each compressed response to 5 MB and uncompressed members to 60 MB;
   never extracts archive paths directly into the workspace.
2. Audits the bundled license/readme. Stops evaluation on conflict or missing
   reuse authorization; no inference that an old "research only" statement
   permits unrestricted publication. No redistribution is planned here.
3. Reports parser success, actual row counts, permitted labels, duplicate
   groups and missingness without raw message/person fields. Keeps source
   count discrepancies visible rather than forcing the advertised count.
4. Produces deterministic entity-group split hashes and an event-order audit,
   **without training or scoring candidates**. Any unusable category remains
   visible. Freeze the later experiment only after measurement feasibility
   is established; do not retune prior scientific experiments.

Source pages establish discoverability and advertised download sizes. No
archive bytes, local dataset hashes, benchmark scores, new external baseline
runs, user sessions or company enrollments exist yet. Both mission gates remain
false. These lanes cannot retroactively validate the unrelated QEC algorithm.

KPI-design guidance influenced the choice of correctness denominators,
false-positive/stale-state guardrails and competent conventional comparators.
