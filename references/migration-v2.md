# Migrating to Expense Bookkeeper 2.0

Version 2.0 preserves the Google Sheet schema, capture pipeline, merchant
master, category taxonomy, adaptive corrections, and existing runtime folder.
The change is concentrated in the local analytical mirror and dashboard.

## Upgrade

1. Stop the dashboard server. Capture and Sheet writes may continue.
2. Pull version 2.0 and update the Python environment.
3. Run `python3 cli.py dashboard-sync` to rebuild the SQLite mirror with schema
   version 2.
4. Optionally run `python3 cli.py dashboard-fx-refresh` to enable all five
   display currencies.
5. Start `python3 cli.py dashboard-serve` and verify Overview, Drivers,
   Commitments, and Evidence.

The SQLite mirror is derived state. Rebuilding it does not alter the Sheet.

## Configuration added in 2.0

```yaml
dashboard:
  fx_rates_path: ~/.expense-bookkeeper/state/dashboard_fx_rates.json
```

`dashboard-fx-refresh` writes this cache with owner-only file permissions. The
dashboard reads it; it does not refresh rates in the background.

## Compatibility notes

- The analytics API now exposes period KPIs, a hierarchical driver tree,
  deterministic findings, and filter-consistent transaction evidence.
- Recurring rows gain `cadence` and `payment_amount` in the derived database.
  Existing Sheet rows without those fields default safely to monthly values.
- Mixed-currency ledger rows still fail closed. The currency toggle converts a
  normalized reporting total; it is not a replacement for accounting FX.
- Existing live state under `~/.expense-bookkeeper/` remains in place. Do not
  move or symlink configuration, locks, state, or active logs.
