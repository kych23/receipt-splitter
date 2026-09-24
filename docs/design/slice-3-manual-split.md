# DESIGN DOC — Slice 3: manual-entry splitting flow

**Status:** revision 4 (answers design-check rounds 1–4; round-4 fixes applied under owner override at the 3-revision cap, not re-reviewed; see Revision log at end). Implements
`docs/design/v0-architecture-and-slice-1.md` §A8 (no accounts, no history) and replaces §A6 row 3.
§A7 store profiles are **not** in this slice. The v0 doc is updated to revision 7 in this slice to
match (see "Changes to the v0 design doc").

## Why
The live site only shows `API: ok`. This slice makes it a working bill splitter without any receipt
parsing: a person types a receipt's items and tax, types who is splitting it, taps items to people,
and reads exact per-person totals computed by the existing allocator (`api/app/domain/allocation.py`).
Slice 2's parser later fills the same receipt with parsed lines instead of typed ones.

Owner decisions for this slice (this conversation, 2026-09-23):
- Receipt state lives in an **ephemeral server row** (§A8), saved as the user edits.
- Tax is entered as **the tax amount printed on the receipt** plus a **taxed yes/no choice per item**.
- **One scrolling page** on a phone, with a sticky totals bar.
- **No shareable link.** The summary is copied to the clipboard as text.

## Scope
**In**
1. Migration `0002`: drop `allocation_snapshots`, `assignments`, `participants`, `households`,
   `users`; reshape `receipts` for ephemeral, account-free use.
2. Receipt API: create (empty or example), read, save (whole document, last writer wins), delete.
   Every read/save response carries the computed allocation.
3. Per-IP rate limiting, a request body size cap, and a JSON 500 handler that keeps CORS headers.
4. Scheduled purge (Railway cron) plus an opportunistic purge on requests.
5. Web: start screen (new receipt / try example), items editor, tax field, people editor, tagging,
   sticky totals bar, summary with "Copy summary", "Delete receipt", "Start a new receipt".
6. Example receipt from the owner's Target receipt (2026-09-22 10:15 PM).
7. v0 design doc revision 7 (slice reorder, participants shape, `store_profile_id` in `0003`).

**Out (explicit)**
- Photo upload, parsing, add-up checks C1–C3, Retry Reading, suspect lines (Slice 2).
- Store profiles, store dropdown, `store_profile_id` column (Slice 2, migration `0003`).
- Editing discount, fee and deposit lines, or printed subtotal/total. The API accepts any valid
  `ParsedReceipt`; the editor passes such lines through unchanged and shows them read-only.
- Shareable links, accounts, saved people, receipt history, payments (by design, §A8).
- Uneven shares; shared items are always split evenly.
- Multi-tab collaboration: two tabs on one receipt overwrite each other (last writer wins).

## Surfaces touched
**API**
- `api/app/db/models.py`: remove `User`, `Household`, `Participant`, `Assignment`,
  `AllocationSnapshot`; reshape `Receipt` (see Migration).
- `api/alembic/versions/0002_ephemeral_receipts.py` (new).
- `api/app/receipts/__init__.py`, `schemas.py`, `service.py`, `example.py`, `purge.py` (new package).
- `api/app/routes/receipts.py` (new router, prefix `/v1/receipts`).
- `api/app/ratelimit.py` (new): limiter + ASGI middleware.
- `api/app/logging_config.py` (new): `configure_logging() -> None` — if the root logger has no
  handlers, `logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")`.
  Called at the top of `create_app` and of `app.scripts.purge.main`, so `app.*` INFO lines (purge
  count, client-IP verification) reach Railway's logs.
- `api/app/middleware.py` (new): body size cap + JSON 500 handler, both ASGI middleware.
- `api/app/scripts/purge.py` (new): `main(database_url: str | None = None) -> int` — uses the
  argument or `get_settings().database_url`, builds its own `create_engine(url, poolclass=NullPool)`,
  calls `purge_expired` in a session, disposes the engine, returns the count. `if __name__ == "__main__"`
  calls `main()`.
- `api/railway.cron.toml` (new): see Ops.
- `api/app/config.py`: add `rate_limit_trusted_proxy_hops: Annotated[int, Field(ge=0, le=5)] = 0` and
  `rate_limit_log_client_ip: bool = False` (deploy-time verification only; see checklist step 4).
- `api/app/main.py`: `FastAPI(..., separate_input_output_schemas=False)`, include receipts router,
  middleware stack (see "Middleware order"), CORS `allow_methods` adds `PUT`,
  `expose_headers=["Retry-After"]`, `create_app(settings=None, rate_limits=None, clock=None)`.
- `api/.env.example`: add `RATE_LIMIT_TRUSTED_PROXY_HOPS=0`.
- Tests: see Verification.

**Generated:** `web/src/lib/api/openapi.json`, `web/src/lib/api/schema.d.ts`.

**Web**
- `web/src/lib/money.ts`, `web/src/lib/ids.ts`, `web/src/lib/stored-receipt-id.ts`,
  `web/src/lib/api/receipts.ts`, `web/src/lib/receipt-state.ts`, `web/src/lib/summary-text.ts` (new).
- `web/src/components/split/`: `SplitApp.tsx`, `StartScreen.tsx`, `ItemsEditor.tsx`, `TaxField.tsx`,
  `PeopleEditor.tsx`, `TagList.tsx`, `TotalsBar.tsx`, `Summary.tsx` (new).
- `web/src/app/page.tsx`: render `<SplitApp />`; `<ApiStatus />` moves to a footer line.

**Ops**
- API service: env `RATE_LIMIT_TRUSTED_PROXY_HOPS` set per the deploy checklist below.
- New file `api/railway.cron.toml` for a second Railway service ("purge"), same repo, root `/api`,
  with its "Config-as-code path" set to `/api/railway.cron.toml` so it does **not** inherit
  `api/railway.toml` (which would start uvicorn, run migrations pre-deploy, and health-check `/readyz`):
  ```toml
  [build]
  builder = "RAILPACK"

  [deploy]
  startCommand = "uv run --frozen --no-dev python -m app.scripts.purge"
  cronSchedule = "0 * * * *"
  restartPolicyType = "NEVER"
  ```
  No `preDeployCommand`, no `healthcheckPath`. Env: `DATABASE_URL=${{Postgres.DATABASE_URL}}`,
  `ENVIRONMENT=production`. The key names are checked against Railway's config-as-code reference at
  deploy time (checklist step 3).
- **Deploy checklist** (manual, in order):
  1. `SELECT count(*) FROM receipts` on production; record it (rows are accepted as lost).
  2. Push; confirm the API deploy runs `0002` and `/readyz` is ok.
  3. Create the purge service from `api/railway.cron.toml`; confirm in Railway's docs that
     `cronSchedule` / `restartPolicyType` are the current key names; trigger one manual run and see
     `purged N expired receipts` in its logs.
  4. Client-IP check: set `RATE_LIMIT_LOG_CLIENT_IP=true` on the API, make one request from a known
     IP, read the logged `X-Forwarded-For` and resolved key, choose `RATE_LIMIT_TRUSTED_PROXY_HOPS`
     so the resolved key equals the known IP (expected: 1), then set `RATE_LIMIT_LOG_CLIENT_IP=false`.
  5. Run the manual browser checks against production.

