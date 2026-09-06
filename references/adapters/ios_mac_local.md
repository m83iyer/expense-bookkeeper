# iPhone and Mac local notifications

**Status:** Reference setup
**Layer:** Capture

## How it works

```
iPhone                Mac (always-on)              Python core
──────                ──────────────              ─────
Card swipe                                        
   │                                              
   ▼                                              
Bank notification                                 
   │ (Continuity/Notification Center mirroring)   
   ▼                                              
   ─────────────► Notification Center            
                    │                             
                    │ (local Python listener, polls every 60s)
                    ▼                             
                  Local event handoff ──────────► parse_transaction.py
                                                   │
                                                   ▼
                                                  resolver → write_sheet → optional confirm
```

## Prerequisites

- iPhone running iOS 16+ with Notifications enabled for your banking apps
- Mac running macOS 13+ with Continuity / Handoff enabled (same iCloud account)
- Python 3.10+ on the Mac that will run the listener
- Bank apps configured to push notifications on every swipe
- Hermes only if you choose WhatsApp confirmation later

## Setup

1. **Enable iPhone notification mirroring on Mac**
   - System Settings → Notifications → Allow notifications from your iPhone → on
   - On iPhone: Settings → Notifications → Show on Mac → on

2. **Install a local notification reader** (one-time, Mac side)
   - The listener watches mirrored bank notifications and hands raw notification text to the Python core.
   - It does not categorise merchants, write the ledger, or send WhatsApp by itself.
   - This repository provides the handoff contract, not a macOS notification database reader.

3. **Configure the notification listener** (`~/.expense-bookkeeper/adapters/ios_mac_local.config.yaml`)
   ```yaml
   listeners:
     - name: bank_notifications
       source: macos_notification_center
       filter:
         apps: ["com.yourbank.app", "com.yourotherbank.app"]
       poll_interval_seconds: 60
   ```

4. **Hand events to the core**
   - Your notification reader should call:
     ```
     python3 scripts/capture_pipeline.py --config ~/.expense-bookkeeper/config.yaml --raw "<notification text>"
     ```
   - Keep the reader private to the local machine and schedule it with the operating system.

## Health check

```
launchctl list | grep expense-bookkeeper
tail -f ~/.expense-bookkeeper/state/listener.log
```

If the agent isn't running:
```
launchctl unload ~/Library/LaunchAgents/com.expense-bookkeeper.listener.plist
launchctl load ~/Library/LaunchAgents/com.expense-bookkeeper.listener.plist
```

## Common failures

| Symptom | Likely cause | Fix |
|---|---|---|
| No notifications arriving | Continuity off | iPhone Settings → Show on Mac → on |
| Some banks missing | App-level filter wrong | Edit `listeners.yaml` apps list |
| Listener running but sheet not writing | config or access failure | run `python3 scripts/validate_install.py --strict --json` |
| Duplicate rows | Two listeners running | `launchctl list | grep listener` and unload duplicates |

## WhatsApp corrections

WhatsApp corrections are optional and covered in
`references/adapters/whatsapp_hermes.md`. Hermes transports messages; the
Python correction handler owns the ledger update.
