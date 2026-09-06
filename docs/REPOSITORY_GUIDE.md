# WaveMind Repository Guide

This guide maps each repository area to its purpose and source of truth. It is
for contributors, reviewers, and operators who need to find the right file
without treating generated evidence as hand-written source.

## Top-Level Map

| Path | Purpose | Change rule |
|---|---|---|
| `wavemind/` | Python library, CLI, API, storage, indexes, integrations, and verified-experience runtime | Change with focused tests under `tests/`. |
| `tests/` | Unit, integration, security, workflow-contract, and admission tests | Keep deterministic and keyless unless a test is explicitly an external profile. |
| `sdk/typescript/` | Repository-local TypeScript HTTP SDK | Run its build, test, and packed-install checks. |
| `examples/` | Small runnable user paths | Prefer examples that work offline and state their evidence boundary. |
| `docs/` | Explanations, operating guides, roadmap, and public positioning | Link claims to checked evidence; start at `docs/README.md`. |
| `benchmarks/` | Benchmark source, frozen protocols, raw records, results, and admission reports | Read `benchmarks/README.md`; do not hand-edit generated results. |
| `.github/workflows/` | CI, exact-SHA admission, security, release, and external evidence jobs | Workflow changes require contract tests and a green required aggregate check. |
| `website/` | Vite source for the public product and evidence site | Run the website build before review. |
| `deploy/` | Docker Compose, Kubernetes, Helm, Terraform, and observability assets | Keep local, loopback, and remote evidence labels separate. |
| `agents/` | Provider-neutral and framework-specific agent integration assets | Preserve the same verification and namespace boundaries as the core runtime. |
| `scripts/` | Repository maintenance and deterministic render/sync utilities | Prefer these scripts over manual edits to generated blocks. |
| `scientific-memory-admission/` | Packaged scientific admission material | Keep protocol and integrity metadata aligned with the canonical benchmark artifacts. |

## Authoritative And Generated Files

| Kind | Examples | Rule |
|---|---|---|
| Product source | `wavemind/`, `sdk/typescript/src/` | Edit directly and test. |
| Test source | `tests/`, SDK tests | Edit directly; do not weaken gates to make a change pass. |
| Human documentation | `README.md`, most files under `docs/` | Edit directly, but preserve claim boundaries. |
| Canonical product status | `docs/data/product-status.json` | Update intentionally, then run the status synchronizer. |
| Generated status blocks | Marked `product-status:start` / `product-status:end` | Run `python scripts/sync_product_status.py --write`; do not drift copies by hand. |
| Benchmark programs and protocols | `benchmarks/*.py`, frozen protocol JSON | Review as source code and immutable protocol input. |
| Benchmark results and reports | `*_results.json`, admission Markdown, dashboard data | Generate from the declared command; retain failures and blocked verdicts. |
| Local runtime state | `*.sqlite`, `*.sqlite3`, `*.db`, `state/`, logs, caches | Ignored by Git; never commit user memory, secrets, or temporary state. |

## Find The Right Change Surface

| Goal | Start here | Verify with |
|---|---|---|
| Fix Python runtime behavior | `wavemind/` and the nearest `tests/test_*.py` | Focused pytest, then full pytest and Ruff |
| Change HTTP contracts | `wavemind/api.py` and API tests | API tests, provider contracts, full suite |
| Change verified experience | Experience modules plus `docs/VERIFIED_EXPERIENCE_RUNTIME.md` | Experience, safety, integration, and exact-SHA admission tests |
| Change the TypeScript client | `sdk/typescript/` | `npm ci`, `npm run build`, `npm test`, packed install |
| Change public claims | README/docs/site plus cited JSON | Product-status check, artifact audit, site build |
| Add benchmark evidence | `benchmarks/` | Frozen command, JSON schema/integrity, admission renderer, artifact audit |
| Change release automation | `.github/workflows/release.yml` and `docs/RELEASE.md` | Workflow contract tests and a dry-run/preflight path |

## Local Quality Gate

Use the project virtual environment if one already exists. The normal local
gate is:

```sh
ruff check .
pytest -q
python scripts/sync_product_status.py --check
python -m build
python -m twine check dist/*
```

For public-site changes:

```sh
cd website
npm ci
npm run build
```

For TypeScript SDK changes:

```sh
cd sdk/typescript
npm ci
npm run build
npm test
```

GitHub's `required / full-check` remains the final merge gate. Exact-current
admission artifacts refer to the exact source SHA; an older checked-in artifact
must be described as historical even when it passed at its own SHA.

## Repository Hygiene

- Keep commits and pull requests focused enough to review.
- Never commit local databases, API keys, `.env` files, caches, build output, or
  private benchmark data.
- Preserve failed scientific outcomes and their raw evidence. History is part
  of the proof, not clutter to delete after a better result appears.
- Do not copy a benchmark number into public text without linking the exact
  artifact and stating its scope.
- Do not merge automated dependency updates only because they are newer. Honor
  supported runtime ranges and require the complete relevant CI surface.
- Keep the root README as the product entrypoint, `docs/README.md` as the guide
  index, and this file as the contributor map.
