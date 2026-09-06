# Gmail bank-alert capture

**Status:** Fallback
**Layer:** Capture

## When to use

Banks that still send a transaction email per swipe. Many banks have stopped doing this in favour of in-app notifications, which is why the recommended primary path is `ios_mac_local` or `android_tasker`. Use email/Gmail if:

- your bank emails every swipe in real time (within seconds), AND
- you can't run a notification listener (no always-on Mac, no rooted Android)

## How it works

```
Bank → email → Gmail inbox → skill polls every 2 min → parse → resolver → sheet
```

## Prerequisites

- Gmail account with bank alert emails arriving
- A Google Cloud project with Gmail API enabled
- OAuth client file (NOT a service account — Gmail API requires user OAuth)

## Setup

1. **Enable Gmail API** in your Google Cloud project (the same one you set up for Sheets):
   - APIs & Services → Library → Gmail API → Enable

2. **Create OAuth client** (one-time):
   - APIs & Services → Credentials → Create Credentials → OAuth client ID
   - Application type: Desktop app
   - Download the client_secret.json

3. **First-run authorization**:
   ```
   python3 scripts/adapters/gmail_auth.py --client-secret <path-to-client-secret.json>
   ```
   This opens a browser, you approve, the script saves a refresh token to `~/.expense-bookkeeper/gmail_token.json`.

4. **Configure filters** in `config.yaml`:
   ```yaml
   capture:
     adapter: email_gmail
     gmail:
       senders_allowlist:
         - "alerts@example.com"
         - "noreply@example.org"
       subject_patterns:
         - "Transaction alert"
         - "Card spend"
       poll_interval_seconds: 120
       state_file: ~/.expense-bookkeeper/state/gmail_last_seen.json
   ```

5. **Run the poller**:
   ```
   python3 scripts/adapters/gmail_poller.py --config <path>
   ```

   Or as a launchd agent:
   ```
   <plist with StartInterval=120 calling gmail_poller.py>
   ```

## Health check

```
cat ~/.expense-bookkeeper/state/gmail_last_seen.json
tail -f ~/.expense-bookkeeper/state/gmail.log
```

If `last_seen` hasn't advanced in > 2 hours and you've spent: re-auth.

## Common failures

| Symptom | Likely cause | Fix |
|---|---|---|
| OAuth token expired | refresh failed | re-run `gmail_auth.py` |
| No emails parsed | sender allowlist wrong | add the actual `From:` address |
| Parser fails on email body | bank changed format | paste 3 examples to skill, regenerate regex |
| Duplicate rows from email + notification | both adapters running | disable one, or rely on hash dedup |

## Limits

- Latency: 2-5 minutes (poll cadence)
- Coverage: only banks that email
- Costs: Gmail API has generous free quota for personal use
