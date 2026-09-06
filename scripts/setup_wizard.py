#!/usr/bin/env python3
"""
setup_wizard.py — interactive end-to-end setup orchestrator.

Performs the actual setup chain (post-2026-05-01 audit upgrade — no longer
just a config writer):

  Phase 1 — Configure
    1. Choose mode: new / migrate / reconcile-only
    2. Connect Google service account (validates service-account JSON)
    3. Provision the ledger Sheet (creates if blank, validates if given)
    4. Set statements folder (creates if missing)
    5. Build taxonomy + categorization config
    6. Choose capture adapter
    7. Choose confirmation adapter
    8. Optional regional merchant pack
    9. Optional recurring-expense seed

  Phase 2 — Bootstrap from user's data
    10. Import statement CSVs → produce proposed merchant master
    11. Stop and ask the user to fill in Category/Subcategory in the master CSV
        (--resume-from-master picks back up here on second run)
    12. Push proposed master → MERCHANT_MASTER tab
    13. Apply regional pack rows on top of master (if selected)
    14. Seed CATEGORIES tab from inferred + user-confirmed taxonomy
    15. Seed RECURRING tab from example template (if user opted in)
    16. Generate adapter config snippet to ~/.expense-bookkeeper/adapters/

  Phase 3 — Validate + arm
    17. Run validate_install.py --strict
    18. Write setup completion report
    19. Arm live mode ONLY if all critical gates pass

Non-destructive: writes to the user's chosen folder; nothing inside the
skill package is modified. User supplies their own Google access, sheet,
statements, and optional adapter access. No live user data ships.
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

THIS = Path(__file__).resolve().parent
TEMPLATES = THIS.parent / "templates"

# Canonical top-level categories — used by INPUTS SUMIFS and DASHBOARD wiring.
# Order here determines row order in both tabs.
CANONICAL_CATEGORIES = [
    "Housing & Home", "Dining & Cafes", "Groceries & Household", "Utilities",
    "Subscriptions & Digital", "Shopping & Retail", "Gifts, Charity & Misc",
    "Personal Care", "Transport & Vehicle", "Health & Medical",
    "Financial & Transfers", "Children & Education",
    "Freelance & Professional", "Entertainment & Leisure",
]

# Row in INPUTS where the first category sits (banner=1, instructions=2,
# blank=3, section=4, month-row=5, blank=6, header=7 → data starts at 8)
_INPUTS_CAT_START_ROW = 8

LEDGER_TABS = {
    "EXPENSES": (
        "HOUSEHOLD EXPENSE TRACKER  |  EXPENSES LOG",
        ["Txn_ID", "Date", "Day", "Month-Year", "Amount", "Currency", "Txn_Type",
         "Category", "Subcategory", "Merchant_Raw", "Merchant_Clean",
         "Card_Used", "Source", "Person", "Notes", "Status", "Review_Reason", "Hash"],
    ),
    "MERCHANT_MASTER": (
        "MERCHANT MASTER  |  Keyword → Taxonomy mapping",
        ["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory",
         "Aliases", "Last_Updated"],
    ),
    "CATEGORIES": (
        "CATEGORIES  |  Top-level taxonomy",
        ["Category", "Subcategory", "Active", "Notes"],
    ),
    "REVIEW_QUEUE": (
        "REVIEW QUEUE  |  Optional workspace for adapter-specific review flows",
        ["Review_ID", "Date", "Amount", "Currency", "Merchant_Raw",
         "Suggested_Category", "Suggested_Subcategory", "Reason", "Status"],
    ),
    "RECONCILIATION": (
        "RECONCILIATION  |  Statement-vs-ledger diffs awaiting resolution",
        ["Run_ID", "Date", "Amount", "Currency", "Merchant_Raw", "Status", "Resolution"],
    ),
    "RECURRING": (
        "RECURRING  |  Fixed monthly entries written to EXPENSES automatically",
        ["Description", "Amount", "Currency", "Category", "Subcategory",
         "Cadence", "Day_of_Month", "Active", "Card_Used", "Person", "Last_Posted", "Notes"],
    ),
    "EXPENSES_TEST": (
        "EXPENSES TEST  |  Dry-run target",
        ["Txn_ID", "Date", "Day", "Month-Year", "Amount", "Currency", "Txn_Type",
         "Category", "Subcategory", "Merchant_Raw", "Merchant_Clean",
         "Card_Used", "Source", "Person", "Notes", "Status", "Review_Reason", "Hash"],
    ),
}


# ── Console UI ─────────────────────────────────────────────────────────────

def banner(s):
    print()
    print("─" * 64)
    print(s)
    print("─" * 64)


def ask(prompt, default=None):
    suffix = f" [{default}]" if default is not None else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val or (default or "")


def ask_choice(prompt, choices, default=None):
    """Accept either the choice number ('1', '2', ...) or the choice text
    (case-insensitive prefix match, so 'y'/'yes'/'YES' all match 'yes').
    On empty input, returns default if provided, else first choice.
    """
    print(prompt)
    for i, c in enumerate(choices, 1):
        marker = " (default)" if c == default else ""
        print(f"  {i}. {c}{marker}")
    raw = input("Choice [1]: ").strip()
    if not raw:
        return default or choices[0]
    # Try numeric first
    try:
        return choices[int(raw) - 1]
    except (ValueError, IndexError):
        pass
    # Try case-insensitive exact-match against choice text
    raw_lower = raw.lower()
    for c in choices:
        if c.lower() == raw_lower:
            return c
    # Try case-insensitive prefix match (handles 'y' for 'yes', 'no' for 'no (default)')
    matches = [c for c in choices if c.lower().startswith(raw_lower)]
    if len(matches) == 1:
        return matches[0]
    # Ambiguous or no match — fall back to default
    return default or choices[0]


def ask_yesno(prompt, default="yes"):
    return ask_choice(prompt, ["yes", "no"], default=default) == "yes"


# ── Phase 1 — Configure ───────────────────────────────────────────────────

def step1_mode():
    banner("Step 1 — What do you want to do?")
    return ask_choice("Mode:", [
        "Set up a new tracker",
        "Migrate from an existing tracker",
        "Reconciliation-only (statements without live capture)",
    ], default="Set up a new tracker")


def step2_google_access():
    """Validate the service-account JSON. Service account = backend writer
    (not a human; Google Drive will not show its sheets in your Drive UI)."""
    banner("Step 2 — Google service-account JSON (backend writer)")
    print("You need a Google Cloud service account with Sheets API access.")
    print("This is the BACKEND identity that writes to your sheet — it is NOT")
    print("you. Your sheet ownership stays with your Google account.")
    print("Setup guide: references/setup-flow.md § service-account-setup")
    sa_path = Path(ask("Path to service account JSON")).expanduser()
    if not sa_path.exists():
        print(f"❌ File not found: {sa_path}")
        sys.exit(1)
    try:
        d = json.loads(sa_path.read_text())
        if d.get("type") != "service_account":
            print(f"❌ Not a service account file (type={d.get('type')})")
            sys.exit(1)
        client_email = d["client_email"]
        print(f"✅ valid service account: {client_email}")
        print(f"   This email is the BACKEND writer. If you bring an existing sheet,")
        print(f"   share it with this email manually. For a freshly-provisioned sheet,")
        print(f"   the wizard will share it with YOUR Google email next.")
    except Exception as e:
        print(f"❌ Unreadable: {e}")
        sys.exit(1)
    return {"service_account_path": str(sa_path), "client_email": client_email}


def step2b_human_email():
    """Capture the human user's Google email for sheet ownership/visibility."""
    banner("Step 2b — Your Google email (for sheet visibility)")
    print("When the wizard provisions a fresh sheet, it shares the sheet with")
    print("YOUR Google email so the sheet appears in your Google Drive")
    print("and you can edit it directly. The backend service account keeps write")
    print("access for automation.")
    while True:
        email = ask("Your Google email").strip()
        if not email:
            print("  email is required so the sheet shows up in your Drive — please enter it")
            continue
        if "@" not in email or "." not in email.split("@", 1)[1]:
            print(f"  '{email}' doesn't look like a valid email — try again")
            continue
        return {"user_email": email}


