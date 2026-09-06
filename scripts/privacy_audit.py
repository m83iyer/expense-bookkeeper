#!/usr/bin/env python3
"""Release-time privacy and secret scanner for the public repository."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


EXCLUDED_DIRS = {
    ".ai", ".codebase-memory", ".git", ".pytest_cache", "__pycache__",
    ".venv", "venv", "node_modules",
}
EXCLUDED_SUFFIXES = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".sqlite", ".db"}
DEFAULT_PRIVATE_TERMS: tuple[str, ...] = ()
PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "api_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})\b"),
    "google_sheet_url": re.compile(r"https://docs\.google\.com/spreadsheets/d/[A-Za-z0-9_-]{20,}"),
    "absolute_user_path": re.compile(r"/Users/(?!you\b|example\b)[A-Za-z0-9._-]+/"),
    "phone_number": re.compile(r"(?<!\w)\+[1-9](?:[\s()-]*\d){7,14}(?!\w)"),
    "email": re.compile(r"\b[A-Z0-9._%+-]+@(?!example\.(?:com|org|net)\b)[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "credential_assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password|client[_-]?secret)\s*[:=]\s*[\"'](?!\s*(?:\$\{|<|your[-_ ]|example|none|null|false|true))[A-Za-z0-9_./+=-]{12,}[\"']"
    ),
}


@dataclass(frozen=True)
class Finding:
    source: str
    line: int
    kind: str
    excerpt: str


def _redact_excerpt(text: str) -> str:
    text = text.strip()
    if len(text) > 160:
        text = text[:157] + "..."
    return text


def _mask_match(line: str, start: int, end: int, label: str = "redacted") -> str:
    return _redact_excerpt(line[:start] + f"<{label}>" + line[end:])


def scan_text(text: str, *, source: str, private_terms: Iterable[str] = DEFAULT_PRIVATE_TERMS) -> list[Finding]:
    findings: list[Finding] = []
    terms = tuple(term.lower() for term in private_terms if term.strip())
    for number, line in enumerate(text.splitlines(), start=1):
        scan_line = line[1:] if source == "git-history" and line[:1] in {"+", "-"} else line
        lower = scan_line.lower()
        for term in terms:
            start = lower.find(term)
            if start >= 0:
                findings.append(Finding(source, number, "private_term",
                                        _mask_match(scan_line, start, start + len(term), "private-term")))
                break
        for kind, pattern in PATTERNS.items():
            match = pattern.search(scan_line)
            if match:
                findings.append(Finding(source, number, kind,
                                        _mask_match(scan_line, match.start(), match.end())))
    return findings


def iter_text_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES or path.name == "privacy-audit-report.json":
            continue
        try:
            chunk = path.read_bytes()[:4096]
        except OSError:
            continue
        if b"\x00" in chunk:
            continue
        yield path


def scan_tree(root: str | Path, *, private_terms: Iterable[str] = DEFAULT_PRIVATE_TERMS) -> list[Finding]:
    root = Path(root).resolve()
    findings: list[Finding] = []
    for path in iter_text_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        findings.extend(scan_text(text, source=str(path.relative_to(root)), private_terms=private_terms))
    return findings


def scan_git_history(root: str | Path, *, private_terms: Iterable[str] = DEFAULT_PRIVATE_TERMS,
                     revision: str = "HEAD") -> list[Finding]:
    """Scan reachable history for high-risk values without checking out commits."""
    root = Path(root).resolve()
    command = ["git", "log", revision, "-p", "--no-ext-diff", "--no-color", "--format=commit:%H"]
    completed = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        return [Finding("git-history", 0, "history_scan_error", "Unable to scan Git history")]
    return scan_text(completed.stdout, source="git-history", private_terms=private_terms)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan a release tree for personal data and secrets")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--private-term", action="append", default=[])
    parser.add_argument("--history", action="store_true", help="Also scan reachable Git history")
    parser.add_argument("--history-ref", default="HEAD", help="Git revision to scan (default: HEAD)")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()
    terms = tuple(DEFAULT_PRIVATE_TERMS) + tuple(args.private_term)
    findings = scan_tree(args.root, private_terms=terms)
    if args.history:
        findings.extend(scan_git_history(args.root, private_terms=terms, revision=args.history_ref))
    report = {"ok": not findings, "finding_count": len(findings),
              "findings": [asdict(item) for item in findings]}
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.json_out:
        Path(args.json_out).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
