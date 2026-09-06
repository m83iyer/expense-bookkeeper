# Repair

The local diagnostic scripts own repair. They do not route users into a package-owner service or private pipeline.

## Diagnostic flow

`scripts/repair_diagnostics.py --config <path>` runs read-only checks first, then offers reversible local fixes.

Output format per check:

```
issue:                <what broke>
likely cause:         <diagnosis>
safe fix:             <reversible local action; applied automatically in dry-run>
requires user action: <true/false; if true, exact step the user must perform>
validation command:   <one-line command the user can run to confirm the fix>
```

Severity tiers:
- **BLOCKER** — skill cannot run; must fix before next capture
- **MAJOR** — skill runs but a feature is broken (e.g. capture adapter offline, no rows in 24h)
- **MEDIUM** — degraded but functional (e.g. log dir not writable; falls back to stderr)
- **MINOR** — cosmetic / advisory (skipped — not in v1)

## Repair playbook (top 5 expected failures)

### 1. Sheet not reachable (BLOCKER)

```
issue: sheet not reachable: APIError 403
likely cause: service account not shared with the sheet
safe fix: share the sheet with <service-account-email> as Editor
requires user action: true
validation command: python3 scripts/validate_install.py --config <path> --dry-run
```

The user opens the sheet, Share → adds the service-account email visible from `cat <service-account-json> | python3 -m json.tool | grep client_email`.

### 2. Service account JSON missing (BLOCKER)

```
issue: service account file not found: <path>
likely cause: file moved/deleted, or wrong path in config
safe fix: restore the file or update sheet.service_account_path
requires user action: true
validation command: ls -la <path>
```

### 3. No rows logged in 24h (MAJOR)

```
issue: no rows logged in the last 24h
likely cause: capture adapter offline, OS permissions revoked, or genuinely no spend
safe fix: check capture adapter health (see references/adapters/<adapter>.md § health)
requires user action: depends — diagnostic may auto-relaunch the listener
validation command: tail -f ~/.expense-bookkeeper/state/run.log
```

For the iPhone+Mac local listener, run `launchctl list | grep expense-bookkeeper`. Reload the listener agent if it is missing. If the user enabled WhatsApp through Hermes, check Hermes as a separate transport layer.
For Telegram bot: poll the bot's `getUpdates`; if no updates, the bot token may have been revoked.
For Email/Gmail: check the OAuth token's last refresh.

### 4. Parser regex outdated (MAJOR)

```
issue: 5 unparsed notifications in last 24h
likely cause: bank changed notification format
safe fix: paste 3 examples; skill regenerates the regex pattern (dry-run first)
requires user action: paste 3 examples
validation command: python3 scripts/parse_transaction.py --test <example>
```

### 5. Hash collision (BLOCKER)

```
issue: two rows with the same Hash but different merchants
likely cause: hash collision (sha1 truncated to 16 chars; rare but possible)
safe fix: extend hash length or include card in hash input
requires user action: confirm before applying (changes hash for all future rows)
validation command: <skill computes new vs old; shows preview>
```

## What repair does NOT do

- It does not change OS permissions
- It does not modify cloud-side access (rotate / regenerate tokens)
- It does not edit the user's bank connections
- It does not auto-merge ledger rows or rewrite history

For all of the above, repair surfaces the exact action the user must take and stops.
