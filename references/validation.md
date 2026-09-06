# Validation

The skill is not "armed" until `scripts/validate_install.py --strict` reports `ready_for_arm: true`. Strict mode (the default) is the audit-locked behaviour from 2026-05-01: any **critical-gate skip** is treated as a FAIL.

## Modes

| Mode | When to use | Critical-gate skip behaviour |
|---|---|---|
| `--strict` (default) | Before live arm. Required for any public install. | Treated as **FAIL**. `ready_for_arm` stays false. |
| `--non-strict` | Development / partial setup only (e.g. wizard reporting progress before sheet is provisioned). | Treated as SKIP. `ready_for_arm` still false unless skips clear. |

`validate_install.py` exits 0 only if `failed == 0`. `--json` flag emits a machine-readable report (used by the wizard).

## Gates

| ID | Critical? | What it checks |
|---|---|---|
| G1 | no | config readable + required keys present (sheet, categorization, capture, confirmation) |
| G2 | no | service-account JSON reachable + parseable |
| **G3** | **yes** | Google Sheet accessible (read) |
| **G4** | **yes** | EXPENSES tab has expected headers |
| **G4b** | **yes** | MERCHANT_MASTER + CATEGORIES tabs present with required headers |
| G5 | no | parser parses ≥ 4 of 5 sample notifications |
| G6 | no | resolver returns correct tier on 4 fixtures (tier 1 / 2 / 3 / vague) |
| G6b | no | **word-boundary safety** — single-token master keys do NOT match inside longer unrelated words. Audit-driven gate proving the resolver no longer fires substring false positives. |
| G7 | no | hash dedup: same input → same hash; different input → different |
| G8 | no | **row-build dry-run** — proves the row builder produces a row in HEADERS order. Does NOT prove live write permission (renamed honestly per re-audit 2026-05-01). |
| **G8b** | **yes** | **safe live-write proof** against `EXPENSES_TEST` tab: append → read-back sentinel → delete row. Proves service-account auth, append permission, and round-trip. Critical in strict mode. |

The four critical gates are the audit's "no public install without these" floor. They cannot be silently skipped. **Note:** G8 was previously critical and claimed write-path proof; the re-audit found it returned before authenticating, so write-path proof was promoted to G8b which actually exercises the live API.

## Pre-arm

Before flipping `armed: true`, the wizard:

1. Runs `validate_install.py --strict --json`
2. Reads `ready_for_arm` from the JSON output. Only `true` allows the arm prompt.
3. Asks the user one final time
4. Sets `armed: true` + `armed_at: <ISO timestamp>`

A setup completion report is written to `~/.expense-bookkeeper/state/setup_report.md` regardless of whether the user arms — it captures every gate result for auditability.

## Post-arm checks

The skill self-monitors via `repair_diagnostics.py` (manual) and the optional `expense-bookkeeper-repair-daily` scheduled task (recipe-only). Common post-arm issues are surfaced as repair findings, not silent failures.

For automation readiness, use the checklist in `references/automation-status.md` in addition to these strict install gates. Validation proves the ledger can be written safely; the automation checklist proves the selected capture sources are actually authenticated, scheduled, and producing events.

## Sample test data

Bundled in `templates/sample_notifications.jsonl` and `templates/sample_statement.csv`. The validation script uses these to exercise parser, resolver, hash, and row-build gates without needing real user data.

## Re-validating

After any config change, the user should re-run validation:

```
python3 scripts/validate_install.py --config ~/.expense-bookkeeper/config.yaml
```

The skill does not auto-disarm on validation failure (that's a repair-system concern), but the next ingestion will refuse to write live and surface the issue via the confirmation adapter.
