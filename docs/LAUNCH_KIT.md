# WaveMind Launch Kit

This document is the working launch package for WaveMind. It keeps public
positioning, channel drafts, objections, and execution steps in one place so
every post points to the same honest story.

## Positioning

### One Sentence

WaveMind is a local-first dynamic memory layer for software that needs to
remember what still matters, not just what text is nearest.

### Short Pitch

Most vector stores return nearest neighbors. WaveMind adds memory state around
retrieval: hotness, decay, TTL, namespaces, audit events, and graph dynamics.
SQLite or Postgres remains the source of truth; FAISS, pgvector, Qdrant, Annoy,
or NumPy can provide candidate search; WaveMind re-ranks the small candidate
set as memory.

### What To Say Clearly

- WaveMind is not trying to replace Qdrant, Chroma, Pinecone, or Postgres.
- It is a memory layer above or beside a vector index.
- The strongest current proof is dynamic-memory behavior: stale facts,
  corrections, TTL, namespace isolation, and repeated recall.
- Public benchmark evidence exists for retrieval on LoCoMo, LongMemEval, and
  BEIR/SciFact, but answer-generation leaderboards are still future work.
- The project is early, local-first, MIT licensed, and practical today for
  small-to-medium memory streams.

### What Not To Claim

- Do not claim "continuous physics field" or "human-level memory".
- Do not claim official VectorDBBench, MTEB, MIRACL, LMEB, or RAGBench results
  until those runs are checked in.
- Do not claim WaveMind is faster than Chroma in static retrieval. It is not.
- Do not hide limitations. The honest limitation section is a feature for
  serious developers.

## Audience

| audience | Pain | Hook |
|---|---|---|
| Agent builders | Agent forgets preferences, corrections, and old context. | Memory that changes importance over time. |
| Local-first AI users | They want private memory without a hosted vector DB. | SQLite source of truth, offline demo, CLI, Python API. |
| RAG engineers | Vector search returns stale or irrelevant records. | TTL, priority, namespaces, audit, explicit forget. |
| Framework users | They need integration points, not a new stack. | LangChain, LangGraph, LlamaIndex, CrewAI, AutoGen adapters. |
| OSS contributors | They want clear technical work. | Benchmarks, FAISS/pgvector/Qdrant, graph memory, observability. |

## Primary Message

Vector search answers "what is similar?" Agent memory also needs to answer
"what still matters?" WaveMind is an open-source attempt to make that second
question first-class.

## Proof Points

- `pip install wavemind`
- CLI, Python API, FastAPI server.
- SQLite persistence by default.
- Optional sentence-transformers, FAISS, pgvector, Qdrant, Annoy.
- Namespaces, tags, TTL, score thresholds, audit log, backup/restore.
- Prometheus-compatible metrics and optional OpenTelemetry traces.
- Benchmarks checked into the repository with commands and JSON results.
- Public benchmark post draft: `docs/BENCHMARK_BRIEF.md`.
- Offline demos: `examples/demo.py` and `examples/dynamic_memory_demo.py`.
- Use-case gallery: `docs/USE_CASES.md`.

## GitHub Page Checklist

- README explains the problem in the first viewport.
- README has a terminal demo and a visual card.
- Dynamic demo script is documented in `docs/DEMO_SCRIPT.md`.
- Use-case gallery is linked from README.
- Badges point to `CaspianG/wavemind`.
- Topics include: `ai-agents`, `memory`, `vector-search`, `llm`, `rag`,
  `python`, `sqlite`, `langchain`.
- Release exists with clear notes.
- PyPI page works with the same Quick Start.
- Issues include `good first issue`, `benchmark`, `integration`, `production`,
  and `documentation`.
- Roadmap has short-term, medium-term, and research tracks.

## Launch Sequence

### Day 0: Preflight

1. Run `pytest -q`.
2. Run `python -m build`.
3. Run `python -m twine check dist\*`.
4. Verify GitHub Actions are green.
5. Verify PyPI install in a clean venv:

```sh
python -m venv .venv-check
.venv-check\Scripts\python -m pip install wavemind
.venv-check\Scripts\python -c "from wavemind import WaveMind; m=WaveMind(); m.remember('demo'); print(m.query('demo')[0].text)"
```

### Day 1: Developer Launch

1. Post a technical X thread.
2. Post a Show HN only if the repo is runnable and Actions are green.
3. Reply to every comment with concrete benchmark links or commands.
4. Do not argue. Treat criticism as issue discovery.

