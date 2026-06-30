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

## One-Minute Product Explanation

Use this for short videos or comments:

> WaveMind is a local-first dynamic memory layer. It keeps durable memory in
> SQLite or Postgres, uses vector search only to find candidates, then applies
> memory-specific state: hotness, priority, decay, TTL, namespaces, tags, audit
> events, and optional graph dynamics. It is not trying to replace vector
> databases. It is meant to make memory behavior reusable on top of ordinary
> retrieval.

## What Not To Show

- Do not claim it is faster than Chroma in static retrieval.
- Do not claim full LoCoMo/LongMemEval answer-quality leaderboard status.
- Do not imply the current graph is a continuous physics field.
- Do not use private API keys or personal memory in public demos.

## Recording Checklist

1. Start from a clean terminal in the repository root.
2. Run `python examples/demo.py`.
3. Run `python examples/dynamic_memory_demo.py`.
4. Open README and show the benchmark table only after the demo.
5. End with the install command:

```sh
python -m pip install wavemind
```

## Suggested Captions

- "Vector search finds similar text. WaveMind tries to remember what still matters."
- "Local-first memory: SQLite source of truth, vector candidates, dynamic recall."
- "Corrections, TTL, namespaces, audit log, and index health in one small memory layer."
