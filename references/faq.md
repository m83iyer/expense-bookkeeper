# FAQ

### Why a Google Sheet, not an app?

So you can leave. The sheet is yours, in your Google account. If you outgrow the skill, the data follows. Apps lock you in; sheets don't.

### Why local Python instead of a hosted service?

You keep your data and Google access. The tracker runs as local Python scripts. You can use an agent runtime for setup and repair, and you can add a messaging relay if you want one.

### Does the tracker work without Hermes?

Yes. Hermes handles optional WhatsApp notifications and reply-based corrections. The ledger, parser, categorizer, recurring writer, reconciliation, and validation run without it.

### Why does the tracker flag some merchants for review?

Tier 3 means the tracker could not resolve the merchant safely. It records the transaction as `Status=Review` with `Misc / Other` instead of pretending the category is confirmed. If a confirmation adapter is enabled, it also asks for a correction. Each confirmed correction teaches the merchant master.

### My bank moved alerts into their app. Can the skill still capture?

Yes — that's why notification capture (rather than email parsing) is the recommended primary path. As long as the bank pushes a notification on swipe, the skill can see it via the OS-level adapter.

### Can the skill capture from iPhone alone (no Mac)?

Limited. iOS doesn't expose all app notifications cleanly to automations. Use iPhone+Mac mirroring (NotificationCenter via Continuity) or fall back to the email/Gmail adapter.

### What about Android?

Tasker, MacroDroid, or Automate can forward notifications to a webhook. See `references/adapters/android_tasker.md`. This path remains a beta recipe.

### Can I use this in a country other than the UAE?

Yes. Locale (country, currency, timezone, date formats) is captured explicitly during setup; it is not inferred silently from statements. The optional UAE regional pack is opt-in only. Your own CSV statements and confirmed merchant master become the source of truth for your taxonomy.

### What does "shadow mode" mean?

For users with an existing tracker, shadow mode runs the skill alongside without writing to the production tab. Shadow rows go to `EXPENSES_TEST`. After 7 days of clean parity, you can promote to live.

### Is my data sent anywhere?

No package-owner service receives it. Your Google Sheet and local state remain under your control. Google Sheets receives ledger data when you enable live capture. Optional merchant research is opt-in and should receive only the merchant name and active taxonomy pairs. There is no telemetry.

### How do I uninstall?

See `references/privacy.md` § Delete / disconnect.

### Does it include charts and spending trends?

Yes. The local dashboard provides monthly trends, MoM, QoQ, YoY, category and subcategory drill-down, spike drivers, recurring commitments, and transaction evidence. Google Sheets remains the source of truth.
