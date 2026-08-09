# WaveMind TypeScript HTTP SDK

`@wavemind/http` is the canonical package name for the repository-local
TypeScript SDK. Build it from this checkout before installing it into another
local project:

```sh
npm --prefix sdk/typescript ci
npm --prefix sdk/typescript run build
npm install ./sdk/typescript
```

```ts
import { WaveMindClient } from "@wavemind/http";

const memory = new WaveMindClient({ baseUrl: "http://localhost:8000" });
const remembered = await memory.remember({
  text: "The deployment uses a canary.",
  namespace: "agent",
});
const recalled = await memory.query({
  text: "How should I deploy?",
  namespace: "agent",
});

await memory.feedback({
  id: remembered.id,
  namespace: "agent",
  useful: true,
  reason: "The expected memory was recalled and verified",
});

const explanation = await memory.explainMemory(remembered.id, "agent");
console.log({ recalled, explanation });
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