def step3_sheet(sa_path: str, user_email: str, currency: str = "AED"):
    """Provision or connect the user's Google Sheet.

    Fresh provisioning shares the new sheet with `user_email` (the human),
    NOT the service account email. The service account already owns the
    sheet by virtue of being the creator; sharing with the human is what
    makes the sheet visible/editable from the human's Google Drive.

    `currency` is passed through to _provision_tabs so the INPUTS tab banner
    and column headers use the user's configured currency instead of a hardcoded value.
    """
    banner("Step 3 — Provision or connect Google Sheet")
    has_sheet = ask_yesno("Do you already have a Google Sheet you want to use?", default="no")
    if has_sheet:
        sheet_id = ask("Sheet ID (the long string in the URL)")
        if not sheet_id:
            print("❌ no sheet ID provided")
            sys.exit(1)
        sheet_id = sheet_id.split("/")[0]  # tolerate full URL
        try:
            gc = _make_gc(sa_path)
            sh = gc.open_by_key(sheet_id)
            added = _provision_tabs(sh, currency=currency)
            if added:
                print(f"  ✅ provisioned missing tabs: {', '.join(added)}")
            else:
                print("  ✅ all required tabs already present")
        except Exception as e:
            print(f"  ⚠️  could not reach sheet to provision tabs: {e}")
            print("  continuing — validation will catch any missing tabs")
        return {"id": sheet_id, "expenses_tab": "EXPENSES", "provisioned_now": False}
    # Create a fresh sheet, share with the HUMAN
    title = ask("Title for new sheet", default="My Expense Tracker")
    print(f"\nProvisioning fresh sheet…")
    try:
        sheet_id = _create_ledger(sa_path, title, share_with=user_email)
        print(f"✅ created: {title}  (id: {sheet_id})")
        print(f"   Shared with: {user_email}  (visible in your Drive shortly)")
        print(f"   URL: https://docs.google.com/spreadsheets/d/{sheet_id}/edit")
        return {"id": sheet_id, "expenses_tab": "EXPENSES", "provisioned_now": True}
    except Exception as e:
        msg = str(e)
        if _is_sa_quota_error(msg):
            print()
            print("❌ Fresh sheet creation failed: service-account Drive quota.")
            print("   Service accounts on free-tier GCP cannot own Drive files.")
            print()
            print("   Switching to 'bring your own sheet' mode:")
            print(f"   1. Create a blank sheet in your Google Drive.")
            print(f"   2. Share it with this SA as Editor: {_sa_email_from_path(sa_path)}")
            print(f"   3. Paste the sheet ID or URL below.")
            print()
            sheet_id = ask("Your sheet ID (from the URL)").strip()
            if not sheet_id:
                print("❌ no sheet ID provided — exiting")
                sys.exit(1)
            sheet_id = sheet_id.split("/")[0]
            try:
                gc = _make_gc(sa_path)
                sh = gc.open_by_key(sheet_id)
                added = _provision_tabs(sh, currency=currency)
                print(f"✅ sheet ready  (id: {sheet_id})")
                if added:
                    print(f"   provisioned tabs: {', '.join(added)}")
                print(f"   See references/setup-flow.md § service-account-quota for OAuth option.")
            except Exception as e2:
                print(f"❌ could not open/provision sheet: {e2}")
                print("   Make sure you shared it with the SA email above as Editor.")
                sys.exit(1)
            return {"id": sheet_id, "expenses_tab": "EXPENSES", "provisioned_now": True}
        print(f"❌ failed to create sheet: {e}")
        sys.exit(1)


