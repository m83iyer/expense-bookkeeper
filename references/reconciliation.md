# Reconciliation

Side lane: catches what the live capture missed. In public v1, the verified path is user-triggered CSV reconciliation: drop a monthly statement into a folder and run:

```
python3 scripts/reconcile_statement.py --config <path> --statement <file>
```

## Match rule

A statement row matches a ledger row when ALL of:

- Date within ± 2 days
- Amount within ± 1%
- Descriptor token overlap ≥ 0.5 (Jaccard between statement merchant and ledger Merchant_Raw + Merchant_Clean)

Otherwise → **GAP**.

## What gaps mean

Gaps are real spends the live lane silently dropped. Common reasons:
- Bank notification didn't fire (network, OS permissions revoked)
- Capture adapter offline at the time
- Foreign-currency transactions where the notification arrives delayed
- Cash spends with no notification

The skill **does not auto-merge** gaps into the ledger. Each gap is presented to the user with three options:
- **Accept** → append to ledger as a normal row, source `StatementImport`
- **Reject** → mark the statement row as already-captured-but-different-descriptor; update merchant master alias
- **Defer** → leave for the next reconciliation pass

## Statement parsing and automation status (v1)

CSV is supported natively (tolerant column-name detection: looks for date / amount / merchant / description / narrative columns).

PDF and Excel are recipe-only at v1: instructions to convert to CSV first using:
- macOS Preview → Export → CSV (for Excel-style PDFs)
- `pdftotext -table` for line-item PDFs
- `xlsx2csv` for Excel files

Future: `pdfplumber` integration scheduled for v2.

Gmail statement attachment filing is a **reference / publish-candidate** lane, not a universal import promise. A scheduled Gmail job may save statement attachments into the user's statements folder, but ledger import is safe only when the file is CSV or a bank-specific parser has been installed and validated. Unsupported PDFs should be saved and reported for review.

See `references/automation-status.md` for the automatic vs manual status table.

## Dedup discipline

When the user accepts a gap, the new row's hash is computed and compared against the ledger. If the hash already exists, the gap is auto-marked `Resolution=already-logged-with-different-descriptor` and the alias is added to merchant master instead.

## Reporting

Each reconciliation run writes to the `RECONCILIATION` tab with one row per gap (`Status=Gap` initially), plus a per-run summary `Run_ID` so reports group cleanly.
