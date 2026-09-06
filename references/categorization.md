# Categorization

The skill resolves `(category, subcategory, merchant_clean)` for every captured transaction using a strict three-tier resolver. Implemented in `scripts/merchant_resolver.py`.

## Tier 1 — Known merchant

Word-boundary match against the user's `MERCHANT_MASTER` tab. Audit-locked 2026-05-01.

- Lookup is normalised: lowercase, alphanumeric only, whitespace collapsed.
- Matching is **word-boundary with longest-keyword wins** (avoids `GEMS` shadowing `GEMS Education`). A master key `rent` matches `RENT MAY 2026` but NOT `rental car` or `current account`.
- A tier-1 hit logs silently with `Status=Confirmed`, `Tier=1`.

## Tier 2 — Keyword resolved

Word-boundary match against conservative seeds in `merchant_resolver.py`. The user's Sheet/CSV master and confirmed adaptive rules take precedence.

Tier-2 hits log with `Status=Confirmed`, `Tier=2`, but the audit trail (Notes) marks them as soft.

## Tier 3 — Review

If neither tier 1 nor tier 2 resolves, the resolver ranks up to three choices from confirmed historical merchant/amount/card/source patterns in the local dashboard mirror and optional merchant-name-only web evidence. A stable named-merchant history can resolve automatically. Ambiguous evidence stays in `EXPENSES` with `Status=Review`; the fallback pair `Misc / Other` is never treated as confirmed. Set `categorization.history_intelligence: false` only if this local evidence should be disabled.

- Vague descriptors (e.g. "PURCHASE", "MERCHANT") → `confidence=rejected-vague`
- Unknown merchant with letters present → `confidence=rejected-unknown`

The user can filter `EXPENSES` by `Status=Review`. The separate `REVIEW_QUEUE` tab is available as a workspace for adapter-specific review flows; the v0.4.1 shared capture path does not mirror rows into that tab.

A confirmed correction must use an active pair from `CATEGORIES`. Generic descriptors use `learning_scope=transaction_only`: the chosen pair fixes that row but must not update `MERCHANT_MASTER` or adaptive rules. Named merchants may be learned after confirmation.

## Merchant research extension (optional)

Research stays outside the deterministic write path. Before asking the user, an adapter should check the curated master, learned aliases, historical recurrence fingerprints, and then bounded web evidence. It should present up to three ranked active taxonomy pairs when evidence exists.

`scripts/web_enrichment.py` provides an opt-in Google Programmable Search evidence helper. It returns search evidence, not an approved category. The shared capture path does not call it on its own.

Research rules:

- Send the merchant name only. Keep the amount, card, Sheet ID, and transaction history local.
- Limit proposals to active `CATEGORIES` pairs.
- Keep the expense in review until the user confirms the proposal.
- Route confirmed changes through `correction_handler.py`; do not let the research layer write the Sheet.

Hermes can host this research step when the user has installed a private merchant-research skill. The public repository includes the WhatsApp relay and narrow correction command shapes. It does not include a private Hermes skill or authenticated browser state.

## Confidence boundary

The deterministic resolver does not invent numeric confidence. It labels exact master matches as `known`, keyword matches as `soft`, and unresolved merchants as rejected. The adaptive store accepts numeric confidence only when an external prediction source submits repeated evidence, and automatic promotion stays off by default.

## Fail-closed

`config.categorization.fail_closed` (default `true`). When ambiguous, refuse and ask. Never guess.

---

## Worked examples

End-to-end transcripts of common categorization issues and how the tracker resolves them. Each example shows the trigger, the action, the files changed, and the user-visible result.

### Example 1 — Single transaction has the wrong category

**Trigger.** User receives a confirmation message:
```
Logged AED 142.50 at "spinneys marina" on Card ..xxxx.
Category: Tech / Hardware. Source: in-app push. Row 1842.
```
The user knows Spinneys is a supermarket, not Tech. Wrong category was assigned because Spinneys isn't yet in MERCHANT_MASTER and a tier-2 keyword cue accidentally matched.

**User reply (on the confirmation channel — WhatsApp / Telegram / email).**
```
change spinneys to Groceries / Online
```

**What the skill does.**
1. `correction_handler.py` parses the reply: `change <merchant> to <category> / <subcategory>`.
2. Updates EXPENSES Row 1842: `category=Groceries`, `subcategory=Online`, `Status=Confirmed`, and clears `Review_Reason`.
3. Adds row to MERCHANT_MASTER: `Merchant_Keyword=spinneys`, `category=Groceries`, `subcategory=Online`, `merchant_clean=Spinneys`, `notes=Added via correction handler`.
4. Records the correction in the local JSONL audit log.

**Files changed.** EXPENSES Row 1842 + MERCHANT_MASTER new row.

**Idempotency.** Sending the same correction twice is a no-op.

---

### Example 2 — Bulk re-categorise after a regional pack install

**Trigger.** User installed the UAE regional pack mid-month. Pack adds 60+ merchants to MERCHANT_MASTER. Many historical EXPENSES rows from the past 30 days were tier-3 (refused, manually categorised) or tier-2 (soft cues) before the pack landed — inconsistent with the pack's mappings now.

**User asks the setup assistant in a fresh session.**
```
I just installed the UAE pack. Re-categorise the last 30 days of transactions
to use the new MERCHANT_MASTER mappings where possible.
```