def _is_sa_quota_error(msg: str) -> bool:
    """Detect Google's misleading 'storage quota exceeded' that actually means
    'service accounts cannot own Drive files on this account type'."""
    msg_lower = msg.lower()
    return (("storage quota" in msg_lower and "exceeded" in msg_lower)
            or "storagequotaexceeded" in msg_lower)


def _sa_email_from_path(sa_path: str) -> str:
    """Extract client_email from a service-account JSON for error messaging."""
    try:
        data = json.loads(Path(sa_path).expanduser().read_text())
        return data.get("client_email", "(unknown)")
    except Exception:
        return "(unknown)"


def step3b_locale():
    """Capture user's locale. No silent UAE defaults.

    Examples shown to the user but they must answer; UAE pack remains
    opt-in and only loaded if they pick it in step 8.
    """
    banner("Step 3b — Your locale")
    print("The skill is locale-agnostic. Pick what fits where you live + bank.")
    print("Examples — answer your own.")
    print("  Country code:    AE / GB / US / IN / SG / DE / AU …")
    print("  Timezone:        Asia/Dubai · Europe/London · America/New_York · Asia/Singapore · Asia/Kolkata")
    print("  Default currency: AED · GBP · USD · INR · SGD · EUR · AUD")
    print("  Date format:     %Y-%m-%d (ISO) · %d/%m/%Y (UK/EU) · %m/%d/%Y (US)")
    country = ask("Country code (ISO 2-letter)").upper().strip()
    if not country or len(country) != 2:
        print("  country code must be 2 letters (e.g. AE, GB, US, IN)")
        sys.exit(1)
    tz = ask("Timezone (IANA, e.g. Asia/Dubai)").strip()
    if not tz or "/" not in tz:
        print("  timezone must be in IANA format (e.g. Asia/Dubai, not 'GMT+4')")
        sys.exit(1)
    currency = ask("Default currency (3-letter ISO)").upper().strip()
    if not currency or len(currency) != 3:
        print("  currency must be 3 letters (e.g. AED, GBP, USD, INR)")
        sys.exit(1)
    primary_date_fmt = ask("Primary date format", default="%Y-%m-%d").strip() or "%Y-%m-%d"
    # Always allow ISO + the user's preferred format as parseable inputs
    formats = [primary_date_fmt]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        if fmt not in formats:
            formats.append(fmt)
    return {
        "country": country,
        "timezone": tz,
        "default_currency": currency,
        "date_formats": formats,
    }


def _make_gc(sa_path: str):
    import gspread
    from google.oauth2.service_account import Credentials
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(str(Path(sa_path).expanduser()), scopes=scopes)
    return gspread.authorize(creds)


def _provision_tabs(sh, currency: str = "AED") -> list[str]:
    """Add any missing canonical tabs to an existing sheet. Returns list of tab names added."""
    existing = {ws.title for ws in sh.worksheets()}
    added = []
    for tab_name, (banner_text, headers) in LEDGER_TABS.items():
        if tab_name not in existing:
            ws = sh.add_worksheet(title=tab_name, rows=2000, cols=max(len(headers), 18))
            ws.update(values=[[banner_text]], range_name="A1")
            ws.update(values=[headers], range_name="A2")
            added.append(tab_name)
    # Dashboard layer tabs
    for tab_name, writer_fn, rows, cols in [
        ("INPUTS",      lambda ws: _write_inputs_content(ws, currency), 100, 8),
        ("DASHBOARD",   _write_dashboard_content,    40,  8),
        ("COMMITMENTS", _write_commitments_content,  80, 12),
    ]:
        if tab_name not in existing:
            ws = sh.add_worksheet(title=tab_name, rows=rows, cols=cols)
            writer_fn(ws)
            added.append(tab_name)
    return added


def _write_inputs_content(ws, currency: str = "AED") -> None:
    """Provision INPUTS tab: budget controls + live SUMIFS against EXPENSES."""
    s = _INPUTS_CAT_START_ROW  # first category row (8)
    rows: list[list] = [
        ["INPUTS — HOUSEHOLD EXPENSE TRACKER"],                             # 1
        [f"Edit Budget {currency} cells only. Month Spend auto-updates from EXPENSES."],  # 2
        [],                                                                  # 3
        ["MONTH CONTROL"],                                                   # 4
        ["Current Month", '=TEXT(TODAY(),"mmm-yyyy")', "Auto-updates"],     # 5
        [],                                                                  # 6
        ["Category", f"Budget {currency}", "Month Spend", "Remaining", "Used %", "Notes"],  # 7
    ]
    for i, cat in enumerate(CANONICAL_CATEGORIES, start=s):
        rows.append([
            cat, "",
            f'=SUMIFS(EXPENSES!E:E,EXPENSES!D:D,$B$5,EXPENSES!G:G,"Expense",EXPENSES!H:H,A{i})',
            f"=B{i}-C{i}",
            f'=IFERROR(C{i}/B{i},"")',
            "Set your monthly budget above",
        ])
    end = s + len(CANONICAL_CATEGORIES)  # row after last category
    rows += [
        [],                                                                  # end
        ["FIXED RECURRING CASH"],                                            # end+1
        ["Item", f"Amount {currency}", "Cycle", "Treatment"],               # end+2
        ["", "", "Monthly", "Fixed cash"],                                  # end+3
        [],
        ["INCOME & SAVINGS"],
        ["Item", f"Amount {currency}", "Notes"],
        ["Salary", "", "Update when salary changes"],
        ["Other Income", "", ""],
        [f"Total Income", f"=SUM(B{end+8}:B{end+9})", "Auto-sum"],
        ["Savings Target", "", "Monthly target"],
    ]
    ws.update(values=rows, range_name="A1")


