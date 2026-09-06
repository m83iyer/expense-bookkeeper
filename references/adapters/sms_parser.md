# SMS bank-alert capture

**Status:** Fallback (recommended when banks still send SMS alerts)
**Layer:** Capture
**Code:** `scripts/adapters/sms_parser.py`

## When to use

Some banks still send a per-swipe SMS to your phone. If your bank does, this adapter turns that SMS into a ledger row. Use SMS as primary capture only if your bank reliably SMS-alerts every transaction; otherwise pair it with `ios_mac_local` or `android_tasker` (in-app push) and let SMS catch the few banks that aren't on push.

**Banks moving away from SMS:** Wio (UAE), most modern fintechs, several US neobanks. If your primary bank dropped SMS alerts, use in-app push as primary.

## How it works

```
Bank SMS to phone
   │
   ▼
SMS source (one of: Mac chat.db / Android Tasker / Twilio webhook)
   │  (raw text + sender + timestamp)
   ▼
sms_parser.feed_sms() → identify bank from sender → apply user regex patterns
   │
   ▼
parse_transaction.parse() → Transaction { date, amount, merchant_raw, card, hash }
   │
   ▼
merchant_resolver → write_sheet → confirmation
```

## Source options — pick one

### Option A — macOS Messages (recommended for iPhone users with always-on Mac)

If your iPhone forwards SMS to your Mac (Settings → Messages → Text Message Forwarding), every bank SMS lands in `~/Library/Messages/chat.db`. A small reader script polls the DB and feeds new messages into `feed_sms()`.

Setup:

1. Enable iPhone → Mac SMS forwarding (one-time, on the iPhone)
2. Grant the skill's runtime Full Disk Access to read `chat.db` (System Settings → Privacy & Security → Full Disk Access → add your Python interpreter)
3. Add a launchd agent that runs the SMS sweep every 5 min (template in this directory: `sms_chatdb_sweep.plist.template`)

### Option B — Android via Tasker / MacroDroid

Tasker can intercept SMS-RECEIVED intents and POST the message body to
`scripts/adapters/webhook_listener.py`. The shared webhook feeds raw text into
the same capture pipeline.

Setup:

1. Install Tasker (or MacroDroid)
2. Create a profile that posts JSON with a `raw` field to
   `http://<your-machine>:7777/expense-bookkeeper/capture`
3. Run `python3 scripts/adapters/webhook_listener.py --config <path> --host 0.0.0.0`
4. Open port 7777 on the private LAN only and configure `capture.shared_secret`

### Option C — SMS aggregator webhook (Twilio / MessageBird / etc.)

If you forward your bank SMS to a Twilio number (or use a virtual SMS number that mirrors your bank notifications), Twilio POSTs each message to a webhook. Same receiver as Option B, just configure Twilio's webhook URL to hit your endpoint.

## User config — `config.yaml`

Each bank's SMS pattern is YOUR config (every bank uses a different format). Example:

```yaml
capture:
  adapter: sms_parser
  currency_default: AED

sms_bank_senders:
  wio:
    - "wiopersonal"
    - "wio personal"
    - "wio bank"
  enbd:
    - "emirates nbd"
    - "enbd"
  cbd:
    - "commercial bank of dubai"
    - "cbd"

sms_bank_patterns:
  wio:
    - 'Payment of AED\s+(?P<amount>[\d,]+\.?\d*)\s+was done at\s+(?P<merchant>.+?)\s+using your Wio'
    - 'AED\s+(?P<amount>[\d,]+\.?\d*)\s+(?:has been |was )?(?:debited|deducted).*?(?:at|from)\s+(?P<merchant>.+?)(?:\.|$)'
  enbd:
    - 'Purchase of AED\s+(?P<amount>[\d,]+\.?\d*)\s+with Credit Card ending \*+\s+at\s+(?P<merchant>.+?)(?:,\s*\w+|\.|\s*$)'
  cbd:
    - 'A transaction of AED\s+(?P<amount>[\d,]+\.?\d*)\s+was debited from your credit card \*+\s+(?P<merchant>.+?)(?:\.|$)'

card_labels:
  wio: "Wio Personal"
  enbd: "ENBD Credit"
  cbd: "CBD"
```

The skill's setup wizard offers a one-pattern starter for the most common bank formats; users add their own banks with `repair_diagnostics --learn-pattern`.

## Failure modes the adapter handles

- **Sender not in any bank list** → returned Transaction has `valid=False`, caller skips silently (it's an OTP or non-financial SMS).
- **Bank matched but no regex hit** → returned Transaction has `valid=False, error="no_pattern_match"`. Logged to skill's review queue.
- **Bank matched, regex hit, amount unparseable** → ditto, with `error="amount_parse_fail"`.

## Limits / non-goals

- This adapter does **not** read SMS directly. You wire one of the source options above.
- This adapter does **not** include OTP filtering — the source script must drop messages whose sender is your OTP gateway.
- Bank-specific patterns are user config, not skill code. The skill ships zero hardcoded bank knowledge to keep the repository public-shareable.
