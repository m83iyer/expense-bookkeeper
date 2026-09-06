# Email confirmation

**Status:** Fallback
**Layer:** Confirm

## When to use

You don't want a messaging app in the loop. Confirmations land as low-priority emails (one per row, or batched daily).

## Setup

1. **SMTP access** — most users use Gmail with an app password:
   - Google Account → Security → 2-Step Verification → App passwords → generate
   - Save the 16-char password

2. **Configure** (`config.yaml`):
   ```yaml
   confirmation:
     adapter: email_confirm
     email:
       smtp_host: smtp.gmail.com
       smtp_port: 587
       username: <your-gmail>
       password_env: EXPENSE_BOOKKEEPER_SMTP_PASS
       to: <where-to-send>
       mode: per-row    # per-row | daily-digest | weekly-digest
       label_prefix: "[expense-bookkeeper]"
   ```

3. **Set env**:
   ```
   export EXPENSE_BOOKKEEPER_SMTP_PASS=<app-password>
   ```

## Format

Subject: `[expense-bookkeeper] AED 87 · Groceries · Amazon`
Body:
```
Logged: AED 87.00 · Groceries / Supermarket · Amazon
Card:   WioCredit
Date:   29 Apr 2026
Hash:   abc123def456

Reply NO to this email to flag for review.
Reply with text "change category to <name>" to correct.
```

## Correction grammar

Same as WhatsApp / Telegram, but processed by the inbound mail watcher (recipe-only at v1; for now corrections require editing the sheet directly).

## Health check

This repository documents the SMTP contract but does not ship an email sender.
Test the account through the sender you connect, then use the Sheet review
queue for corrections.

## Why "fallback"

- Latency from SMTP to inbox is variable
- No good way to surface tier-3 questions interactively (no real-time reply loop)
- Spam filters can intercept
- Inbox noise (one email per swipe is a lot)

If you can use Telegram, use Telegram instead.