## Data lifecycle (§A8)
- The only rows written are `receipts` (from Slice 2 also `parse_attempts` / `corrections`).
- `expires_at` = `now() + 1 hour` on create (a never-saved receipt is cheap to recreate, and a burst
  of creates must not hold live-receipt slots for a day) and `now() + 24 hours` on every successful
  save (sliding). *(Pre-commit review, round 1.)*
- A receipt with `expires_at <= now()` is nonexistent to every route (404) even before purge.
- **Purge** — `purge_expired(session: Session) -> int` runs
  `DELETE FROM receipts WHERE expires_at <= clock_timestamp()` (cascades to `parse_attempts`,
  `corrections`), commits, returns the row count, logs `"purged %d expired receipts"` at INFO. Runs:
  1. hourly from the Railway cron (`app.scripts.purge`), which is what makes the promise
     "deleted within about an hour after expiring" true with no traffic;
  2. inside `POST /v1/receipts`, before the insert.
- `DELETE /v1/receipts/{id}` deletes immediately.
- **Logging:** this slice adds no request logging. Uvicorn's access log records method, path
  (containing the random receipt id) and status. No code logs item names, people's names or amounts.
- **Browser:** `localStorage["receiptsplit.receiptId"]` holds only the current receipt id.

## Migration & deploy — `0002_ephemeral_receipts`
`revision = "0002"`, `down_revision = "0001"`. All constraint/index names via `op.f()`, ≤ 63 chars.

**upgrade()**
1. `DELETE FROM receipts` (cascades). Receipts are ephemeral by design; any rows are disposable. The
   deploy checklist runs `SELECT count(*) FROM receipts` first and records the number; rows are
   accepted as lost, not a reason to abort.
2. `op.drop_table("allocation_snapshots")`, `op.drop_table("assignments")`.
3. Drop FK `fk_receipts_payer_participant_id_participants`, column `payer_participant_id`;
   drop FK `fk_receipts_household_id_households`, column `household_id`.
4. `op.drop_table("participants")`, `op.drop_table("households")`, `op.drop_table("users")`.
5. On `receipts` add:
   - `content JSONB NOT NULL DEFAULT '{"lines": [], "tax_lines": []}'::jsonb`
   - `participants JSONB NOT NULL DEFAULT '[]'::jsonb`
   - `assignments JSONB NOT NULL DEFAULT '{}'::jsonb`
   - `is_example BOOLEAN NOT NULL DEFAULT false`
   - `expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '24 hours')`
   - index `ix_receipts_expires_at` on `(expires_at)`
6. Drop check `ck_receipts_status_valid`; recreate it as
   `status IN ('draft', 'uploaded', 'parsing', 'needs_review', 'finalized', 'parse_failed')`;
   set `status` server default to `'draft'`.

**downgrade()**: `DELETE FROM receipts`; drop the `status` default; restore the 0001 status check;
drop the index and the five added columns; recreate `users`, `households`, `participants` exactly as
in `0001` (same names, same constraints); re-add `receipts.household_id` (NOT NULL, FK CASCADE) and
`payer_participant_id` (deferred FK); recreate `assignments` and `allocation_snapshots` as in `0001`.
Data loss on downgrade is intended.

**Backward compatibility (a deliberate one-step contract).** CLAUDE.md asks for expand → deploy →
contract. This migration contracts in one step, which is safe only because the deployed Slice 1 app
never queries these tables (its only DB statement is `SELECT 1` in `/readyz`). The exception is
recorded in the v0 doc's revision log.

**ORM**: delete the five classes. `Receipt` loses `household_id`, `payer_participant_id`; gains
`content: Mapped[dict[str, Any]]`, `participants: Mapped[list[dict[str, Any]]]`,
`assignments: Mapped[dict[str, list[str]]]` (all `JSONB` with matching `server_default=text(...)`),
`is_example: Mapped[bool]` (`server_default=text("false")`), `expires_at: Mapped[datetime]`
(`server_default=text("(now() + interval '24 hours')")`), `Index("ix_receipts_expires_at", "expires_at")`,
and the new status check; `status` gets `server_default=text("'draft'")`. `ParseAttempt` and
`Correction` are unchanged.

## Interfaces

### API schemas (`api/app/receipts/schemas.py`)
All models `ConfigDict(extra="forbid")`. `ParsedReceipt` is `app.domain.receipt.ParsedReceipt`.
```python
NameStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]

class Participant(BaseModel):
    key: UUID
    display_name: NameStr

class ReceiptState(BaseModel):
    content: ParsedReceipt
    participants: Annotated[list[Participant], Field(max_length=20)]   # list order = display order
    assignments: dict[str, list[UUID]]                                  # line_id -> participant keys

class CreateReceiptRequest(BaseModel):
    example: bool = False

class SaveReceiptRequest(ReceiptState):
    pass

class AllocationProblem(BaseModel):
    code: AllocationErrorCode
    detail: str

class ReceiptResponse(ReceiptState):
    id: UUID
    is_example: bool
    updated_at: datetime
    expires_at: datetime
    allocation: AllocationResult | None
    allocation_problem: AllocationProblem | None      # exactly one of allocation / allocation_problem is non-null

class ErrorResponse(BaseModel):                          # 404, 413, 429, 500
    detail: str

```
`main.py` passes `separate_input_output_schemas=False` so `ParsedReceipt` (and therefore
`content`) is one OpenAPI schema used by both the save body and the response.