### Day 2-3: Community Launch

1. Reddit: answer relevant memory/RAG/agent threads first.
2. Then post in communities only where the rules allow project sharing.
3. Use the "I built this, here is what it does, here are limitations" tone.
4. Invite benchmark reproduction, not praise.

### Day 4-7: Contributor Loop

1. Open 5 to 10 `good first issue` tasks.
2. Open 3 benchmark issues with exact commands.
3. Publish a short progress update with the first feedback incorporated.

## Channel Drafts

### GitHub Description

Local-first dynamic memory for agents and apps: SQLite source of truth, vector
search candidates, hotness/decay/TTL re-ranking, namespaces, benchmarks.

### Show HN Title

Show HN: WaveMind, a local-first dynamic memory layer for agents and apps

### Show HN Text

I built WaveMind because vector search alone felt too static for long-running
software.

Most vector stores answer: "what text is closest to this query?" WaveMind tries
to answer a second question: "what information still matters right now?"

It stores memories in SQLite by default, supports namespaces/tags/TTL/forget,
and re-ranks vector candidates with memory state such as hotness, priority,
decay, and optional graph dynamics. It can run as a Python library, CLI, or
FastAPI service. Optional backends include sentence-transformers, FAISS,
pgvector, Qdrant, and Annoy.

The repo includes benchmarks and checked-in result JSON for dynamic memory
policy, LoCoMo retrieval, LongMemEval retrieval, BEIR/SciFact, and local ANN
curves. The honest limitation: static vector search is still faster. The goal is
not to replace vector databases, but to add a memory layer where stale facts,
corrections, TTL, namespaces, and repeated recall matter.

Install:

```sh
python -m pip install wavemind
wavemind remember "Andrey is a trader" --namespace demo
wavemind query "trader" --namespace demo
```

I would especially like feedback on the memory model, benchmarks, and where the
API feels wrong for real agent systems.

### Reddit Post

Title:

I built an open-source local-first memory layer for agents: SQLite + vector
search + hotness/decay/TTL

Body:

I have been working on WaveMind, an MIT-licensed Python library for dynamic
long-term memory.

The idea is simple: vector databases are good at "nearest text", but agent
memory also needs "what still matters?" A preference repeated many times should
become stronger. A corrected fact should suppress the stale version. Temporary
context should expire. Different users/projects should not leak into each
other.

WaveMind keeps the durable state in SQLite by default and can use NumPy, FAISS,
Annoy, pgvector, or Qdrant for candidate search. Then it applies memory state:
hotness, priority, TTL, namespaces, tags, audit events, and optional graph
dynamics.

It is early, and I am not claiming it replaces Chroma/Qdrant/Pinecone. Static
vector search is still faster. The point is dynamic memory behavior, not raw
vector DB scale.

Quick start:

```sh
python -m pip install wavemind
wavemind remember "The user prefers short answers" --namespace demo
wavemind query "answer style" --namespace demo
```

I would appreciate feedback from people building long-running agents, local AI
tools, or RAG systems where stale memory is a real problem.

### X Thread

1. I am building WaveMind: open-source dynamic memory for software that needs to
remember what still matters, not just what text is nearest.

Vector search answers similarity. Memory also needs priority, decay, TTL,
corrections, and scope.

2. The core idea:

SQLite/Postgres = source of truth
Vector index = candidate search
WaveMind = dynamic memory state over the result

Hot memories rise. Stale memories fade. Temporary facts expire. Namespaces stop
cross-user leakage.

3. This is not "another vector DB".

WaveMind can sit above NumPy, FAISS, Annoy, pgvector, or Qdrant. The goal is to
make agent memory behave less like a flat list and more like state that evolves.

4. It already has:

- Python API
- CLI
- FastAPI server
- SQLite persistence
- TTL / tags / namespaces
- audit log
- backup / restore
- LangChain, LangGraph, LlamaIndex, CrewAI, AutoGen adapters

5. Benchmarks are checked into the repo.

The strongest current signal is dynamic memory behavior: corrections, TTL,
namespace isolation, stale suppression, and repeated recall.

Static vector search is still faster. That is written honestly in the README.

6. Quick start:

python -m pip install wavemind
wavemind remember "The user prefers short answers" --namespace demo
wavemind query "answer style" --namespace demo

