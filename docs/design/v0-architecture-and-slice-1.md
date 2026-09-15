# DESIGN DOC — receipt-splitter: v0 architecture + Slice 1 (scaffold, data model, allocator)

**Revision:** 4 (addresses design-check rounds 1–4; round-4 fixes applied under user override at the 3-revision cap, not re-reviewed; see Revision log at end)

- **Project:** `receipt-splitter` (new, `~/cs/personal/receipt-splitter`). Monorepo: `web/` (Next.js App Router, TypeScript) + `api/` (FastAPI, Python 3.13).
- **Why:** 4 roommates split shared grocery receipts. Payer photographs receipt → app parses → payer tags items to people → exact per-person totals, tax only on taxable items. User's flagship portfolio project. Source: brainstorm conversation + user decisions (payer tags all; no payments; iOS Safari; location-agnostic; LOW CONFIDENCE + Retry Reading; manual add/edit).

## Part A — v0 architecture (context for all slices; only Slice 1 is built now)

### A1. Components
| Component | Tech | Hosting |
|---|---|---|
| web | Next.js (version produced by `create-next-app@latest` at scaffold time, pinned exactly in `package.json`), App Router, TypeScript strict, Tailwind, ESLint (flat config), Prettier, Vitest + Testing Library. **Node 24 LTS** (`.nvmrc` = `24`, `package.json` `"engines": {"node": ">=24 <25"}`) | Vercel (Node 24.x) |
| api | FastAPI, Python 3.13 (`api/.python-version` = `3.13`), `uv` 0.9.7, SQLAlchemy 2.0 (**sync** engine, psycopg 3), Alembic, pydantic v2, pydantic-settings | Railway |
| db | **PostgreSQL 16** everywhere (local: Homebrew `postgresql@16`; CI: `postgres:16` service; prod: Railway Postgres pinned to major 16, verified with `SELECT version()` during deploy) | Railway |
| object storage | S3-compatible (decided in Slice 2) | — |
| vision LLM | behind `ReceiptParser` protocol; provider chosen by Week-1 benchmark (Slice 2) | — |
| auth | decided in Slice 3 design; data model carries `users.id UUID` now | — |

Sync SQLAlchemy rationale: FastAPI runs `def` routes in a threadpool, so sync DB calls don't block the event loop; Slice 2 revisits if concurrent LLM calls require async routes.

### A2. Source of truth for money logic
`api/app/domain/` is authoritative for allocation, add-up checks, suspect-line detection, and correction folding. It is pure (no I/O, no framework imports besides pydantic). In Slice 3, web re-implements **only** the C1/C2 sum checks (C1: items+discounts+fees = subtotal; C2: subtotal + tax = total — defined in Slice 2) for the instant balance bar, verified against shared JSON fixtures run by both test suites. Allocation results always come from the API.

### A3. Module layout
```
receipt-splitter/
  .gitignore  .editorconfig  .nvmrc  README.md
  .github/workflows/ci.yml
  docs/design/v0-architecture-and-slice-1.md
  api/
    pyproject.toml  uv.lock  alembic.ini  .env.example  .python-version  railway.toml  mise.toml
    alembic/env.py
    alembic/script.py.mako
    alembic/versions/0001_initial.py
    app/__init__.py
    app/main.py              # create_app(settings=None), module-level app
    app/config.py            # Settings, get_settings()
    app/db/__init__.py
    app/db/base.py           # Base (DeclarativeBase) with naming convention
    app/db/models.py         # ORM models (A4)
    app/db/session.py        # get_engine, get_session, check_database, get_database_check
    app/domain/__init__.py
    app/domain/money.py      # split_evenly, allocate_proportionally
    app/domain/receipt.py    # ParsedReceipt schema (A5)
    app/domain/allocation.py # allocate (B5)
    app/routes/__init__.py
    app/routes/health.py
    app/scripts/__init__.py
    app/scripts/export_openapi.py
    tests/conftest.py
    tests/test_config.py
    tests/domain/test_money.py
    tests/domain/test_receipt_schema.py
    tests/domain/test_allocation.py
    tests/domain/strategies.py      # hypothesis strategies for allocation inputs
    tests/db/test_migrations.py
    tests/db/test_schema_constraints.py
    tests/routes/test_health.py
    tests/routes/test_cors.py
  web/                        # created by create-next-app (B7)
```
Import setup: `api/pyproject.toml` has **no** `[build-system]` (uv virtual project). `[tool.pytest.ini_options]`: `pythonpath = [".", "tests/domain"]`, `testpaths = ["tests"]`, `markers = ["db: requires Postgres"]` (see B8). `"."` makes `import app` work; `"tests/domain"` lets tests `from strategies import allocation_inputs`. `tests/` and its subfolders have **no** `__init__.py`; test module basenames are unique across folders.

### A4. Data model (all tables created by Slice 1 migration `0001_initial`)

**Conventions**
- `app/db/base.py`: `class Base(DeclarativeBase): metadata = MetaData(naming_convention=NAMING_CONVENTION)` with
  `NAMING_CONVENTION = {"ix": "ix_%(table_name)s_%(column_0_N_name)s", "uq": "uq_%(table_name)s_%(column_0_N_name)s", "ck": "ck_%(table_name)s_%(constraint_name)s", "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s", "pk": "pk_%(table_name)s"}`.
