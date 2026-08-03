# TEMPORARY: the AI token & cost counter — how to remove it

This feature exists to answer one question before a credit system is priced:
**what does a user actually cost, and which feature is spending the money.**

It is instrumentation, not product. It is meant to be deleted, and this file is
the checklist for doing that in one pass. Everything below is either a whole file
to delete or a clearly-marked block to remove — every marked block says
`TEMPORARY` in the code so `grep -rn "TEMPORARY (token counter)"` finds them.

## Why it must not outlive the credit system

Once billing exists, per-call accounting belongs to the billing system, which
needs guarantees this ledger deliberately does not have: idempotency keys so a
retried request cannot double-charge, immutability, and a reconciliation trail
against the provider's invoice. Keeping this table alive alongside a real one
means two disagreeing sources of truth for money, and the wrong one will get
quoted to a customer.

It is also an estimate, not an invoice. Costs come from provider-reported token
counts multiplied by the price sheet in `anthropic_provider._PRICE_PER_MTOK`.
That is a close upper bound — the sheet is set to list price while the
promotional rate applies — but it is not what the card is charged.

## Switch it off without deploying

`AI_USAGE_LEDGER_ENABLED=false` stops all writes and makes the admin view 404.
Useful for confirming nothing depends on it before deleting.

## Remove it

### 1. Drop the table

```bash
cd backend && uv run alembic downgrade 010
```

The downgrade is tested and drops the table and its three indexes. Then delete
the migration file — but only if no deployed environment is still above 010:

```
database/migrations/versions/011_ai_usage_ledger.py
```

If any environment has already run 011, keep the file and let the downgrade run
there too. A missing revision in the chain is worse than a dead file.

### 2. Delete these files outright

```
backend/app/models/ai_usage.py
backend/app/services/ai/usage.py
backend/app/api/v1/ai_usage.py
backend/tests/test_ai_usage.py
frontend/src/app/(dashboard)/ai-usage/page.tsx
TEMPORARY-token-counter.md          <- this file
```

### 3. Revert these edits

| File | What to remove |
| --- | --- |
| `backend/app/services/ai/generate.py` | the `from .usage import record_call` import and all **four** `await record_call(...)` blocks — one on success, one after `AIValidationError`, one after the `is_valid` rejection |
| `backend/app/core/config.py` | the `AI_USAGE_LEDGER_ENABLED` field and its comment block |
| `backend/app/core/security.py` | the `TEMPORARY (token counter)` block near the end of `get_current_user`. **Also remove `import contextlib`** — that import exists only for this block and nothing else in the file uses it |
| `backend/app/models/__init__.py` | the `AIUsage` import and its `__all__` entry |
| `backend/app/api/v1/router.py` | `ai_usage` from the import list and its `include_router` call |
| `frontend/src/components/layout/Sidebar.tsx` | the `/ai-usage` entry from `ADMIN_NAV_ITEMS` and the `Coins` icon import. **Keep** `useIsAdmin` and the rest of `ADMIN_NAV_ITEMS` — the admin Users page is permanent and needs both |
| `backend/app/api/v1/admin.py` | nothing to delete, but `_cost_by_user`, the `ai_cost_usd`/`ai_calls` fields and `cost_data_available` become dead once the ledger is gone. They already degrade to zero rather than failing, so the page keeps working — repoint them at whatever billing records, or strip the column |
| `frontend/src/app/(dashboard)/admin/page.tsx` | the AI-cost column is already conditional on `cost_data_available`, so it disappears on its own. Remove the column and `usd()` only if you are not replacing it with credit data |

### 4. Verify

```bash
cd backend && uv run ruff check app tests && uv run mypy app && uv run pytest -q
cd frontend && npx tsc --noEmit && npm run lint && npm run build
grep -rn "TEMPORARY (token counter)\|ai_usage\|AIUsage\|record_call" backend/app frontend/src
```

The last grep must come back empty.

## How it works, while it is here

**One seam.** Every AI-backed feature in the product already routes through
`generate_structured`, which already receives a `context` label naming the
feature and a `ProviderResponse` carrying token counts and an estimated cost. So
the ledger hooks in at exactly one place and instruments all twelve features
without touching a single call site. Adding a thirteenth feature instruments it
automatically, as long as it passes `context=`.

**It records waste.** A provider call that returned malformed JSON, or whose
result failed the call site's `is_valid` predicate, was still billed in full.
Those rows are stored with `outcome='discarded'`. A feature whose discarded
spend is a third of its total has a prompt problem, not a volume problem, and
success-only accounting cannot show that.

**It cannot break a request.** Every write is wrapped and failures are logged and
swallowed. Accounting is strictly less important than the feature being
accounted for.

**It writes on its own connection.** The money was spent the moment the provider
answered, so the row must survive the surrounding request rolling back. Sharing
the caller's transaction would silently discard exactly the calls most worth
recording.

**Money is NUMERIC, not float.** One call costs a fraction of a cent and the
interesting figure is a `SUM` over tens of thousands of rows, which is precisely
where binary floating point drifts.

**Attribution is a ContextVar** set in the auth dependency, so no user id is
threaded through five layers that have no business knowing about users. Calls
made outside a request — background jobs — are recorded with a NULL user and
surface as `unattributed_cost_usd`.

## Reading the numbers

`/ai-usage` (admin only, 403 otherwise).

- **Cost per call** tells you what to optimise: lower the tier, shrink the
  prompt, cache more of it.
- **Share** tells you what to optimise *first*. A feature can be cheap per call
  and still dominate the bill by being called constantly.
- **Wasted** is free money. Non-zero means a prompt or schema needs fixing.
- **p95 cost per user** is what a flat monthly price has to survive. Pricing to
  the mean underprices the tail, and interview usage is long-tailed — a handful
  of accounts run many sessions.
