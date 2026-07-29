# WaveMind TypeScript HTTP SDK

```ts
import { WaveMindClient } from "@wavemind/http";

const memory = new WaveMindClient({ baseUrl: "http://localhost:8000" });
await memory.remember({ text: "The deployment uses a canary.", namespace: "agent" });
const packet = await memory.compileExperiencePacket({
  query: "How should I deploy?",
  namespace: "agent",
});

await memory.feedback({
  id: 42,
  namespace: "agent",
  useful: true,
  reason: "The agent used this memory successfully",
});

const explanation = await memory.explainMemory(42, "agent");
await memory.forget({ id: 42, namespace: "agent" });
```

The client has no runtime dependencies and works with Node.js 18+ or modern
browsers that provide `fetch`. Safe read operations retry `408`, `429`, and
transient `5xx` responses twice by default. Mutations are never retried
automatically, so `remember`, `feedback`, `forget`, trajectory ingestion, and
bundle import cannot be duplicated by the client.

Use an `AbortSignal` to cancel any operation:

```ts
const controller = new AbortController();
const pending = memory.query(
  { text: "deployment history", namespace: "agent" },
  { signal: controller.signal },
);
controller.abort();
await pending;
```

Configure retry behavior when constructing the client:

```ts
const memory = new WaveMindClient({
  baseUrl: "http://localhost:8000",
  maxRetries: 3,
  retryBaseDelayMs: 150,
});
```
