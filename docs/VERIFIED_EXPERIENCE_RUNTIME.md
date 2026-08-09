# Verified Agent Experience Runtime

The runtime turns completed tool executions into inspectable experience without
trusting the agent's own claim that it succeeded.

## Lifecycle

1. Capture session, run, task, tool call, tool result, error, and outcome events.
2. Redact secrets, enforce payload limits, deduplicate retries, and isolate the namespace.
3. Ask a test, tool, environment, or operator to verify the outcome.
4. Derive procedures, gotchas, constraints, corrections, and failure patterns with trajectory provenance.
5. Keep unverified candidates in shadow; promote only after independent evidence.
6. Inject a minimal cited Experience Packet only when it is applicable.
7. Inspect, approve, reject, or roll back the result through Python, HTTP, MCP, or Studio.

## Local Demo

```sh
python examples/verified_experience_runtime.py
```

The demo needs no key, network, model, or GPU. It uses an executable environment
state check rather than an agent self-rating.

## Integration Surfaces

| Surface | Entry point |
|---|---|
| Python | `AgentExperienceRuntime.begin_run()` / `decide()` |
| Context manager | `AgentExperienceRuntime.run()` |
| OpenAI Agents | `make_openai_experience_hooks()` |
| Anthropic | `make_anthropic_experience_hooks()` |
| LangGraph | start, wrapped-node, and finish helpers |
| MCP | `ExperienceMCPAdapter` and `build_experience_mcp_server()` |
| HTTP | `/experience/runtime/*` |
| TypeScript | runtime lifecycle methods in the repository-local `@wavemind/http` package |
| Studio | `/studio/experience` |

All surfaces use the same event and verification contracts. Provider wrappers
do not create a separate trust model.

`@wavemind/http` is the canonical TypeScript package name in this repository;
`@wavemind/sdk` is not a second package or alias. The generated TypeScript
starter uses the local `sdk/typescript` package and runs `npm run
quickstart`, which builds the SDK, starts the required HTTP server, exercises
remember, recall, feedback, and explanation, restarts the server against the
same SQLite database, and checks that the same memory remains available. This
is a local checkout flow and does not assert public registry publication.

## Outcome Verification

Valid evidence sources are `test`, `tool`, `environment`, and `operator`.
`llm_self_assessed=true` is rejected. Three independent successful validations
move the default procedure lifecycle from shadow to canary to active. Two
verified failures against an applied procedure reject it.

## Frozen Evidence

The checked local benchmark compares no memory, static always-on memory, and
selective verified experience on 150 held-out stateful tasks across travel,
customer support, and shopping assistant domains. It runs five repeats with 95%
confidence intervals and uses the same executable verifier for every mode.

```sh
python benchmarks/verified_experience_benchmark.py
wavemind verified-experience-admission --root . --fail-on-blocked
python benchmarks/validate_verified_experience_artifacts.py
```

See [the result](../benchmarks/VERIFIED_EXPERIENCE_RESULTS.md) and
[admission](../benchmarks/VERIFIED_EXPERIENCE_ADMISSION.md).

## STATE-Bench

`WaveMindStateBenchLearningAdapter` implements the read-only
`retrieve_learnings(query, top_k=3) -> list[str]` hook. The artifact builder
accepts only the official three-domain training layout, requires exactly 100
training trajectories per domain, rejects test paths, records the upstream
repository SHA, and never labels runner readiness as an official score.

An official submission still requires the benchmark's locked simulator and
judge, five runs per task, scored trajectories, and metrics for every domain.
