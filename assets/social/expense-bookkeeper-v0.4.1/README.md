# Expense Bookkeeper v0.4.1 evidence cards

These two portrait cards are exact synthetic-output receipts for the v0.4.1
evidence release, not generic product covers.

## Cards

1. `card-a-capture-review.png` shows the real pipeline result for the synthetic
   alert `AED 155.40 spent on ExampleCard at XYZ123 UNKNOWN on 19/04/2026`.
   The row is retained as `Misc / Other` with status `Review`.
2. `card-b-merchant-learning.png` shows `Corner Cafe` explicitly taught as
   `Dining / Cafe`, the next variant resolved, auto-promotion disabled,
   conflicts held for approval, and rollback proven.

Both cards are 1600 × 2000 PNGs using the `stockcentric-artifact-v1` design
system and the Expense Bookkeeper mint, teal, navy, coral, gold, and blue
identity.

## Reproducible build

The builder executes the pinned repository behavior against deterministic
synthetic inputs, writes `evidence.json`, generates committed SVG source, and
renders each PNG twice with `rsvg-convert` to prove repeatable local SHA output.

```bash
PYTHONPATH=scripts python3 \
  assets/social/expense-bookkeeper-v0.4.1/build_cards.py --render
```

Verify the committed images, source, dimensions, hashes, and current synthetic
behavior without rewriting them:

```bash
PYTHONPATH=scripts python3 \
  assets/social/expense-bookkeeper-v0.4.1/build_cards.py --check
```

`manifest.json` is the machine-readable integrity record. `ALT_TEXT.md`
contains the complete accessible descriptions, and `visual-qa.json` records
the full-size human inspection and its limitations. `validation.json` records
the clean-clone baseline, asset tests, full suite, and repeat-render check.

## Safety boundary

The build uses temporary state inside this card directory on the SSD. It does
not read or modify a live ledger, Google Sheet, credential, relay,
`~/.expense-tracker`, or `~/.expense-bookkeeper` state. All names and
transactions are synthetic.