**Action.**
1. Reads `references/repair.md` and `references/edit-mappings.md`.
2. Runs a preview:
   ```bash
   python3 scripts/recategorise_history.py --config ~/.expense-bookkeeper/config.yaml --since 2026-04-12
   ```
   The preview lists each row that would change. Unresolved merchants stay unchanged.
3. Re-runs with `--confirm` after the user approves the preview. More than 50 changes also require `--large-batch`.

**Files changed.** Matching `EXPENSES` rows and the local audit log.

**Why it's safe.** Preview is the default, active taxonomy pairs are enforced, and every applied change reaches the local audit log.

---

### Example 3 — Restructure taxonomy (split one category into two)

**Trigger.** User started with single `Food` category. After 3 months they want `Groceries` + `Dining Out` separately.

**User asks the setup assistant.**
```
Split Food into Groceries and Dining Out. Re-categorise everything historical.
```

**Action.** Read the "Splitting a category" pattern in `references/edit-mappings.md`, then guide the user through:

1. **Add new categories.** Open Sheet, CATEGORIES tab. Add `Groceries` and `Dining Out`. Don't delete `Food` yet. Save.
2. **Re-point MERCHANT_MASTER.** List each merchant mapped to `Food`, ask the user to place it in a new bucket, then update the Sheet through gspread.
3. **Re-resolve history.**
   ```bash
   python3 scripts/recategorise_history.py --config ~/.expense-bookkeeper/config.yaml --map "Food=>auto"
   ```
   `--map "X=>auto"` re-runs the resolver against the updated MERCHANT_MASTER for every EXPENSES row currently categorised as `X`. The first run previews; the approved run adds `--confirm`.
4. **Resolve reviewed rows.** Filter `EXPENSES` by `Status=Review`, then update the expense and `MERCHANT_MASTER` through the correction path.
5. **Delete old category.** Delete `Food` only after no `EXPENSES` or `MERCHANT_MASTER` row references it. Run strict validation first.

**Files changed.** `CATEGORIES`, `MERCHANT_MASTER`, matching `EXPENSES` rows, and the local audit log.

**Why this matters.** Splits and merges are highest-risk. Discipline (dry-run, audit trail, per-step validation) is what prevents silent corruption.

---

### Example 4 — Unknown merchant, optional Hermes research

**Trigger.** User receives a confirmation:
```
Expense needs review: AED 89.00 at "axs paymen 4527".
Current bucket: Misc / Other.
Reason: Unknown merchant.
```

**Optional Hermes step.** A user-owned merchant-research skill searches `axs paymen`, reads public evidence, and proposes `Bills / Government & Utilities` from the active taxonomy. Hermes sends the proposal to the user with a short evidence note.

**User reply.** The user confirms the proposal.

**What the tracker does.**

1. `correction_handler.py` validates the proposed pair against `CATEGORIES`.
2. It changes the existing `EXPENSES` row to `Status=Confirmed`.
3. It adds or updates `axs` in `MERCHANT_MASTER` and writes the audit record.

The research skill cannot write the ledger. A missing or invalid taxonomy pair keeps the transaction in review.

---

### Example 5 — Correction handler conflict

**Trigger.** User previously corrected `spinneys` → `Groceries / Online`. A month later they reply to a fresh Spinneys transaction:
```
change spinneys to Groceries / In-store
```

**What the skill does.**
1. `correction_handler.py` parses the reply.
2. Detects MERCHANT_MASTER already has a row for `spinneys` with a different subcategory.
3. **Asks before overwriting:** "Spinneys is currently mapped to `Groceries / Online`. You want to change it to `Groceries / In-store` for *this transaction only*, or for *all future Spinneys swipes too*? Reply `this only` or `all future`."
4. On `this only`: updates the single EXPENSES row, leaves MERCHANT_MASTER alone.
   On `all future`: updates MERCHANT_MASTER + the single row. Future swipes route to In-store.

**Why this matters.** Single-transaction fixes vs taxonomy decisions are different actions. The skill never silently mutates the master mapping when there's a conflict — it asks. This is the only place in the correction handler that stops to confirm.

---

### Pattern summary

| User intent | Path | Files touched | Reversible? |
|---|---|---|---|
| Fix one transaction | Reply on confirmation channel | EXPENSES + MERCHANT_MASTER | yes |
| Bulk re-categorise after pack install | Setup session runs `recategorise_history.py --since DATE` | EXPENSES, local audit | yes if preview retained |
| Split / merge / rename a category | Approved multi-step workflow | CATEGORIES, MERCHANT_MASTER, EXPENSES, local audit | yes if preview retained |
| Unknown merchant, optional research | Confirm a proposed active taxonomy pair | EXPENSES, MERCHANT_MASTER, local audit | yes |
| Conflicting correction | Reply on confirmation channel → skill asks | depends on `this only` vs `all future` | yes |

To review recent changes, inspect the EXPENSES `notes` column and the local JSONL audit logs.
## Adaptive rules

`scripts/adaptive_categories.py` keeps learned merchant rules in local JSON state with an append-only JSONL audit.

- A confirmed user correction adds a missing merchant rule.
- A conflicting correction creates a pending overwrite proposal.
- Repeated prediction evidence remains observation-only until the user enables `auto_promote_repeated`.
- Automatic promotion needs consistent evidence, the configured confidence floor, and the configured observation count.
- Category rename, split, and merge requests record the number of affected transactions and wait for approval.
- Rule events can be rolled back by event ID.

The Google Sheet or configured merchant CSV remains authoritative. Adaptive rules fill missing merchant keys and do not overwrite the explicit master during capture.
