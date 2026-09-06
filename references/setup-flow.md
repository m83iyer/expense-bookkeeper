# Setup Flow

The wizard at `scripts/setup_wizard.py` walks the user through the setup steps below. An agent runtime can also conduct setup from this file.

The user completes one-time setup, supplies Google access, and can import old statements to build a personal `MERCHANT_MASTER`. Gmail OAuth, phone permissions, scheduled runners, and the optional Hermes relay apply only to the lanes the user selects. The package includes no account access or live jobs.

## Prerequisites

- A Google account
- A Google Cloud project with the Google Sheets API and Google Drive API enabled (free tier is fine)
- A service account JSON file. Fresh Sheet creation uses both Sheets and Drive scopes (`https://www.googleapis.com/auth/spreadsheets`, `https://www.googleapis.com/auth/drive`).
- Python ≥ 3.10
- An agent runtime is optional. The standalone path needs Python only.

If the user doesn't have the Cloud project yet, walk them through:

1. visit https://console.cloud.google.com
2. Create a project (or pick existing)
3. APIs & Services → Library → enable **Google Sheets API** and **Google Drive API**
4. APIs & Services → Credentials → Create Credentials → Service Account
5. Download the JSON; save it locally (the path becomes `sheet.service_account_path`)

## ⚠ Important: Service-account Drive quota (read this before fresh-sheet provisioning)

**Google platform limitation:** service accounts on free-tier GCP / non-Workspace projects **cannot own Google Drive files**. Their effective Drive storage quota is 0. When the wizard tries to create a fresh sheet under such a service account, Google returns the error `storageQuotaExceeded` — even when the SA owns zero files.

This affects the wizard's "provision fresh sheet" path, not the "connect existing sheet" path.

**Three workarounds, in order of preference:**

