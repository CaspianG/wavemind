# Framework Integrations

This guide contains the complete framework and agent integration reference moved from the project README.

## LangChain Memory

Install the optional integration:

```sh
pip install "wavemind[langchain]"
```

Use WaveMind as a drop-in LangChain memory object:

```python
from wavemind.integrations.langchain import WaveMindMemory

memory = WaveMindMemory(db_path="agent_memory.sqlite3")
# Replace: memory = ConversationBufferMemory()
```

Offline runnable example from a cloned repository:

```sh
python examples/langchain_memory.py
```

## Framework Integrations

WaveMind only needs two touch points in an agent, service, notebook, or app:

1. Before work happens, `query()` for relevant memory and pass the short result
   into the next step: a prompt, search screen, tool call, support workflow, or
   decision function.
2. After work happens, `remember()` durable facts, preferences, summaries,
   outcomes, corrections, or notes.

That makes it usable in more than LangChain:

| Use case | Integration style |
|---|---|
| LangChain agent | Use `WaveMindMemory` from `wavemind.integrations.langchain`. |
| LangGraph workflow | Use `make_recall_node()` and `make_persist_node()` from `wavemind.integrations.langgraph`. |
| LlamaIndex pipeline | Use `WaveMindRetriever` from `wavemind.integrations.llamaindex`. |
| CrewAI crew | Use `WaveMindCrewAITools` from `wavemind.integrations.crewai`. |
| AutoGen loop | Use `WaveMindAutoGenMemory` from `wavemind.integrations.autogen`. |
| Custom Python agent | Create one `WaveMind` instance and call `query()` before the LLM. |
| Node, Go, Ruby, PHP, or no-code app | Run `wavemind serve` and call the HTTP API. |
| Multi-user SaaS | Use `namespace="user:<id>"` or `namespace="tenant:<id>:agent:<id>"`. |
| Knowledge base or notebook | Store notes by project namespace and retrieve a small evidence set. |
| Support or CRM workflow | Store issues, preferences, resolutions, and corrections with tags. |
| Research workflow | Store observations with source metadata and expire temporary hypotheses. |
| Temporary context | Store with `ttl_seconds=...` so stale memory expires automatically. |
| Preference/profile memory | Store with tags such as `profile`, `preference`, `project`, `decision`. |
| Corrections/privacy | Use `forget()` or namespace deletion workflows. |

More examples: [`docs/USE_CASES.md`](USE_CASES.md).
Migrating from a Chroma memory store: [`docs/CHROMA_MIGRATION.md`](CHROMA_MIGRATION.md).

Framework examples in this repository:

| Framework / pattern | Example |
|---|---|
| LangChain memory | `examples/langchain_memory.py` |
| OpenAI/OpenRouter-style agent loop | `examples/agent_with_memory.py` |
| LangGraph hooks | `wavemind.integrations.langgraph`, `examples/framework_integrations.py` |
| LlamaIndex-style retriever | `wavemind.integrations.llamaindex`, `examples/llamaindex_retriever.py` |
| CrewAI-style tools | `wavemind.integrations.crewai`, `examples/framework_integrations.py` |
| AutoGen-style hooks | `wavemind.integrations.autogen`, `examples/framework_integrations.py` |
| Namespace sharding | `examples/sharded_memory.py` |

Run the dedicated offline LlamaIndex-style retriever example:

```sh
python examples/llamaindex_retriever.py
```

## OpenClaw Integration

