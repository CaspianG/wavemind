# WaveMind TypeScript HTTP SDK

```ts
import { WaveMindClient } from "@wavemind/http";

const memory = new WaveMindClient({ baseUrl: "http://localhost:8000" });
await memory.remember({ text: "The deployment uses a canary.", namespace: "agent" });
const packet = await memory.compileExperiencePacket({
  query: "How should I deploy?",
  namespace: "agent",
});
```

The client has no runtime dependencies and works with Node.js 18+ or modern
browsers that provide `fetch`.
