import assert from "node:assert/strict";
import test from "node:test";

import { WaveMindClient, WaveMindHTTPError } from "../dist/index.js";


test("client sends typed memory and experience requests", async () => {
  const requests = [];
  const fetch = async (url, init) => {
    requests.push({ url, init });
    const body = url.endsWith("/remember")
      ? { id: 7 }
      : {
          schema: "wavemind.experience_packet.v1",
          namespace: "agent",
          query: "recover",
          token_budget: 200,
          estimated_tokens: 12,
          items: [],
          omitted_count: 0,
          generated_at: 1,
          compiler_policy: {},
          citations: [],
        };
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  const client = new WaveMindClient({
    baseUrl: "https://memory.example.test/",
    apiKey: "secret",
    fetch,
  });

  assert.deepEqual(
    await client.remember({ text: "A durable fact", namespace: "agent" }),
    { id: 7 },
  );
  const packet = await client.compileExperiencePacket({
    query: "recover",
    namespace: "agent",
    token_budget: 200,
  });
  assert.equal(packet.schema, "wavemind.experience_packet.v1");
  assert.equal(requests[0].url, "https://memory.example.test/remember");
  assert.equal(requests[0].init.headers.authorization, "Bearer secret");
  assert.deepEqual(JSON.parse(requests[1].init.body), {
    query: "recover",
    namespace: "agent",
    token_budget: 200,
  });
});


test("client encodes experience IDs and exposes structured HTTP errors", async () => {
  const fetch = async (url) => {
    assert.equal(
      url,
      "https://memory.example.test/experience/id%2Fwith%20space?namespace=a%2Fb",
    );
    return new Response(JSON.stringify({ detail: "Experience not found" }), {
      status: 404,
      headers: { "content-type": "application/json" },
    });
  };
  const client = new WaveMindClient({
    baseUrl: "https://memory.example.test",
    fetch,
  });

  await assert.rejects(
    () => client.getExperience("id/with space", "a/b"),
    (error) => {
      assert.ok(error instanceof WaveMindHTTPError);
      assert.equal(error.status, 404);
      assert.deepEqual(error.body, { detail: "Experience not found" });
      return true;
    },
  );
});


test("client exposes feedback, forget, and explain contracts", async () => {
  const requests = [];
  const fetch = async (url, init) => {
    requests.push({ url, init });
    let body;
    if (url.endsWith("/feedback")) {
      body = {
        ok: true,
        id: 12,
        namespace: "tenant/a",
        priority: 1.5,
        access_count: 3,
        cache_invalidated: 1,
      };
    } else if (url.endsWith("/forget")) {
      body = { deleted: 1 };
    } else {
      body = {
        schema: "wavemind.memory_explanation.v1",
        id: 12,
        namespace: "tenant/a",
        text: "A durable fact",
        tags: ["profile"],
        metadata: {},
        provenance: { source: "chat" },
        created_at: 1,
        updated_at: 2,
        expires_at: null,
        priority: 1.5,
        access_count: 3,
        audit_events: [],
      };
    }
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  const client = new WaveMindClient({
    baseUrl: "https://memory.example.test",
    fetch,
  });

  const feedback = await client.feedback({
    id: 12,
    namespace: "tenant/a",
    useful: true,
    strength: 0.5,
  });
  assert.equal(feedback.priority, 1.5);
  assert.deepEqual(await client.forget({ id: 12, namespace: "tenant/a" }), {
    deleted: 1,
  });
  const explanation = await client.explainMemory(12, "tenant/a", 25);
  assert.equal(explanation.provenance.source, "chat");

  assert.equal(requests[0].url, "https://memory.example.test/feedback");
  assert.equal(requests[1].init.method, "DELETE");
  assert.deepEqual(JSON.parse(requests[1].init.body), {
    id: 12,
    namespace: "tenant/a",
  });
  assert.equal(
    requests[2].url,
    "https://memory.example.test/memories/12/explain" +
      "?namespace=tenant%2Fa&audit_limit=25",
  );
});


test("client retries safe reads but never retries mutations", async () => {
  let queryAttempts = 0;
  const queryFetch = async () => {
    queryAttempts += 1;
    if (queryAttempts < 3) {
      return new Response(JSON.stringify({ detail: "busy" }), {
        status: 503,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ results: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  const retryingClient = new WaveMindClient({
    baseUrl: "https://memory.example.test",
    fetch: queryFetch,
    maxRetries: 2,
    retryBaseDelayMs: 0,
  });
  assert.deepEqual(await retryingClient.query({ text: "recover" }), {
    results: [],
  });
  assert.equal(queryAttempts, 3);

  let mutationAttempts = 0;
  const mutationClient = new WaveMindClient({
    baseUrl: "https://memory.example.test",
    fetch: async () => {
      mutationAttempts += 1;
      return new Response(JSON.stringify({ detail: "busy" }), {
        status: 503,
        headers: { "content-type": "application/json" },
      });
    },
    maxRetries: 5,
    retryBaseDelayMs: 0,
  });
  await assert.rejects(
    () => mutationClient.remember({ text: "do not duplicate" }),
    WaveMindHTTPError,
  );
  assert.equal(mutationAttempts, 1);
});


test("client propagates cancellation without retrying", async () => {
  let attempts = 0;
  const fetch = async (_url, init) => {
    attempts += 1;
    return new Promise((_resolve, reject) => {
      init.signal.addEventListener(
        "abort",
        () => reject(init.signal.reason),
        { once: true },
      );
    });
  };
  const client = new WaveMindClient({
    baseUrl: "https://memory.example.test",
    fetch,
    maxRetries: 3,
  });
  const controller = new AbortController();
  const request = client.query(
    { text: "cancel me" },
    { signal: controller.signal },
  );
  controller.abort(new Error("cancelled by caller"));

  await assert.rejects(request, /cancelled by caller/);
  assert.equal(attempts, 1);
});


test("client supports concurrent requests without shared mutable state", async () => {
  const seen = new Set();
  const fetch = async (_url, init) => {
    const body = JSON.parse(init.body);
    seen.add(body.text);
    await Promise.resolve();
    return new Response(
      JSON.stringify({
        results: [
          {
            id: Number(body.text.split("-")[1]),
            text: body.text,
            score: 1,
            vector_score: 1,
            field_score: 0,
            graph_score: 0,
            namespace: "parallel",
            tags: [],
            metadata: {},
          },
        ],
      }),
      {
        status: 200,
        headers: { "content-type": "application/json" },
      },
    );
  };
  const client = new WaveMindClient({
    baseUrl: "https://memory.example.test",
    fetch,
  });
  const responses = await Promise.all(
    Array.from({ length: 32 }, (_, index) =>
      client.query({ text: `query-${index}`, namespace: "parallel" }),
    ),
  );

  assert.equal(seen.size, 32);
  assert.deepEqual(
    responses.map((response) => response.results[0].id),
    Array.from({ length: 32 }, (_, index) => index),
  );
});


test("client validates destructive and retry configuration", () => {
  const client = new WaveMindClient({
    baseUrl: "https://memory.example.test",
    fetch: async () => new Response(),
  });
  assert.throws(() => client.forget({ namespace: "default" }), /id or text/);
  assert.throws(
    () => client.explainMemory(1, "default", 0),
    /between 1 and 100/,
  );
  assert.throws(
    () =>
      new WaveMindClient({
        baseUrl: "https://memory.example.test",
        fetch: async () => new Response(),
        maxRetries: -1,
      }),
    /non-negative integer/,
  );
});