def _write_dashboard_content(ws) -> None:
    """Provision DASHBOARD tab: budget pressure map wired to INPUTS."""
    s = _INPUTS_CAT_START_ROW  # category start row in INPUTS
    # Dashboard category rows start at row 6
    d = 6
    rows: list[list] = [
        ["HOUSEHOLD SPEND CONTROL"],                                         # 1
        ["Month", '=INPUTS!B5', "", "Status", ""],                          # 2
        [],                                                                  # 3
        ["BUDGET PRESSURE MAP"],                                             # 4
        ["Category", "Budget", "Spend", "Usage", "Left", "State"],          # 5
    ]
    for i, cat in enumerate(CANONICAL_CATEGORIES):
        row_i = d + i
        inp_row = s + i
        rows.append([
            cat,
            f"=INPUTS!B{inp_row}",
            f"=INPUTS!C{inp_row}",
            f'=IFERROR(SPARKLINE(C{row_i}/B{row_i},{{"charttype","bar";"max",1;"color1","#1b6f5f"}}),"—")',
            f"=INPUTS!D{inp_row}",
            f'=IFERROR(IF(C{row_i}/B{row_i}<0.5,"ok",IF(C{row_i}/B{row_i}<0.8,"watch","over")),"—")',
        ])
    ws.update(values=rows, range_name="A1")


def _write_commitments_content(ws) -> None:
    """Provision COMMITMENTS tab: subscription + installment tracking shell."""
    rows: list[list] = [
        ["COMMITMENTS — SUBSCRIPTION & INSTALLMENT TRACKER"],
        [],
        ["SUBSCRIPTION PLANS"],
        ["Service", "Subcategory", "Auto-Renew", "Billing Cycle",
         "Charge Amount", "Monthly Eq", "Renewal", "Last Charge", "Status"],
        *[[""] * 9 for _ in range(10)],   # 10 empty rows for user to fill
        [],
        ["INSTALLMENT SCHEDULES"],
        ["Plan", "Category", "Subcategory", "Provider",
         "Installments", "Amount", "Estimated Total", "Status", "Notes"],
        *[[""] * 9 for _ in range(6)],
        [],
        ["IRREGULAR / ANNUAL CASHFLOW"],
        ["Item", "Budget Treatment", "Notes"],
        ["Annual subscriptions", "Monthly equivalent + due-month cash", ""],
        ["Car insurance / registration", "Due-month cash only", ""],
        ["Government / visa fees", "Due-month cash only", ""],
    ]
    ws.update(values=rows, range_name="A1")


def _create_ledger(sa_path: str, title: str, share_with: str | None = None) -> str:
    """Programmatic sheet creation — same logic as create_ledger.py but in-process."""
    gc = _make_gc(sa_path)
    sh = gc.create(title)
    first = list(LEDGER_TABS)[0]
    default_ws = sh.sheet1
    default_ws.update_title(first)
    banner_text, headers = LEDGER_TABS[first]
    default_ws.update(values=[[banner_text]], range_name="A1")
    default_ws.update(values=[headers], range_name="A2")
    for tab_name, (banner_text, headers) in list(LEDGER_TABS.items())[1:]:
        ws = sh.add_worksheet(title=tab_name, rows=2000, cols=max(len(headers), 18))
        ws.update(values=[[banner_text]], range_name="A1")
        ws.update(values=[headers], range_name="A2")

    if share_with:
        try:
            sh.share(share_with, perm_type="user", role="writer", notify=False)
        except Exception as e:
            print(f"  (warning: could not share with {share_with}: {e})")
    return sh.id


def step4_statements():
    banner("Step 4 — Statements folder")
    print("Drop CSV statements into a folder. Setup will parse them and seed")
    print("your MERCHANT_MASTER. PDF statements are recipe-only at v1 — convert")
    print("to CSV first (instructions in references/setup-flow.md § pdf-import).")
    default_visible = str(Path.home() / "Documents" / "expense-bookkeeper" / "statements")
    folder = ask("Statements folder", default=default_visible)
    p = Path(folder).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    csv_count = sum(1 for _ in p.glob("*.csv"))
    print(f"✅ folder ready: {p}  ({csv_count} CSV(s) found)")
    return {"path": str(p), "csv_count_at_setup": csv_count}


def step5_taxonomy():
    banner("Step 5 — Taxonomy + categorization rules")
    print("The deterministic resolver fails closed. Unknown merchants go to review.")
    print("Confirmed corrections teach the merchant map; prediction promotion stays off.")
    return {"confidence_threshold": 0.75, "fail_closed": True,
            "web_enrichment": "never", "web_enrichment_provider": "none",
            "adaptive": {
                "enabled": True,
                "state_path": "~/.expense-bookkeeper/state/adaptive_categories.json",
                "auto_promote_repeated": False,
                "minimum_observations": 3,
                "minimum_confidence": 0.90,
            }}


