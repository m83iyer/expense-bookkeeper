# Editing Your Mappings By Hand

The tracker respects your taxonomy. You own the Google Sheet. Two tabs are designed to be hand-edited: **`MERCHANT_MASTER`** and **`CATEGORIES`**. `RECURRING` is also user-managed. The tracker owns `EXPENSES`; `REVIEW_QUEUE` is an optional workspace for adapter-specific review flows.

This doc covers when to edit by hand vs when to let the skill do it.

---

## The two paths to fix categorization

You almost never need to open the Sheet. The skill exposes two faster paths:

| Path | When to use | How |
|---|---|---|
| **A. Reply to the confirmation message** | A single transaction came through with the wrong category | On WhatsApp / Telegram / email, reply: `change Spinneys to Groceries / Online`. The skill's `correction_handler.py` parses this, updates the row in EXPENSES, and adds/updates the entry in MERCHANT_MASTER so future Spinneys swipes route the same way. Idempotent — replying twice with the same correction is safe. |
| **B. Edit the Sheet directly** | You want to bulk-add merchants, restructure your taxonomy, or set up regional packs | Open the Sheet, edit MERCHANT_MASTER or CATEGORIES, save. Next transaction picks up your changes immediately (the skill reads the Sheet on every resolve, no cache to bust). |

If you open the Sheet often to fix categorization, run the checks in `references/repair.md` and fix the recurring cause.

---

## MERCHANT_MASTER — the merchant→category map

### What it does

Every captured transaction goes through `merchant_resolver.py` (see `categorization.md` for the full 3-tier resolver). MERCHANT_MASTER is **tier 1** — the user's source of truth. A match here is silent and final; the skill never overrides what's in this tab.

### Schema

| Column | Required | Example | Notes |
|---|---|---|---|
| `Merchant_Keyword` | yes | `Spinneys` | Matched as a normalized word-boundary phrase. More-specific multi-word keys win. |
| `Merchant_Clean` | optional | `Spinneys` | Display name written into `EXPENSES.Merchant_Clean`. If blank, the tracker uses the keyword. |
| `Category` | yes | `Groceries` | Must be part of an active pair in `CATEGORIES`. |
| `Subcategory` | yes | `Supermarket` | Must be paired with the chosen category in `CATEGORIES`. |
| `Aliases` | optional | `spinneys market|spinneys dubai` | Pipe-separated alternative merchant phrases. |
| `Last_Updated` | optional | `2026-07-20` | Audit-friendly date updated by the correction handler. |

### How to add a new mapping

1. Open the Sheet, MERCHANT_MASTER tab.
2. Append a row with a concise merchant phrase and an active category/subcategory pair from `CATEGORIES`.
3. Save. Next transaction picks it up.

### Common edits

- **Renaming a merchant** — change `merchant_clean` only. Existing EXPENSES rows are not back-edited (the skill respects history). New rows pick up the new display name.
- **Re-categorising a merchant** — change `category` (and `subcategory`). Existing EXPENSES rows stay as-logged. To back-edit history, run `scripts/recategorise_history.py` (see `repair.md` for safe usage).
- **Splitting one merchant into many** — add multiple rows with longer substrings. Longest-match wins. Example: `apple` → `Tech` is too broad; replace with `apple.com/bill` → `Subscriptions / Apple` and `apple store` → `Tech / Hardware`.
- **Removing a mapping** — delete the row. Future swipes for that merchant fall through to tier 2, then `Status=Review` if unresolved.

### Don't

- Don't put personal notes, account numbers, or full transaction strings in MERCHANT_MASTER. Merchant phrases only.
- Don't use a category that doesn't exist in CATEGORIES — the skill will refuse to load and surface the error in the next session.
- Don't add a substring that's a subset of an existing one without thinking through which should win. `gems` is a real footgun (matches `gems education`, which you may not want).

---

## CATEGORIES — your taxonomy

### What it does

The list of valid categories the skill is allowed to use. The skill never invents a category that isn't in this tab. Setup wizard seeds a starter list during install; you customise it from there.

### Schema