### Service (`api/app/receipts/service.py`)
```python
class ReceiptNotFound(Exception): ...
class ReceiptValidationError(Exception):
    def __init__(self, problems: list[str]) -> None

def validate_state(state: ReceiptState) -> None                          # raises ReceiptValidationError
def compute_allocation(state: ReceiptState) -> tuple[AllocationResult | None, AllocationProblem | None]
def create_receipt(session: Session, *, example: bool) -> Receipt           # purges first, checks cap, commits
class ServiceBusy(Exception): ...                                           # live-receipt cap reached
def get_receipt(session: Session, receipt_id: UUID) -> Receipt              # raises ReceiptNotFound
def save_receipt(session: Session, receipt_id: UUID, state: ReceiptState) -> Receipt   # raises both; commits
def delete_receipt(session: Session, receipt_id: UUID) -> None             # raises ReceiptNotFound; commits
def to_response(receipt: Receipt) -> ReceiptResponse                       # re-validates stored JSON, allocates
```
- **`validate_state` rules**, each producing one message string:
  - participant keys unique → `"duplicate participant key"`
  - display names unique after `.strip().lower()` → `"duplicate person name: <name>"`
  - every assignment key is a `line_id` in `content.lines` whose kind is `item` or `deposit` →
    `"tag on unknown or non-item line: <line_id>"`
  - every assigned key is a participant key → `"tag references unknown person"`
  - no assignment list is empty and none has duplicates → `"empty or duplicate tag list: <line_id>"`
  The route catches `ReceiptValidationError` and raises FastAPI's `RequestValidationError(errors=[
  {"loc": ["body"], "msg": problem, "type": "value_error"} for problem in problems])`, so every 422
  (body parsing, path parsing, service rules) has FastAPI's standard `HTTPValidationError` shape and
  the generated OpenAPI 422 schema stays accurate. Routes do **not** declare a custom 422 model.
- **`compute_allocation`** builds `AllocationInput(receipt=state.content, participant_ids=[p.key ...],
  assignments=...)` and calls `allocate`. `AllocationError` → `(None, AllocationProblem(code, detail))`.
  Any other exception (e.g. `AllocationInvariantError`) propagates → 500.
- **Lookups** use `WHERE id = :id AND expires_at > clock_timestamp()`.
- **Storage caps.** `MAX_LIVE_RECEIPTS = 10_000`: after purging, `create_receipt` counts rows with
  `expires_at > clock_timestamp()`; at or above the cap it raises `ServiceBusy`, which the route maps
  to 503 `{"detail": "busy, try again later"}` (declared). `MAX_STATE_BYTES = 262_144`: `save_receipt`
  measures `len(json.dumps(state.model_dump(mode="json")).encode())` and raises
  `ReceiptValidationError(["receipt too large"])` (→ 422) above it. Worst case is therefore
  10,000 × 256 KiB ≈ 2.5 GB, bounded; normal receipts are a few KB. The 1 MiB request cap stays as
  the transport limit; the 256 KiB state cap is the storage limit.
- **`save_receipt`** loads the row with the ORM, assigns `content`, `participants`, `assignments`
  (`model_dump(mode="json")`), sets `expires_at = func.clock_timestamp() + timedelta(hours=24)` and
  `updated_at = func.clock_timestamp()` explicitly, commits. `Receipt.updated_at`'s ORM `onupdate`
  also changes to `func.clock_timestamp()` (Python-side only; no DDL change). `clock_timestamp()` is
  used instead of `now()` so values advance inside a single test transaction.
- **Transactions:** the service owns `commit()`. `get_session` does not commit.
- **Last writer wins.** There is no version check. A single tab never loses edits because the client
  always sends its *current* full state (never a queued stale body) and allows one request in flight.
  Two tabs on the same receipt overwrite each other; out of scope.

### Routes (`api/app/routes/receipts.py`, prefix `/v1/receipts`)
| Method, path | Body | Success | Errors (all declared in `responses=`) |
|---|---|---|---|
| `POST /v1/receipts` | `CreateReceiptRequest` | 201 `ReceiptResponse` | 413, 422, 429, 500, 503 |
| `GET /v1/receipts/{id}` | — | 200 `ReceiptResponse` | 404, 422, 429, 500 |
| `PUT /v1/receipts/{id}` | `SaveReceiptRequest` | 200 `ReceiptResponse` | 404, 413, 422, 429, 500 |
| `DELETE /v1/receipts/{id}` | — | 204 | 404, 422, 429, 500 |
- 404 body `{"detail": "receipt not found"}`. 422 is always FastAPI's `HTTPValidationError` shape.
  Declared `responses=` cover 404/413/429/500 (and 503 on create) with `ErrorResponse`; 422 is FastAPI's default.
- Routes are sync `def`, depend on `get_session` (`api/app/db/session.py`).
- Receipt ids are random UUIDv4 (`gen_random_uuid()`); possession of an id is the only access
  control. Ids never appear in the UI or in URLs.

### Middleware order (`api/app/main.py`)
Starlette's `add_middleware` makes the **last added the outermost**. Added in this order, so the
request passes through them top to bottom:
1. `CORSMiddleware` — outermost (added last), so every response below it, including 413/429/500,
   carries CORS headers. `expose_headers=["Retry-After"]`.
2. `JsonErrorMiddleware` — catches any exception from inside, logs it with traceback, returns
   500 `{"detail": "internal error"}`.
3. `RateLimitMiddleware` — applies to paths starting `/v1/receipts`; every request counts,
   including ones that later fail with 413/422.
4. `BodySizeLimitMiddleware` — for POST/PUT under `/v1/receipts`, limit **1 MiB (1048576 bytes)**:
   `Content-Length` over the limit → 413 `{"detail": "request too large"}` sent directly, without
   calling the app. Without `Content-Length`, the middleware wraps `receive`, counts bytes, and on
   overflow raises `HTTPException(status_code=413, detail="request too large")` from the wrapped
   `receive` (FastAPI re-raises `HTTPException` from body reading; any other exception would become
   a 400). The limit is sized so the largest state the model allows fits (300 lines × 20 people with
   36-char ids is ≈ 400 KB); a test builds that state and asserts it serializes under the limit.
Code: `app.add_middleware(BodySizeLimitMiddleware)`, then `RateLimitMiddleware`, then
`JsonErrorMiddleware`, then `CORSMiddleware`.

### Rate limiting (`api/app/ratelimit.py`)
```python
@dataclass(frozen=True)
class Bucket:
    capacity: int
    period_s: float                                   # full refill time

@dataclass(frozen=True)
class RateLimits:
    create: Bucket = Bucket(30, 3600)                 # POST /v1/receipts, keyed by client key
    per_receipt: Bucket = Bucket(1200, 3600)          # GET/PUT/DELETE /v1/receipts/{id}, keyed by path id
    per_client: Bucket = Bucket(20_000, 3600)         # every /v1/receipts* request, keyed by client key

class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic, max_keys: int = 10_000) -> None
    def check(self, bucket_name: str, bucket: Bucket, client_key: str) -> float | None
        # None = allowed (one token consumed); else seconds until one token is available
```
- A `threading.Lock` guards all state (routes run in a threadpool).
- Eviction: at most once per 60 s (by clock), `check` sweeps and removes keys idle > 3600 s. Each
  bucket name has its own LRU capped at `max_keys`, trimmed on every `check`, so churn in one bucket
  (e.g. many receipt ids) can never evict — and so refill — another bucket's keys. *(Pre-commit
  review, round 1.)*
- Every `/v1/receipts*` request first consumes a `per_client` token, then its route bucket
  (`create` for POST, `per_receipt` otherwise); either being empty → 429. `per_client` caps what one
  client can do across random ids (20,000 requests/hour ≈ 5.5/s: enough for ~70–200 people editing
  receipts behind one campus NAT, while still bounding a single abusive client).
- **Client key**: take the address resolved below; if it parses with `ipaddress.ip_address`, IPv6 is
  keyed by its `/64` network (`ipaddress.ip_network(f"{ip}/64", strict=False)`) — `/48` for the
  `create` bucket, since one household or VPS often holds a whole /56 or /48 — and IPv4 by the full
  address; if it does not parse (e.g. TestClient's `"testclient"`) the raw string is the key; if
  `scope["client"]` is `None`, the key is `"unknown"`.
- `create` and `per_client` use the client key. `per_receipt` uses the
  `{id}` path segment in canonical UUID form (`str(uuid.UUID(segment))`, so every spelling of one id
  shares a bucket); a segment that isn't a UUID gets no bucket (the route answers 422). Keying edits per receipt means
  roommates behind one campus NAT don't share an autosave budget; 1200 saves/hour/receipt is far above
  the ~100–300 saves a long hand-typed receipt produces, and a receipt id is only known to its creator.
- IP resolution, with `hops = settings.rate_limit_trusted_proxy_hops`: if `hops == 0`,
  `scope["client"][0]`; otherwise split `X-Forwarded-For` on commas, strip, take the element at index
  `-hops`; if there are fewer than `hops` elements or it is not a valid IP, fall back to
  `scope["client"][0]`.
- Exceeded → 429 `{"detail": "too many requests"}`, header `Retry-After: <ceil(seconds)>`.
- `create_app(rate_limits=..., clock=...)` lets tests use tiny buckets and a fake clock; the limiter
  lives on `app.state.rate_limiter`.
- When `settings.rate_limit_log_client_ip` is true, the middleware logs the raw `X-Forwarded-For`
  and the resolved key once per request at INFO (deploy verification only; default off).
- Known limits: per-process state (fine for Railway's single replica); people behind one NAT share the
  `create` bucket (30 new receipts/hour/network) and the `per_client` bucket (20,000 requests/hour); `hops` must match Railway's actual header shape
  (deploy checklist step 4).

### Example receipt (`api/app/receipts/example.py`)
From the owner's Target receipt, 2026-09-22 10:15 PM (photo `spikes/receipts/target2.jpg`, gitignored;
line amounts transcribed from it, totals verified in `spikes/chain-tax-codes.md`).
| line_id | name | total_cents | taxable | tax_code | tagged to |
|---|---|---|---|---|---|
| `ex-1` | Cheetos | 489 | false | NF | Alex, Sam |
| `ex-2` | e.l.f. | 1112 | true | T | Jordan |
| `ex-3` | Kitsch | 999 | true | T | Sam |
| `ex-4` | e.l.f. | 463 | true | T | Jordan |
| `ex-5` | Slime Mart | 500 | true | T | Alex, Sam, Jordan |
`merchant_name: "Target"`, `tax_lines: [{"label": "NY TAX 8%", "amount_cents": 246}]`,
`subtotal_cents: 3563`, `total_cents: 3809`. People Alex, Sam, Jordan with keys
`00000000-0000-4000-8000-000000000001` … `…003`. Stored with `is_example = true`.

**Pinned expected allocation** (hand-checked, and confirmed by running the allocator):
| Person | Line shares | Items | Tax | Total |
|---|---|---|---|---|
| Alex | ex-1 245, ex-5 167 | 412 | 14 | **426** |
| Sam | ex-1 244, ex-3 999, ex-5 167 | 1410 | 93 | **1503** |
| Jordan | ex-2 1112, ex-4 463, ex-5 166 | 1741 | 139 | **1880** |
Sum 3809 = `computed_total_cents` = `total_cents`; no warnings. Alex's and Sam's Cheetos shares are
untaxed (Alex's tax comes only from his Slime Mart share).

### Web

**IDs (`web/src/lib/ids.ts`)**: `export function newId(): string` returns a v4 UUID built from
`crypto.getRandomValues` (works on insecure origins such as `http://<LAN-IP>:3000`, where
`crypto.randomUUID` is unavailable).

