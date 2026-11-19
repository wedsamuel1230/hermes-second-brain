"""Health checks that a human can act on. Exit 1 only for errors."""

from __future__ import annotations

import os
import re

from .store import Vault, parse_frontmatter, today
from .text import wikilinks

REQUIRED = {"notes": ("title", "type")}
STALE_DAYS = 120


def check(vault: Vault) -> list[dict]:
    issues: list[dict] = []

    def add(level: str, code: str, detail: str, path: str = "") -> None:
        issues.append({"level": level, "code": code, "detail": detail, "path": path})

    titles: dict[str, str] = {}
    for rel, _m, _s in vault.md_files("."):
        if rel.startswith(("_meta/", "_archive/")):
            continue
        meta, body = parse_frontmatter(vault.read(rel))
        stem = os.path.basename(rel)[:-3].lower()
        if stem in titles:
            add("error", "duplicate-note", f"two files share the slug {stem}", rel)
        titles[stem] = rel
        if rel.startswith("notes/"):
            missing = [k for k in REQUIRED["notes"] if not meta.get(k)]
            if missing:
                add("error", "missing-frontmatter", "missing " + ", ".join(missing), rel)
        if rel.startswith("preferences/"):
            conf = meta.get("confidence")
            if not isinstance(conf, (int, float)):
                add("error", "rule-no-confidence", "rule without numeric confidence", rel)
            if not meta.get("evidence"):
                add("warn", "rule-no-evidence", "rule promoted with no evidence dates", rel)
        if not body.strip():
            add("warn", "empty-body", "frontmatter only", rel)

    # wikilinks resolve to a real file
    for rel, _m, _s in vault.md_files("."):
        if rel.startswith(("_meta/", "_archive/")):
            continue
        for target in wikilinks(vault.read(rel)):
            key = re.sub(r"[^\w\u3400-\u9fff-]+", "-", target.lower()).strip("-")
            if key and key not in titles and target.lower() not in titles:
                add("warn", "broken-wikilink", f"[[{target}]] has no page", rel)

    # orphan notes: nothing links to them and they link nowhere
    inbound: dict[str, int] = {k: 0 for k in titles}
    outbound: dict[str, int] = {k: 0 for k in titles}
    for rel, _m, _s in vault.md_files("."):
        if rel.startswith(("_meta/", "_archive/")):
            continue
        stem = os.path.basename(rel)[:-3].lower()
        links = wikilinks(vault.read(rel))
        outbound[stem] = len(links)
        for target in links:
            key = re.sub(r"[^\w\u3400-\u9fff-]+", "-", target.lower()).strip("-")
            if key in inbound:
                inbound[key] += 1
    for stem, rel in titles.items():
        if rel.startswith("notes/") and inbound.get(stem, 0) == 0 and outbound.get(stem, 0) == 0:
            add("warn", "orphan-note", "no inbound or outbound wikilinks", rel)

    inbox = vault.md_files("inbox")
    if len(inbox) > 20:
        add("warn", "inbox-backlog", f"{len(inbox)} signals waiting for a dream pass")
    return issues


def render(issues: list[dict]) -> str:
    if not issues:
        return "brain ok — no issues"
    order = {"error": 0, "warn": 1, "info": 2}
    issues = sorted(issues, key=lambda i: (order.get(i["level"], 9), i["code"], i["path"]))
    lines = [f"{len(issues)} issue(s) · {today()}"]
    for issue in issues:
        where = f" {issue['path']}" if issue["path"] else ""
        lines.append(f"[{issue['level']}] {issue['code']}:{where} {issue['detail']}")
    return "\n".join(lines)
