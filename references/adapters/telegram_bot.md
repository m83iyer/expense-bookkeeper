# Telegram confirmation

**Status:** Beta
**Layer:** Confirm

## Why this is the recommended public path

WhatsApp gateways are policy-restricted; Telegram bots are not. Setting up a Telegram bot takes 5 minutes and costs nothing.

## Setup

1. **Create a bot** via @BotFather on Telegram:
   - `/newbot`
   - Pick a name + username
   - Save the token (looks like `123456:ABC-DEF...`)

2. **Get your chat ID** (one-time):
   - Send any message to your bot
   - `curl https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Read `result[0].message.chat.id`

3. **Configure the skill** (`config.yaml`):
   ```yaml
   confirmation:
     adapter: telegram_bot
     telegram:
       bot_token: <token>            # or env: EXPENSE_BOOKKEEPER_TG_TOKEN
       chat_id: <chat_id>
       confirmations: terse
       poll_interval_seconds: 30
   ```

   **Recommended:** put the bot token in env, not config:
   ```
   export EXPENSE_BOOKKEEPER_TG_TOKEN=<token>
   ```
   And in config:
   ```yaml
   telegram:
     bot_token_env: EXPENSE_BOOKKEEPER_TG_TOKEN
   ```

4. **Connect a poller**

   This repository documents the Telegram contract but does not ship a
   Telegram poller. Route approved replies through `correction_handler.py`, or
   use the implemented Hermes adapter.

## Confirmation format

Same as WhatsApp adapter. Plain text; Telegram supports basic Markdown.

## Correction grammar

Same as WhatsApp adapter. The skill's correction handler is shared.

## Health check

```
curl https://api.telegram.org/bot<TOKEN>/getMe
```

Should return `"ok": true, "result": {...}`.

## Common failures

| Symptom | Likely cause | Fix |
|---|---|---|
| Bot doesn't respond | wrong chat_id | re-run getUpdates with a fresh message |
| `getUpdates` returns 401 | bot token revoked | regenerate via @BotFather |
| Confirmations sent but not delivered | rate limit | reduce `confirmations` from `verbose` to `terse` |

## Why "beta"

This stays beta until Telegram users run the path for at least 7 days. The path itself works; the "beta" label is about repair diagnostics being tested against this adapter, not the basic delivery.