**Stored id (`web/src/lib/stored-receipt-id.ts`)**
```ts
export function useStoredReceiptId(): string | null | undefined
    // useSyncExternalStore. Server snapshot = undefined ("not known yet"); client snapshot = an
    // in-memory variable initialised once from localStorage (null if absent or storage throws).
export function setStoredReceiptId(id: string | null): void
    // updates the in-memory variable FIRST, notifies subscribers, then best-effort writes localStorage
```
All `localStorage` access is in `try/catch`. The in-memory variable is the source of truth for the
current tab, so the app works when storage is unavailable; only reopening after a refresh is lost.
This avoids reading storage in an effect (fails `react-hooks/set-state-in-effect`) and avoids a
hydration mismatch (the server renders the start state; the client re-renders after hydration).

**Money (`web/src/lib/money.ts`)** — string parsing only, never `parseFloat`:
```ts
export function parseDollars(input: string): number | null
export function formatCents(cents: number): string          // 489 -> "$4.89", -200 -> "−$2.00", 0 -> "$0.00", 123456 -> "$1,234.56" (comma thousands)
export function centsToInput(cents: number): string          // 489 -> "4.89", 400 -> "4.00"
```
`parseDollars`: trim; strip one leading `$`; trim again; must match `^(\d{1,5})(?:\.(\d{1,2}))?$`;
cents = `int(whole) * 100 + int(frac.padEnd(2, "0"))`. Valid: `"4.89"`→489, `"4"`→400, `"4.8"`→480,
`"$4.89"`→489, `" 4.89 "`→489, `"0"`→0, `"0.00"`→0, `"007"`→700, `"99999.99"`→9999999.
Invalid (→ `null`): `""`, `"-1"`, `"4.891"`, `"4."`, `".5"`, `"1,000.00"`, `"abc"`, `"100000"`.

**API client (`web/src/lib/api/receipts.ts`)**
```ts
export type ReceiptResponse = components["schemas"]["ReceiptResponse"];
export type SaveReceiptRequest = components["schemas"]["SaveReceiptRequest"];
export class ApiError extends Error {
  constructor(public status: number | null, public retryAfterS: number | null) // null status = network
}
export type SaveResult =
  | { kind: "saved"; receipt: ReceiptResponse }
  | { kind: "not_found" }
  | { kind: "rate_limited"; retryAfterS: number }        // Retry-After header, default 60 if absent
  | { kind: "rejected" }                                 // 413 or 422
  | { kind: "server_error" }                             // any 5xx
  | { kind: "network_error" };                           // fetch rejected (not aborted)
export async function createReceipt(example: boolean): Promise<ReceiptResponse>   // throws ApiError
export async function getReceipt(id: string): Promise<ReceiptResponse | null>     // 404 -> null; else throws ApiError
export async function saveReceipt(id: string, body: SaveReceiptRequest, signal?: AbortSignal): Promise<SaveResult>
    // Combines the caller's signal with AbortSignal.timeout(15_000) via AbortSignal.any.
    // Timeout (DOMException name "TimeoutError") -> { kind: "network_error" }.
    // Caller abort (name "AbortError") -> rejects; SplitApp ignores it.
export async function deleteReceipt(id: string): Promise<void>                     // 204/404 resolve; else throws ApiError
```

**Editor state (`web/src/lib/receipt-state.ts`)** — pure, unit-tested:
```ts
type ItemDraft = {
  lineId: string; name: string; priceInput: string; taxable: boolean | null;
  taxCode: string | null;             // kept from the server; cleared when `taxable` changes
  passthrough: Record<string, unknown>; // other ReceiptLine fields (raw_text, quantity, unit_price_cents) sent back unchanged
};
type EditorState = {
  base: Omit<ParsedReceipt, "lines" | "tax_lines">;   // merchant_name, chain, purchased_on, currency, subtotal_cents, total_cents, printed_item_count
  items: ItemDraft[];                  // kind "item" lines only, in receipt order
  readOnlyLines: ReceiptLine[];        // discount/fee/deposit lines, passed through unchanged
  taxInput: string; taxLabel: string;  // single editable tax line
  extraTaxLines: TaxLine[] | null;     // non-null when the server content had 2+ tax lines (tax field read-only)
  people: { key: string; name: string }[];
  tags: Record<string, string[]>;      // lineId -> person keys in people order; a key is absent, never []
  dirty: boolean;                      // local changes not yet acknowledged by a save
};
type Action =
  | { type: "addItem" } | { type: "updateItem"; lineId: string; patch: { name?: string; priceInput?: string; taxable?: boolean } }
  | { type: "removeItem"; lineId: string }
  | { type: "setTax"; input: string }
  | { type: "addPerson"; name: string } | { type: "removePerson"; key: string }
  | { type: "toggleTag"; lineId: string; key: string }
  | { type: "loadFromServer"; receipt: ReceiptResponse }
  | { type: "markSaved" };
export function initialState(): EditorState
export function reducer(state: EditorState, action: Action): EditorState
export function addPersonError(state: EditorState, name: string): string | null
export function toSaveBody(state: EditorState): { body: SaveReceiptRequest } | { invalid: string[] }
```
Rules:
- Every action except `loadFromServer` and `markSaved` sets `dirty = true`. `loadFromServer` sets
  `dirty = false` and never triggers a save.
