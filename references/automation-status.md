# Automation status

This page describes the public package for a new user. It does not use evidence, paths, credentials, account details, or transaction counts from a private tracker.

The Python core can run without an LLM after setup. Each user still supplies Google access, OS permissions, adapter authentication, source-specific filters, and scheduler entries.

| Lane | Trigger | Public status |
|---|---|---|
| Google Sheet write | Parsed event | Verified with strict write, read, and delete gate |
| Recurring expenses | Local schedule | Verified script; user installs the schedule |
| CSV reconciliation | User-owned CSV | Verified; gap acceptance needs review |
| iPhone to Mac notification capture | Mirrored bank alert | Reference setup; depends on macOS permissions and bank behavior |
| Android webhook capture | Tasker or similar | Beta recipe |
| Gmail bank alerts | Gmail poller | Fallback; needs user OAuth and bank filters |
| Gmail statement attachment intake | Gmail poller | Publish candidate; bank formats differ |
| WhatsApp confirmations through Hermes | Logged transaction or correction reply | Optional reference adapter; user owns Hermes and the target |
| Adaptive merchant learning | Confirmed correction | Verified local state, audit, proposal, and rollback path |
| Merchant master + taxonomy integrity | Every capture and strict validation | Verified; invalid or inactive pairs fail closed |
| Duplicate hash protection | Every live append | Verified against Sheet history and the incoming batch |
| Dashboard mirror | Local schedule or post-import hook | Verified atomic SQLite rebuild |
| Dashboard UI | Local HTTP service | Included; loopback by default, private-LAN binding is opt-in |

## Runs unattended after setup

- Capture adapters that the user has wired, authenticated, scheduled, and validated.
- Parsing, Sheet-backed merchant resolution, hash deduplication, Sheet writes, recurring entries, and local health reports.
- Dashboard synchronization and serving when the user installs the supplied service-manager templates.
- WhatsApp confirmations when the user enables Hermes and supplies a target.

## Needs user review

- Unknown merchants and low-confidence categories.
- Merchant-research proposals from an optional Hermes or agent extension.
- Statement gaps before the tracker adds or ignores them.
- Merchant mapping conflicts.
- Taxonomy rename, split, or merge proposals.
- OS permission and account authorization changes.

## Publish boundary

Public claims may state that the architecture supports unattended operation after adapter setup, the iPhone and Mac lane is the reference capture path, and CSV reconciliation has tests.

Do not claim universal bank alert support, automatic PDF parsing, inherited Gmail access, bundled WhatsApp targets, or silent statement-gap acceptance.

## Release proof

1. Run the full tests.
2. Run strict validation on a user-owned test install.
3. Test each configured adapter in dry-run and live test mode.
4. Confirm the scheduler entry on the user's machine.
5. Run a CSV reconciliation dry-run.
6. Run `scripts/privacy_audit.py` on the release tree and Git history with private project terms supplied through `--private-term`.