- Every `id`: `UUID PRIMARY KEY DEFAULT gen_random_uuid()` — generated by the **database**. ORM: `id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))`.
- Every `created_at`: `TIMESTAMPTZ NOT NULL DEFAULT now()`. ORM: `mapped_column(DateTime(timezone=True), server_default=func.now())`.
- `receipts.updated_at`: same as created_at plus ORM `onupdate=func.now()`.
- Money = integer cents (`INT`/`BIGINT` as noted).
- CHECK constraints are declared in the ORM `__table_args__` with the short `name=` shown in brackets below; the naming convention expands them to `ck_<table>_<name>`.
- The two composite FKs get **explicit short names** in the ORM (`ForeignKeyConstraint(..., name="fk_corrections_attempt_receipt")` and `name="fk_allocation_snapshots_attempt_receipt"`); the `fk` convention has no `%(constraint_name)s` token, so an explicit name is used verbatim. (The convention-expanded name for the snapshot FK would be 66 chars, over Postgres's 63-char limit.)
- Every constraint/index name, as it exists in the database, is ≤ 63 characters and is exactly one of the names listed in **A4.1**.
- The migration file `alembic/versions/0001_initial.py` has `revision = "0001"`, `down_revision = None`, `branch_labels = None`, `depends_on = None`, docstring `"initial schema"`. It is **hand-written**. Because `alembic/env.py` passes `target_metadata = Base.metadata` (which carries the naming convention), every constraint and index name in `0001_initial.py` is written as `op.f("<final database name>")` (e.g. `sa.CheckConstraint("status IN (...)", name=op.f("ck_receipts_status_valid"))`) so Alembic does not re-apply the convention (a plain string would become `ck_receipts_ck_receipts_status_valid`).
- Parity is verified two ways (B6 `tests/db/test_migrations.py`): (1) `alembic.autogenerate.compare_metadata(...) == []` after `upgrade head` — covers tables, columns, types, nullability, FK targets/ondelete/deferrable; (2) a catalog test that queries `pg_constraint` and `pg_indexes` and asserts the exact name set from A4.1, each constraint's type, the deferrable/initially-deferred flags, and the partial-index predicate — covering what `compare_metadata` does not (constraint names, CHECK constraints, partial-index `WHERE`).
- Column defaults in the ORM use `server_default` (`receipts.manual_retry_count`: `server_default=text("0")`). ORM attribute names equal column names; mapped class names are listed in A4 ORM mapping.

**Tables**
- **users**: `id`, `email TEXT NOT NULL` + `uq_users_email`, `created_at`
- **households**: `id`, `owner_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE`, `name TEXT NOT NULL` [`name_length`: `char_length(name) BETWEEN 1 AND 80`], `created_at`
- **participants**: `id`, `household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE`, `display_name TEXT NOT NULL` [`display_name_length`: 1..40], `sort_order INT NOT NULL`, `archived_at TIMESTAMPTZ NULL`, `created_at`; partial unique index `uq_participants_active_display_name ON participants (household_id, display_name) WHERE archived_at IS NULL` (ORM: `Index("uq_participants_active_display_name", "household_id", "display_name", unique=True, postgresql_where=text("archived_at IS NULL"))`)
- **receipts**: `id`, `household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE`, `payer_participant_id UUID NULL REFERENCES participants(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED`, `status TEXT NOT NULL` [`status_valid`: `IN ('uploaded','parsing','needs_review','finalized','parse_failed')`], `image_object_key TEXT NULL`, `image_width INT NULL`, `image_height INT NULL`, `active_parse_attempt_id UUID NULL`, `manual_retry_count INT NOT NULL DEFAULT 0` [`manual_retry_count_range`: `BETWEEN 0 AND 5`], `created_at`, `updated_at`, `finalized_at TIMESTAMPTZ NULL`
- **parse_attempts**: `id`, `receipt_id UUID NOT NULL REFERENCES receipts(id) ON DELETE CASCADE`, `attempt_number INT NOT NULL` [`attempt_number_positive`: `>= 1`], `trigger TEXT NOT NULL` [`trigger_valid`: `IN ('initial','auto_retry','manual_retry')`], `provider TEXT NOT NULL`, `model TEXT NOT NULL`, `prompt_version TEXT NOT NULL`, `outcome TEXT NOT NULL` [`outcome_valid`: `IN ('ok','invalid_output','provider_error')`], `parsed JSONB NULL`, `raw_output TEXT NULL`, `error_message TEXT NULL`, `check_results JSONB NULL`, `latency_ms INT NULL`, `input_tokens INT NULL`, `output_tokens INT NULL`, `cost_microusd BIGINT NULL`, `created_at`; `uq_parse_attempts_receipt_id_attempt_number UNIQUE (receipt_id, attempt_number)`; `uq_parse_attempts_id_receipt_id UNIQUE (id, receipt_id)` (target for composite FKs)
- **Circular FK**: `fk_receipts_active_parse_attempt_id_parse_attempts`: `receipts.active_parse_attempt_id → parse_attempts(id) ON DELETE SET NULL`, created with `op.create_foreign_key` **after** both tables exist; ORM `ForeignKey("parse_attempts.id", ondelete="SET NULL", use_alter=True)`. Downgrade drops this FK **first**, then drops tables in reverse creation order: `allocation_snapshots, assignments, corrections, parse_attempts, receipts, participants, households, users`.
- **corrections**: `id`, `receipt_id UUID NOT NULL REFERENCES receipts(id) ON DELETE CASCADE`, `parse_attempt_id UUID NOT NULL`, `sequence INT NOT NULL` [`sequence_positive`: `>= 1`], `kind TEXT NOT NULL` [`kind_valid`: `IN ('add_line','update_line','delete_line','update_totals')`], `line_id TEXT NULL`, `payload JSONB NOT NULL`, `created_at`; `uq_corrections_parse_attempt_id_sequence UNIQUE (parse_attempt_id, sequence)`; composite `fk_corrections_attempt_receipt FOREIGN KEY (parse_attempt_id, receipt_id) REFERENCES parse_attempts(id, receipt_id) ON DELETE CASCADE` (DB-enforces that a correction's receipt matches its attempt's receipt). Payload shapes specified in Slice 3; Slice 1 only stores JSONB.
- **assignments**: `parse_attempt_id UUID NOT NULL REFERENCES parse_attempts(id) ON DELETE CASCADE`, `line_id TEXT NOT NULL`, `participant_id UUID NOT NULL REFERENCES participants(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED`, `created_at`; `PRIMARY KEY (parse_attempt_id, line_id, participant_id)`
- **allocation_snapshots**: `id`, `receipt_id UUID NOT NULL REFERENCES receipts(id) ON DELETE CASCADE`, `parse_attempt_id UUID NOT NULL`, `allocator_version TEXT NOT NULL`, `input JSONB NOT NULL`, `result JSONB NOT NULL`, `created_at`; composite `fk_allocation_snapshots_attempt_receipt FOREIGN KEY (parse_attempt_id, receipt_id) REFERENCES parse_attempts(id, receipt_id) ON DELETE CASCADE`; index `ix_allocation_snapshots_receipt_id_created_at (receipt_id, created_at)`. **Not unique per receipt**: each finalize appends a snapshot; the current one is the latest `created_at`.

**ORM mapping:** one mapped class per table in `app/db/models.py`: `User` (users), `Household` (households), `Participant` (participants), `Receipt` (receipts), `ParseAttempt` (parse_attempts), `Correction` (corrections), `Assignment` (assignments), `AllocationSnapshot` (allocation_snapshots); SQLAlchemy 2.0 `Mapped[...]` / `mapped_column`; attribute names = column names; JSONB via `sqlalchemy.dialects.postgresql.JSONB`; no `relationship()`s in Slice 1.

#### A4.1 Complete list of database constraint/index names (asserted by the catalog test)
| Name | Type | Notes |
|---|---|---|
| `pk_users`, `pk_households`, `pk_participants`, `pk_receipts`, `pk_parse_attempts`, `pk_corrections`, `pk_assignments`, `pk_allocation_snapshots` | primary key (`p`) | `pk_assignments` is composite |
| `uq_users_email` | unique (`u`) | |
| `uq_parse_attempts_receipt_id_attempt_number` | unique (`u`) | |
| `uq_parse_attempts_id_receipt_id` | unique (`u`) | composite FK target |
| `uq_corrections_parse_attempt_id_sequence` | unique (`u`) | |
| `ck_households_name_length` | check (`c`) | |
| `ck_participants_display_name_length` | check (`c`) | |
| `ck_receipts_status_valid`, `ck_receipts_manual_retry_count_range` | check (`c`) | |
| `ck_parse_attempts_attempt_number_positive`, `ck_parse_attempts_trigger_valid`, `ck_parse_attempts_outcome_valid` | check (`c`) | |
| `ck_corrections_sequence_positive`, `ck_corrections_kind_valid` | check (`c`) | |
| `fk_households_owner_user_id_users` | foreign key (`f`) | CASCADE |
| `fk_participants_household_id_households` | foreign key (`f`) | CASCADE |
| `fk_receipts_household_id_households` | foreign key (`f`) | CASCADE |
| `fk_receipts_payer_participant_id_participants` | foreign key (`f`) | NO ACTION, `condeferrable = true`, `condeferred = true` |
| `fk_receipts_active_parse_attempt_id_parse_attempts` | foreign key (`f`) | SET NULL |
| `fk_parse_attempts_receipt_id_receipts` | foreign key (`f`) | CASCADE |
| `fk_corrections_receipt_id_receipts` | foreign key (`f`) | CASCADE |
| `fk_corrections_attempt_receipt` | foreign key (`f`) | composite, CASCADE |
| `fk_assignments_parse_attempt_id_parse_attempts` | foreign key (`f`) | CASCADE |
| `fk_assignments_participant_id_participants` | foreign key (`f`) | NO ACTION, `condeferrable = true`, `condeferred = true` |
| `fk_allocation_snapshots_receipt_id_receipts` | foreign key (`f`) | CASCADE |
| `fk_allocation_snapshots_attempt_receipt` | foreign key (`f`) | composite, CASCADE |
| `uq_participants_active_display_name` | unique **index** (in `pg_indexes`, not `pg_constraint`) | `indexdef` ends with `WHERE (archived_at IS NULL)` |
| `ix_allocation_snapshots_receipt_id_created_at` | index (in `pg_indexes`) | |

All other FKs in this list are not deferrable. The catalog test asserts: the set of `conname` for tables in schema `public` (excluding `alembic_version`) equals exactly the `pk_/uq_/ck_/fk_` names above with matching `contype`; the two deferrable FKs have `condeferrable AND condeferred`; all other FKs have `NOT condeferrable`; `pg_indexes` contains both index names and the partial predicate. The `uq_users_email` etc. unique constraints also create same-named indexes in `pg_indexes`; the index assertion only checks that the two listed index names are present.

**Deletion semantics**
- Participants are **never hard-deleted by the app**; removal = set `archived_at`. The participant FKs from `receipts.payer_participant_id` and `assignments.participant_id` are `NO ACTION DEFERRABLE INITIALLY DEFERRED`: a direct participant delete that is still referenced fails at commit, while deleting a household/user (which cascades to participants **and**, via receipts → parse_attempts, to assignments) succeeds because the check runs at commit after the whole cascade finishes. (Immediate `RESTRICT`/`NO ACTION` fails here because Postgres checks the participant reference before the nested cascade removes assignments — reproduced in design review.)
- Deleting a household or user removes everything beneath it.

**Invariants enforced by application code (not the DB), tested in the slice that first writes these rows**
- I1: `receipts.active_parse_attempt_id`, when set, references an attempt whose `receipt_id` is that receipt. (A composite FK would need `ON DELETE SET NULL (column)`, which SQLAlchemy's FK `ondelete` validator does not accept.) Written/tested in Slice 2.
- I2: `receipts.payer_participant_id` and every `assignments.participant_id` belong to the receipt's household. Written/tested in Slice 3.
- I3: `assignments.line_id` exists in the effective receipt for that attempt. Slice 3.

### A5. `ParsedReceipt` schema (`app/domain/receipt.py`, pydantic v2)
All models: `model_config = ConfigDict(extra="forbid", frozen=True)`. All cents/count integers are `StrictInt` (rejects `"123"`, `12.0`, `True`).
```python
MAX_ABS_CENTS = 10_000_000  # $100,000 sanity cap
LINE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"

LineKind = Literal["item", "discount", "fee", "deposit"]

class ReceiptLine(BaseModel):
    line_id: Annotated[str, Field(pattern=LINE_ID_PATTERN)]
    kind: LineKind
    raw_text: Annotated[str, Field(max_length=200)] = ""
    name: Annotated[str, Field(min_length=1, max_length=120)]
    quantity: Annotated[Decimal, Field(gt=0, decimal_places=3)] | None = None   # informational in v0
    unit_price_cents: Annotated[StrictInt, Field(ge=0, le=MAX_ABS_CENTS)] | None = None
    total_cents: Annotated[StrictInt, Field(ge=-MAX_ABS_CENTS, le=MAX_ABS_CENTS)]
    taxable: bool | None = None       # None = unknown; ignored by allocator on discount lines
    tax_code: Annotated[str, Field(max_length=8)] | None = None   # as printed; ignored by allocator
    discount_target_line_id: str | None = None  # allowed only when kind == "discount"

class TaxLine(BaseModel):
    label: Annotated[str, Field(min_length=1, max_length=40)]
    amount_cents: Annotated[StrictInt, Field(ge=0, le=MAX_ABS_CENTS)]

class ParsedReceipt(BaseModel):
    merchant_name: Annotated[str, Field(max_length=120)] | None = None
    chain: Annotated[str, Field(max_length=60)] | None = None
    purchased_on: date | None = None
    currency: Literal["USD"] = "USD"
    lines: Annotated[list[ReceiptLine], Field(max_length=300)]
    subtotal_cents: Annotated[StrictInt, Field(ge=0, le=MAX_ABS_CENTS)] | None = None
    tax_lines: Annotated[list[TaxLine], Field(max_length=5)] = []
    total_cents: Annotated[StrictInt, Field(ge=0, le=MAX_ABS_CENTS)] | None = None
    printed_item_count: Annotated[StrictInt, Field(ge=0)] | None = None
```
`ReceiptLine` `model_validator(mode="after")`: kind `item`/`fee`/`deposit` requires `total_cents >= 0`; kind `discount` requires `total_cents <= 0`; `discount_target_line_id` set on a non-discount → `ValueError`.
`ParsedReceipt` `model_validator(mode="after")`: `line_id`s unique; each `discount_target_line_id` references an existing line of kind `item` or `deposit`.

**Out of scope for v0 schema** (documented so Slice 2's parser maps them): voided/returned items, negative tax adjustments. Bottle-deposit **refunds** and coupons are represented as `discount` lines (targeted when the receipt ties them to an item, otherwise untargeted).

### A6. Slice plan
| Slice | Content | Gate |
|---|---|---|
| **1 (this doc)** | scaffold, CI, data model, receipt schema, allocator, health endpoints, deployed walking skeleton | this design check |
| 2 | storage upload, `ReceiptParser` protocol + providers, C1/C2/C3 checks, auto retry, suspect-line detectors, Retry Reading (cap 5), parse API, invariant I1 | own `/eg-new-feature`, after Week-1 benchmark |
| 3 | auth, households/participants UI, edit screen (correction events, live balance bar, LOW CONFIDENCE marker), tagging, finalize, summary, demo mode, rate limiting, invariants I2–I3 | own `/eg-new-feature` |
| 4 | auto-capture (corner/coverage/lighting/motion/focus checks, Capture + Upload always visible) | own `/eg-new-feature`, after iOS camera spike (`spikes/`) |

Migration policy for later slices: Railway runs migrations in a pre-deploy step while the previous container still serves traffic, so every migration after `0001` must be backward-compatible with the previous app version (expand → deploy → contract).

---

## Part B — Slice 1 detailed design

### Scope
**In:**
1. `git init` at repo root; root `.gitignore` (Python: `__pycache__/`, `.venv/`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `.hypothesis/`; Node: `node_modules/`, `.next/`, `coverage/`; env: `.env`, `.env.*` with `!.env.example`; OS: `.DS_Store`), `.editorconfig` (utf-8, lf, final newline, 2-space indent, 4-space for `*.py`), `.nvmrc`, `README.md`, `docs/design/`.
2. API scaffold (B1–B3).
3. SQLAlchemy models + Alembic migration `0001_initial` (A4).
4. Domain: `money.py`, `receipt.py` (A5), `allocation.py` (B4–B5).
5. API tests (B6).
6. Web scaffold + `ApiStatus` + tests (B7).
7. GitHub Actions CI (B8).
8. `.env.example` files; README (B9).
9. Walking-skeleton deploy (B10), done interactively with the user.

**Out:** auth, object storage, any LLM call, any allocation/receipt API endpoint, checks/suspects/corrections logic, UI beyond status page, camera spike, rate limiting, demo mode.

### B1. Settings (`app/config.py`)
```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore",
                                      hide_input_in_errors=True)   # never echo DATABASE_URL
    database_url: str                                                   # DATABASE_URL, required
    environment: Literal["local", "ci", "production"]                   # ENVIRONMENT, required (no default)
    cors_allowed_origins: Annotated[list[str], NoDecode] = []           # CORS_ALLOWED_ORIGINS, comma-separated
    vercel_preview_project: str | None = None                           # VERCEL_PREVIEW_PROJECT, ^[a-z0-9-]+$
    vercel_team_slug: str | None = None                                 # VERCEL_TEAM_SLUG, ^[a-z0-9-]+$

    @property
    def cors_allowed_origin_regex(self) -> str | None:
        # rf"^https://{re.escape(project)}-[a-z0-9-]+-{re.escape(team)}\.vercel\.app$" when both set

def get_settings() -> Settings: ...   # functools.lru_cache(maxsize=1)
```
*(Updated during pre-commit review: the preview regex is built from validated slugs instead of a free-form `CORS_ALLOWED_ORIGIN_REGEX`, which could be written to match any origin, e.g. `^https://.*|x\.vercel\.app$`; `environment` is required so production guards can't be silently skipped; the backend/driver must be `postgresql`+`psycopg`.)*
- `model_validator(mode="after")`: `VERCEL_PREVIEW_PROJECT` and `VERCEL_TEAM_SLUG` must be set together.
- `field_validator("cors_allowed_origins")` (after splitting): every entry other than `"*"` must satisfy `_canonical_origin(entry) == entry`, i.e. already be exactly what a browser sends in the `Origin` header (CORSMiddleware matches by string equality) → otherwise `ValueError("invalid CORS_ALLOWED_ORIGINS entry: ...")`. `_canonical_origin` returns `None` for any parse error and builds `scheme://host[:port]` where: scheme ∈ {http, https}; host is lowercase ASCII `[a-z0-9-]+(\.[a-z0-9-]+)*`, or dotted-quad IPv4 via `ipaddress.IPv4Address`, or bracketed compressed IPv6 via `ipaddress.IPv6Address`; port is numeric, in range, non-zero, and omitted when it is the scheme default. Rejected examples: trailing slash, path, query/fragment (even empty `?`/`#`), userinfo, uppercase scheme/host, `:443`/`:80`, `:0`, non-numeric port, `127.1`, `[0:0:0:0:0:0:0:1]`, non-ASCII (use punycode), spaces, unterminated `[`.
- `database_url` validator also rejects any backend/driver other than `postgresql`/`psycopg` (e.g. `postgresql+psycopg2://`, `sqlite://`) with `invalid DATABASE_URL`.
- Module-level `def normalize_database_url(url: str) -> str`: if `url` starts with `postgres://` or `postgresql://`, replace that prefix with `postgresql+psycopg://`; otherwise return `url` unchanged. `field_validator("database_url")` calls it, then validates with `sqlalchemy.engine.make_url(normalized)` and additionally reads `.port` (which raises `ValueError` for a non-numeric port); any `sqlalchemy.exc.ArgumentError` or `ValueError` is re-raised as `ValueError("invalid DATABASE_URL")` (message never includes the URL, which may contain a password). So a malformed URL fails at startup like a missing one. `tests/conftest.py` imports and reuses `normalize_database_url`.
- `get_settings()` body is `return Settings()` (mypy with pydantic-settings 2.15 needs no ignore).
- `field_validator("cors_allowed_origins", mode="before")`: if `str` → `[s.strip() for s in value.split(",") if s.strip()]`; if list → returned as is.
- `model_validator(mode="after")`: if `environment == "production"` and `"*" in cors_allowed_origins` → `ValueError("CORS wildcard not allowed in production")`.
- Missing `DATABASE_URL` → `pydantic.ValidationError` whose text contains `database_url`; raised when `get_settings()` is first called (inside `create_app()`), so uvicorn exits non-zero at import.

### B2. DB session (`app/db/session.py`)
```python
@lru_cache(maxsize=4)
def engine_for(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True, pool_timeout=2,
                         connect_args={"connect_timeout": 2})

def get_app_settings(request: Request) -> Settings:          # request.app.state.settings (set in create_app)
def get_engine(settings: Annotated[Settings, Depends(get_app_settings)]) -> Engine
def get_session(engine: Annotated[Engine, Depends(get_engine)]) -> Iterator[Session]

def check_database(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL statement_timeout = 2000"))   # scoped to this check only
        conn.execute(text("SELECT 1"))

def get_database_check(engine: Annotated[Engine, Depends(get_engine)]) -> DatabaseCheck:
    return lambda: check_database(engine)
```
*(Updated during pre-commit review: DB dependencies derive the engine from the settings passed to `create_app`, never from the process-wide `DATABASE_URL`, so an app built for one database can't silently use another; the statement timeout is scoped to the readiness transaction instead of every query.)*
`get_session` is not used by any Slice 1 route (future slices use it); it exists so the dependency pattern is established. Engine creation is lazy; importing never connects. Malformed URLs are rejected at startup by `Settings` (B1), so at request time `check_database` only raises `SQLAlchemyError` subclasses (e.g. `OperationalError`), which the route's `try` handles.

`alembic/env.py`: `url = context.config.attributes.get("connection_url") or get_settings().database_url`; online mode builds `create_engine(url, poolclass=NullPool)`; `target_metadata = Base.metadata` (imports `app.db.models` so all tables register). Offline mode not supported (raises `RuntimeError("offline migrations not supported")`).
`alembic.ini` and `alembic/script.py.mako` come from `uv run alembic init alembic` (generic template), with these changes to `alembic.ini`: `script_location = %(here)s/alembic`, `prepend_sys_path = .`, `sqlalchemy.url` left empty (URL comes from `env.py`), and `file_template = %%(rev)s_%%(slug)s`. `env.py` is then replaced per the above.

### B3. Endpoints (`app/routes/health.py`, `app/main.py`)
```python
router = APIRouter()

class HealthResponse(BaseModel):
    status: Literal["ok"]

class ReadyResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["ok", "error"]

@router.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse: return HealthResponse(status="ok")

@router.get("/readyz", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
def readyz(check: Annotated[DatabaseCheck, Depends(get_database_check)]) -> ReadyResponse | JSONResponse:
    try:
        check()
    except SQLAlchemyError:
        logger.warning("readiness check failed", exc_info=True)
        return JSONResponse(status_code=503, content=ReadyResponse(status="unavailable", database="error").model_dump())
    return ReadyResponse(status="ok", database="ok")
```
All dependencies use `Annotated[..., Depends(...)]` (no `Depends()` in defaults → ruff B008 clean). Routes are sync `def`. Worst-case `/readyz` latency ≈ 2 s pool wait + 2 s connect timeout + 2 s statement timeout.

`app/main.py`:
```python
def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="receipt-splitter API", version="0.1.0")
    app.state.settings = settings   # DB dependencies (B2) read this, never the global env
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_origin_regex=settings.cors_allowed_origin_regex,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    app.include_router(health.router)
    return app

app = create_app()
```
Logging: `logging.basicConfig(level=logging.INFO)` is **not** called by the app; uvicorn's logging config applies. Module logger `logger = logging.getLogger(__name__)`.

OpenAPI export (`app/scripts/export_openapi.py`): `main()` does `os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://localhost/unused")` and `os.environ.setdefault("ENVIRONMENT", "local")`, then `from app.main import create_app` (import inside `main()`), writes `json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"` to `Path(__file__).resolve().parents[3] / "web" / "src" / "lib" / "api" / "openapi.json"` (`parents[3]` = repo root for `api/app/scripts/export_openapi.py`), prints the path. `if __name__ == "__main__": main()`.

### B4. Money helpers (`app/domain/money.py`)
```python
def split_evenly(amount_cents: int, n: int, start_offset: int) -> list[int]:
    """Split a non-negative amount into n parts differing by at most 1 cent.
    Extra cents go to indices (start_offset + j) % n for j in range(amount_cents % n)."""
    # ValueError if amount_cents < 0, n < 1, or start_offset < 0

def allocate_proportionally(amount_cents: int, weights: list[int]) -> list[int]:
    """Largest-remainder allocation, integer math only.
    - ValueError if weights is empty or any weight < 0
    - amount_cents < 0: return [-x for x in allocate_proportionally(-amount_cents, weights)]
    - sum(weights) == 0: return split_evenly(amount_cents, len(weights), 0)
    - else: floor_i = amount*w_i // W; rem_i = amount*w_i % W; leftover = amount - sum(floor_i);
      add +1 to the first `leftover` indices sorted by (rem_i descending, index ascending)."""
```
No floats or `Decimal`. Known, accepted bias: on exact remainder ties the lower index wins; at most `len(weights) - 1` cents per call.

### B5. Allocator (`app/domain/allocation.py`)
```python
ALLOCATOR_VERSION = "1"
MAX_PARTICIPANTS = 20

class AllocationInput(BaseModel):          # extra="forbid", frozen=True
    receipt: ParsedReceipt
    participant_ids: list[UUID]            # order = tie-break order; size/uniqueness validated in allocate()
    assignments: dict[str, list[UUID]]     # line_id -> assignee ids

class LineShare(BaseModel):
    line_id: str
    share_cents: int
    split_count: int

class ParticipantAllocation(BaseModel):
    participant_id: UUID
    line_shares: list[LineShare]           # receipt line order; only lines assigned to this participant
    items_cents: int                       # Σ line_shares.share_cents
    receipt_discounts_cents: int           # <= 0
    fees_cents: int                        # >= 0
    tax_base_cents: int                    # >= 0; the base this participant's tax was computed on
    tax_cents: int                         # >= 0
    total_cents: int                       # items + receipt_discounts + fees + tax

class AllocationWarning(StrEnum):
    TAX_FALLBACK_PROPORTIONAL = "tax_fallback_proportional"
    TAX_WITHOUT_TAXABLE_LINES = "tax_without_taxable_lines"
    UNKNOWN_TAXABILITY = "unknown_taxability"
    ZERO_BASE_EQUAL_SPLIT = "zero_base_equal_split"

class AllocationResult(BaseModel):
    allocator_version: str
    participants: list[ParticipantAllocation]   # same order as participant_ids; idle participants included
    computed_total_cents: int
    printed_total_cents: int | None             # receipt.total_cents passthrough
    warnings: list[AllocationWarning]           # unique, sorted by enum value (string sort)

AllocationErrorCode = Literal[
    "no_participants", "too_many_participants", "duplicate_participant",
    "unknown_line", "assigned_non_assignable", "empty_assignment", "unknown_participant",
    "unassigned_line", "negative_line_net", "no_assignable_lines", "discount_exceeds_items",
]

class AllocationError(ValueError):
    def __init__(self, code: AllocationErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail       # human-readable; MUST contain the offending identifier(s) (see step 1)

class AllocationInvariantError(RuntimeError):
    """Internal arithmetic invariant violated — a programming bug."""

def allocate(inp: AllocationInput) -> AllocationResult: ...
```

**Definitions**
- *Assignable lines*: kind `item` or `deposit`. *Targeted discount*: kind `discount` with `discount_target_line_id`. *Receipt-level discount*: kind `discount` without target. *Fee*: kind `fee`. Only assignable lines may appear as assignment keys.
- *Active participants*: participants appearing in at least one assignment list (after de-dup). *Idle*: all others. Every zero-base/equal-split fallback distributes **only among active participants, in `participant_ids` order**; idle participants always receive 0 for every component.
- `alloc_active(amount, weights)`: build the sub-list of weights for active participants (in `participant_ids` order), call `allocate_proportionally(amount, sub_weights)`, scatter results back (idle = 0). Returns `(values, used_equal_fallback)` where `used_equal_fallback = amount != 0 and sum(sub_weights) == 0`.
- `T_total = Σ tax_lines.amount_cents`.

**Algorithm (steps in order)**
1. **Validate.** Checks run **one rule at a time over all inputs**, in this order; the first rule that finds any violation raises, reporting the first offender as defined:
   1. `participant_ids` empty → `no_participants`
   2. `len(participant_ids) > 20` → `too_many_participants`
   3. duplicate in `participant_ids` (first repeated id in list order) → `duplicate_participant`
   4. assignment key not a `line_id` in the receipt (smallest such key, lexicographic) → `unknown_line`
   5. assignment key on a non-assignable line (first such line in receipt order) → `assigned_non_assignable`
   6. assignment list empty (first such line in receipt order) → `empty_assignment`
   7. assignee not in `participant_ids` (first line in receipt order, then first id in list order) → `unknown_participant`
   8. assignable line without assignment key (first in receipt order) → `unassigned_line`
   9. `net(L) < 0` for an assignable line (first in receipt order; see step 2) → `negative_line_net`
   10. no assignable lines and (any discount `total_cents != 0` or any fee `total_cents != 0` or `T_total != 0`) → `no_assignable_lines`
   11. `-D > Σ net(L)` where `D` = Σ receipt-level discounts (step 4) → `discount_exceeds_items`

   `detail` format (exact wording otherwise free): rules 1–2 include the participant count; rule 3 includes the duplicated participant id; rules 4–6, 8–9 include the offending `line_id`; rule 7 includes both the `line_id` and the participant id; rules 10–11 include the relevant cents amounts. Tests assert `.code`, and the precedence test asserts the offending id appears in `detail`.
   Duplicate ids within one assignment list are de-duplicated (first occurrence kept) before rule 7. If there are no assignable lines and every amount is zero, return a result with all-zero participant rows, `computed_total_cents = 0`, no warnings.
2. **Line net:** `net(L) = L.total_cents + Σ total_cents of targeted discounts whose target is L`.
3. **Item shares:** keep `rotation: dict[frozenset[UUID], int]` (default 0). For each assignable line in receipt order: `assignees` = its de-duplicated ids sorted by position in `participant_ids`; `key = frozenset(assignees)`; `shares = split_evenly(net(L), len(assignees), rotation[key] % len(assignees))`; `rotation[key] += 1`. Append `LineShare(line_id=L.line_id, share_cents=s, split_count=len(assignees))` to each assignee. `items_i = Σ shares`.
4. **Receipt-level discounts:** `D = Σ receipt-level discount totals` (≤ 0). `(receipt_discounts, fb) = alloc_active(D, items)`; if `fb` add `ZERO_BASE_EQUAL_SPLIT` (cannot occur after rule 11 unless D = 0; kept for totality).
5. **Fees:** `F_tax = Σ fee totals with taxable is True`; `F_non = Σ other fee totals`. `(fee_tax, fb1) = alloc_active(F_tax, items)`; `(fee_non, fb2) = alloc_active(F_non, items)`; `fees_i = fee_tax_i + fee_non_i`; if `fb1 or fb2` add `ZERO_BASE_EQUAL_SPLIT`.
6. **Tax mode and base** (only item/deposit/fee lines are considered; discount lines' `taxable` is ignored):
   - **explicit** if any such line has `taxable is True and total_cents > 0`: `base_i = Σ share_cents_i over assignable lines with taxable is True + fee_tax_i`. If `T_total > 0` and any such line has `taxable is None` → add `UNKNOWN_TAXABILITY` (those lines treated as non-taxable).
   - else **fallback_unknown** if any such line has `taxable is None`: `base_i = items_i + fees_i`; if `T_total > 0` add `TAX_FALLBACK_PROPORTIONAL`.
   - else **fallback_none_taxable** (every such line is `taxable is False`, or `True` with total 0): `base_i = items_i + fees_i`; if `T_total > 0` add `TAX_WITHOUT_TAXABLE_LINES`.
   - Receipt-level discounts do **not** reduce the base (v0 limitation; NY store coupons do reduce taxable price).
   - `tax_base_cents_i = base_i` (idle participants: 0).
7. **Tax:** for each tax line in order: `(t, fb) = alloc_active(amount, base)`; `tax_i += t_i`; if `fb` add `ZERO_BASE_EQUAL_SPLIT`.
8. **Totals:** `total_i = items_i + receipt_discounts_i + fees_i + tax_i`. `computed_total_cents = Σ assignable line totals + Σ all discount totals + Σ fee totals + T_total`. If `Σ total_i != computed_total_cents` → raise `AllocationInvariantError`. Also raise `AllocationInvariantError` if any `total_i < 0`.

Receipt `subtotal_cents`/`total_cents` are not used for allocation (only passed through); reconciling them is Slice 2's checks.

### B6. Tests (api)

**`tests/conftest.py`**
- First statements (before importing `app`): `load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)` (`python-dotenv`, already a pydantic-settings dependency; also listed explicitly in the dev group), then `os.environ["DATABASE_URL"] = "postgresql+psycopg://localhost/unused"` (**overwrite**, never `setdefault`: `load_dotenv` already ran, so a default would let tests inherit the dev database URL from `api/.env`) and `os.environ.setdefault("ENVIRONMENT", "local")`.
- Hypothesis: `settings.register_profile("dev", max_examples=100)`, `settings.register_profile("ci", max_examples=500, derandomize=True)`, `settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))`.
- `test_database_url` (session scope): reads `os.environ.get("DATABASE_URL_TEST")` (populated from `api/.env` locally by `load_dotenv`, or by CI env). If unset: `pytest.fail("DATABASE_URL_TEST not set")` when `REQUIRE_DB_TESTS == "1"`, else `pytest.skip("DATABASE_URL_TEST not set")`. If `make_url(url).database` does not end with `_test` → `pytest.fail("refusing to run against non-test database")`. Returns `normalize_database_url(url)` (imported from `app.config`).
- `alembic_config` (session): `Config(str(API_ROOT / "alembic.ini"))` with `script_location` set to absolute `API_ROOT / "alembic"` and `cfg.attributes["connection_url"] = test_database_url`.
- `migrated_engine` (session): `command.downgrade(cfg, "base")`, `command.upgrade(cfg, "head")`; yields `create_engine(test_database_url, poolclass=NullPool)`; teardown `engine.dispose()` then `command.downgrade(cfg, "base")`. **All** `@pytest.mark.db` tests depend on this fixture, so schema state is owned in one place.
- `db_session` (function): `conn = migrated_engine.connect(); trans = conn.begin(); session = Session(bind=conn, join_transaction_mode="create_savepoint")`; yield; teardown `session.close(); trans.rollback(); conn.close()`. Every test's writes are rolled back.
- Factory helper `make_graph(session: Session) -> Graph` (in conftest). IDs are DB-generated, so the helper calls `session.flush()` **after each insert whose id is needed by a later row**:
  1. `User(email=f"{uuid4()}@test.local")` → flush
  2. `Household(owner_user_id=user.id, name="Test House")` → flush
  3. `Participant(household_id=..., display_name="P1", sort_order=0)` and `P2` (`sort_order=1`) → flush
  4. `Receipt(household_id=..., payer_participant_id=p1.id, status="needs_review")` → flush
  5. `ParseAttempt(receipt_id=receipt.id, attempt_number=1, trigger="initial", provider="test", model="test", prompt_version="v0", outcome="ok")` → flush
  6. `receipt.active_parse_attempt_id = attempt.id` → flush
  7. `Correction(receipt_id=receipt.id, parse_attempt_id=attempt.id, sequence=1, kind="update_line", line_id="L1", payload={})`, `Assignment(parse_attempt_id=attempt.id, line_id="L1", participant_id=p2.id)`, `AllocationSnapshot(receipt_id=receipt.id, parse_attempt_id=attempt.id, allocator_version="1", input={}, result={})` → flush
  8. `session.refresh(receipt)` and return
  ```python
  @dataclass(frozen=True)
  class Graph:
      user_id: UUID
      household_id: UUID
      payer_id: UUID        # P1
      member_id: UUID       # P2 (assigned to L1)
      receipt_id: UUID
      attempt_id: UUID
      correction_id: UUID
      snapshot_id: UUID
  ```
  Called independently per test so tests never share rows (emails are unique per call).

**`tests/test_config.py`**
- Autouse fixture deletes `ENVIRONMENT`, `CORS_ALLOWED_ORIGINS`, `VERCEL_PREVIEW_PROJECT`, `VERCEL_TEAM_SLUG` from the environment; helper `make_settings(**overrides)` = `Settings(_env_file=None, database_url=..., environment="local", **overrides)`.
- `normalize_database_url` / `Settings.database_url`: `postgres://…` and `postgresql://…` → `postgresql+psycopg://…`; `postgresql+psycopg://…` unchanged.
- `CORS_ALLOWED_ORIGINS=" https://a.com, https://b.com,, "` (via `monkeypatch.setenv`) → `["https://a.com", "https://b.com"]`.
- Malformed origins rejected with `invalid CORS_ALLOWED_ORIGINS entry`: trailing slash, path, query, empty `?`, empty `#`, no scheme, `ftp://`, no host, uppercase scheme, uppercase host, `:443` on https, `:80` on http, non-numeric port, out-of-range port, userinfo. Accepted: `http://localhost:3000`, `https://receipt-splitter.vercel.app`, `https://app.example.com:8443`, `http://[::1]:3000`.
- `environment="production"` with `cors_allowed_origins=["*"]` → `ValidationError`; `environment="local"` with `["*"]` → OK.
- Missing `DATABASE_URL` → `ValidationError` containing `database_url`; missing `ENVIRONMENT` → `ValidationError` containing `environment`.
- Vercel preview: no slugs → `cors_allowed_origin_regex is None`; slugs `receipt-splitter`/`kyle-team` → regex fullmatches `https://receipt-splitter-git-main-kyle-team.vercel.app` and rejects `https://evil.example`, `https://x.vercel.app`, `https://attacker.vercel.app`, another team's preview, `http://` preview, and a suffix-attack origin; only one slug set, or slugs containing regex/uppercase/underscore characters → `ValidationError`.
- Malformed/unsupported `DATABASE_URL` (non-numeric port, `not a url`, `postgresql+psycopg2://`, `sqlite:///x.db`, `mysql://`) → `ValidationError` containing `invalid DATABASE_URL` and never the password.

**`tests/domain/test_money.py`**
- Examples: `split_evenly(1000, 3, 0) == [334, 333, 333]`; `split_evenly(1000, 3, 1) == [333, 334, 333]`; `split_evenly(0, 4, 2) == [0, 0, 0, 0]`; `allocate_proportionally(1, [1, 1, 1]) == [1, 0, 0]`; `allocate_proportionally(100, [1000, 3000]) == [25, 75]`; `allocate_proportionally(-300, [1000, 2000]) == [-100, -200]`; `allocate_proportionally(5, [0, 0]) == [3, 2]`.
- `ValueError`: `split_evenly(5, 0, 0)`, `split_evenly(5, 2, -1)`, `split_evenly(-1, 2, 0)`, `allocate_proportionally(5, [1, -1])`, `allocate_proportionally(5, [])`.
- Properties (amount ∈ [-100_000, 100_000], weights: 1–10 ints ∈ [0, 100_000]): sum preserved; when `sum(weights) > 0`: `abs(result_i - Fraction(amount * w_i, W)) < 1`; `split_evenly` (amount ∈ [0, 100_000], n ∈ [1, 20], offset ∈ [0, 50]) parts differ by ≤ 1 and sum preserved.

**`tests/domain/test_receipt_schema.py`**
Rejects: duplicate `line_id`; discount with `total_cents=1`; item with `total_cents=-1`; `discount_target_line_id` on an item; target id not present; target pointing at a discount; target pointing at a fee; extra field `foo`; `total_cents=MAX_ABS_CENTS + 1`; `quantity=Decimal("1.2345")`; `line_id="bad id"`; `total_cents="123"` (strict); `total_cents=12.0` (strict). Accepts: a receipt containing one line of every kind with a valid targeted discount.

**`tests/domain/test_allocation.py`** (UUID constants `A`, `B`, `C`; lines default `taxable=None`; `name="x"`)
- **E1 NY tax** (`[A,B]`): `L1` item 6000 `taxable=False` → [A]; `L2` item 2000 `taxable=True` → [B]; tax 160 → A: tax_base 0, tax 0, total 6000; B: tax_base 2000, tax 160, total 2160; computed 8160; warnings `[]`.
- **E2 rotation same set** (`[A,B,C]`): `L1` item 1000 → [A,B,C]; `L2` item 1000 → [C,A,B] → L1 shares A 334, B 333, C 333; L2 shares A 333, B 334, C 333.
- **E2b rotation keyed by set** (`[A,B,C]`): `L1` item 101 → [A,B]; `L2` item 100 → [C]; `L3` item 101 → [A,B] → L1 A 51, B 50; L3 A 50, B 51.
- **E3 targeted discount** (`[A,B]`): `L1` item 500 → [A,B]; `D1` discount −100 target `L1` → shares 200/200; receipt_discounts 0/0; computed 400.
- **E4 receipt discount** (`[A,B]`): `L1` 1000 → [A]; `L2` 2000 → [B]; untargeted discount −300 → A −100, B −200.
- **E5 fallback unknown** (`[A,B]`): `L1` 1000 → [A]; `L2` 3000 → [B] (both `None`); tax 100 → A 25, B 75; warnings `[TAX_FALLBACK_PROPORTIONAL]`.
- **E6 unknown taxability** (`[A,B]`): `L1` 1000 `True` → [A]; `L2` 1000 `None` → [B]; tax 80 → A 80, B 0; warnings `[UNKNOWN_TAXABILITY]`.
- **E7 fees** (`[A,B]`): `L1` 1000 `False` → [A]; `L2` 3000 `False` → [B]; fee 10 `True`; tax 1 → fees A 3, B 7; tax_base A 3, B 7; tax A 0, B 1; warnings `[]`.
- **E8 zero base among active only** (`[A,B,C]`): `L1` item 500 `True` → [A,B]; `D1` discount −500 target `L1`; `L2` item 1000 `False` → [A]; tax 5 → tax A 3, B 2, C 0; C total 0; A total 1003; B total 2; computed 1005; warnings `[ZERO_BASE_EQUAL_SPLIT]`.
- **E9 idle participant** (`[A,B,C]`): `L1` 1000 → [A]; no tax lines (`tax_lines=[]`) → C row all zeros, `line_shares == []`.
- **E10 all non-taxable with tax** (`[A,B]`): `L1` 1000 `False` → [A]; `L2` 3000 `False` → [B]; tax 100 → A 25, B 75; warnings `[TAX_WITHOUT_TAXABLE_LINES]`.
- **E11 empty receipt** (`[A]`): no lines, no tax → A all zeros, computed 0, warnings `[]`. Same with tax 5 → `no_assignable_lines`.
- **E12 zero-total taxable line doesn't switch mode** (`[A,B]`): `L1` 1000 `None` → [A]; `L2` 0 `True` → [B]; tax 10 → A 10, B 0; warnings `[TAX_FALLBACK_PROPORTIONAL]`.
- **E13 fee with zero items base** (`[A,B]`): `L1` item 100 → [A,B]; `D1` discount −100 target `L1`; fee 5 `False` → fees A 3, B 2; warnings `[ZERO_BASE_EQUAL_SPLIT]`.
- **Errors:** one test per `AllocationErrorCode` asserting `.code`; plus two precedence tests: (a) input with both an unknown line key and an unassigned line → `unknown_line`; (b) two unassigned lines `L2`, `L5` → error raised (code `unassigned_line`) and `"L2" in err.detail`.
- **Properties** (`tests/domain/strategies.py` `allocation_inputs()` composite strategy; generator constructs only valid inputs — **no `assume` filtering**):
  - 1–5 participants; 1–30 lines with ≥ 1 assignable line; item/deposit totals ∈ [0, 50_000]; fee totals ∈ [0, 5_000]; `taxable` ∈ {True, False, None}.
  - Targeted discounts: target drawn from already-generated item/deposit lines; amount = −x with x ∈ [0, remaining_net(target)], then remaining_net decremented (guarantees net ≥ 0).
  - Receipt-level discounts: generated after all lines; amounts drawn so their total magnitude ≤ Σ nets.
  - Every assignable line assigned to a non-empty random subset (order shuffled); 0–3 tax lines ∈ [0, 5_000].
  - Test body calls `allocate`; any `AllocationError` fails the test.
  - P1 `Σ total_i == computed_total_cents`.
  - P2 per assignable line: Σ shares == net and max − min ≤ 1.
  - P3 `Σ tax_i == T_total`.
  - P4 explicit mode and `Σ tax_base > 0` → every participant with `tax_base_i == 0` has `tax_i == 0`.
  - P5 shuffling every assignment list yields an identical `AllocationResult`.
  - P6 every `total_i >= 0` and `items_i + receipt_discounts_i >= 0`.
  - P7 `T_total == 0` → all `tax_i == 0`.
  - P8 proportional bounds: if `len(tax_lines) > 0` and `Σ tax_base > 0`: `abs(tax_i − Fraction(T_total·tax_base_i, Σ tax_base)) < len(tax_lines)` (with no tax lines, P7 already covers tax); if `Σ items > 0`: `abs(receipt_discounts_i − Fraction(D·items_i, Σ items)) < 1` and `abs(fees_i − Fraction(F_total·items_i, Σ items)) < 2`.
  - P9 idle participants have every component 0.
  - P10 targeted-discount locality: for a generated input with at least one targeted discount `d` on target `L` where `L.total_cents + d.total_cents > 0`, build a variant with `d` removed and `L.total_cents += d.total_cents` → identical `participants` list. (Strategy `allocation_inputs_with_targeted_discount()` in `strategies.py` returns `tuple[AllocationInput, str]` — a valid input containing at least one targeted discount whose target's `total_cents > |discount total|`, and that discount's `line_id`. The test builds the variant from it.)

**`tests/db/test_migrations.py`** (`@pytest.mark.db`, uses `alembic_config`, `migrated_engine`)
- `test_round_trip`: `command.downgrade(cfg, "base")`, `command.upgrade(cfg, "head")`, `command.downgrade(cfg, "base")`, `command.upgrade(cfg, "head")` — ends at head.
- `test_orm_matches_migration`: with `migrated_engine.connect()` → `MigrationContext.configure(conn)`; `compare_metadata(ctx, Base.metadata) == []`.
- `test_catalog_names_and_predicates`: with `migrated_engine.connect()`:
  - `SELECT c.conname, c.contype, c.condeferrable, c.condeferred FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace WHERE n.nspname = 'public' AND t.relname <> 'alembic_version'` → `{conname: contype}` equals `EXPECTED_CONSTRAINTS` (dict literal in the test built from A4.1); `condeferrable and condeferred` is true exactly for `fk_receipts_payer_participant_id_participants` and `fk_assignments_participant_id_participants`; `condeferrable` is false for every other `f` row; every `len(conname) <= 63`.
  - `SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'` → contains `uq_participants_active_display_name` whose `indexdef` contains `UNIQUE` and ends with `WHERE (archived_at IS NULL)`, and contains `ix_allocation_snapshots_receipt_id_created_at`.

**`tests/db/test_schema_constraints.py`** (`@pytest.mark.db`, uses the `db_session` fixture and the plain helper imported via `from conftest import Graph, make_graph`, which resolves because `tests/` has no `__init__.py` and pytest's default import mode puts `tests/` on `sys.path`)
- `test_graph_inserts`: `make_graph` succeeds; `session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))` succeeds.
- Each of the following in its own test with `with pytest.raises(IntegrityError): with db_session.begin_nested(): ...; db_session.flush()`: `manual_retry_count = 6`; second parse_attempt with same `(receipt_id, attempt_number)`; second active participant with same `display_name`; correction whose `receipt_id` differs from its attempt's receipt (second receipt created in the same household).
- `test_archived_name_reuse`: archiving P1 then inserting a new participant with P1's name succeeds.
- `test_delete_parse_attempt_nulls_active_pointer`: **preconditions** (asserted before deleting): `db_session.get(Receipt, g.receipt_id).active_parse_attempt_id == g.attempt_id`; counts of corrections, assignments, allocation_snapshots with `parse_attempt_id == g.attempt_id` are each 1. Then `db_session.execute(delete(ParseAttempt).where(ParseAttempt.id == g.attempt_id))`; `SET CONSTRAINTS ALL IMMEDIATE`; `db_session.expire_all()`; assert receipt `active_parse_attempt_id is None` and the three counts are 0. All deletes in these tests are Core `delete()` statements (DB-side cascades, not ORM cascades).
- `test_delete_household_cascades` (separate `make_graph` call): **preconditions**: counts of receipts, parse_attempts, corrections, assignments, allocation_snapshots, participants reachable from `g.household_id` are 1, 1, 1, 1, 1, 2. Then `delete(Household).where(Household.id == g.household_id)`; `SET CONSTRAINTS ALL IMMEDIATE` (forces the deferred participant FK checks); all six counts are 0.
- `test_delete_referenced_participant_fails`: delete P2 (still assigned) → `IntegrityError` on `SET CONSTRAINTS ALL IMMEDIATE` (inside `begin_nested`).

**`tests/routes/test_health.py`**
- Fixture `app_and_client` yields `(app, TestClient(app))` for `app = create_app(Settings(_env_file=None, database_url="postgresql+psycopg://localhost/unused", environment="local"))` and clears `app.dependency_overrides` afterwards.
- `/healthz` → 200 `{"status": "ok"}`.
- `/readyz` with `app.dependency_overrides[get_database_check] = lambda: failing_check` where `failing_check()` raises `OperationalError("SELECT 1", {}, Exception("secret-conn-detail"))` → 503 `{"status": "unavailable", "database": "error"}` and `"secret-conn-detail" not in response.text`.
- Same with `ArgumentError("secret-conn-detail")` → 503, detail not leaked.
- `@pytest.mark.db` app built with `Settings(database_url=test_database_url, environment="local")` and **no** overrides → `/readyz` 200 `{"status": "ok", "database": "ok"}`.
- `@pytest.mark.db` isolation regression: process `DATABASE_URL` set to the reachable test DB (`get_settings.cache_clear()`), app built with settings pointing at a missing database → `/readyz` 503 (proves DB dependencies use `app.state.settings`, not the global URL).

**`tests/routes/test_cors.py`**
- App with `environment="production"`, `cors_allowed_origins=["http://localhost:3000"]`, `vercel_preview_project="receipt-splitter"`, `vercel_team_slug="kyle-team"`; `https://attacker.vercel.app` and `https://x.vercel.app` are also rejected.
- `OPTIONS /readyz` with `Origin: http://localhost:3000`, `Access-Control-Request-Method: GET` → 200 and `access-control-allow-origin == "http://localhost:3000"`.
- Same with `Origin: https://receipt-splitter-git-main-kyle-team.vercel.app` → allowed.
- Same with `Origin: https://evil.example` → response has no `access-control-allow-origin` header.
- `GET /healthz` with allowed `Origin` → `access-control-allow-origin` present.

### B7. Web
**Scaffold** (run from repo root **after** `git init`):
`npx create-next-app@latest web --ts --tailwind --eslint --app --src-dir --import-alias "@/*" --use-npm --disable-git --yes`
Post-scaffold steps (all required):
1. Verify `web/.git` does not exist.
2. **Keep and commit** `web/AGENTS.md` and `web/CLAUDE.md` as generated (Next 16's `next dev` regenerates them when it detects a coding agent, so deleting them would leave a dirty tree). They are not edited in this slice.
3. Leave React Compiler and bundler at `--yes` defaults; record resulting `next`, `react`, `eslint` versions in the README "Stack" table.
4. Confirm `tsconfig.json` has `"strict": true`.
5. Replace `src/app/page.tsx` boilerplate (below); keep `layout.tsx` and `globals.css` as generated.
6. Add `"engines": {"node": ">=24 <25"}` to `package.json`.
7. Keep the generated `web/.gitignore` (its `next-env.d.ts`, `*.tsbuildinfo`, `.vercel` rules are needed) and append a line `!.env.example` after its `.env*` rule, so `web/.env.example` is committed. Verify with `git check-ignore -q web/.env.example; echo $?` → `1` (not ignored). (`-v` would print the matching negation rule even when correct.)
8. After all web files in B7 are written, run `npx prettier --write .` once (the generated `next.config.ts` and others do not match Prettier defaults), then confirm `npm run format:check` passes.

**Dev dependencies added:** `prettier`, `eslint-config-prettier`, `vitest`, `@vitejs/plugin-react`, `jsdom`, `@testing-library/react`, `@testing-library/dom`, `@testing-library/jest-dom`, `openapi-typescript`.

**Config files**
- `.prettierrc`: `{}`. `.prettierignore`: `.next`, `node_modules`, `coverage`, `src/lib/api/schema.d.ts`, `src/lib/api/openapi.json`, `package-lock.json`.
- `eslint.config.mjs` (generated flat config): add `import eslintConfigPrettier from "eslint-config-prettier/flat";` and append `eslintConfigPrettier` as the **last** config entry; add `"src/lib/api/schema.d.ts"` to the generated ignores list (`globalIgnores([...])` if the template uses it, otherwise an `{ ignores: [...] }` entry).
- `vitest.config.mts`:
  ```ts
  import { defineConfig } from "vitest/config";
  import react from "@vitejs/plugin-react";
  import { fileURLToPath } from "node:url";
  export default defineConfig({
    plugins: [react()],
    test: { environment: "jsdom", setupFiles: ["./vitest.setup.ts"], include: ["src/**/*.test.{ts,tsx}"] },
    resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  });
  ```
- `vitest.setup.ts`:
  ```ts
  import "@testing-library/jest-dom/vitest";
  import { cleanup } from "@testing-library/react";
  import { afterEach, vi } from "vitest";
  afterEach(() => { cleanup(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
  ```
- `package.json` scripts: `dev` / `build` / `start` (as generated), `lint`: `eslint .`, `format:check`: `prettier --check .`, `typecheck`: `next typegen && tsc --noEmit` (generated `layout.tsx` uses the global `LayoutProps` type, which exists only after `next typegen`/`dev`/`build`), `test`: `vitest run`, `gen:api`: `openapi-typescript ./src/lib/api/openapi.json -o ./src/lib/api/schema.d.ts`.
- `web/.env.example`: `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`.

**`src/lib/api/config.ts`**
```ts
export function apiBaseUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!raw || raw.trim() === "") throw new Error("NEXT_PUBLIC_API_BASE_URL is not set");
  return raw.trim().replace(/\/+$/, "");
}
```
Note: `NEXT_PUBLIC_*` is inlined at **build** time; changing the API URL requires a web rebuild/redeploy.

**`src/components/ApiStatus.tsx`** (`"use client"`)
```ts
import type { components } from "@/lib/api/schema";
type ReadyResponse = components["schemas"]["ReadyResponse"];

export type ApiStatusState =
  | { kind: "checking" }
  | { kind: "ok" }
  | { kind: "unavailable" }                  // 503 with body.status === "unavailable"
  | { kind: "error"; httpStatus: number }    // any other non-ok status, or unparseable/unexpected body
  | { kind: "unreachable" }                  // network/CORS failure
  | { kind: "misconfigured" };               // NEXT_PUBLIC_API_BASE_URL missing

export function ApiStatus(): React.JSX.Element
```
Behavior:
- `const [state, setState] = useState<ApiStatusState>({ kind: "checking" })`.
- `useEffect(() => { const controller = new AbortController(); async function run(signal: AbortSignal): Promise<void> { ... } void run(controller.signal); return () => controller.abort(); }, [])`. **`run` is declared inside the effect callback** (not in the component body): Next 16's `eslint-plugin-react-hooks` rule `react-hooks/set-state-in-effect` errors when an effect calls a component-scope function that sets state.
- `run(signal)` body:
  1. `let base: string; try { base = apiBaseUrl(); } catch { setState({ kind: "misconfigured" }); return; }`
  2. `let res: Response; try { res = await fetch(\`${base}/readyz\`, { signal, cache: "no-store" }); } catch (err) { if (signal.aborted) return; setState({ kind: "unreachable" }); return; }`
  3. `let body: unknown; try { body = await res.json(); } catch { if (signal.aborted) return; setState({ kind: "error", httpStatus: res.status }); return; }`
  4. `if (signal.aborted) return;`
  5. `isReadyResponse(body)` (type guard: object with `status` ∈ {"ok","unavailable"} and `database` ∈ {"ok","error"}) is false → `{ kind: "error", httpStatus: res.status }`.
  6. `res.status === 200 && body.status === "ok"` → `ok`; `res.status === 503 && body.status === "unavailable"` → `unavailable`; otherwise `error` with `res.status`.
- The component never calls `console.*`.
- Render: `<p role="status">` with text: checking `Checking API…`; ok `API: ok`; unavailable `API: unavailable (database)`; error `` `API error (HTTP ${httpStatus})` ``; unreachable `API unreachable`; misconfigured `API URL not configured`.
- SSR: `page.tsx` is a server component; `ApiStatus` renders `Checking API…` on the server and in the first client render (identical → no hydration mismatch); the fetch runs only in the effect.

**`src/app/page.tsx`**: server component: `<main className="p-6"><h1 className="text-2xl font-semibold">receipt-splitter</h1><ApiStatus /></main>`.

**`src/lib/api/config.test.ts`**: `vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test///")` → `"http://api.test"`; `""` → throws `NEXT_PUBLIC_API_BASE_URL is not set`.

**`src/components/ApiStatus.test.tsx`** (each test stubs env `http://api.test` unless stated; `fetch` stubbed with `vi.fn()`):
1. resolves `new Response(JSON.stringify({status:"ok",database:"ok"}), {status:200})` → `await screen.findByText("API: ok")`; `fetch` called with `"http://api.test/readyz"` and an object containing `cache: "no-store"`.
2. resolves 503 `{status:"unavailable",database:"error"}` → `API: unavailable (database)`.
3. resolves 500 `{detail:"x"}` → `API error (HTTP 500)`.
4. resolves 200 body `"not json"` → `API error (HTTP 200)`.
5. rejects `new TypeError("Failed to fetch")` → `API unreachable`.
6. env stubbed to `""` → `API URL not configured`; `fetch` not called.
7. unmount before resolve: `fetch` mock returns a promise that rejects with `new DOMException("Aborted", "AbortError")` when the passed `signal` fires `abort`; render, `unmount()`; assert captured `signal.aborted === true`; then `await capturedPromise.catch(() => undefined)` (the promise rejects by design; this waits for the component's rejection handler to run); test passes with no unhandled rejection (Vitest fails the run on unhandled rejections by default).

### B8. CI (`.github/workflows/ci.yml`)
Triggers: `push` to `main`, `pull_request` targeting `main`. `concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: true }`.

**api job** (`runs-on: ubuntu-latest`, `defaults.run.working-directory: api`):
- `services.postgres`: `image: postgres:16`, `env: {POSTGRES_PASSWORD: postgres, POSTGRES_DB: receipt_splitter_test}`, `ports: ["5432:5432"]`, `options: --health-cmd pg_isready --health-interval 5s --health-timeout 5s --health-retries 10`.
- Job `env`: `DATABASE_URL: postgresql+psycopg://postgres:postgres@localhost:5432/receipt_splitter_test`, `DATABASE_URL_TEST` (same), `REQUIRE_DB_TESTS: "1"`, `HYPOTHESIS_PROFILE: ci`, `ENVIRONMENT: ci`.
- Steps: `actions/checkout@v4`; `astral-sh/setup-uv@v6` with `version: "0.9.7"`, `python-version: "3.13"`, `enable-cache: true`; `uv sync --frozen`; `uv run ruff check .`; `uv run ruff format --check .`; `uv run mypy app`; `uv run pytest`; `uv run python -m app.scripts.export_openapi`; `test -z "$(git status --porcelain -- ../web/src/lib/api/openapi.json)"`.

**web job** (`runs-on: ubuntu-latest`, `defaults.run.working-directory: web`):
- Steps: `actions/checkout@v4`; `actions/setup-node@v4` with `node-version-file: .nvmrc`, `cache: npm`, `cache-dependency-path: web/package-lock.json`; `npm ci`; `npm run lint`; `npm run format:check`; `npm run gen:api`; `test -z "$(git status --porcelain -- src/lib/api/schema.d.ts)"`; `npm run typecheck`; `npm test`; `npm run build` with `env: NEXT_PUBLIC_API_BASE_URL: http://localhost:8000`.

**`api/pyproject.toml`** (relevant parts):
```toml
[project]
name = "receipt-splitter-api"
version = "0.1.0"
requires-python = ">=3.13,<3.14"
dependencies = ["fastapi", "uvicorn[standard]", "sqlalchemy>=2.0", "alembic", "psycopg[binary]>=3.2", "pydantic>=2.7", "pydantic-settings>=2.7"]

[dependency-groups]
dev = ["pytest", "hypothesis", "httpx", "ruff", "mypy", "python-dotenv"]

[tool.ruff]
line-length = 100
target-version = "py313"
[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "RUF"]
[tool.ruff.lint.per-file-ignores]
"tests/conftest.py" = ["E402"]            # load_dotenv must run before importing app

[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]

[tool.pytest.ini_options]
pythonpath = [".", "tests/domain"]
testpaths = ["tests"]
markers = ["db: requires Postgres"]
```
(Exact dependency versions are resolved by `uv lock` at scaffold time and committed in `uv.lock`; `uv sync` includes the `dev` group by default.)

### B9. Local dev (README)
1. `brew install postgresql@16 && brew services start postgresql@16`; `createdb receipt_splitter`; `createdb receipt_splitter_test`. (Stop any other running Homebrew Postgres on 5432 first.)
2. `nvm install 24 && nvm use` (reads `.nvmrc`).
3. `cd api && cp .env.example .env && uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --reload --port 8000`. `api/.env.example`:
   ```
   DATABASE_URL=postgresql+psycopg://localhost/receipt_splitter
   DATABASE_URL_TEST=postgresql+psycopg://localhost/receipt_splitter_test
   CORS_ALLOWED_ORIGINS=http://localhost:3000
   ENVIRONMENT=local
   ```
4. `cd web && cp .env.example .env.local && npm install && npm run dev`.
5. Tests: `cd api && REQUIRE_DB_TESTS=1 uv run pytest` (conftest loads `api/.env`, so `DATABASE_URL_TEST` is found); `cd web && npm test`.
6. After changing API routes: `cd api && uv run python -m app.scripts.export_openapi && cd ../web && npm run gen:api`, commit both files.

README also contains: project one-liner, Stack table (with versions from B7 step 3), architecture sketch (web → api → Postgres), link to this design doc.

### B10. Deploy (interactive with user; nothing created without their confirmation)
- **GitHub:** user creates repo, pushes `main`; CI must be green before connecting platforms.
- **Railway (api):** project with a Postgres service (major version 16; verify via `SELECT version()` in Railway's query tab; if the template default differs, choose the v16 image before creating data) and an api service with root directory `api/`. `api/railway.toml`:
  ```toml
  [build]
  builder = "RAILPACK"

  [deploy]
  preDeployCommand = ["uv run --frozen --no-dev alembic upgrade head"]
  startCommand = "uv run --frozen --no-dev uvicorn app.main:app --host 0.0.0.0 --port $PORT"
  healthcheckPath = "/readyz"
  healthcheckTimeout = 60
  ```
  Service setting "Config-as-code path" = `/api/railway.toml`. Env: `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `ENVIRONMENT=production`, `CORS_ALLOWED_ORIGINS=<vercel production URL>`, `VERCEL_PREVIEW_PROJECT=receipt-splitter`, `VERCEL_TEAM_SLUG=<vercel-team-slug>`. If Railpack does not expand `$PORT` in `startCommand`, wrap it as `sh -c "uv run --frozen --no-dev uvicorn app.main:app --host 0.0.0.0 --port $PORT"`. `api/mise.toml` pins uv for Railpack's build: `[tools]` / `uv = "0.9.7"` (same version as CI and A1). `--frozen` makes `uv run` use `uv.lock` as-is without re-resolving at container start.
  **CORS preview-regex limitation (security):** the regex also matches the production domain of any Vercel project anyone creates named `receipt-splitter-<x>-<team-slug>`. Acceptable in Slice 1 only because every endpoint is public and `allow_credentials=False`. **Slice 3 (auth) must, before shipping any authenticated endpoint, unset `VERCEL_PREVIEW_PROJECT`/`VERCEL_TEAM_SLUG` in production** and either enable Vercel Deployment Protection for previews with a separate preview API service, or accept that previews call no authenticated endpoints. Recorded in Out-of-scope follow-ups.
- **Vercel (web):** root directory `web/`, Node.js version 24.x, env `NEXT_PUBLIC_API_BASE_URL=<railway api public URL>` for Production and Preview.
- **Checks:** Railway `/readyz` → 200; Vercel production URL shows `API: ok`; a Vercel preview URL also shows `API: ok` (CORS regex).

### Failure modes
| Failure | What user/dev sees |
|---|---|
| Postgres down / wrong creds / locked | `/readyz` → 503 JSON within ~4 s; web `API: unavailable (database)`; API logs WARNING with traceback |
| Malformed `DATABASE_URL` (bad scheme, non-numeric port) | API exits at startup with `invalid DATABASE_URL` (no URL echoed) |
| API down or origin not allowed by CORS | web `API unreachable`; browser console shows its own network/CORS error |
| Wrong API base URL pointing at a server that returns 404 with CORS headers | web `API error (HTTP 404)` |
| Unhandled exception in API (500) | Starlette's `ServerErrorMiddleware` sits outside `CORSMiddleware`, so the 500 carries no CORS headers; the browser blocks it and web shows `API unreachable`. The `error` branch for 5xx is exercised only by the mocked unit test (reachable if a future proxy returns 5xx with CORS headers). API logs the traceback. |
| `NEXT_PUBLIC_API_BASE_URL` missing at build | web `API URL not configured`; no fetch |
| `DATABASE_URL` missing | API exits at startup; pydantic error names `database_url` |
| Railway `postgres://` URL | normalized by `Settings` |
| Migration fails on deploy | pre-deploy command fails → deploy aborted; previous deployment keeps serving |
| Invalid allocator input | `AllocationError(code, detail)`; Slice 3 maps to HTTP 422 |
| Allocator arithmetic bug | `AllocationInvariantError` (not `assert`, survives `python -O`); property tests catch in CI |
| OpenAPI drift or uncommitted generated file | CI `git status --porcelain` check fails |
| DB tests silently skipped in CI | `REQUIRE_DB_TESTS=1` → `pytest.fail` |
| Tests pointed at dev DB | fixture refuses DB names not ending `_test` |
| Participant deleted while referenced | deferred FK fails at commit (app archives instead) |
| Vercel preview calling API | allowed via regex built from `VERCEL_PREVIEW_PROJECT` + `VERCEL_TEAM_SLUG` |

### Validation & auth
No auth in Slice 1. `/healthz`, `/readyz` public; fixed enum bodies expose no internals. CORS: explicit allowlist + preview regex; `*` rejected in production. Receipt data validation: pydantic `ParsedReceipt` (`extra="forbid"`, `StrictInt` money).

### Verification criteria
1. `cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy app && REQUIRE_DB_TESTS=1 uv run pytest` green locally against Postgres 16: includes `test_config.py`, E1–E13, every error code + precedence tests, P1–P10, schema tests, migration round-trip + `compare_metadata == []`, all constraint/cascade tests, health + CORS tests.
2. `cd web && npm run lint && npm run format:check && npm run typecheck && npm test && npm run build` green (Node 24).
3. `curl -i localhost:8000/healthz` → 200 `{"status":"ok"}`; `curl -i localhost:8000/readyz` → 200 `{"status":"ok","database":"ok"}`; after `brew services stop postgresql@16`, `/readyz` → 503 `{"status":"unavailable","database":"error"}`; `curl -i -X OPTIONS localhost:8000/readyz -H "Origin: http://localhost:3000" -H "Access-Control-Request-Method: GET"` shows `access-control-allow-origin: http://localhost:3000`.
4. Chrome MCP against a **production build** of web (`cd web && npm run build && npm start`, with `.env.local` pointing at `http://localhost:8000`) at `http://localhost:3000`; only console messages at **warning or error** level are evaluated (info/debug/log ignored): (a) all up → `API: ok`, zero warnings/errors; (b) Postgres stopped → reload shows `API: unavailable (database)`; the only warning/error is the browser's own "Failed to load resource … 503"; (c) uvicorn stopped → reload shows `API unreachable`; the only warnings/errors are the browser's own network-failure messages. In all cases no React/hydration errors.
5. CI workflow green on first push to GitHub.
6. Production: Railway `/readyz` 200; Vercel production URL shows `API: ok`; a preview URL (created during B10 by pushing a throwaway branch `deploy-preview-check`, deleted afterwards) shows `API: ok`.
7. `cd api && uv run alembic downgrade base && uv run alembic upgrade head` succeeds against the local dev DB.

### Out-of-scope follow-ups
Slices 2–4 (A6); iOS Safari camera resolution spike (`spikes/camera-res/`); Week-1 20-receipt LLM benchmark; auth provider choice; object storage provider; allocation endpoint + 422 mapping; tax-base handling of store coupons; per-item multiple tax rates; voided/returned items and negative tax; invariants I1–I3 enforcement + tests; async DB driver if Slice 2 needs it; fairer tie-breaking in `allocate_proportionally` (rotation) if penny bias proves noticeable; **Slice 3 blocker:** disable the Vercel preview CORS allowance (`VERCEL_PREVIEW_PROJECT`/`VERCEL_TEAM_SLUG`) or replace it before any authenticated endpoint ships (B10).

---

## Revision log (round 1 → revision 1)
| Source | Gap | Resolution |
|---|---|---|
| Critic 1 / Readiness 1 | Household delete fails on RESTRICT participant FKs | A4: participant FKs `NO ACTION DEFERRABLE INITIALLY DEFERRED`; participants archived, never hard-deleted; tests force `SET CONSTRAINTS ALL IMMEDIATE` |
| Critic 2 / Readiness 2 | `DATABASE_URL_TEST` not loaded locally | B6 conftest `load_dotenv(api/.env)` before anything else |
| Critic 3 | `app` not importable | A3 lists every `__init__.py`; pytest `pythonpath` |
| Critic 4 | Cross-row integrity; snapshot UNIQUE vs history | A4 composite FKs for corrections/snapshots; invariants I1–I3 app-enforced with named slices; snapshots append-only, no UNIQUE |
| Critic 5 | ORM/migration parity, UUID/timestamp defaults, names, downgrade order | A4 conventions: DB-generated UUIDs, `server_default`, naming convention, explicit downgrade order, `compare_metadata` test |
| Critic 6 | Zero-base fallback charges idle participants; fees no warning | B5 active-participant fallback (`alloc_active`), warnings in steps 4/5/7, E8/E13, P9 |
| Critic 7 | Tax mode flips on all-False or $0 True line | B5 step 6 three modes (explicit requires `True` with total > 0), new `TAX_WITHOUT_TAXABLE_LINES`, E10/E12; discount `taxable` ignored |
| Critic 8 | Penny rotation biased | B5 step 3 rotation keyed per assignee set (E2b); proportional tie bias documented in B4 |
| Critic 9 / Readiness 6 | Validation order ambiguous | B5 step 1 rule-at-a-time with explicit first-offender definition; `detail` non-contract; precedence tests |
| Critic 10 | `assert` stripped under -O | `AllocationInvariantError` |
| Critic 11 | Schema can't express refunds/voids/negative tax; empty receipt | A5 out-of-scope note + refunds as discounts; B5 rule 10 + E11 |
| Critic 12 | Property test validity (W=0, discount sign, assume filtering) | B6 bounds restricted to W>0; constructive generator, no `assume` |
| Critic 13 | Properties too weak | P6 `total_i ≥ 0`, P8 proportional bounds (via new `tax_base_cents`), P9 idle, P10 discount locality |
| Critic 14 / Readiness 5 | Settings/CORS/`apiBaseUrl` untested | `tests/test_config.py`, `tests/routes/test_cors.py`, `config.test.ts` |
| Critic 15 | `/readyz` hang / 500 on bad URL | B2 `statement_timeout`, `pool_timeout`; `check_database` dependency called inside `try` |
| Critic 16 / Readiness 4 | ApiStatus mislabels errors; console criterion contradictory | B7 state union with `error`/`misconfigured`, JSON-parse handling, no app logging; Verification 4 allows browser-originated network log entries |
| Critic 17 | Weak web tests (cleanup, abort, stub restore) | `vitest.setup.ts` cleanup + unstub; abort-aware fetch mock; React 18 warning assertion removed |
| Critic 18 | Node 20 EOL | Node 24 LTS everywhere |
| Critic 19 | create-next-app prompts, AGENTS.md, nested git, prettier flat config | B7 `--yes --disable-git` after root `git init`, delete AGENTS.md/CLAUDE.md, flat-config prettier + ignores |
| Critic 20 | Ruff B008 | `Annotated[..., Depends(...)]` |
| Critic 21 | Railway runtime/migration/version/CORS previews/build-time env | B10 `railway.toml` pre-deploy + `--no-dev`, `.python-version`, PG16 pin, preview regex, build-time env note; A6 expand/contract policy |
| Critic 22 | Drift check misses untracked; setup-uv unpinned; dev group | B8 `git status --porcelain`, `setup-uv@v6` uv 0.9.7, `[dependency-groups] dev` |
| Critic 23 | DB fixture ordering / IntegrityError rollback | B6 single `migrated_engine` owner, per-test rollback session, `begin_nested` per expected error |
| Critic 24 | Lax int coercion | A5 `StrictInt` + strict tests |
| Readiness 3 | Shared smoke data between delete tests | `make_graph` per test, per-test rollback |
| Comprehension | P3 wording | Rewritten |

## Revision log (round 2 → revision 2)
| Source | Gap | Resolution |
|---|---|---|
| Readiness 1 | P8 tax bound false with zero tax lines | P8 tax bound applies only when `len(tax_lines) > 0` |
| Readiness 2 | Generated `web/.gitignore` `.env*` hides `web/.env.example` | B7 step 7: keep file, append `!.env.example`, verify with `git check-ignore` |
| Readiness 3 | Verification 4 console criterion ambiguous in dev | Run against production build; only warning/error level evaluated |
| Critic (round 2) | Did not complete (API rate limit) | Re-run in round 3 |

## Revision log (round 3 → revision 3)
| Source | Gap | Resolution |
|---|---|---|
| Critic 1 / Readiness 1 | Snapshot composite FK name 66 chars > 63 | Explicit short names `fk_corrections_attempt_receipt`, `fk_allocation_snapshots_attempt_receipt`; A4.1 name list; ≤63 asserted |
| Critic 2 | Plain-string names double-prefixed by naming convention in migration | All migration names wrapped in `op.f()` |
| Critic 3 | `compare_metadata` misses names, CHECKs, partial-index predicate | New `test_catalog_names_and_predicates` against `pg_constraint`/`pg_indexes` |
| Critic 4 | `tsc` fails on clean checkout (`LayoutProps`) | `typecheck` = `next typegen && tsc --noEmit` |
| Critic 5 | Prettier fails on scaffold | B7 step 8 `npx prettier --write .` |
| Critic 6 | `next dev` regenerates AGENTS.md/CLAUDE.md | Keep and commit them |
| Critic 7 / Readiness minor | `NoDecode` needs pydantic-settings ≥ 2.7 | Floor raised |
| Critic 8 | `make_graph` ids None before flush; vacuous delete test | Per-step flushes, `Graph` dataclass, precondition asserts, Core deletes |
| Critic 9 | `await` rejecting promise throws | `await capturedPromise.catch(() => undefined)` |
| Critic 10 | Preview CORS regex matches foreign Vercel projects | Documented limitation + Slice 3 blocker |
| Readiness minor | web job `runs-on`; revision id; normalizer name; ORM class names | `ubuntu-latest`; `revision = "0001"`; `normalize_database_url`; ORM mapping paragraph |

## Revision log (round 4 → revision 4, user override at 3-revision cap)
Round 4: readiness `implementation ready`; critic `design needs revision` (5 gaps). User chose "Override and proceed"; fixes below applied without a further goldfish round.
| Source | Gap | Resolution |
|---|---|---|
| Critic 1 | `run` in component body fails `react-hooks/set-state-in-effect` | B7: `run` declared inside effect callback |
| Critic 2 | `git check-ignore -v` prints on correct config | `git check-ignore -q`, expect exit 1 |
| Critic 3a | Real API 500 has no CORS headers → web shows unreachable | Failure-modes row corrected |
| Critic 3b | Non-numeric port raises `ValueError` → 500 | `Settings` validates via `make_url` + `.port`; startup failure; config test (no password echo) |
| Critic 4 | Railpack uv unpinned; `uv run` re-resolves | `api/mise.toml` uv 0.9.7; `uv run --frozen --no-dev` |
| Critic 5 | `detail` "not a contract" vs precedence test | `detail` must contain offending identifiers; format per rule |
| Readiness (minor) | `make_graph` import; E402; mypy `Settings()`; alembic.ini template; E9 tax wording; strategy return type; preview URL | `from conftest import ...`; per-file E402 ignore; `# type: ignore[call-arg]`; `alembic init` + listed changes; `tax_lines=[]`; `tuple[AllocationInput, str]`; throwaway branch |