- `loadFromServer`: `kind: "item"` lines → `items` (`priceInput = centsToInput(total_cents)`, taxable,
  tax_code, other fields into `passthrough`); other kinds → `readOnlyLines`; 0 tax lines → `taxInput ""`,
  label `"Tax"`; 1 → `taxInput = centsToInput(amount)`, `taxLabel = label`; 2+ → `extraTaxLines` set,
  `taxInput` = their sum (display only); people from `participants`; tags from `assignments`.
- Editing any item price, adding/removing an item, or changing tax sets `base.subtotal_cents` and
  `base.total_cents` to `null` (the printed figures no longer describe the edited receipt).
- `toggleTag`: adds the key in people order, or removes it; removing the last key deletes the entry.
  `removeItem` deletes the item's entry. `removePerson` removes the key everywhere and deletes
  entries that become empty.
- `addItem` appends `{name: "", priceInput: "", taxable: null, taxCode: null, passthrough: {}}`; ignored
  at 300 lines (items + readOnlyLines). New ids from `newId()`. `taxable: null` is deliberate: the
  choice is required, and until it is made the allocator reports `unknown_taxability`.
- `initialState()` has zero items. `loadFromServer` appends one blank item row (not dirty) when the
  loaded receipt has no `kind: "item"` lines, so a new receipt opens ready to type.
- `removeItem` also removes every `readOnlyLines` discount whose `discount_target_line_id` equals the
  removed line (a discount for a deleted item has nothing to apply to).
- Deposit lines (kind `deposit`) are assignable, so they appear in `TagList` (read-only name and amount,
  taggable) and are counted in "Tag every item — N left". Discount and fee lines are not taggable.
- `addPersonError`: trimmed empty → `"Enter a name"`; case-insensitive duplicate (`trim().toLowerCase()`)
  → `"Already added"`; more than 40 code points (`[...name].length`) → `"Up to 40 characters"`;
  20 people already → `"Up to 20 people"`. `addPerson` is a no-op when this is non-null.
- `toSaveBody`:
  - a row with blank name **and** blank price is skipped, and its tag entry is dropped;
  - every other row needs a trimmed name of 1–120 code points and `parseDollars(priceInput) !== null`,
    else its `lineId` goes into `invalid`;
  - `taxInput` must be blank or parse, else the string `"tax"` goes into `invalid` (the TaxField is
    outlined when `invalid` contains `"tax"`); blank or 0 → no editable tax line; otherwise
    `{label: taxLabel, amount_cents}`; if `extraTaxLines` is set they are sent unchanged instead;
  - lines = items (as `kind: "item"`, `name` trimmed, `taxable`, `tax_code: taxCode`, passthrough
    fields) followed by `readOnlyLines`;
  - participants `[{key, display_name}]` in people order; assignments = tags with no empty lists.

**Summary text (`web/src/lib/summary-text.ts`)**
`summaryText(receipt: ReceiptResponse): string | null` — null when `allocation` is null. Otherwise
`"<merchant_name or 'Receipt'> — <formatCents(computed_total_cents)>\n<Name> <formatCents(total)>\n…\n(split with ReceiptSplit)"`,
people in list order.

**Save loop (`SplitApp.tsx`)**
- When `dirty`, schedule a save 600 ms after the last change. At most one request in flight. When
  a save starts it reads the **current** state via `toSaveBody` (never a stored earlier body).
- `invalid` → do not send; rows listed are outlined; status "Fix highlighted rows to update totals".
- Results:
  - `saved` → `markSaved` only if no change happened since this save started (otherwise another
    save is scheduled); show returned allocation. Response content is **not** reloaded into the
    editor (the local state is already newer or equal).
  - `not_found` → the edits exist only locally, so move them: `createReceipt(false)`, store the new
    id (the editor stays mounted — it is keyed by a session counter, not the id), and save the
    current state to it. If the create fails with a network error, treat it as `network_error`
    (each retry re-sends, 404s and recreates); if it returns 429, treat it as `rate_limited`. Any
    other create failure, or a replacement that 404s before its first successful save, goes to
    `gave_up` (Retry allows one more recreate per click, so it can never loop).
    "This receipt expired" is shown only when a stored id 404s on reopen. *(Pre-commit review,
    round 2: the 1-hour unsaved TTL made the old "exit on 404" lose edits.)*
  - `rate_limited` → pause saves for `retryAfterS`; status "Saving paused — too many changes".
  - `rejected` → status "Couldn't save — something doesn't look right. Your edits are still here."
    No automatic retry; the next edit tries again.
  - `server_error` → retry after 2, 4, 8, 16, 32 s (5 retries, so 6 requests including the first);
    after the 6th failure, status "Couldn't save — try again"
    with a Retry button. Edits stay local.
  - `network_error` → status "Offline — will retry"; retry after 2, 4, 8 s, then every 30 s, no cap.
- **Retry state machine.** `retry: { kind: "none" } | { kind: "backoff"; reason: "server" | "network";
  attempt: number } | { kind: "gave_up" } | { kind: "paused"; until: number }`.
  - New edit while `backoff` or `gave_up`: cancel the retry timer, set `retry = none`, schedule the
    normal 600 ms save (the counter resets).
  - New edit while `paused`: no save is scheduled; when the pause ends one save of the current state
    runs.
  - Retry button (shown only in `gave_up`): same as a new edit.
  - A `saved` result sets `retry = none`.
- **No unload flush.** A cross-origin `keepalive` PUT needs a CORS preflight (support is uneven) and
  can race the next page's `GET`. Accepted trade-off: an edit made less than ~600 ms before a refresh
  or tab close may be lost. The status line reads "Saving…" during that window.
- Effect cleanup clears timers and aborts the in-flight save.
- **Delete / Start new**: cancel timers and abort the in-flight save first. "Delete receipt" →
  `deleteReceipt` → clear stored id → StartScreen. "Start a new receipt" → `deleteReceipt` (best
  effort; a failure is ignored because the row expires anyway) → clear stored id → StartScreen.
  If "Delete receipt" throws: status "Couldn't delete — try again", stay on the receipt.

**Initial load**: stored id `undefined` (server render and before hydration) → a neutral
"Loading…" placeholder with no buttons. Stored id null → StartScreen. Otherwise `getReceipt(id)`: `null` → clear id →
StartScreen; throws → "Can't reach ReceiptSplit" + Retry (keeps the id); ok → `loadFromServer`.
StartScreen: "Start a new receipt" → `createReceipt(false)`, "Try an example" → `createReceipt(true)`;
on success store the id and load; on `ApiError` 429 → "Too many new receipts from this network — try
again in N min" (N = ceil(retryAfterS/60)); 503 → "ReceiptSplit is busy — try again in a few minutes";
other errors → "Can't reach ReceiptSplit — try again".

