import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from privacy_audit import scan_text, scan_tree


def test_detects_personal_path_email_phone_and_private_term():
    path = "/" + "Users" + "/alice/private"
    email = "alice" + "@" + "company.test"
    phone = "+971" + " 50 123 4567"
    term = "Project" + "Codename"
    text = f"{path}\n{email}\n{phone}\n{term}\n"
    kinds = {finding.kind for finding in scan_text(text, source="sample", private_terms=("ProjectCodename",))}
    assert {"absolute_user_path", "email", "phone_number", "private_term"}.issubset(kinds)


def test_allows_documented_placeholders():
    text = "/Users/you/project\nowner@example.com\napi_key: ${MY_API_KEY}\n"
    assert scan_text(text, source="sample") == []


def test_scans_tree_and_skips_local_control_metadata(tmp_path):
    (tmp_path / "safe.txt").write_text("owner@example.com", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("private-owner", encoding="utf-8")
    (tmp_path / ".ai").mkdir()
    private_path = "/" + "Users" + "/private/repository"
    (tmp_path / ".ai" / "coordination.json").write_text(
        f'{{"canonical_checkout":"{private_path}"}}', encoding="utf-8"
    )
    assert scan_tree(tmp_path) == []


def test_detects_secret_token_shape():
    token = "ghp_" + "a" * 30
    findings = scan_text(f"token={token}", source="sample")
    assert any(finding.kind == "api_token" for finding in findings)
