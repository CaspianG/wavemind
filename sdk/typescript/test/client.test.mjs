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