**UX (one page, phone first, 375 px wide)**
```
<StartScreen>   [ Start a new receipt ]  [ Try an example ]
<SplitApp>
  header: "ReceiptSplit" · "Example receipt" badge when receipt.is_example
  <ItemsEditor>   row: [name][ $price ][ Taxed? Yes | No ][ × ]  · "+ Add item" (disabled at 300)
                  read-only rows for readOnlyLines (label + amount)
  <TaxField>      "Tax on receipt" [ $ ___ ] "Type the tax printed on your receipt"
                  (read-only with note "Multiple tax lines" when extraTaxLines)
  <PeopleEditor>  chips: Alex × · Sam × · [ name ___ ][ Add ]   error text from addPersonError
  <TagList>       per item or deposit: "Cheetos $4.89" [Alex][Sam][Jordan]  (2+ selected = split evenly)
  <Summary>       per person: name, each line share, tax, total · [ Copy summary ] (disabled while
                  allocation is null — hint "Finish tagging to copy" — or while dirty/invalid — hint
                  "Saving… copy when done"; Summary amounts are dimmed in the same states) ·
                  [ Delete receipt ] [ Start a new receipt ]
  <TotalsBar>     sticky bottom: "Alex $4.26 · Sam $15.03 · Jordan $18.80"
                  dimmed with "Saving…" while dirty; or the problem message
  footer: <ApiStatus />
```
- **TotalsBar problems** (`allocation_problem.code`): `no_participants` → "Add the people splitting
  this receipt"; `unassigned_line` → "Tag every item — N left" (N = item and deposit lines, excluding
  skipped blank rows, without a tag entry);
  `no_assignable_lines` → "Add an item"; other codes → "Can't split yet — check the items".
