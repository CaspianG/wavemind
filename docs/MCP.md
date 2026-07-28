# MCP Integration

WaveMind includes a Model Context Protocol server for agents that need durable,
adaptive memory without a custom adapter.

## Start In Two Commands

```sh
python -m pip install "wavemind[mcp]"
wavemind-mcp --db ./state/agent-memory.sqlite3
```

The default transport is `stdio`. The database path is explicit and remains
the source of truth after the MCP process or client restarts.

## Client Configuration

Use the same command and database path in any MCP client:

```json
{
  "mcpServers": {
    "wavemind": {
      "command": "wavemind-mcp",
      "args": ["--db", "./state/agent-memory.sqlite3"]
    }
  }
}
```

Restart the client after editing its MCP configuration. The WaveMind tools
should then appear in the client's tool list.

## Tools

| Tool | Purpose |
|---|---|
| `remember` | Store text, tags, TTL, priority, metadata, and provenance. Optional idempotency keys make retries safe. |
| `recall` | Return ranked, non-expired memories from exactly one namespace. |
| `feedback` | Reinforce or suppress a recalled memory with an auditable signal. |
| `forget` | Delete one memory from exactly one namespace. |
| `inspect_memory` | Read the stored state of one memory without cross-namespace search. |
| `explain_memory` | Return provenance, priority, access state, expiration, and related audit events. |
| `manage_namespace` | Show stats, list memories, or clear a namespace with explicit confirmation. |

Every tool accepts an explicit namespace. A memory in `user:42` is never
returned, modified, or deleted through a request for `user:43`.

## Safe Retries

Pass an `idempotency_key` when an agent may retry a write:

```json
{
  "text": "The user prefers short practical answers.",
  "namespace": "user:42",
  "tags": ["preference"],
  "provenance": {
    "source": "chat",
    "message_id": "msg-108"
  },
  "idempotency_key": "chat:msg-108"
}
```

Repeating the same payload returns the original memory ID. Reusing the key
with different content is rejected instead of silently creating conflicting
state.

## Transport And Security

`stdio` is the recommended local transport because it creates no listening
network socket. For local development, streamable HTTP is available on
loopback:

```sh
wavemind-mcp --db ./state/agent-memory.sqlite3 \
  --transport streamable-http --host 127.0.0.1 --port 8000
```

Binding streamable HTTP outside loopback is rejected unless
`--allow-remote` is explicitly supplied. Do not expose that mode directly to
the internet. Put authentication, authorization, TLS, request limits, and
tenant-to-namespace policy enforcement in the deployment gateway.

## Verified Behavior

The integration suite starts a real MCP stdio subprocess with the official
Python MCP client and verifies:

- tool discovery and structured responses;
- SQLite persistence across process restart;
- namespace isolation for read, feedback, and deletion;
- idempotent replay and conflicting-retry rejection;
- concurrent writes and client cancellation without database corruption;
- TTL-based stale-memory suppression;
- provenance and audit explanation;
- explicit confirmation for destructive namespace clearing;
- invalid-input errors and loopback-safe HTTP defaults.

Run it locally:

```sh
python -m pytest -q tests/test_mcp_server.py
```
