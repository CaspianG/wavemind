# Public-workflow selection and measurement contract

Frozen before source selection or measurement, 2026-09-07. This is the next
practical branch, separate from the QEC theorem. Goal: find one ordinary
consumer workflow and one organizational workflow on authentic public data
where correctness and resource costs can be independently measured. Selection
does not imply that WaveMind improves either workflow.

## Acceptance criteria, before looking at outcomes

Each source/workflow must satisfy all of the following:

1. An identifiable real activity documented by its operator, not a fabricated
   benchmark story: e.g. finding/organizing public information for a person,
   or ingesting/reconciling a public operational feed for an organization.
2. Authoritative public machine-readable data and explicit reuse terms that
   permit this local evaluation. Preserve source URL, retrieval time, version
   or response hash, attribution, and exclusions. Public visibility alone
   is not a license. Do not fetch GitHub or private account contents.
3. Observable correctness: stable identifiers and complete retrieval, or a
   published objective answer. Separate missing values from negative answers.
   No LLM judge, guessed ground truth, reconstructed private users or labels.
4. Repeated tasks/changes where verified reuse could plausibly matter. Include
   exact lookup, ambiguous/missing records, changed query, and fresh/stale
   context. These are test-contract categories, not invented favorable data.
5. Free public reads and local CPU, with bounded requests/data. Respect site
   limits; do not retry rate-limit failures in a loop or change identities.
6. Low stakes: read-only metadata, no transactions, health/legal advice,
   account writes, messaging, purchases, confidential or personal payloads.

Reject sources with unclear reuse rights, mandatory paid credentials, no
measurable outcome, only synthetic records represented as real, or a safety
boundary requiring new permission. Preserve every rejection reason. Prefer
small official extracts over huge crawls; no more than three candidate source
families per lane in this first selection pass. Do not choose by candidate win.

## Comparisons required before a performance claim

Use the same task inputs, source snapshot, and correctness oracle for:

- Direct, stateless execution of the task with the source's documented API.
- A competent ordinary cache: canonical query keys, explicit source version
  or freshness contract, invalidation and conditional retrieval where offered.
- A task-specific deterministic implementation that avoids unnecessary calls.
- WaveMind only once a concrete integration and reuse admission rule exists.

Cache-hit rate alone is rejected as a primary metric: it can increase by
returning wrong or stale results. Raw answer length and total test count are
also rejected as usefulness metrics. A weak no-cache baseline is insufficient
to claim an innovation. If ordinary caching matches the candidate, record that.

## Measurement specification

Primary KPI 1: **verified completion rate** = tasks whose entire output passes
the predeclared independent source/identifier/completeness/freshness check,
divided by every attempted held-out task. Errors, timeout and abstention stay
in the denominator. Report their categories separately; missing source truth
is unresolved rather than success.

Primary KPI 2: **resource cost per verified completion** = total calls, bytes
and CPU/wall-clock cost across all attempted tasks divided by verified
completions, with numerator and denominator also shown. If the denominator is
zero, the ratio is undefined, not zero. Network and cached-local timing must
be reported separately. This measures bounded task efficiency, not money saved
or user time without actual measurements.

Drivers: admission/abstention rate and correctly invalidated changed-context
tasks. Guardrails: no false successful answer under the oracle and no stale
reuse beyond the predeclared source freshness contract. Measure worst category
as well as pooled completion so easy duplicates cannot hide failures.

Success thresholds are **not** inferred before data: first establish attainable
baseline correctness and measurement resolution. The mission's order-of-
magnitude aspiration is not a statistical target justified by these sources.
A proposed integration advances only if it matches the strongest baseline's
correctness with a reproducible cost advantage; a breakthrough requires the
separate, much stronger independent gates.

## Splits, selection and safety

Before processing a chosen dataset, freeze exact identifiers, filtering rules,
train/development/evaluation split by entity and (where available) time, query
construction rule, excluded columns, source snapshot, request cap, and oracle.
Do not tune on evaluation outcomes. Independently real records do not make
programmatically constructed queries into real logged user sessions; label
them as source-grounded test tasks. A public replay is not a live user pilot.

Initial source inspection cap: official documentation plus at most 20 small
read-only metadata responses per lane, no automatic bulk download. Stop on
access denial, ambiguous license, or rate limiting. No uploads, publication,
reviewer contact, reset credits, model endpoints or hardware calls.

Owner of local evaluation: this repository's investigation. No consumer,
company or external evaluator is represented as enrolled. Before operational
claims, obtain real task-owner validation and independently run evaluations.
Review cadence: after the fixed source-selection pass and each frozen replay,
not repeated unstructured metric hunting.

The Data Analytics KPI-design skill shaped this contract: correctness before
cache hits, explicit denominators, strong baselines, and stale-answer guardrails.
The primary artifact is this repository protocol, not a business dashboard.
