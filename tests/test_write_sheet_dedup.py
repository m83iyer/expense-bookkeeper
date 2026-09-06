import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import write_sheet
from write_sheet import HEADERS, append_rows, transaction_to_row


class Worksheet:
    def __init__(self, rows):
        self.rows = [list(row) for row in rows]
        self.appended = []

    def get_all_values(self):
        return [list(row) for row in self.rows]

    def append_rows(self, rows, value_input_option=None):
        self.appended.extend([list(row) for row in rows])


class Sheet:
    def __init__(self, worksheet):
        self._worksheet = worksheet

    def worksheet(self, name):
        assert name == "EXPENSES"
        return self._worksheet


def _row(hash_value):
    row = [""] * len(HEADERS)
    row[HEADERS.index("Txn_ID")] = "TXN" + hash_value.upper()
    row[HEADERS.index("Hash")] = hash_value
    return row


def _config():
    return {"sheet": {"id": "sheet-id", "service_account_path": "/private/config.json"}}


def test_duplicate_hash_is_not_appended(monkeypatch):
    ws = Worksheet([["banner"], HEADERS, _row("same-hash")])
    monkeypatch.setattr(write_sheet, "open_spreadsheet", lambda config: Sheet(ws))
    assert append_rows(_config(), [_row("same-hash")]) == 0
    assert ws.appended == []


def test_batch_deduplicates_against_sheet_and_itself(monkeypatch):
    ws = Worksheet([["banner"], HEADERS, _row("existing")])
    monkeypatch.setattr(write_sheet, "open_spreadsheet", lambda config: Sheet(ws))
    count = append_rows(
        _config(),
        [_row("existing"), _row("new"), _row("new"), _row("another")],
    )
    assert count == 2
    assert [row[HEADERS.index("Hash")] for row in ws.appended] == ["new", "another"]


def test_transaction_id_is_stable_when_hash_exists():
    row = transaction_to_row({"hash": "abc123", "amount": 1})
    assert row[HEADERS.index("Txn_ID")] == "TXNABC123"
