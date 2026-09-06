# Android via Tasker, MacroDroid, or Automate

**Status:** Beta — recipe
**Layer:** Capture

## How it works

```
Android phone                                 Skill (any always-on machine)
─────────────                                 ─────────────────────────────
Card swipe                                    
   │                                          
   ▼                                          
Bank notification                             
   │ (Tasker NotificationListenerService)     
   ▼                                          
HTTP POST to skill webhook ────────────────► parse_transaction.py
                                              │
                                              ▼
                                             resolver → write_sheet → confirm
```

## Prerequisites

- Android phone (any version with NotificationListenerService = Android 4.3+)
- Tasker (recommended, paid) OR MacroDroid OR Automate (free alternatives)
- An always-on machine accessible from the phone via HTTP — this can be:
  - a Mac/Linux on the same Wi-Fi
  - a small VPS (Cloudflare Tunnel + Caddy works)
  - a smart home hub running the listener

## Setup with Tasker (recommended)

1. **Grant notification access**
   - Settings → Notifications → Special access → Notification access → Tasker → on

2. **Create a Tasker profile**
   - Profile: Event → Plugin → AutoNotification → Intercept
   - Filter: app = your bank's package name(s)
   - Task: HTTP Request
     - Method: POST
     - URL: `http://<your-machine-ip>:7777/expense-bookkeeper/capture`
     - Body type: JSON
     - Body:
       ```json
       {
         "raw": "%antitle - %antext",
         "package": "%anpkg",
         "received_at": "%TIMES"
       }
       ```

3. **Run the skill listener** on your always-on machine:
   ```
   python3 scripts/adapters/webhook_listener.py \
     --config ~/.expense-bookkeeper/config.yaml \
     --port 7777
   ```

4. **Test**: swipe a card; the notification should fire the Tasker profile, which POSTs to the listener, which calls `parse_transaction.parse(raw)`.

## Setup with MacroDroid (free)

1. Macro: Trigger → Notification → All Notifications (filter by app)
2. Action: HTTP Request → POST → same URL/body as above

## Setup with Automate (free)

Build a flow: Listen for notifications → Filter by app → HTTP request POST.

## Health check

- Tasker: Profile log shows recent invocations
- Listener: `tail -f ~/.expense-bookkeeper/state/listener.log`
- Sheet: rows appearing within 2 minutes of a swipe

## Common failures

| Symptom | Likely cause | Fix |
|---|---|---|
| Profile not firing | Notification access revoked | re-grant in Settings |
| Profile fires but no POST | Tasker can't reach listener IP | check phone + machine on same network; ping from phone |
| POST received but no parse | Notification text format unfamiliar | paste 3 examples to skill, regenerate parser regex |
| Battery saver killing Tasker | OEM aggressive battery management | exclude Tasker from battery optimization |

## Why this is `beta` not `verified`

This stays `beta` until several installations have run it end to end. The
package does not collect telemetry.
