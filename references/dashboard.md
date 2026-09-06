# Moneta dashboard

Moneta is a private analytical layer over the Expense Bookkeeper ledger.
Google Sheets remains the source of truth. `dashboard-sync` builds an atomic,
read-optimized SQLite mirror; the browser reads that mirror through a local
HTTP server.

## The four views

- **Overview** compares a selected period with either the preceding period or
  the same period last year. It shows exact values, a trend, allocation, and
  deterministic findings.
- **Drivers** reconciles the change from category to subcategory to merchant.
  Selecting a node reveals the confirmed transactions behind it.
- **Commitments** converts recurring items to monthly and annual equivalents.
  Only monthly items receive a next-payment date unless the source provides a
  precise future date; Moneta does not guess the month of annual charges.
- **Evidence** shows the ledger rows supporting the current filters and search.

Category, subcategory, and merchant use multi-choice slicers. Open the whole
control, choose one or several values, and apply the selection. `Select all`
returns to the complete scope; `Clear all` makes it quick to build a small
selection. Changing a parent scope clears incompatible child selections.

Comparisons fail closed. If one or more baseline months are absent from the
ledger, Moneta identifies the missing months and withholds the percentage.

## Privacy-safe demo

Build a deterministic demo without connecting Google:

```bash
python3 cli.py dashboard-demo --output ./demo-runtime
python3 cli.py dashboard-serve --config ./demo-runtime/config.demo.yaml
```

The page displays a `SYNTHETIC DEMO` badge. The generated database contains
fixed fictional spending, common global merchant names, and no credentials or
personal identifiers.

## Live operation

After setup and validation:

```bash
python3 cli.py dashboard-sync
python3 cli.py dashboard-serve
```

Open `http://127.0.0.1:8765` on the host computer. Run `dashboard-sync` after
an import or on a short schedule. The atomic database replacement prevents a
browser request from reading a half-built mirror.

For a phone on the same trusted Wi-Fi:

```bash
python3 cli.py dashboard-serve --host 0.0.0.0
```

Open `http://<computer-private-LAN-IP>:8765`. Do not port-forward the service
or expose it directly to the public internet. Use a private overlay network for
remote access.

## Five display currencies

The dashboard supports USD, INR, GBP, EUR, and AED. First refresh the local
reference-rate cache:

```bash
python3 cli.py dashboard-fx-refresh
```

The refresh sends only a base currency and four quote codes to the Frankfurter
API. No transaction, merchant, amount, Sheet ID, or user identifier is sent.
The browser never calls an exchange-rate service. It reads the validated local
snapshot and shows its date in the footer.

If the snapshot is missing, only the ledger currency is available. If a rate
is invalid, the API fails closed instead of displaying an unverified total.
This is display conversion only; normalize mixed-currency ledger rows before
syncing.

## Cash entry security

The public scaffold is read-only by default. To enable cash entry:

1. Set `dashboard.allow_cash_entry: true`.
2. Export a long random `EXPENSE_BOOKKEEPER_DASHBOARD_WRITE_TOKEN`.
3. Leave `allow_lan_writes: false` unless writes from a trusted phone are
   required.
4. Enter the token in the form when writing. The page does not persist it.

Unknown merchants follow the review path. The dashboard cannot invent a
category or bypass the categorization controls.

The cash form can optionally supply both an active category and subcategory.
The pair is validated against the canonical taxonomy and applies only to that
transaction; it does not create a merchant-wide rule. Leave both blank to use
the normal resolver and review loop.

## Files that must stay private

Keep these outside the repository:

- live `config.yaml`
- Google credentials and OAuth tokens
- Sheet IDs and URLs
- the SQLite mirror
- FX cache snapshots created for a live ledger
- logs, exports, and screenshots of real expenses

The generated demo is the only supported source for public screenshots.
