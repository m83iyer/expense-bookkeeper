from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_directories_do_not_contain_documentation():
    assert not list((ROOT / "scripts").rglob("*.md"))


def test_dashboard_launchd_templates_use_the_scheduler_directory():
    names = {path.name for path in (ROOT / "templates" / "launchd").glob("*")}
    assert {"dashboard.plist.template", "dashboard-sync.plist.template"} <= names
    assert not list((ROOT / "templates").glob("*.plist.example"))


def test_readme_is_concise_and_local_links_resolve():
    readme = (ROOT / "README.md").read_text()
    assert len(readme.splitlines()) <= 150
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", readme)
    local_links = [link.split("#", 1)[0] for link in links if "://" not in link]
    assert local_links
    assert all((ROOT / link).exists() for link in local_links)


def test_documentation_local_links_resolve():
    failures = []
    files = [*ROOT.glob("*.md"), *(ROOT / "references").rglob("*.md")]
    for document in files:
        for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text()):
            target = link.split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            if not (document.parent / target).resolve().exists():
                failures.append(f"{document.relative_to(ROOT)}: {link}")
    assert failures == []
