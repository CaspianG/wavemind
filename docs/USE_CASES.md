# WaveMind Use Cases

WaveMind is useful when stored information changes in importance over time.
If the data is a static document corpus, a mature vector database may be the
right primary tool. If the data is memory, preference, correction, temporary
context, user history, or agent state, WaveMind is the layer that makes those
rules explicit.

## 1. Long-Running Agent Memory

Problem:

An agent remembers facts for a few turns, then loses preferences, repeats old
mistakes, or recalls stale information.

Pattern:

```python
from wavemind import WaveMind

memory = WaveMind(db_path="./state/agent-memory.sqlite3")

def before_llm(user_id: str, message: str) -> str:
    namespace = f"user:{user_id}"
    hits = memory.query(message, namespace=namespace, top_k=5, min_score=0.25)
    return "\n".join(f"- {hit.text}" for hit in hits)

def after_turn(user_id: str, fact: str) -> None:
    memory.remember(fact, namespace=f"user:{user_id}", tags=["conversation"])
```

Remember:

- user preferences;
- stable profile facts;
- decisions;
- corrections;
- summaries after long tasks.

Avoid:

- storing every raw message forever without summarization;
- mixing users in one namespace.

## 2. Personal Assistant

Problem:

A personal assistant needs local memory that can be inspected, backed up, and
forgotten on request.

Pattern:

```python
memory.remember(
    "User prefers short direct answers.",
    namespace="user:local",
    tags=["preference"],
    priority=3.0,
)

memory.remember(
    "Temporary travel plan: Berlin next week.",
    namespace="user:local",
    tags=["temporary", "travel"],
    ttl_seconds=7 * 24 * 3600,
)
```

Why WaveMind:

- SQLite source of truth;
- TTL for temporary context;
- explicit `forget()`;
- audit events;
- local-first operation.

## 3. Customer Support Or CRM Memory

Problem:

Support bots need to remember a customer's preferences, previous issues, and
resolved problems without leaking data between accounts.

Runnable demo:

```sh
python examples/customer_support_memory.py
```

The demo is offline and keyless. It shows four behaviors support teams usually
have to implement by hand: corrected CRM data outranking stale data, temporary
discount codes expiring, customer namespaces preventing cross-account leakage,
and audit-friendly state in SQLite.

Pattern:

```python
namespace = "tenant:acme:customer:42"

memory.remember(
    "Customer reports invoices should be sent to finance@example.invalid.",
    namespace=namespace,
    tags=["billing", "preference"],
)

memory.remember(
    "Resolved issue: SSO login failed because SAML certificate expired.",
    namespace=namespace,
    tags=["support", "resolution"],
)

hits = memory.query("what do we know about billing?", namespace=namespace, tags=["billing"])
```

Why WaveMind:

- namespaces for tenant/customer isolation;
- tags for workflow filters;
- audit log for compliance review;
- HTTP API for non-Python systems.

## 4. Research Notebook Or Analyst Memory

Problem:

Research work changes over time. Some hypotheses expire, some findings become
core, and source metadata matters.

Pattern:

```python
memory.remember(
    "Hypothesis: latency spikes are caused by index rebuilds.",
    namespace="project:latency",
    tags=["hypothesis"],
    ttl_seconds=14 * 24 * 3600,
    metadata={"source": "incident-review-2026-06"},
)

memory.remember(
    "Confirmed: p95 latency improved after reducing rerank_k.",
    namespace="project:latency",
    tags=["finding", "performance"],
    priority=4.0,
)
```

Why WaveMind:

- temporary hypotheses can expire;
- confirmed findings can get higher priority;
- source metadata stays attached to recall results.

## 5. Trading Or Market-Research Agent

Problem:

Market agents often confuse stale assumptions with current conditions.

Pattern:

```python
memory.remember(
    "BTC thesis: breakout requires volume confirmation.",
    namespace="strategy:btc",
    tags=["thesis", "risk"],
    metadata={"source": "research-note"},
)

memory.remember(
    "Invalidated: previous support level failed after CPI release.",
    namespace="strategy:btc",
    tags=["correction", "risk"],
    metadata={"conflict_group": "btc-support-level"},
    priority=5.0,
)
```

Why WaveMind:

- corrections can outrank stale facts;
- temporary signals can use TTL;
- strategies can stay isolated by namespace.

Important:

WaveMind is a memory layer, not a trading strategy. Backtests, fees, slippage,
and risk controls are separate.

## 6. Internal Company Copilot

Problem:

Company copilots need memory across projects, but must keep teams and users
separate.

Pattern:

```python
namespace = "org:acme:team:infra"

memory.remember(
    "Decision: use PostgreSQL source-of-truth for production memory.",
    namespace=namespace,
    tags=["decision", "architecture"],
    metadata={"ticket": "ARCH-123"},
)

hits = memory.query("why postgres?", namespace=namespace, tags=["decision"])
```

Why WaveMind:

- project/team namespaces;
- durable decisions;
- metadata for provenance;
- backup/restore and audit.

## 7. HTTP Sidecar For Any Runtime

Problem:

The main app is not Python.

Pattern:

```sh
wavemind --db ./state/wavemind.sqlite3 serve --host 127.0.0.1 --port 8000
```

Store:

```sh
curl -X POST http://127.0.0.1:8000/remember \
  -H "Content-Type: application/json" \
  -d '{"text":"User prefers concise answers","namespace":"user:42","tags":["preference"]}'
```

Query:

```sh
curl -X POST http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query":"answer style","namespace":"user:42","top_k":3}'
```

Why WaveMind:

- usable from Node, Go, Ruby, PHP, no-code, or shell;
- API keys and rate limits are opt-in;
- `/metrics`, `/audit`, `/backup`, and `/index/health` support operations.

## 8. Migration From Static Retrieval

If you already have a vector store, keep it. Add WaveMind where memory policy is
currently spread across application code.

Start with:

- user preferences;
- corrections;
- temporary context;
- decisions;
- support resolutions;
- profile facts.

Do not start with:

- millions of static documents;
- large public web corpora;
- raw logs without filtering;
- workloads where plain vector search latency is the only success metric.

## Production Checklist

Before using WaveMind in a production service:

- choose explicit namespaces;
- use a stable `db_path` or Postgres storage;
- set API keys if serving HTTP;
- set rate limits for shared deployments;
- configure backups;
- check `/index/health`;
- keep benchmark claims tied to your real workload.
