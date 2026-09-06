# Privacy

The skill is privacy-first by default. Users keep their data; nothing leaves their boundary unless they explicitly enable it.

## Data residency

- The Google Sheet is the user's, in their Google account.
- The service account belongs to the user's Cloud project.
- Local state (config, merchant cache, web cache, run logs) lives in `~/.expense-bookkeeper/` and never leaves the local filesystem.

## What the skill never does

- Bundle secrets, API keys, sheet IDs, or account access.
- Send data to a package-owner service.
- Log full transaction rows to public/shared logs.
- Pull from the web without explicit user opt-in.

## Merchant research (opt-in)

Disabled by default. `scripts/web_enrichment.py` is an evidence helper for an external review flow; the shared capture pipeline does not call it on its own.

The helper understands these configuration modes when an external review flow calls it:

- `never` — no network for category resolution
- `ask` — available to a user-triggered review flow
- `always` — available to an explicitly wired automated review flow

These settings alone do not add research to the shared capture pipeline.

When enabled:
- Searches **merchant name only** (never amount, date, or other transaction fields)
- Caches results 30 days; never re-queries
- Stores summary evidence (title + snippet), not full pages
- Provider is user-configured: `google_pse` (user-supplied API key + cx) or `none`

## Logs

Default verbosity logs:
- Timestamp + check name + status (pass/fail)
- Counts of rows processed
- Tier distribution per run

Logs do **not** include:
- Merchant names (redacted by default in shared logs)
- Amounts
- User identifiers

The user can opt into verbose logging for debug. Verbose logs go to `~/.expense-bookkeeper/state/debug.log` and the user can review/redact before sharing.

## Delete / disconnect

To remove the skill:

```
# remove local state (config, cache, logs)
rm -rf ~/.expense-bookkeeper/

# remove the launchd agents (if installed)
launchctl unload ~/Library/LaunchAgents/com.expense-bookkeeper.*.plist
rm ~/Library/LaunchAgents/com.expense-bookkeeper.*.plist

# remove the skill folder from your agent runtime, if you installed it there
```

The user's Google Sheet remains intact. The user can revoke the service account's access by removing it from the sheet's Share settings and/or deleting the service account in Google Cloud Console.

## Opt-in summary

| Feature | Default | User can change |
|---|---|---|
| Merchant research helper | `never` | Explicit external review flow |
| Verbose logging | off | on via `EXPENSE_BOOKKEEPER_DEBUG=1` |
| Telemetry | none | n/a — no telemetry, ever |