- **Status precedence** in the bar: a save status ("Offline — will retry", "Saving paused…", "Couldn't
  save…", "Fix highlighted rows…") replaces the dimmed "Saving…" label when both apply.
- **Warnings** (`allocation.warnings`, one line under the bar): `unknown_taxability` or
  `tax_fallback_proportional` → "Mark every item taxed or not — tax may be off";
  `tax_without_taxable_lines` → "Tax entered but no item is marked taxed"; `zero_base_equal_split`
  → no message.
- **Copy summary**: if `navigator.clipboard?.writeText` is a function, call it inside `try` and await
  it; if it is missing, throws synchronously, or rejects, show the text in a selectable
  `<textarea readonly>` instead (plain-http LAN origins have no clipboard API).
- Tag chips are `<button aria-pressed>`; inputs have `<label>`s; tap targets ≥ 44 px.
- Summary line names come from the local items by `line_id`; a share whose line no longer exists
  locally (only possible while dirty) is shown as "(edited item)".

## Money semantics
- Integer cents end to end: text → `parseDollars` (string arithmetic) → cents; API uses `StrictInt`
  cents (`ParsedReceipt`); the allocator is integer-only (v0 §B4–B5). The browser displays the
  allocator's result and never computes shares.
- Remainders: unchanged allocator rules — per-line largest remainder rotated by assignee set; tax
  spread over taxable bases by largest remainder.
- Proofs: existing P1 (`tests/domain/test_allocation.py`); the pinned example table above; the new
  service property tests below.

## Failure modes
| Situation | What the user sees | API |
|---|---|---|
| API unreachable at load | "Can't reach ReceiptSplit" + Retry | — |
| Network drop mid-edit | "Offline — will retry"; edits kept locally | — |
| Server error mid-edit | Retries ×5, then "Couldn't save — try again" + Retry | 500 (with CORS headers) |
| Receipt expired, found on reopen | "This receipt expired" + Start new | 404 |
| Receipt expired while editing | Nothing: edits move to a new receipt (Offline / paused / Retry if that create fails) | 404, then 201 |
| Service at the live-receipt cap | "ReceiptSplit is busy — try again in a few minutes" | 503 on create |
| Receipt state over 256 KiB | "Couldn't save — something doesn't look right…" | 422 |
| Too many creates / saves | "Too many new receipts…" / "Saving paused…" | 429 + Retry-After |
| Invalid row | Row outlined; totals bar "Fix highlighted rows…" | (not sent) |
| Server rejects state | "Couldn't save — something doesn't look right…" | 413 / 422 |
| Delete fails | "Couldn't delete — try again" | 5xx / network |
| Refresh within ~600 ms of the last keystroke | That last edit may be lost (status showed "Saving…") | — |
| Two tabs, same receipt | Last save wins | 200 |
| localStorage unavailable | Works (in-memory id); refresh returns to StartScreen | — |
| Clipboard blocked | Summary shown in a selectable box | — |

## API contract regeneration and deploy order
After routes land: `cd api && uv run python -m app.scripts.export_openapi` then
`cd web && npm run gen:api`; commit both (CI checks drift). One push deploys both; Railway runs
`0002` pre-deploy. Until Railway finishes, the new web's `POST /v1/receipts` 404s against the old API
and StartScreen shows "Can't reach ReceiptSplit — try again", which clears once the API is live.

## Changes to the v0 design doc (revision 7, in this slice)
- §A6: Slice 2 = parsing + checks + Retry Reading + store profiles (`0003`, `store_profile_id`) +
  scheduled image cleanup; Slice 3 = this doc (migration `0002`, receipt API, rate limiting, purge
  cron, manual-entry UI). Slice 3 is built before Slice 2.
- §A8: participants are `[{key, display_name}]` in list order (no `sort_order`); receipts carry
  `content`, `participants`, `assignments`, `is_example`, `expires_at`; purge = hourly cron + on create;
  saves are last-writer-wins whole documents; the correction-event model is revisited in Slice 2.
- §A2: the web-side C1/C2 re-implementation moves to Slice 2 with the checks.
- §A6 row 2 (Slice 2) also takes, from the old row 3: the store picker and rule review/edit screen
  (§A7), the correction-event edit history, the live balance bar and the LOW CONFIDENCE marker — all
  depend on parsing and checks.
- §A4 invariants I2/I3: marked superseded — there is no participants table; `validate_state` enforces
  that tags reference existing lines and people.
- §A4.1 / §A8: the constraint list and the "Migration `0002` (Slice 2)" block are rewritten to describe
  the `0002` in this doc; `store_profile_id` moves to `0003`.
- §A8 "Consequences": remove the sentence moving per-IP rate limiting and the upload cap into
  Slice 2 (they are in Slice 3); state that `expires_at` slides to 24h after the **last save**, and
  that live receipts are capped at 10,000 and 256 KiB of state each.
- §A7: "new tables, Slice 2 migration `0002`" becomes `0003` (`store_profiles`, `store_tax_codes`,
  `receipts.store_profile_id`).
- §A6 row 2 text: remove "migration `0002` (A8), ephemeral receipt storage + purge" and "per-IP rate
  limiting" (now Slice 3); keep parsing, checks, Retry Reading, store profiles.
- Out-of-scope follow-ups: "allocation endpoint + 422 mapping" marked done by this slice.
- Revision log: `0002` is a deliberate one-step contract (reason above).
- "Slice 3 blocker" (Vercel preview CORS): resolved as not blocking — there is no auth and no
  endpoint lists receipts; a site matching the preview regex can only create receipts (rate-limited)
  or touch a receipt whose random id it already knows.

## Verification criteria
**API (`REQUIRE_DB_TESTS=1 uv run pytest`)**
- `tests/db/test_migrations.py`: `EXPECTED_CONSTRAINTS` = post-`0002` set (dropped tables' constraints
  gone); `DEFERRED_FKS = set()`; `ix_receipts_expires_at` present; round-trip; `compare_metadata == []`.
- `tests/db/test_migrations.py::test_upgrade_from_0001_with_data`: `downgrade base`, `upgrade 0001`,
  insert a user → household → participant → receipt → assignment graph, `upgrade head`; assert
  `receipts` is empty and the five tables are gone; `downgrade 0001`; assert the five tables exist and
  are empty; **finally `upgrade head`** so later tests see head.
- `tests/conftest.py::make_graph` and `Graph` rewritten for the new schema (receipt → parse_attempt →
  correction). `tests/db/test_schema_constraints.py` rewritten: receipt defaults (`status == 'draft'`,
  `is_example is False`, `content` validates as `ParsedReceipt`, `expires_at` in (now+23h59m, now+24h]);
  new status value accepted, unknown rejected; deleting a receipt cascades its attempts and corrections.
  Tests that need expiry **set `expires_at` explicitly** (e.g. `now() - interval '1 minute'`), because
  `now()` is fixed inside the test transaction.
- `tests/receipts/test_service.py`: each `validate_state` rule (one rejected case each); `purge_expired`
  deletes only rows with past `expires_at` and returns the count; example state allocates to the
  pinned table; property test A — for `ReceiptState`s generated from `strategies.allocation_inputs`
  with a random subset of assignment keys removed and a random subset of people dropped, then pruned
  so `validate_state` passes — each assignee list de-duplicated (first occurrence kept), keys of
  dropped people removed, emptied lists deleted, and display names generated as `P0`, `P1`, … by
  position — `compute_allocation` never raises and returns exactly one non-null; when it
  returns a result, totals sum to `computed_total_cents`; property test B — `to_response` of a state
  stored as `model_dump(mode="json")` and reloaded gives the same allocation as `compute_allocation`
  on the original.
- `tests/routes/test_receipts.py` (uses `db_session` via `app.dependency_overrides[get_session]`, whose
  commits become savepoints): 201 create (empty and example, example allocation = pinned table),
  200 get, 200 put (content round-trips, `expires_at` and `updated_at` move later — both use
  `clock_timestamp()`), 204 delete
  then 404; expired (backdated) → 404 on GET/PUT/DELETE; 422 for each validation rule and a malformed
  id, each with FastAPI's `{"detail": [{"loc", "msg", "type"}]}` shape; 413 for a body of 1 MiB + 1 byte
  **with `access-control-allow-origin`**; 429 on create using
  `create_app(rate_limits=RateLimits(create=Bucket(1, 3600)), clock=fake)` and on PUT using
  `per_receipt=Bucket(1, 3600)` (a second receipt is unaffected), **with CORS header and
  `Retry-After`**; 500 from a route patched to raise, returning `{"detail": "internal error"}` **with
  CORS header**; `allocation` / `allocation_problem` mutually exclusive.
- `tests/test_ratelimit.py`: refill with fake clock; `Retry-After` value; eviction after idle;
  `max_keys` LRU cap; XFF resolution for hops 0/1/2, short header, invalid entry, spoofed left entry;
  IPv6 addresses in the same /64 share a bucket; concurrent `check` from 8 threads consumes exactly
  `capacity` tokens.
- `tests/routes/test_cors.py`: `PUT` preflight allowed; `Retry-After` in
  `access-control-expose-headers`.
- `tests/test_config.py`: autouse cleanup also clears `RATE_LIMIT_TRUSTED_PROXY_HOPS`; negative value
  rejected.
- `tests/scripts/test_purge_script.py` (`@pytest.mark.db`, uses `migrated_engine` and
  `test_database_url`, **not** `db_session`): insert and **commit** one backdated and one live receipt
  on a fresh connection; call `main(test_database_url)`; assert it returns 1, the backdated row is gone
  and the live row remains; delete the live row in `finally`.
- `tests/test_ratelimit.py` also covers: `create` keyed by client key, `per_receipt` keyed by path id,
  `per_client` applied to every request (random ids from one client hit 429); non-IP client host
  (`"testclient"`) and `None` client keyed as specified; `rate_limit_log_client_ip` logs only when
  enabled (asserted with `caplog`).
- `tests/test_middleware.py`: a chunked (no `Content-Length`) body over 1 MiB → 413 with CORS header;
  a Content-Length body over 1 MiB → 413; a maximal state (300 lines × 20 people, 36-char ids, every
  line tagged to everyone) is under 1 MiB (passes transport) and gets 422 "receipt too large"; a
  60-line, 6-person receipt saves with 200.
- `tests/receipts/test_service.py` also: `create_receipt` raises `ServiceBusy` when live rows ≥ cap
  (cap patched to 2 in the test); expired rows don't count; route returns 503 with CORS header.
- `tests/test_logging_config.py`: `configure_logging()` adds a handler only when none exists.

**Web (`npm test`)**
- `money.test.ts`: every valid and invalid case listed; `formatCents`, `centsToInput`.
- `ids.test.ts`: `newId()` matches the v4 pattern with `crypto.randomUUID` deleted.
- `stored-receipt-id.test.ts`: with a `localStorage` whose methods throw, `setStoredReceiptId("x")`
  makes the hook return `"x"`; server snapshot is `undefined`; normal storage round-trips.
- `SplitApp.test.tsx` also: renders "Loading…" (no start buttons) while the id is `undefined`.
- `receipt-state.test.ts`: `addItem` defaults (`taxable: null`); a loaded empty receipt gets one blank
  row and is not dirty; removing an item drops its targeted discounts; deposit lines taggable and
  counted; invalid tax reported as `"tax"`; each action; tag entries never empty; blank row's tags dropped by
  `toSaveBody`; invalid rows reported; tax 0/blank/value/multi-line; `base` totals cleared on edit;
  passthrough fields preserved; `loadFromServer` of the example round-trips through `toSaveBody` to
  the same content; `addPersonError` messages.
- `summary-text.test.ts`: example text; `'Receipt'` fallback; null when no allocation.
- `Summary.test.tsx`: Copy writes via clipboard when available; falls back to the textarea when
  `navigator.clipboard` is undefined, when `writeText` throws synchronously, and when it rejects; Copy
  disabled while dirty and while allocation is null.
- `SplitApp.test.tsx` (mocked `fetch`, fake timers): example loads with three totals; edits debounce to
  one PUT that uses the latest state; edit during an in-flight save triggers a second save;
  a PUT that never settles times out after 15 s and follows the `network_error` path (fake timers);
  lost-response scenario (first PUT rejects with network error, user edits, retry) sends the newest
  state; 429 pauses, edits during the pause produce exactly one save when it ends; 500 retries, an edit
  during backoff resets the counter, after the 6th failed request (first + 5 retries) Retry appears and restarts; Copy disabled
  while dirty; invalid row not sent; 404 on save → edits saved to a replacement receipt, editor intact;
  404 on reopen → "This receipt expired"
  screen; delete during an in-flight save aborts it and shows StartScreen; unmount aborts.
- `TotalsBar.test.tsx`: each problem code, each warning, dimmed "Saving…" when dirty.

**Manual (Chrome MCP, 375 × 812, `npm run build && npm start` + local API)**
1. Try an example → bar shows Alex $4.26 · Sam $15.03 · Jordan $18.80; summary total $38.09.
2. Start new → "Eggs" $10.00 taxed No; people A, B, C; tag all three → $3.34 / $3.33 / $3.33.
3. Type the owner's Target receipt by hand with the same tags as the example → same three totals.
4. Edit a price, refresh after the "Saving…" state clears → edit persisted. Delete receipt → StartScreen;
   `curl` of the old id → 404.
5. Stop the API mid-edit → "Offline — will retry"; restart → saves resume.
6. Console shows no app errors; every control reachable by keyboard.

## Out-of-scope follow-ups
Slice 2: parsing into `content`, checks C1–C3 (server and web), Retry Reading, reconciling whole-
document saves with the `corrections` event model, store profiles + `store_profile_id` (`0003`), image
cleanup. Later: shared rate-limiter state if the API scales past one replica; uneven shares; editing
discount/fee/deposit lines; multi-tab merge.

---

## Revision log
### Revision 1 (design-check round 1)
Readiness (R) and critic (C) items, by number:
| Item | Resolution |
|---|---|
| C1 lost edits after a network error | Dropped optimistic concurrency: last writer wins, client always sends its current full state, one request in flight; test for the lost-response case |
| C2, R7, R8 empty/stale tag lists | Tag entries are deleted, never empty; `toSaveBody` drops tags of skipped rows; tests |
| C3, R4, R5 413/429 invisible to the browser | Middleware order specified (CORS outermost); `expose_headers=["Retry-After"]`; tests assert CORS headers on 413/429/500 |
| C4 5xx looks offline | `JsonErrorMiddleware` inside CORS; `server_error` result with capped retries |
| C5, R19 limiter races and memory | Lock; timed sweep + LRU cap; IPv6 /64 keys; every request counts; injectable limits/clock |
| C6, R16 self-referential example test | Pinned hand-checked table (426 / 1503 / 1880); bar mock corrected |
| C7, R15 unsaved edits and stale totals | `pagehide` keepalive flush; dimmed "Saving…" bar; invalid-row status |
| C8, R12, R13 delete/new during save; error handling | Cancel then delete; "Start new" deletes the old row; `getReceipt`/`deleteReceipt` error behaviour and UI specified |
| C9, R21 conflicts with v0 doc | v0 revision 7 in this slice (listed changes) |
| C10 retention promise | Hourly Railway cron + purge on create; wording now "deleted within about an hour after expiring" |
| C11, R1, R3 example badge and summary | `is_example` column and response field; `summaryText` spec with 'Receipt' fallback; Copy disabled without allocation |
| C12, R23 money parsing edge cases | Full valid/invalid list; string arithmetic only |
| C13, R9, R10 client/server validation drift | Code-point lengths, `.lower()`/`toLowerCase()`, trimming, 120/40/300/20 limits, messages |
| C14, R17 service 422 shape | `ReceiptValidationError` → 422 `ValidationErrorResponse{detail: list[str]}`; client treats all 422 alike |
| C15 OpenAPI gaps | Error bodies declared; `SaveReceiptRequest` exported; `separate_input_output_schemas=False` |
| C16 `updated_at` not refreshed | Save uses the ORM (onupdate fires); no raw SQL |
| C17 test timing and migration order | Explicit backdating; `test_upgrade_from_0001_with_data` ends at head |
| C18 testing 429 | `create_app(rate_limits, clock)`; config cleanup + `ge=0` |
| C19 weak property test | Two new properties (incomplete states; JSON round-trip) |
| C20 missing web tests | Added lost-response, 429, 500, invalid row, delete-during-save, second-save cases |
| C21 localStorage lint/hydration | `useSyncExternalStore` hook with null server snapshot; try/catch |
| C22 one-step contract | Recorded as a deliberate exception; pre-check count logged, rows accepted as lost |
| C23 minor | Citation corrected; preview-CORS blocker resolved in writing; `newId()` works on insecure origins; NAT note |
| R2, R6 fields the editor doesn't edit | `base`, `passthrough`, `readOnlyLines`, `extraTaxLines`; printed totals cleared on edit |
| R11 `ApiError` | Defined with `status` and `retryAfterS` |
| R14 load triggering a save | `loadFromServer` sets `dirty = false`; no save |
| R18 route tests and commits | Service commits; route tests override `get_session` with `db_session` (savepoints) |
| R20 logging | No new request logging; uvicorn access log only |
| R22 preview CORS blocker | Resolved as not blocking, reasoning in the v0 changes section |

### Revision 2 (design-check round 2)
| Item | Resolution |
|---|---|
| C1, R1 `updated_at` frozen in test transaction | `save_receipt` sets `updated_at = clock_timestamp()`; ORM `onupdate` uses `clock_timestamp()` |
| C2, R4 cron inherits `railway.toml` | Separate `api/railway.cron.toml`, custom config path, no pre-deploy/healthcheck; deploy checklist step 3 |
| C3 purge script untestable | `main(database_url=None) -> int`; test commits its own rows outside the rollback fixture |
| C4 property-test pruning | De-duplicate, drop emptied lists, names `P0…` |
| C5 editor defaults | `addItem` → `taxable: null`; empty receipt loads with one blank row, not dirty |
| C6 pass-through lines | Deposits taggable and counted; `removeItem` drops its targeted discounts |
| C7 write limit under NAT | Edits keyed per receipt id (1200/h); only creates keyed per IP |
| C8 keepalive racing an in-flight save | Flush only when nothing is in flight; stated as best effort |
| C9 422 OpenAPI shape | Service errors raised as `RequestValidationError`; FastAPI default 422 schema kept |
| C10 v0 revision 7 incomplete | Added: row 3 items moved to Slice 2, I2/I3 superseded, A4.1/A8 rewrite, follow-up marked done |
| C11 unverified XFF shape | `rate_limit_log_client_ip` switch + deploy checklist step 4 |
| R2 invalid tax field | `"tax"` sentinel in `invalid`; TaxField outlined |
| R3 edits during backoff/pause | Retry state machine specified; tests added |

### Revision 3 (design-check round 3)
| Item | Resolution |
|---|---|
| C1 INFO logs never printed | `app/logging_config.configure_logging()` called in `create_app` and the purge script |
| C2 non-IP / missing client | Raw string key when not an IP; `"unknown"` when `scope["client"]` is None |
| C3 no per-IP ceiling on edits | `per_client` bucket (3000/h) on every `/v1/receipts*` request |
| C4 chunked 413 becomes 400 | Raise `HTTPException(413)` from wrapped `receive`; streaming test |
| C5 valid state over the body cap | Cap raised to 1 MiB; test that the maximal state fits |
| C6 Copy with stale totals | Copy disabled and amounts dimmed while dirty/invalid |
| C7 keepalive flush unverified | Flush removed; last ~600 ms of typing may be lost on refresh (stated) |
| C8 v0 §A7/§A6 references | Added §A7 `0002`→`0003` and explicit §A6 row 2 removals |
| C9 clipboard missing on http | Fallback when missing, throwing, or rejecting; tests |
| Readiness notes | Abort rejects and is ignored; status precedence; `formatCents` thousands separators |

### Revision 4 (design-check round 4, applied under owner override at the 3-revision cap)
| Item | Resolution |
|---|---|
| R1, C1 413 test used 300 KiB | Test sends 1 MiB + 1 byte |
| R2 5 vs 6 server-error attempts | First + 5 retries = 6 requests; test asserts 6 |
| C2 hung save blocks all saving | 15 s `AbortSignal.timeout`, TimeoutError → `network_error`, test |
| C3 no-storage stuck on StartScreen | In-memory id is the source of truth; storage best effort; test |
| C4 unbounded storage | 10,000 live-receipt cap (503) and 256 KiB state cap (422); tests |
| C5 per_client vs NAT | Raised to 20,000/h; listed under known limits |
| C6 clickable StartScreen before hydration | Server snapshot `undefined` renders "Loading…" |
| C7 wrong photo path | `spikes/receipts/target2.jpg` |
| C8 stale v0 §A8 sentences | Added to revision-7 change list |
