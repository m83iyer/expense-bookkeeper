---
name: expense-bookkeeper
description: Build, operate, validate, and repair a local-first expense tracker and private dashboard using transaction alerts, CSV statements, Google Sheets, adaptive merchant categories, reconciliation, and optional messaging confirmations.
dependencies: python>=3.10, pyyaml, requests, gspread, google-auth, google-auth-oauthlib, google-api-python-client, python-dateutil
license: see LICENSE.txt
---

# Expense Bookkeeper

Use this skill when a user wants to set up, run, repair, or extend the expense-bookkeeper repository. The tracker runs through local Python scripts. An agent may guide setup and explain reports, but normal capture does not depend on an LLM.

## Modes

1. Set up a new tracker.
2. Add or test a capture adapter.
3. Import or reconcile a CSV statement.
4. Diagnose parsing or categorization.
5. Repair an existing install.
6. Explain automation status and privacy boundaries.
7. Synchronize, serve, or diagnose the Moneta finance dashboard.
8. Build a privacy-safe synthetic demo or refresh the five-currency display cache.

## Required boundaries

- The user supplies Google access, a Sheet, adapter targets, statement files, and OS permissions.
- Keep credentials, Sheet IDs, phone numbers, transaction data, and user paths outside this package.
- Use token-boundary merchant matching. Never use raw substring matching.
- Send unknown or vague merchants to review.
- Read `MERCHANT_MASTER` and active `CATEGORIES` pairs from the user's Sheet before capture. A configured local merchant CSV is an explicit override.
- Reject merchant mappings and corrections that do not use an active category and subcategory pair.
- Keep live writes disabled while `armed: false`, and block duplicate transaction hashes before append.
- Preview merchant-wide corrections and historical re-categorisation before writing. Require `--confirm-bulk` for a correction command and `--confirm` for `recategorise_history.py`.
- Refuse a merchant mapping conflict unless the user approves an overwrite.
- Record applied corrections in the JSONL audit log.
- Keep strict validation enabled. Live mode needs every critical gate, including the `EXPENSES_TEST` write, read, and delete proof.
- Keep merchant research disabled unless the user opts in. Treat research output as a proposal, not a write instruction.
- Treat Hermes as an optional confirmation relay. Expense capture, categorization, and ledger writes must run without it.
- Keep taxonomy rename, split, and merge operations in proposal state until the user approves the impact preview.

## Setup

Follow `references/setup-flow.md`.

The wizard must:

1. Validate user-owned Google credentials.
2. Provision or connect the 10-tab Google Sheet.
3. collect country, timezone, currency, and date formats from the user.
4. Import optional CSV history and build a proposed merchant master.
5. Write the selected capture and confirmation adapter config.
6. Run strict validation.
7. Arm live mode only when the report says `ready_for_arm: true`.

## Categorization

The resolver uses three tiers:

1. Match the user's merchant master.
2. Match a seeded word-boundary cue.
3. Send the transaction to review.

`scripts/adaptive_categories.py` learns explicit corrections, stores evidence for opt-in promotion, creates conflict proposals, and supports rollback. The Sheet or configured merchant CSV wins over local adaptive state.

## Hermes adapter

Use `scripts/adapters/hermes_whatsapp.py` and `references/adapters/whatsapp_hermes.md` when the user chooses WhatsApp.

- Read the target from `EXPENSE_BOOKKEEPER_HERMES_TARGET` or user config.
- Send allowlisted transaction fields only.
- Hide merchant names by default when the user wants a reduced data surface.
- Treat send failures as deferred delivery. Do not roll back the ledger.
- Queue only supported correction commands. Ignore arbitrary inbound text.
- Require bulk confirmation for named-merchant corrections.
- A private Hermes merchant-research skill may propose an active taxonomy pair for a reviewed merchant. It must not own Sheet credentials or approve its own proposal.

## Validation and repair

Run:

```bash
python3 scripts/validate_install.py --config ~/.expense-bookkeeper/config.yaml --strict --json
python3 scripts/repair_diagnostics.py --config ~/.expense-bookkeeper/config.yaml
```

Start repair with read-only checks. Apply reversible local fixes after a dry-run. Stop for account access, OS permissions, or destructive history changes.

## Dashboard

Use `python3 cli.py dashboard-sync` to rebuild the analytical mirror and
`python3 cli.py dashboard-serve` to serve it on loopback. Follow
`references/dashboard.md` for private-LAN access, guarded cash entry, and
service-manager templates.

Use `python3 cli.py dashboard-demo --output <folder>` for public demonstrations.
Never use real ledger data for screenshots. Use `python3 cli.py dashboard-fx-refresh`
only when the user wants USD, INR, GBP, EUR, and AED display conversion. This
refresh sends currency codes only and does not normalize mixed-currency ledger rows.

## Release gate

Before publishing a package or support bundle:

```bash
python3 -m pytest tests/ -q
python3 -m compileall -q cli.py scripts dashboard tests
node --check dashboard/static/app.js
python3 scripts/privacy_audit.py . --history --private-term 'PRIVATE_PROJECT_NAME'
```

Do not publish a release if the privacy scan finds a secret, personal identifier, private project term, Sheet URL, or user-specific path.
