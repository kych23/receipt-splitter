# ReceiptSplit

Photograph a shared grocery receipt, tag who bought what, and get exact per-person totals —
with tax charged only on the items that were actually taxed.

**Live:** https://receiptsplit-beta.vercel.app

> **No sign-up, no saved people, no receipt history.** Scan a receipt, split it, leave — the only
> thing kept between visits is how to read a given store's receipt format.

> **Status:** Slice 1 of v0 — project skeleton, data model, and the allocation engine.
> Receipt capture, parsing, and the tagging UI arrive in later slices
> (see [the design doc](docs/design/v0-architecture-and-slice-1.md)).

## Why

Splitting a grocery run "proportionally" is wrong in states like New York, where most groceries
are tax-exempt but soda and household goods are taxed. If one roommate buys $60 of produce and
another buys $20 of soda, the proportional split charges the produce buyer $1.20 of tax on items
that weren't taxed. This project allocates tax per taxable line, in integer cents, with every
share summing exactly to the receipt.

## Architecture

```
web (Next.js, Vercel) ──HTTP──▶ api (FastAPI, Railway) ──▶ PostgreSQL 18 (Railway)
```

- `api/app/domain/` — pure, framework-free money logic: largest-remainder allocation, receipt
  schema, and the allocator (property-tested with Hypothesis).
- `api/app/db/` + `api/alembic/` — SQLAlchemy 2.0 models and a hand-written migration, verified
  against the live Postgres catalog in tests.
- `web/` — Next.js App Router frontend; API types are generated from the backend's OpenAPI schema.

## Stack

| Layer | Versions |
|---|---|
| Web | Next.js 16.3.5, React 19.2.8, ESLint 9, TypeScript 5, Tailwind 4, Vitest 5, Node 24 |
| API | Python 3.13, FastAPI 0.141, SQLAlchemy 2.0.53, Alembic 1.20, pydantic 2.13, uv 0.9.7 |
| Database | PostgreSQL 18 |

## Local development

Prerequisites: Homebrew, [uv](https://docs.astral.sh/uv/) 0.9.7, [nvm](https://github.com/nvm-sh/nvm).

1. **Database**
   ```sh
   brew install postgresql@18 && brew services start postgresql@18
   createdb receipt_splitter
   createdb receipt_splitter_test
   ```
   (Stop any other Postgres running on port 5432 first.)
2. **Node**: `nvm install 24 && nvm use` (reads `.nvmrc`).
3. **API**
   ```sh
   cd api
   cp .env.example .env
   uv sync
   uv run alembic upgrade head
   uv run uvicorn app.main:app --reload --port 8000
   ```
4. **Web**
   ```sh
   cd web
   cp .env.example .env.local
   npm install
   npm run dev
   ```
   Open http://localhost:3000 — it should show `API: ok`.

## Tests and checks

```sh
# API (loads api/.env, so DATABASE_URL_TEST is picked up)
cd api
uv run ruff check . && uv run ruff format --check . && uv run mypy app
REQUIRE_DB_TESTS=1 uv run pytest

# Web
cd web
npm run lint && npm run format:check && npm run typecheck && npm test && npm run build
```

After changing API routes, regenerate the frontend types and commit both files:

```sh
cd api && uv run python -m app.scripts.export_openapi
cd ../web && npm run gen:api
```

## Design

- [v0 architecture + Slice 1 design](docs/design/v0-architecture-and-slice-1.md)
