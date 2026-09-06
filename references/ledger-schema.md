# Ledger schema

The user's Google Sheet has these tabs. `create_ledger.py` provisions all of them; `validate_install.py` checks for headers; `repair_diagnostics.py` flags missing tabs.

## EXPENSES (transaction log)

| Column | Type | Notes |
|---|---|---|
| Txn_ID | string | unique; `TXN<HASH>` when a parsed hash exists, otherwise a microsecond timestamp |
| Date | YYYY-MM-DD | normalised on write |
| Day | string | derived: Mon/Tue/... |
| Month-Year | string | derived: Apr-2026 |
| Amount | float | always positive; refunds use Txn_Type=Refund |
| Currency | string | ISO 4217 |
| Txn_Type | enum | Expense / Refund / Transfer / Income |
| Category | string | active taxonomy pair; unresolved rows use `Misc` with `Status=Review` |
| Subcategory | string | active taxonomy pair; unresolved rows use `Other` with `Status=Review` |
| Merchant_Raw | string | as captured |
| Merchant_Clean | string | normalised display |
| Card_Used | string | user's card label |
| Source | enum | NotificationCapture / GmailSweep / Manual / StatementImport / etc. |
| Person | string | default "Household"; user-defined values OK |
| Notes | string | free text; corrections leave a trail |
| Status | enum | Confirmed / Review / Excluded |
| Review_Reason | string | tier 3 reason or correction note |
| Hash | string | sha1(date|amount|merchant)[:16] for dedup |

## MERCHANT_MASTER

| Column | Type | Notes |
|---|---|---|
| Merchant_Keyword | string | word-boundary phrase cue (e.g. "Carrefour") |
| Merchant_Clean | string | display name |
| Category | string | required for tier-1 hits |
| Subcategory | string | required for tier-1 hits |
| Aliases | string | pipe-separated alternatives |
| Last_Updated | YYYY-MM-DD | autoset on write |

## CATEGORIES

| Column | Type | Notes |
|---|---|---|
| Category | string | top-level |
| Subcategory | string | within category |
| Active | bool | TRUE/FALSE |
| Notes | string | optional |

`Misc / Other` must remain active because it is the fail-closed pair for transactions awaiting review.

## RECURRING (fixed monthly entries)

User-managed list of recurring expenses (rent, househelp, carwash, gym, school bus, utilities). `recurring_writer.py` runs daily at 03:00 user-local; rows where Active=TRUE and today.day == Day_of_Month and Last_Posted month != current month get appended to EXPENSES with Source="Recurring".

| Column | Type | Notes |
|---|---|---|
| Description | string | shown as Merchant_Raw + Merchant_Clean in EXPENSES |
| Amount | float | always positive |
| Currency | string | ISO 4217 |
| Category | string | required |
| Subcategory | string | required |
| Cadence | enum | "monthly" (v1; weekly/yearly are v1.1) |
| Day_of_Month | int 1-28 | 28 max avoids edge cases on short months |
| Active | bool | TRUE/FALSE |
| Card_Used | string | "Bank Transfer", "Cash", or your card label |
| Person | string | default "Household" |
| Last_Posted | YYYY-MM-DD | autoset by writer; manual edit OK to force re-post |
| Notes | string | free text |

Idempotency: a second run on the same day finds Last_Posted already in current month → no-op.

## REVIEW_QUEUE

This tab is available for adapter-specific review workflows. In v0.4.1, the shared capture path marks the canonical row in `EXPENSES` as `Status=Review`; it does not duplicate that row into `REVIEW_QUEUE`.

| Column | Type | Notes |
|---|---|---|
| Review_ID | string | unique |
| Date | YYYY-MM-DD | |
| Amount | float | |
| Currency | string | |
| Merchant_Raw | string | |
| Suggested_Category | string | tier-1/2 best guess |
| Suggested_Subcategory | string | |
| Reason | string | "vague descriptor" / "unknown merchant" / etc. |
| Status | enum | Open / Resolved / Discarded |

## RECONCILIATION

Side-lane tab; one row per statement gap surfaced.

| Column | Type | Notes |
|---|---|---|
| Run_ID | string | per reconcile invocation |
| Date | YYYY-MM-DD | from statement |
| Amount | float | |
| Currency | string | |
| Merchant_Raw | string | |
| Status | enum | Gap / Matched / User-Resolved / User-Rejected |
| Resolution | string | optional notes |

## EXPENSES_TEST

Same schema as EXPENSES. Strict validation uses this tab for an append, read-back, and delete sentinel. Normal capture with `armed=false` or `--dry-run` prints a preview and does not write to either expense tab.
