# Adapter Matrix · v1 launch

| Adapter | Layer | Status | Setup recipe |
|---|---|---|---|
| iPhone + Mac local notification listener | Capture | **Reference** | `references/adapters/ios_mac_local.md` |
| Android via Tasker / MacroDroid / Automate | Capture | **Beta — recipe** | `references/adapters/android_tasker.md` |
| Email / Gmail bank alerts | Capture | **Fallback** | `references/adapters/email_gmail.md` |
| Gmail statement / attachment intake | Reconciliation intake | **Reference / publish-candidate** | `references/automation-status.md`, `references/reconciliation.md` |
| SMS bank-alert parser | Capture | **Fallback** | `references/adapters/sms_parser.md` |
| Manual logging via WhatsApp / Telegram command | Capture | **Recipe** | (recipe in primary confirmation adapter) |
| Google Sheets via service account | Ledger | **Verified** | (built-in, see setup-flow) |
| WhatsApp via Hermes | Optional confirm/relay | **Reference / optional** | `references/adapters/whatsapp_hermes.md` |
| Telegram bot | Confirm | **Beta** | `references/adapters/telegram_bot.md` |
| Email confirmation | Confirm | **Fallback** | `references/adapters/email_confirm.md` |
| macOS local runner | Runtime | **Verified** | macOS is the reference runtime |

## Tier definitions

- **Verified** — tested end-to-end; works as documented; supported by repair diagnostics.
- **Beta** — recipe shipped, awaiting broader verification. Should work but expect rough edges.
- **Recipe-only** — instructions exist; not yet validated as a supported public path. Power users only.
- **Fallback** — works for the limited cases its description allows; not the recommended primary path.
- **Reference** — documented as the primary known-good recipe, but still depends on the user's local OS permissions and bank notification behaviour.
- **Reference / advanced** — optional advanced setup; possible but requires the user to run the supporting stack.
- **Reference / publish-candidate** — validated as a pattern, but not a universal public claim until the user's own account, file formats, and schedule are configured.

## Recommendation logic (used by the wizard)

```
phone = iPhone, always_on = Mac           → ios_mac_local
phone = Android, always_on in {Mac/Win/Hosted} → android_tasker
banks_email = "Yes — primary"             → email_gmail
no always_on machine                      → manual_only + monthly reconcile
```

Hermes remains optional. Use it when the user wants WhatsApp delivery and reply-based corrections.

## Tier transitions

A `Beta` adapter graduates to `Verified` when:
- A new user has run it for ≥ 7 days
- Strict validation passes on that user's setup, including G8b safe live-write proof
- At least one repair diagnostic finding has been resolved through the skill

A `Recipe-only` adapter has no graduation path until someone in the community verifies it. The wizard does not recommend recipe-only adapters.
