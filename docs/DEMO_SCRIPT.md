# WaveMind Demo Script

This is the public demo script for launch videos, GIFs, README snippets, and
conference-style walkthroughs. Keep it reproducible and honest: no external
keys, no network, no hidden setup.

## 30-Second Terminal Demo

Goal: show that WaveMind works immediately after cloning.

```sh
python examples/demo.py
```

What to say:

> WaveMind stores local memory in SQLite-compatible state and returns a small
> recall set from a normal command-line workflow. This demo is offline and
> keyless.

Expected shape:

```text
[ok] Remembered: "Andrey is a trader who tracks market breakouts."
[ok] Remembered: "Andrey prefers short practical answers about AI agents."

Query: "Andrey trader agent"
-> Result 1 (...): "..."
-> Result 2 (...): "..."
```

## 60-Second Dynamic Memory Demo

Goal: show why WaveMind is not just static nearest-neighbor search.

```sh
python examples/dynamic_memory_demo.py
```

What it demonstrates:

- a corrected newer fact outranks a stale fact;
- a temporary memory expires and is not recalled by its tag;
- two users stay isolated by namespace;
- the candidate index reports health against source-of-truth memory ids.

Narration:

> Vector search answers "what is similar?" Agent memory also needs "what still
> matters?" Here the old budget is still in memory, but the corrected budget
> ranks first. The temporary discount code expires. Maria's namespace does not
> leak into Andrey's recall. The index-health line shows whether candidate
> search is synchronized with durable memory.

Expected shape:

```text
WaveMind dynamic memory demo

[store]   user:andrey -> "User budget is $500."
[correct] user:andrey -> "User budget is $2000."
[expire]  user:andrey -> "Temporary discount code is ALPHA-24."
[store]   user:maria  -> "User budget is $9000."
[purge]   expired memories removed: 1

Query user:andrey: "what is the user budget?"
-> Result 1 (...): "User budget is $2000."
-> Result 2 (...): "User budget is $500."
[ok] corrected newer budget outranks the stale budget

Query user:maria: "what is the user budget?"
-> Result 1 (...): "User budget is $9000."
[ok] namespace isolation keeps Maria separate from Andrey

Query user:andrey temporary tag: "discount code"
[ok] expired temporary memory is not recalled

Index health
[ok] numpy-exact healthy=True expected=3 vectors=3
```

## 90-Second Verified Experience Demo

Goal: show the actual product breakthrough rather than only memory retrieval.

```sh
python examples/verified_experience_runtime.py
```

Narration:

> A normal memory system can save what an agent said. WaveMind waits for an
> independent outcome. This cold run fails, so the failed procedure is
> preserved but not promoted. Repeated verified executions create a bounded,
> cited Experience Packet. A held-out run can reuse that packet, and an
> operator can inspect or roll it back. The agent learns from proof, not from
> its own confidence.

Show these moments:

1. the cold attempt and independent verification;
2. the candidate remaining in shadow before its evidence threshold;
3. the cited Experience Packet on the next run;
4. the successful held-out outcome;
5. inspection and rollback.

## One-Minute Product Explanation

Use this for short videos or comments:

> WaveMind is a trust layer for agent memory. It captures completed tool work,
> waits for a test, tool, operator, or downstream state to verify the outcome,
> and promotes only a bounded procedure. The next run receives a compact
> Experience Packet with its evidence, scope, corrections, and rollback path.
> Vector search can still find candidates; WaveMind governs what is safe to
> carry forward.

## What Not To Show

- Do not claim it is faster than Chroma in static retrieval.
- Do not claim full LoCoMo/LongMemEval answer-quality leaderboard status.
- Do not imply the current graph is a continuous physics field.
- Do not use private API keys or personal memory in public demos.

## Recording Checklist

1. Start from a clean terminal in the repository root.
2. Run `python examples/demo.py`.
3. Run `python examples/dynamic_memory_demo.py`.
4. Run `python examples/verified_experience_runtime.py`.
5. Open README and show the evidence table only after the product loop.
6. End with the install command:

```sh
python -m pip install wavemind
```

## Suggested Captions

- "Vector search finds similar text. WaveMind tries to remember what still matters."
- "Local-first memory: SQLite source of truth, vector candidates, dynamic recall."
- "Corrections, TTL, namespaces, audit log, and index health in one dynamic memory layer."
- "The agent learns from an independently verified outcome, not from its own confidence."
- "Every reusable procedure keeps its source, scope, and rollback path."
