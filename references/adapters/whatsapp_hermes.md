# WhatsApp through Hermes

**Status:** Reference adapter  
**Layer:** Optional confirmation and correction relay

The Python tracker writes the ledger first. Hermes sends a confirmation after that write and can hand a supported reply back to the local correction queue. A Hermes outage does not block expense capture.

For an unknown merchant, the tracker writes `Status=Review` and Hermes labels the message `Expense needs review`. It does not describe the fallback `Misc / Other` pair as confirmed.

## Prerequisites

- A working expense-bookkeeper install that passes strict validation without WhatsApp.
- Hermes installed on the user's machine.
- WhatsApp connected through the user's Hermes setup.
- A user-owned target supplied through `EXPENSE_BOOKKEEPER_HERMES_TARGET`.

## Configuration

```yaml
confirmation:
  adapter: whatsapp_hermes
  confirmations: terse

hermes:
  target_env: EXPENSE_BOOKKEEPER_HERMES_TARGET
  include_merchant: false
  state_dir: ~/.expense-bookkeeper/state/hermes
```

Set the target outside the repository:

```bash
export EXPENSE_BOOKKEEPER_HERMES_TARGET='whatsapp'
```

Hermes also accepts a target such as `whatsapp:<chat-id>` when the local install needs one. Do not commit that value.

## Test outbound delivery

Create a local event file outside the repository:

```json
{
  "event_id": "test-001",
  "amount": "12.50",
  "currency": "USD",
  "merchant": "Example Cafe",
  "category": "Dining",
  "subcategory": "Cafe"
}
```

Run a dry test:

```bash
python3 scripts/adapters/hermes_whatsapp.py send /path/to/event.json \
  --target "$EXPENSE_BOOKKEEPER_HERMES_TARGET" --dry-run
```

Remove `--dry-run` after you inspect the message. The adapter stores sent event IDs in `~/.expense-bookkeeper/state/hermes/delivery_state.json` and will not send the same event twice.

## Inbound corrections

Route the WhatsApp reply from the user's Hermes workflow into:

```bash
python3 scripts/adapters/hermes_whatsapp.py receive \
  "change to Groceries / Supermarket" --txn-id TXN_ID
```

The adapter accepts two command shapes:

- `change to Category / Subcategory` for one transaction. This needs a transaction ID.
- `change Merchant to Category / Subcategory` for a merchant-wide correction. The queued command requires bulk confirmation.

It appends validated commands to `~/.expense-bookkeeper/state/hermes/inbound_commands.jsonl`. The local correction worker can process that queue with `scripts/correction_handler.py`. Arbitrary messages do not enter the queue.

## Failure handling

- `disabled`: no user target exists.
- `duplicate`: the event ID has been sent.
- `deferred`: Hermes could not deliver. The ledger row remains committed.
- `sent`: Hermes accepted the message.

Keep category logic and Sheet credentials in the Python tracker. Hermes handles message transport only.

## Optional merchant research skill

A user may teach Hermes a private skill that searches a new merchant and proposes a category and subcategory. Keep that skill behind the review boundary:

1. Give it the merchant name and the active pairs from `CATEGORIES`. Do not send the amount, card, Sheet ID, or transaction history.
2. Ask it for a proposal and a short evidence note.
3. Show the proposal to the user.
4. Send the confirmed correction through the supported command shape.

`correction_handler.py` validates the pair, updates the expense row and `MERCHANT_MASTER`, and writes the audit record. The research skill has no Sheet credentials and cannot approve its own proposal.