[OpenClaw memory](https://docs.openclaw.ai/concepts/memory) is file-centered:
it writes durable memory into `MEMORY.md`, daily notes under `memory/`, and uses
tools such as `memory_search` / `memory_get`. OpenClaw's documented agent loop
also exposes hooks such as `before_prompt_build`, `agent_end`,
`message_received`, and `message_sent`.

The safest WaveMind integration is a sidecar, not a replacement:

- Keep OpenClaw's Markdown memory as the human-readable source of durable truth.
- Use WaveMind as the dynamic recall layer for hotness, TTL, namespaces, and
  correction-sensitive ranking.
- Store the SQLite file outside committed workspace files, for example
  `~/.openclaw/wavemind/<agent-id>.sqlite3`.
- Query WaveMind from `before_prompt_build` and inject a compact memory block
  with `prependContext`.
- Capture new durable summaries from `agent_end` or message hooks.

Sketch of the adapter logic:

```python
from pathlib import Path
from wavemind import WaveMind

db_path = Path.home() / ".openclaw" / "wavemind" / "main.sqlite3"
memory = WaveMind(db_path=db_path)

def before_prompt_build(agent_id: str, user_text: str) -> str:
    namespace = f"openclaw:{agent_id}"
    hits = memory.query(user_text, namespace=namespace, top_k=5, min_score=0.25)
    return "\n".join(f"- {hit.text}" for hit in hits)

def agent_end(agent_id: str, summary: str) -> None:
    namespace = f"openclaw:{agent_id}"
    memory.remember(summary, namespace=namespace, tags=["summary"], priority=1.5)
```

For a production OpenClaw plugin, translate that sketch into the documented
plugin hook surface: `before_prompt_build` for recall and `agent_end` /
`message_received` / `message_sent` for capture.

## Hermes and Custom Agent Loops

The public [HERMES Agent](https://github.com/aziksh-ospanov/HERMES) is a
LangChain / LangGraph mathematical-reasoning agent. Its README describes
`HermesReasoner` as a LangChain `BaseTool` and mentions an optional in-memory
embedding store for previously verified claims.

WaveMind fits there as a persistent memory layer around that loop:

- Recall previously verified claims before `HermesReasoner` is invoked.
- Store successfully verified claims with `tags=["verified-claim"]`.
- Scope by `user_id`, project, benchmark, or theorem namespace.
- Replace short-lived in-memory vector recall when the agent needs restarts,
  TTL, explicit forgetting, or cross-session reuse.

Generic Hermes-style loop:

```python
from wavemind import WaveMind

memory = WaveMind(db_path="./state/hermes_claims.sqlite3")

def verify_with_memory(user_id: str, problem: str) -> str:
    namespace = f"hermes:{user_id}"
    claims = memory.query(problem, namespace=namespace, tags=["verified-claim"], top_k=5)
    context = "\n".join(f"- {claim.text}" for claim in claims)

    result = call_hermes_reasoner(problem=problem, extra_context=context)

    if result.label == "CORRECT":
        memory.remember(result.claim, namespace=namespace, tags=["verified-claim"], priority=2.0)
    return result.text
```

For any other agent framework, the rule is the same: recall before the model,
capture after the turn, isolate users with namespaces, and use TTL for temporary
facts.

## Non-Agent Use Cases

WaveMind can store any small-to-medium memory stream where meaning, freshness,
and repeated use matter. It is useful when "show me the nearest text" is not
enough and the application needs "show me what is relevant now."

| Use case | Example |
|---|---|
| Support memory | Recall past user issues, plans, bugs, and resolutions. |
| Product research | Store interview snippets with `tags=["customer", "pain"]`. |
| Team knowledge | Remember project decisions and suppress expired decisions with TTL. |
| Personal assistant | Store preferences, routines, people, and recurring context. |
| Game/NPC memory | Give characters scoped memory that strengthens after repeated events. |
| Trading research | Store labeled OHLCV pattern notes before building a backtest layer. |
| Document notebook | Import text/PDF/JSON chunks and query by namespace/project. |
| Personal knowledge base | Keep decisions, recurring context, people, links, and notes searchable without sending them to a hosted vector DB. |

## Why Dynamic Memory

WaveMind is not positioned as "a faster Chroma." Chroma, Qdrant, Pinecone, and
Weaviate are vector databases: they store embeddings and return nearest
neighbors. That is the right tool for many static RAG workloads.

WaveMind is a dynamic memory layer. It still uses vector search first, but then
applies memory-specific signals that a plain vector store does not model by
default:

| memory behavior | Why it matters | WaveMind mechanism |
|---|---|---|
| Hot memories | Information that keeps being useful should become easier to recall again. | Wave-field hotness and priority updates. |
| Aging memories | Old low-value facts should fade instead of competing forever. | TTL and decay-aware scoring. |
| Scoped memory | One user, app, workspace, or project should not leak into another. | Namespaces and tags. |
| Explicit forgetting | Real systems need deletion, privacy cleanup, and correction workflows. | `forget()` plus SQLite persistence. |
| Stable restart behavior | A memory system must survive process restarts. | SQLite source of truth, reloadable indexes. |
| Vector plus memory rank | Semantic similarity is necessary but not sufficient for long-running memory. | k-NN candidates first, wave field as re-ranker. |

The current Chroma benchmark below is intentionally conservative: it compares
static retrieval on the same facts and the same hash embeddings. That benchmark
is useful, but it does not exercise WaveMind's main thesis: memory that changes
over time as software recalls, reinforces, ages, and forgets information.

The benchmark that should decide whether WaveMind is worth using is a dynamic
memory benchmark:

| scenario | What should happen |
|---|---|
| A fact, preference, or decision is used many times. | WaveMind should rank it higher than equally similar but unused facts. |
| A fact expires via TTL. | WaveMind should suppress it without requiring manual vector cleanup. |
| A user or system corrects an old fact. | WaveMind should prefer the newer or reinforced memory. |
| A query is ambiguous across namespaces. | WaveMind should return only the scoped user's memory. |
| A long history has many irrelevant facts. | WaveMind should preserve useful recall instead of treating all vectors equally. |

In short: static vector search answers "what is nearest?" Dynamic memory also
asks "what is still relevant, reinforced, scoped, and allowed to be remembered?"

## Research Branches

The main branch stays focused on the core WaveMind library: dynamic memory,
storage, indexes, APIs, integrations, and public memory benchmarks.

Experimental domains live in separate branches so they can move quickly without
overloading the main README:

| Branch | Scope |
|---|---|
| [`research/crypto-pattern-memory`](https://github.com/CaspianG/wavemind/tree/research/crypto-pattern-memory) | OHLCV pattern-memory research, historical analogue retrieval, and future backtest experiments. |