| Column | Required | Example | Notes |
|---|---|---|---|
| `Category` | yes | `Groceries` | Top-level bucket. Keep it short and consistent. |
| `Subcategory` | yes | `Supermarket` | One category/subcategory pair per row. |
| `Active` | yes | `TRUE` | Only active pairs can be written. |
| `Notes` | optional | `Everyday groceries` | User-owned context for the pair. |

### How to add a new category

1. Open the Sheet, CATEGORIES tab.
2. Append one row for each allowed category/subcategory pair and set `Active=TRUE`.
3. Save.
4. (Optional) Update MERCHANT_MASTER rows to point to the new category.

### How to restructure your taxonomy

This is where most mistakes happen. Three patterns:

**Splitting a category.** Example: `Food` → `Groceries` + `Dining Out`.
1. Add the two new categories to CATEGORIES.
2. In MERCHANT_MASTER, re-point each merchant to the right new category.
3. Preview with `python3 scripts/recategorise_history.py --config ~/.expense-bookkeeper/config.yaml --map "Food=>auto"`. The tracker re-resolves every historical `EXPENSES` row whose category was `Food`; unresolved rows stay unchanged.
4. Re-run with `--confirm` after reviewing the preview. Add `--large-batch` when more than 50 rows would change.
5. Filter `EXPENSES` by `Status=Review`, resolve any remaining merchants, then remove the old `Food` pairs after strict validation passes.

**Merging two categories.** Example: `Subscriptions` + `Apps` → `Software`.
1. Add `Software` to CATEGORIES.
2. Preview `python3 scripts/recategorise_history.py --config ~/.expense-bookkeeper/config.yaml --map "Subscriptions=>Software,Apps=>Software"`. Literal renames preserve each row's subcategory, so every resulting `Software / <existing subcategory>` pair must already be active.
3. Re-run with `--confirm` after reviewing the preview.
4. Update MERCHANT_MASTER rows from the old categories to `Software`.
5. Delete the `Subscriptions` and `Apps` rows from CATEGORIES after strict validation passes.

**Renaming a category.** Example: `Bills` → `Utilities`.
1. Add `Utilities` to CATEGORIES (don't delete `Bills` yet).
2. Preview `python3 scripts/recategorise_history.py --config ~/.expense-bookkeeper/config.yaml --map "Bills=>Utilities"`, then re-run with `--confirm`.
3. Update MERCHANT_MASTER rows from `Bills` to `Utilities`.
4. Delete the `Bills` pairs after strict validation passes.

### Don't

- Don't delete a category before re-pointing every `MERCHANT_MASTER` row that uses it. Strict validation blocks dangling merchant mappings; migrate historical expenses before removing the old pair.
- Don't have two categories that mean the same thing (e.g. `Food` and `Groceries`). The resolver can't tell which is right and falls through to tier 3.
- Don't use special characters in category names. Stick to letters, numbers, spaces. The skill writes them into Sheet formulas in places.

---

## Regional packs (optional)

A regional pack is a pre-built set of MERCHANT_MASTER rows for merchants common in a specific country/region. v0.2.0 ships with a UAE pack (60+ merchants, no personal data). To install:

1. During setup wizard step 6b, say yes to the regional pack prompt.
2. Or, post-setup: open the Sheet, MERCHANT_MASTER tab, copy-paste rows from `templates/regional_packs/uae_merchants.csv` (or your region's pack if available).

You can edit, remove, or re-categorise any row from a regional pack — the pack is a starting point, not a contract.

---

## Validation

After any hand-edit, validate the result. Either:

- Mode 5 (Troubleshoot) runs `scripts/repair_diagnostics.py` for read-only diagnostics.
- Run the release gate directly with `python3 scripts/validate_install.py --config ~/.expense-bookkeeper/config.yaml --strict`.

If validation fails, the report tells you exactly which row + what's wrong. Fix in the Sheet, re-validate.

---

## Worked examples

See the appendix in `categorization.md` for end-to-end examples of common corrections (single-transaction fix, bulk merchant cleanup, taxonomy restructure).
