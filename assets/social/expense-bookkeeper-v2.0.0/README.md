# Moneta 2.0 launch gallery

These four 1600 x 900 images are real Chromium captures of the deterministic
synthetic demo. Together they answer the four questions the dashboard is built
around: what changed, what caused it, what is already committed, and which
ledger rows support the result.

No live ledger, credential, Sheet ID, message target, email address, phone
number, or personal expense was used. Familiar merchant names and the displayed
USD, AED, EUR, and GBP amounts belong to the synthetic demo. INR remains
available in the dashboard's five-currency toggle.

The broader Drivers capture was deliberately excluded from the launch set after
human review found inconsistent headline framing in headless Chromium. Passing
automation did not override that visual rejection.

Rebuild the complete browser proof with:

```bash
python3 scripts/capture_moneta_demo.py --output ./moneta-proof/screenshots
```

See [alt text](ALT_TEXT.md), [manifest](manifest.json), [evidence](evidence.json),
and [visual QA](visual-qa.json).