def step6_capture():
    banner("Step 6 — Capture adapter")
    phone = ask_choice("Phone:", ["iPhone", "Android", "Other / none"], default="iPhone")
    always_on = ask_choice("Do you have a machine that can stay on?",
                           ["Mac", "Windows", "Hosted (VPS)", "No"], default="Mac")
    bank_sms = ask_choice("Per-swipe SMS alerts from your banks?",
                          ["Yes — every bank", "Yes — some banks", "No"], default="Yes — some banks")
    bank_email = ask_choice("Per-swipe email alerts from your banks?",
                            ["Yes — every bank", "Yes — some banks", "No"], default="Yes — some banks")

    if phone == "iPhone" and always_on == "Mac":
        rec = "ios_mac_local"
    elif phone == "Android" and always_on in ("Mac", "Windows", "Hosted (VPS)"):
        rec = "android_tasker"
    elif bank_sms == "Yes — every bank":
        rec = "sms_parser"
    elif bank_email != "No":
        rec = "email_gmail"
    elif bank_sms != "No":
        rec = "sms_parser"
    else:
        rec = "manual_only"

    fallbacks: list[str] = []
    if rec != "sms_parser" and bank_sms != "No":
        fallbacks.append("sms_parser")
    if rec != "email_gmail" and bank_email != "No":
        fallbacks.append("email_gmail")

    print(f"\n  Primary recommendation: {rec}")
    print(f"  See references/adapters/{rec}.md for setup instructions.")
    if fallbacks:
        print(f"  Suggested fallback adapter(s): {', '.join(fallbacks)}")

    return {
        "adapter": rec, "fallback_adapters": fallbacks,
        "phone": phone, "always_on": always_on,
        "bank_sms": bank_sms, "bank_email": bank_email,
    }


def step7_confirmation():
    banner("Step 7 — Confirmation adapter")
    return {"adapter": ask_choice("Confirmation channel:",
        ["whatsapp_hermes", "telegram_bot", "email_confirm", "none"],
        default="telegram_bot")}


def step8_taxonomy_seed():
    banner("Step 8 — Regional merchant pack (optional)")
    pack = ask_choice(
        "Apply a regional merchant pack? (Adds known merchants to MERCHANT_MASTER. No personal data.)",
        ["None", "UAE", "Custom path"], default="None",
    )
    if pack == "None":
        return {"regional_pack": None}
    if pack == "Custom path":
        p = ask("Path to merchant pack CSV (Merchant_Keyword,Merchant_Clean,Category,Subcategory,Aliases)")
        return {"regional_pack": p or None}
    pack_path = TEMPLATES / "regional_packs" / "uae_merchants.csv"
    print(f"  Will import: {pack_path}")
    return {"regional_pack": str(pack_path)}


def step9_recurring():
    banner("Step 9 — Recurring expenses (optional)")
    seed = ask_yesno("Seed RECURRING from the example template now?", default="yes")
    if seed:
        seed_path = TEMPLATES / "recurring.example.csv"
        return {"seed_recurring": True, "seed_path": str(seed_path)}
    return {"seed_recurring": False, "seed_path": None}


# ── Phase 2 — Bootstrap ───────────────────────────────────────────────────

