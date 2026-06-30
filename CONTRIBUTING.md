# Contributing To WaveMind

WaveMind is an early dynamic-memory engine. Contributions are welcome, but the
project has one strict rule: benchmark and production claims must be
reproducible.

## Local Setup

```sh
git clone https://github.com/CaspianG/wavemind.git
cd wavemind
python -m pip install -e ".[dev]"
pytest -q
```

Optional extras:

```sh
python -m pip install -e ".[sentence,bench,indexes,postgres]"
```

Notes:

- `faiss-cpu` is not installed by the `indexes` extra on Windows because the
  package is not consistently available there.
- `postgres` installs `psycopg`; it still requires a running PostgreSQL
  database with the pgvector extension available.
- Benchmark dependencies such as Chroma and Qdrant are intentionally optional.
- Public datasets are not downloaded by default.

## Good First Areas

- Documentation examples for real applications and frameworks.
- Benchmark adapters that produce checked-in JSON output.
- Small tests around TTL, namespaces, corrections, and graph behavior.
- Production hardening around auth, rate limits, metrics, backups, and sharding.
- Import/export tools.
- CLI and FastAPI ergonomics.

## Benchmark Rules

Do not add a README claim unless it has:

- a reproducible command;
- a checked-in JSON result under `benchmarks/`;
- the dataset name and size;
- the encoder used;
- the compared engines;
- latency and quality metrics;
- a limitation note when the result is retrieval-only, synthetic, local-mode, or
  not leaderboard-equivalent.

It is acceptable to add planned benchmark rows, but they must be marked as
planned and must not be phrased as wins.

## Development Checks

Before opening a PR, run:

```sh
pytest -q
python -m build
python -m twine check dist/*
```

On Windows PowerShell:

```powershell
pytest -q
python -m build
python -m twine check dist\*
```

## Architecture Direction

WaveMind should stay local-first by default:

- SQLite remains the default source of truth.
- Vector indexes generate candidates.
- WaveMind applies memory-specific reranking on the candidate window.
- No backend should silently replace another backend. If an optional dependency
  is missing, raise a clear error or mark the benchmark row as skipped.

Current scale roadmap:

- FAISS candidate index.
- Postgres + pgvector prototype.
- Service-mode Qdrant benchmark.
- Faster dynamic reranking.
- Background jobs for decay, consolidation, graph updates, and backups.
- Observability through metrics, traces, and audit logs.

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the full roadmap.
See [`docs/RELEASE.md`](docs/RELEASE.md) for release mechanics.
See [`docs/LAUNCH_KIT.md`](docs/LAUNCH_KIT.md) for public positioning,
benchmark-claim guardrails, and community launch drafts.

## Pull Request Style

Keep PRs focused. A good PR usually changes one of:

- one backend;
- one benchmark;
- one integration;
- one documentation section;
- one bug fix with tests.

If a change affects benchmark numbers, update both the result JSON and the
README/report text that cites it.