7. The research direction is a stronger memory field:

related memories excite each other,
conflicting memories inhibit stale facts,
low-value memory decays,
clusters can form higher-level concepts.

8. I am looking for feedback from people building long-running agents, local AI
apps, RAG systems, and personal assistants.

Repo: https://github.com/CaspianG/wavemind

### LinkedIn Post

I am building WaveMind, an open-source dynamic memory layer for software that
needs long-term memory.

The problem: most retrieval systems answer "what is semantically close?" That
is useful, but long-running agents and applications also need "what still
matters?"

WaveMind stores memory locally in SQLite by default, then combines vector
candidate search with dynamic memory signals: hotness, decay, TTL, namespaces,
tags, priority, audit events, and optional graph dynamics.

It is not meant to replace vector databases. It is designed to sit above or
beside them, especially when stale facts, corrections, user preferences,
temporary context, or scoped recall matter.

The project is MIT licensed, installable from PyPI, and includes a CLI, Python
API, FastAPI server, integrations, and reproducible benchmark artifacts.

I am looking for feedback from developers building agentic systems, RAG
products, support copilots, personal AI tools, and local-first AI workflows.

GitHub: https://github.com/CaspianG/wavemind

## Tough Questions

### Why not just use Chroma or Qdrant metadata?

You can implement some of this in application code on top of Chroma or Qdrant.
WaveMind packages that policy into the memory layer: TTL, priority, hotness,
forgetting, audit events, source-of-truth storage, and benchmarks. It can also
use Qdrant or pgvector as candidate indexes.

### Is this actually a mathematical field?

Today it is a practical dynamic-memory model with a wave-field projection and a
discrete memory graph. It is not a continuous physical field. The roadmap is to
make graph dynamics, consolidation, excitation, inhibition, and decay more
explicit and measurable.

### Is it faster than Chroma?

Not for static vector retrieval. Chroma is faster in static cases. WaveMind's
bet is dynamic memory behavior: corrections, TTL, stale suppression, namespace
isolation, auditability, and local-first state.

### Is this production ready?

It has practical production hooks: FastAPI, auth keys, rate limits, audit log,
metrics, OpenTelemetry, backups, index health, and optional external indexes.
It is still early for large-scale HA deployments. The README says that clearly.

### What would make this convincing?

Full answer-quality runs on LoCoMo/LongMemEval, service-mode FAISS/Qdrant/
pgvector latency curves, and real app integrations where stale memory causes
observable failures.

## 14-Day Content Plan

| day | action | goal |
|---:|---|---|
| 1 | X thread + GitHub release post | First developer attention. |
| 2 | Show HN | High-signal technical feedback. |
| 3 | Write "Why vector DBs are not enough for agent memory" | Explain category. |
| 4 | Reddit comments in relevant threads | Participate before posting. |
| 5 | Reddit project post where allowed | Reach local AI/RAG builders. |
| 6 | Short benchmark post | Show evidence, not hype. |
| 7 | Open good-first-issue batch | Convert attention into contributors. |
| 8 | Publish integration demo video/GIF | Make it visually understandable. |
| 9 | LangChain/LlamaIndex integration post | Reach framework users. |
| 10 | "Limitations" post | Build trust with serious developers. |
| 11 | Roadmap post | Show direction and seriousness. |
| 12 | Ask for benchmark datasets | Involve community. |
| 13 | Publish first feedback-driven patch | Show responsiveness. |
| 14 | Weekly recap | Close the loop and ask for stars/contributors. |

## Success Metrics

Track weekly:

- GitHub stars.
- PyPI downloads.
- README click-through from social posts.
- Issues opened by non-maintainers.
- Benchmark reproductions.
- Integration requests.
- Time-to-first-response on comments and issues.

## Source Notes

- Hacker News Show HN is for things people can run or try:
  <https://news.ycombinator.com/showhn.html>
- Hacker News Launch HN writing guidance is useful even outside YC:
  <https://news.ycombinator.com/yli.html>
- Reddit self-promotion guidance: be a real participant, disclose clearly, and
  check each community's own rules before posting:
  <https://www.reddit.com/r/reddit.com/wiki/selfpromotion/>
- GitHub Topics help repositories become discoverable by subject:
  <https://docs.github.com/articles/classifying-your-repository-with-topics>
- X normal posts should fit the 280-character path unless using Premium long
  posts. Keep launch posts short enough to work on a normal account.