def _auto_categorize_from_pack(master_csv: Path, pack_path: str) -> int:
    """Pre-fill Category/Subcategory in proposed master from regional pack.
    Uses exact match first, then substring match. Returns count filled."""
    pack_p = Path(pack_path).expanduser()
    if not pack_p.exists():
        return 0

    pack_lookup: dict[str, tuple[str, str, str]] = {}
    with open(pack_p, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            kw = (row.get("Merchant_Keyword") or "").strip()
            cat = (row.get("Category") or "").strip()
            sub = (row.get("Subcategory") or "").strip()
            clean = (row.get("Merchant_Clean") or kw).strip()
            if kw and cat:
                pack_lookup[kw.lower()] = (cat, sub, clean)
    if not pack_lookup:
        return 0

    rows = []
    with open(master_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            rows.append(row)

    filled = 0
    for row in rows:
        if row.get("Category"):
            continue
        m_lower = (row.get("Merchant_Keyword") or "").strip().lower()
        if not m_lower:
            continue
        match = pack_lookup.get(m_lower)
        if not match:
            for kw, val in pack_lookup.items():
                if kw in m_lower or m_lower in kw:
                    match = val
                    break
        if match:
            row["Category"], row["Subcategory"], row["Merchant_Clean"] = match
            filled += 1

    with open(master_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return filled

def import_statements_proposed(folder: str, state_dir: Path) -> tuple[Path, int]:
    """Read CSV statements; produce proposed merchant master CSV.

    Returns (path_to_master_csv, unique_merchant_count).
    """
    folder_p = Path(folder).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)

    merchant_freq: Counter = Counter()
    merchant_amounts: dict[str, list[float]] = defaultdict(list)

    for f in folder_p.glob("*.csv"):
        try:
            with open(f, newline="", encoding="utf-8", errors="replace") as fh:
                rows = [r for r in csv.reader(fh) if any((c or "").strip() for c in r)]
        except Exception as e:
            print(f"  (warning: failed to read {f.name}: {e})")
            continue
        if not rows:
            continue
        header = rows[0]
        low = [c.lower() for c in header]
        i_m = next((i for i, c in enumerate(low) if "merchant" in c or "description" in c or "narrative" in c), None)
        i_a = next((i for i, c in enumerate(low) if "amount" in c or "debit" in c or "value" in c), None)
        if i_m is None:
            continue
        for r in rows[1:]:
            if len(r) <= i_m:
                continue
            m = (r[i_m] or "").strip()
            if not m:
                continue
            merchant_freq[m] += 1
            if i_a is not None and i_a < len(r):
                try:
                    merchant_amounts[m].append(float((r[i_a] or "").replace(",", "")))
                except ValueError:
                    pass

    out_master = state_dir / "merchant_master_proposed.csv"
    with open(out_master, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory", "Frequency", "Total_Amount"])
        for m, freq in merchant_freq.most_common():
            total = sum(merchant_amounts[m])
            w.writerow([m, m, "", "", freq, f"{total:.2f}"])
    return out_master, len(merchant_freq)


def push_master_to_sheet(cfg: dict, master_csv: Path, regional_pack: str | None) -> int:
    """Push proposed master + optional regional pack rows into MERCHANT_MASTER tab."""
    import gspread
    from google.oauth2.service_account import Credentials
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(
        str(Path(cfg["sheet"]["service_account_path"]).expanduser()), scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(cfg["sheet"]["id"])
    ws = sh.worksheet("MERCHANT_MASTER")

    # Read current to dedupe
    existing = ws.get_all_values()
    existing_keywords = set()
    if len(existing) > 2:
        # header is row 1 (banner=row 0, header=row 1, data from row 2)
        for r in existing[2:]:
            if r and r[0]:
                existing_keywords.add(r[0].strip().lower())

    new_rows: list[list[str]] = []
    today = datetime.now(timezone.utc).date().isoformat()

    # User's proposed master from imported statements (only rows where category is filled)
    if master_csv.exists():
        with open(master_csv, encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                kw = (row.get("Merchant_Keyword") or "").strip()
                cat = (row.get("Category") or "").strip()
                sub = (row.get("Subcategory") or "").strip()
                if not kw or not cat:
                    continue
                if kw.lower() in existing_keywords:
                    continue
                clean = (row.get("Merchant_Clean") or kw).strip()
                new_rows.append([kw, clean, cat, sub, "", today])
                existing_keywords.add(kw.lower())

    # Regional pack
    if regional_pack:
        pack_p = Path(regional_pack).expanduser()
        if pack_p.exists():
            with open(pack_p, encoding="utf-8") as f:
                r = csv.DictReader(f)
                for row in r:
                    kw = (row.get("Merchant_Keyword") or "").strip()
                    if not kw or kw.lower() in existing_keywords:
                        continue
                    new_rows.append([
                        kw,
                        (row.get("Merchant_Clean") or kw).strip(),
                        (row.get("Category") or "").strip(),
                        (row.get("Subcategory") or "").strip(),
                        (row.get("Aliases") or "").strip(),
                        today,
                    ])
                    existing_keywords.add(kw.lower())

    if new_rows:
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")
    return len(new_rows)


def seed_categories(cfg: dict) -> int:
    """Seed CATEGORIES tab from the categories present in MERCHANT_MASTER."""
    import gspread
    from google.oauth2.service_account import Credentials
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(
        str(Path(cfg["sheet"]["service_account_path"]).expanduser()), scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(cfg["sheet"]["id"])
    master = sh.worksheet("MERCHANT_MASTER")
    cats = sh.worksheet("CATEGORIES")

    existing = cats.get_all_values()
    have = set()
    if len(existing) > 2:
        for r in existing[2:]:
            if r and len(r) >= 2:
                have.add((r[0].strip(), r[1].strip()))

    master_rows = master.get_all_values()
    seen = []
    for r in master_rows[2:]:
        if len(r) < 4:
            continue
        cat = r[2].strip()
        sub = r[3].strip()
        if cat and (cat, sub) not in have:
            have.add((cat, sub))
            seen.append([cat, sub, "yes", "Seeded from MERCHANT_MASTER at setup"])

    if seen:
        cats.append_rows(seen, value_input_option="USER_ENTERED")
    return len(seen)


def seed_recurring(cfg: dict, seed_path: str) -> int:
    """Seed RECURRING tab from the example template."""
    if not seed_path or not Path(seed_path).expanduser().exists():
        return 0
    import gspread
    from google.oauth2.service_account import Credentials
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(
        str(Path(cfg["sheet"]["service_account_path"]).expanduser()), scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(cfg["sheet"]["id"])
    ws = sh.worksheet("RECURRING")

    existing = ws.get_all_values()
    if len(existing) > 2:
        # Already has data — don't double-seed
        return 0

    rows = []
    with open(Path(seed_path).expanduser(), encoding="utf-8") as f:
        r = csv.reader(f)
        header = next(r, None)
        for row in r:
            if any((c or "").strip() for c in row):
                rows.append(row)
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    return len(rows)


def write_adapter_snippet(state_dir: Path, capture: dict, confirmation: dict) -> Path:
    """Write a placeholder adapter config the user fills in per the recipe."""
    adapter_dir = state_dir / "adapters"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    snippet_path = adapter_dir / f"{capture['adapter']}.config.yaml"
    if not snippet_path.exists():
        snippet_path.write_text(
            f"# Adapter config — fill in per references/adapters/{capture['adapter']}.md\n"
            f"adapter: {capture['adapter']}\n"
            f"# Add your specifics below (paths, tokens, polling intervals, etc.)\n"
        )
    confirm_path = adapter_dir / f"{confirmation['adapter']}.config.yaml"
    if confirmation["adapter"] != "none" and not confirm_path.exists():
        confirm_path.write_text(
            f"# Confirmation adapter config — fill in per references/adapters/{confirmation['adapter']}.md\n"
            f"adapter: {confirmation['adapter']}\n"
            f"# Add your specifics below.\n"
        )
    return snippet_path


# ── Phase 3 — Validate + arm ──────────────────────────────────────────────

def run_validation(config_path: Path, strict: bool = True) -> dict:
    """Run validate_install.py --json and return parsed result."""
    cmd = [sys.executable, str(THIS / "validate_install.py"),
           "--config", str(config_path), "--json",
           "--strict" if strict else "--non-strict"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"exit_code": result.returncode, "raw_stdout": result.stdout, "stderr": result.stderr}


def write_setup_report(state_dir: Path, config: dict, validation: dict,
                       master_count: int, master_pushed: int,
                       cats_seeded: int, recurring_seeded: int,
                       proposed_master_path: Path | None) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    report = state_dir / "setup_report.md"
    armed = config.get("armed", False)
    armed_str = "✅ live mode armed" if armed else "❌ live mode NOT armed"
    lines = [
        f"# Expense Bookkeeper — setup completion report",
        "",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}Z",
        f"**Status:** {armed_str}",
        "",
        "## Configuration",
        f"- Mode: {config.get('mode')}",
        f"- Sheet ID: {config['sheet'].get('id', '(none)')}",
        f"- Service account: {config['sheet'].get('service_account_path', '(none)')}",
        f"- Statements folder: {config['statements'].get('path')}",
        f"- Capture adapter: {config['capture'].get('adapter')}",
        f"- Confirmation adapter: {config['confirmation'].get('adapter')}",
        f"- Categorization: confidence={config['categorization']['confidence_threshold']} "
        f"fail_closed={config['categorization']['fail_closed']} "
        f"web_enrichment={config['categorization']['web_enrichment']}",
        "",
        "## Bootstrap from your data",
        f"- Statement CSVs scanned in: {config['statements'].get('path')}",
        f"- Unique merchants found: {master_count}",
        f"- Proposed master CSV: {proposed_master_path or '(none)'}",
        f"- Master rows pushed to MERCHANT_MASTER tab: {master_pushed}",
        f"- Categories seeded into CATEGORIES tab: {cats_seeded}",
        f"- Recurring rows seeded into RECURRING tab: {recurring_seeded}",
        f"- Regional pack: {config['taxonomy_seed'].get('regional_pack') or '(none)'}",
        "",
        "## Validation (strict mode)",
        f"- Passed: {validation.get('passed', '?')}",
        f"- Failed: {validation.get('failed', '?')}",
        f"- Skipped: {validation.get('skipped', '?')}  (critical-skipped: {validation.get('skipped_critical', '?')})",
        f"- Ready for arm: {validation.get('ready_for_arm', False)}",
        "",
        "### Per-gate results",
    ]
    for r in validation.get("results", []):
        marker = "✅" if r["status"] == "pass" else ("⏭️ " if r["status"] == "skip" else "❌")
        crit = " [CRITICAL]" if r.get("critical") else ""
        lines.append(f"- {marker} **{r['gate']}**{crit} — {r['message']}")

    lines += [
        "",
        "## Next steps",
        f"- Open your sheet: https://docs.google.com/spreadsheets/d/{config['sheet'].get('id')}/edit",
        f"- Fill any gaps in MERCHANT_MASTER (rows where Category is blank).",
        f"- Wire your capture adapter per references/adapters/{config['capture']['adapter']}.md",
        f"- Run `python3 scripts/setup_wizard.py --resume-from-master <path>` if you edit the proposed master CSV first.",
        f"- To arm later: edit `armed: true` in config.yaml after validation reports `ready_for_arm: true`.",
    ]
    report.write_text("\n".join(lines))
    return report


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.expanduser("~/.expense-bookkeeper"),
                    help="Output folder for config + state (default: ~/.expense-bookkeeper)")
    ap.add_argument("--resume-from-master", metavar="PATH",
                    help="Resume setup using a previously-generated proposed master CSV "
                         "(after the user has filled in Category/Subcategory). Skips Phase 1 "
                         "questions where possible (reads existing config.yaml).")
    ap.add_argument("--non-strict", dest="strict", action="store_false", default=True,
                    help="Run validation in non-strict mode (skips on critical gates allowed). "
                         "Live arm is only possible in strict mode.")
    args = ap.parse_args()

    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    state_dir = out / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    config_path = out / "config.yaml"
    import yaml

    # ── Resume path ────────────────────────────────────────────────────
    if args.resume_from_master:
        master_path = Path(args.resume_from_master).expanduser()
        if not master_path.exists():
            print(f"❌ master CSV not found: {master_path}")
            sys.exit(1)
        if not config_path.exists():
            print(f"❌ no config at {config_path} — run a fresh `setup_wizard.py` first to create one.")
            sys.exit(1)
        config = yaml.safe_load(open(config_path))
        print(f"Resuming from {master_path}")
        print(f"Pushing user-confirmed master → MERCHANT_MASTER tab…")
        try:
            pushed = push_master_to_sheet(config, master_path,
                                          config.get("taxonomy_seed", {}).get("regional_pack"))
            cats = seed_categories(config)
        except Exception as e:
            print(f"❌ resume failed: {e}")
            sys.exit(1)
        print(f"✅ pushed {pushed} merchant rows · seeded {cats} categories")

        validation = run_validation(config_path, strict=args.strict)
        report = write_setup_report(state_dir, config, validation,
                                    master_count=0, master_pushed=pushed,
                                    cats_seeded=cats, recurring_seeded=0,
                                    proposed_master_path=master_path)
        print(f"Report: {report}")
        if validation.get("ready_for_arm"):
            if ask_yesno("Arm live mode now?", default="no"):
                config["armed"] = True
                config["armed_at"] = datetime.now(timezone.utc).isoformat() + "Z"
                with open(config_path, "w") as f:
                    yaml.safe_dump(config, f, sort_keys=False)
                print("✅ Armed.")
        sys.exit(0)

    # ── Fresh setup ────────────────────────────────────────────────────
    print(f"Setup will write config + state to: {out}")

    mode = step1_mode()
    creds = step2_google_access()
    user = step2b_human_email()
    locale = step3b_locale()
    sheet = step3_sheet(creds["service_account_path"], user["user_email"],
                        currency=locale.get("default_currency", "AED"))
    sheet["service_account_path"] = creds["service_account_path"]
    sheet["service_account_email"] = creds["client_email"]
    sheet["user_email"] = user["user_email"]
    statements = step4_statements()
    taxonomy = step5_taxonomy()
    capture = step6_capture()
    confirmation = step7_confirmation()
    taxonomy_seed = step8_taxonomy_seed()
    recurring = step9_recurring()

    config = {
        "mode": mode,
        "armed": False,
        "locale": locale,
        "user": user,
        "sheet": sheet,
        "statements": statements,
        "categorization": taxonomy,
        "capture": capture,
        "confirmation": confirmation,
        "taxonomy_seed": taxonomy_seed,
        "recurring": recurring,
        "metadata": {
            "skill": "expense-bookkeeper",
            "version": "0.4.1",
            "setup_at": datetime.now(timezone.utc).isoformat() + "Z",
            "state_dir": str(state_dir),
        },
    }
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)
    print(f"\n✅ config written: {config_path}")

    # Phase 2 — Bootstrap
    banner("Phase 2 — Bootstrap from your data")
    print("Importing statement CSVs…")
    proposed_master_path, master_count = import_statements_proposed(statements["path"], state_dir)
    print(f"  Found {master_count} unique merchants → {proposed_master_path}")

    if master_count > 0 and taxonomy_seed.get("regional_pack"):
        auto_filled = _auto_categorize_from_pack(proposed_master_path, taxonomy_seed["regional_pack"])
        if auto_filled:
            print(f"  Auto-categorized {auto_filled}/{master_count} merchants from regional pack")
            remaining = master_count - auto_filled
            print(f"  {remaining} merchants still need manual Category + Subcategory")
        else:
            print(f"  No auto-matches from regional pack — all {master_count} need manual review")

    if master_count > 0:
        print()
        print("⚠️  Open the proposed master CSV and fill in Category + Subcategory for remaining merchants.")
        print(f"   File: {proposed_master_path}")
        print(f"   Then resume setup with:")
        print(f"     python3 {THIS}/setup_wizard.py --resume-from-master {proposed_master_path}")
        print()
        proceed_now = ask_yesno("Skip the manual fill and apply only the regional pack now?", default="no")
        if not proceed_now:
            print("Setup paused. Resume after editing the master CSV.")
            sys.exit(0)

    print("Pushing master + regional pack to sheet…")
    pushed = push_master_to_sheet(config, proposed_master_path, taxonomy_seed.get("regional_pack"))
    print(f"  ✅ pushed {pushed} master rows")

    print("Seeding CATEGORIES tab…")
    cats_seeded = seed_categories(config)
    print(f"  ✅ {cats_seeded} categories seeded")

    recurring_seeded = 0
    if recurring.get("seed_recurring"):
        print("Seeding RECURRING tab…")
        recurring_seeded = seed_recurring(config, recurring["seed_path"])
        print(f"  ✅ {recurring_seeded} recurring rows seeded")

    print("Writing adapter config snippet…")
    snippet = write_adapter_snippet(state_dir, capture, confirmation)
    print(f"  ✅ {snippet}")
    print(f"     Edit per references/adapters/{capture['adapter']}.md")

    # Phase 3 — Validate + arm
    banner("Phase 3 — Validate + arm")
    validation = run_validation(config_path, strict=args.strict)
    if validation.get("ready_for_arm"):
        print(f"✅ all critical gates pass — eligible for arm")
    else:
        print(f"❌ validation incomplete — {validation.get('failed', '?')} failed, "
              f"{validation.get('skipped_critical', '?')} critical-skipped")
        print(f"   Live arm not possible until all critical gates pass.")

    report = write_setup_report(state_dir, config, validation,
                                master_count=master_count, master_pushed=pushed,
                                cats_seeded=cats_seeded, recurring_seeded=recurring_seeded,
                                proposed_master_path=proposed_master_path)
    print(f"\nSetup report: {report}")

    if validation.get("ready_for_arm"):
        if ask_yesno("Arm live mode now?", default="no"):
            config["armed"] = True
            config["armed_at"] = datetime.now(timezone.utc).isoformat() + "Z"
            with open(config_path, "w") as f:
                yaml.safe_dump(config, f, sort_keys=False)
            print(f"✅ Armed. Live mode enabled. Disable any time by editing {config_path}.")

    print("\nDone.")


if __name__ == "__main__":
    main()
