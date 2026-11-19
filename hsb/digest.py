"""The part Hermes actually needs every turn: a small, ranked context block.

This is the Hermes answer to CLAUDE.md / gbrain's "brain-first" block. A long
instruction file is read once and then forgotten by the next session; a digest
rebuilt from the files, capped at a character budget, is always current and
always the same size.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .index import Hit, search
from .store import Card, Vault, today

BULLET = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.*)$")
BULLET_MAX = 110


def _bullets(body: str, limit: int) -> list[str]:
    out: list[str] = []
    for line in body.splitlines():
        m = BULLET.match(line)
        if not m:
            continue
        text = m.group(1).strip()
        if not text or text.startswith("（"):
            continue
        if len(text) > BULLET_MAX:
            text = text[: BULLET_MAX - 1].rstrip() + "…"
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _decisions(card: Card, limit: int) -> list[str]:
    """Newest decision headings first, each with its first reason line.

    Order comes from the date in the heading, not from file position: some logs
    are appended, some are prepended, and the digest has to be right either way.
    """
    blocks: list[tuple[str, str, str]] = []
    head, reason = "", ""
    for line in card.body.splitlines():
        if line.startswith("## "):
            if head:
                blocks.append((_head_date(head), head, reason))
            head, reason = line[3:].strip(), ""
        elif head and line.strip() and not reason:
            reason = line.strip()
    if head:
        blocks.append((_head_date(head), head, reason))
    blocks.sort(key=lambda b: (b[0], b[1]), reverse=True)
    out = []
    for _d, head, reason in blocks[:limit]:
        out.append(f"{head} — {reason}" if reason else head)
    return out


def _head_date(head: str) -> str:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", head.strip())
    return m.group(1) if m else "0000-00-00"


@dataclass
class Rule:
    path: str
    text: str
    confidence: float
    applied: int
    violated: int

    def line(self) -> str:
        return f"{self.text} (信心 {self.confidence:.2f} · {self.applied}/{self.applied + self.violated} 次應驗)"


def active_rules(vault: Vault, limit: int = 6) -> list[Rule]:
    rules: list[Rule] = []
    for card in vault.cards("preferences"):
        if str(card.meta.get("status") or "active") != "active":
            continue
        text = str(card.meta.get("rule") or "").strip()
        if not text:
            first = next((ln.strip() for ln in card.body.splitlines() if ln.strip() and not ln.startswith("#")), "")
            text = first
        if not text:
            continue
        try:
            conf = float(card.meta.get("confidence") or 0.5)
        except (TypeError, ValueError):
            conf = 0.5
        rules.append(Rule(
            path=card.path,
            text=text,
            confidence=conf,
            applied=int(card.meta.get("applied") or 0),
            violated=int(card.meta.get("violated") or 0),
        ))
    rules.sort(key=lambda r: (-r.confidence, r.path))
    return rules[:limit]


def render(vault: Vault, message: str = "", budget: int | None = None) -> str:
    cfg = vault.config()
    budget = int(budget or cfg.get("digest_budget") or 1200)
    capsule = str(cfg.get("name") or "Second Brain")
    blocks: list[list[str]] = [[f"[{capsule}] 開工前先讀；答完要寫返。 ({vault.root})"]]

    identity = vault.card("identity.md")
    who = _bullets(identity.body, 3)
    if who:
        blocks.append(["你是誰：" + _clamp("；".join(who), 210)])

    now = _bullets(vault.card("now.md").body, 3)
    if now:
        blocks.append(["現在：" + _clamp(" | ".join(now), 190)])

    rules = active_rules(vault, 5)
    if rules:
        blocks.append(["規則："] + [f"- {r.line()}" for r in rules])

    decisions = _decisions(vault.card("decisions.md"), 3)
    if decisions:
        blocks.append(["最近決定："] + [f"- {d}" for d in decisions])

    if message.strip():
        hits: list[Hit] = search(_load_index(vault), message, limit=3)
        if hits:
            blocks.append(["命中筆記（先開檔再答）："] + [f"- {h.line()}" for h in hits])

    return _fit(blocks, budget)


def _clamp(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _load_index(vault: Vault):
    from .index import load

    return load(vault)


def _fit(blocks: list[list[str]], budget: int) -> str:
    """Keep whole blocks: a section header never appears without at least one item."""
    out: list[str] = []
    used = 0
    cut = False
    for block in blocks:
        header, items = block[0], block[1:]
        if not items:
            if used + len(header) + 1 > budget:
                cut = True
                break
            out.append(header)
            used += len(header) + 1
            continue
        if used + len(header) + 1 + len(items[0]) + 1 > budget:
            cut = True
            break
        out.append(header)
        used += len(header) + 1
        for item in items:
            if used + len(item) + 1 > budget:
                cut = True
                break
            out.append(item)
            used += len(item) + 1
        if cut:
            break
    if cut:
        out.append("…（其餘略）")
    text = "\n".join(out)
    return text if len(text) <= budget else text[: max(0, budget - 1)] + "…"


def write_active(vault: Vault, budget: int | None = None) -> str:
    text = render(vault, budget=budget)
    header = (
        f"---\ntitle: Active\ntype: generated\nupdated: {today()}\n---\n\n"
        "# 現行摘要（自動生成，勿手改）\n\n"
    )
    vault.write("active.md", header + text + "\n")
    return text