1. **Connect to a sheet you already own (recommended for v1).** Create an empty sheet manually in your Google Drive (10 seconds: https://sheets.google.com → **+ Blank**). Share it with your service-account email as **Editor**. Then run the wizard and answer **yes** to "Do you already have a Google Sheet?" — paste the sheet ID. The sheet stays in your Drive (which has its own 15 GB quota), the service account just writes to it.

2. **Use a Shared Drive** (Google Workspace only). Create a Shared Drive (formerly Team Drive), add the service account as a Content Manager. Sheets created in a Shared Drive don't hit the per-SA quota. Requires a paid Workspace subscription.

3. **OAuth-as-user instead of service account** (recipe-only at v1; planned for v1.1). The user authenticates via browser OAuth; sheets are created in the user's own Drive.

The wizard detects this error and surfaces it explicitly — you won't get a confusing failure. But it's worth knowing upfront so you can pick path 1 from the start instead of hitting it at provisioning time.

## Step-by-step

### 1. Mode

`new tracker` / `migrate` / `reconcile-only`

### 2. Connect Google Sheet

Two paths:

- **Create from template** — `setup_wizard.py` (or `scripts/create_ledger.py` standalone) provisions a new sheet with **all 7 canonical data tabs**: `EXPENSES`, `MERCHANT_MASTER`, `CATEGORIES`, `REVIEW_QUEUE`, `RECONCILIATION`, `RECURRING`, `EXPENSES_TEST`, plus dashboard tabs. The fresh sheet is shared with the user's Google email (captured in step 2b) so it appears in their Drive. The service account remains the backend writer.
- **Use existing** — user provides sheet ID. Skill verifies tabs/headers; the user is responsible for sharing that sheet with the service account email (Editor permission).

### 3. Locale (no defaults)

User answers: country code (ISO 2-letter), timezone (IANA, e.g. `Asia/Dubai` / `Europe/London` / `America/New_York`), default currency (3-letter ISO), and primary date format (`%Y-%m-%d` / `%d/%m/%Y` / `%m/%d/%Y`). The wizard does not silently default to UAE/AED. The UAE regional pack is a separate opt-in step (see step 6).

### 4. Import past statements (CSV only at v1)

User drops 6–12 months of **CSV statements** into `~/Documents/expense-bookkeeper/statements/` (default; visible in Finder/Files). Skill state stays at `~/.expense-bookkeeper/` (hidden, conventional). `setup_wizard.py` calls `import_statements_proposed()` which produces:

- `state/merchant_master_proposed.csv` — proposed master with frequency + amount totals (one row per unique merchant string seen in the user's CSVs)

User opens this file and fills in `Category` / `Subcategory` for each merchant they want mapped. Then resumes setup with:

```
python3 scripts/setup_wizard.py --resume-from-master ~/.expense-bookkeeper/state/merchant_master_proposed.csv
```

The resume step pushes the user-confirmed master into the `MERCHANT_MASTER` tab, optionally appends regional-pack rows (UAE pack ships; opt-in), and seeds the `CATEGORIES` tab from the categories present in the master.

**v1 limitations (honest):**
- **PDF and Excel statements are recipe-only.** Convert to CSV first. The wizard parses CSVs only.
- **No locale auto-inference from statements.** Users set locale explicitly in step 3.
- **No automatic taxonomy proposal beyond merchant frequency counts.** The user confirms category for each merchant in the proposed master; the skill does not pre-bucket merchants into categories without user input.

### 5. Build taxonomy

The user confirms or edits the `CATEGORIES` tab. The skill seeds `CATEGORIES` from whatever categories appear in the user-confirmed `MERCHANT_MASTER`. Default keyword cues (in `merchant_resolver.py`) are English-language fallbacks; non-English regions should add their own cues to `MERCHANT_MASTER` as the canonical override.

The wizard sets `categorization.confidence_threshold` to 0.75, `fail_closed=true`, adaptive confirmed-correction learning on, and merchant research off. Advanced users can wire a separate opt-in research flow after setup; research output remains a proposal until the user confirms it.

### 5. Capture adapter (recommendation + optional fallbacks)

Skill asks:
- What phone? (iPhone / Android / Other)
- Do you have an always-on machine? (Mac / Windows / Hosted / No)
- Do your banks send transaction SMS alerts? (every / some / no)
- Do your banks send transaction email alerts? (every / some / no)

Recommends a primary:
- iPhone+Mac → `ios_mac_local` local notification recipe
- Android+anything → `android_tasker` (beta)
- All banks SMS → `sms_parser` (fallback)
- Some banks email → `email_gmail` (fallback)
- Some banks SMS → `sms_parser` (fallback)
- nothing always-on → `manual_only` + monthly reconciliation

Optional fallback adapters: when in-app push is the primary, the wizard suggests adding `sms_parser` and/or `email_gmail` as additional capture sources for banks that don't send push notifications. The pipeline dedupes via sha1 hash, so the same transaction arriving from two sources produces one ledger row.

For users who want the complete automatic/manual picture, cite `references/automation-status.md`. It covers notification capture, Gmail transaction alerts, Gmail statement attachments, SMS, recurring entries, validation, and monthly reconciliation without exposing any private setup.

User can pick any adapter regardless of the recommendation. Each adapter has its own setup recipe in `references/adapters/<name>.md`.

The capture adapter feeds transaction events into the Python core. It is not an LLM operation: once wired, the local scripts parse, dedupe, categorise, and write the ledger row.

Each user wires adapters on their own machine. The package includes no notification listener state, Gmail OAuth tokens, Hermes target, Sheet ID, local paths, or scheduled jobs.

### 6. Confirmation adapter

`whatsapp_hermes` (reference) / `telegram_bot` (beta) / `email_confirm` (fallback) / `none`.

Confirmation is optional. Choose `none` for a quiet ledger-only install. Choose `whatsapp_hermes` when the user wants WhatsApp pings or reply-based corrections and runs Hermes on their own machine. Hermes transports messages; Python owns the expense logic.

### 7. Dry run

`scripts/validate_install.py --config <path> --strict` runs the readiness gates, including G8b safe live-write proof. Must return `ready_for_arm: true` before live mode.

### 8. Arm live mode

User explicitly confirms. Wizard sets `armed: true` in config. Skill begins live ingestion.

To disarm at any time: edit config `armed: false` or delete config file.

## Service account setup (one-time, more detail)

If the wizard prompt isn't enough:

```
Project: <your-project>
Service account name: expense-bookkeeper
Roles: none (the sheet share grants edit; no project-level IAM needed)
Key type: JSON  → downloads <project>-<id>.json
Save as: ~/.expense-bookkeeper/google-service-account.json
```

Then back in the wizard:

```
Path to service account JSON: ~/.expense-bookkeeper/google-service-account.json
```

And in the user's Google Sheet:
```
Share → add email: <service-account-client-email> → Editor → Send
```

The service-account email looks like `expense-bookkeeper@<project>-<id>.iam.gserviceaccount.com`.
