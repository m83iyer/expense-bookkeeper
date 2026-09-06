# Security policy

## Supported version

The project accepts security fixes for the current `0.4.x` release line.

## Report a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/m83iyer/expense-bookkeeper/security/advisories/new). Include the affected file or workflow, a reproduction, and the impact.

Do not open a public issue for credentials, account access, data exposure, or an unpatched vulnerability.

## Data boundary

The repository ships no Google credentials, Sheet IDs, messaging targets, or transaction history. Users store those values under `~/.expense-bookkeeper/` or in environment variables.

Run the release scanner before sharing a fork or support bundle:

```bash
python3 scripts/privacy_audit.py . --history --private-term 'PRIVATE_TERM'
```

The scanner redacts matched values from its report.
