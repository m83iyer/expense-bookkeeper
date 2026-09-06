# Architecture

OS-agnostic Python core. Adapters at the edges.

```
[ Capture adapter ] ──┐
   iPhone+Mac local listener · Android+Tasker · SMS · Email · Manual
                       │
                       ▼
              [ Python core: parse_transaction.py ]
                       │
                       ▼
              [ normalise + hash ]   ← sha1(date|amount|merchant) for dedup
                       │
                       ▼
              [ CATEGORIES + MERCHANT_MASTER ]
                       │   active taxonomy + user mappings
                       ▼
              [ merchant_resolver.py ]   ← three-tier
                       │   tier 1: Sheet/CSV/adaptive master hit
                       │   tier 2: keyword cue
                       │   tier 3: preserve as Review
                       ▼
              [ write_sheet.py ]   ← armed gate + hash dedup + gspread
                       │
                       ▼
                 [ Google Sheet ]
                    ┌──┴──────────────────────┐
                    ▼                         ▼
       [ optional confirmation ]     [ atomic SQLite mirror ]
                    │                         │
                    ▼                         ▼
       WhatsApp · Telegram · email    [ responsive dashboard ]
                    │
                    ▼
       [ correction handler → merchant cache update ]

  Side lanes:
    - reconcile_statement.py  (on-demand CSV diff; scheduled wrappers may call it)
    - Gmail/SMS/statement intake recipes  (source-specific, user-owned access)
    - repair_diagnostics.py   (on-demand or scheduled)
    - validate_install.py     (gates dry-run → live transition)
```

## Module roles

| Module | Owns |
|---|---|
| `parse_transaction.py` | Raw notification → structured `Transaction` |
| `merchant_resolver.py` | 3-tier, word-boundary resolver |
| `capture_pipeline.py` | Reads the Sheet/CSV master, checks active taxonomy, resolves, and enforces armed mode |
| `adaptive_categories.py` | Local confirmed-correction learning, proposals, audit, and rollback |
| `web_enrichment.py` | Optional evidence helper for an external review flow; no Sheet writes |
| `write_sheet.py` | gspread append, dry-run flag, header guard |
| `reconcile_statement.py` | Statement parser + ledger diff; never auto-merges |
| `repair_diagnostics.py` | Read-only health checks + reversible local fixes |
| `setup_wizard.py` | Interactive setup; writes config.yaml |
| `validate_install.py` | Gates 1–8 functional sign-off |
| `import_statements.py` | Bootstrap proposed merchant master from CSV statements |
| `create_ledger.py` | Provision new Google Sheet with template tabs |
| `adapters/hermes_whatsapp.py` | Optional fail-soft WhatsApp confirmation and correction queue |
| `dashboard/sync.py` | Atomic Google Sheet to SQLite analytical mirror |
| `dashboard/intelligence.py` | Deterministic period, comparison, and root-cause analysis |
| `dashboard/fx.py` | Validated local cache for five display currencies |
| `dashboard/demo.py` | Deterministic privacy-safe demonstration ledger |
| `dashboard/server.py` | Local analytics API, Moneta UI, and guarded cash entry |

## Runtime boundary

After setup, the expense tracker is a Python automation system, not an LLM loop.

- Python scripts own capture intake, parsing, merchant resolution, Google Sheet writes, recurring posts, reconciliation, validation, and diagnostics.
- The CLI or an agent runtime can guide setup, repair, and optional conversational corrections.
- Hermes handles WhatsApp transport when the user enables it. A private Hermes skill may research an unknown merchant and propose an active taxonomy pair. Python validates and writes confirmed corrections.
- A user can run the tracker with `confirmation.adapter: none` and still have a working ledger.
- Automation status is documented in `references/automation-status.md`. That file is the public boundary for what can run unattended, what is fallback-only, and what still requires user review.

## Adapters

Each adapter is a markdown recipe + (where applicable) a thin runtime shim.
The core never knows which adapter sourced the signal.

- `references/adapters/ios_mac_local.md` — reference iPhone+Mac local capture recipe
- `references/adapters/android_tasker.md` — beta recipe
- `references/adapters/email_gmail.md` — fallback
- `references/adapters/whatsapp_hermes.md` — optional reference
- `references/adapters/telegram_bot.md` — beta
- `references/adapters/email_confirm.md` — fallback

## Data flow guarantees

- **No core path makes a network call** except gspread (Sheet operations),
  optional merchant research, and the owner-triggered FX refresh. The FX request
  contains currency codes only; it never contains ledger data.
- **The skill only writes to the user's sheet.** Adapters running locally never write directly; they hand off to the core.
- **Idempotency:** `parse_transaction.py` computes the hash. `write_sheet.py` checks existing Sheet hashes and duplicates inside the incoming batch before append.
- **Fail-closed:** an unarmed tracker stays in dry-run mode. Invalid taxonomy mappings stop capture, and uncertain merchants use `Status=Review`.
