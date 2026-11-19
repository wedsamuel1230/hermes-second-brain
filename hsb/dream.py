"""The dream pass: deterministic consolidation, no model in the loop.

Behaviour is copied from what works in the wild (open-second-brain's nightly
pass, Zep's invalidation-not-overwrite rule, MemoryBank's decay) and from what
fails: letting a small model decide what to delete.

Rules of this pass:

* A signal is one line the agent captured during work: a correction, a stated
  preference, a decision or a fact.
* Repeated signals become a *rule*. Promotion is by measured similarity plus
  support count, both deterministic, so the same vault always yields the same
  rules and the report can be re-derived.
* Confidence is a Beta posterior: ``(1 + support + applied) / (2 + support +
  applied + violated)``, where ``support`` counts independent promoting signals
  (repeat on one day counts once per occurrence). Two independent signals
  already beat coin-flip; real reminders raise it; each violation drags it down.
* A rule below ``retire_below`` (0.45 — it now fails nearly as often as it
  holds) is archived, never deleted. Old rules decay instead of silently
  winning forever.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime

from . import digest
from .store import Card, Vault, slugify, today, now_iso
from .text import normalize, similarity, slugify_key

KINDS = ("correction", "preference", "decision", "fact")
SIGNAL_TTL_DAYS = 30

# "唔該" is politeness, not negation — strip those before looking for a negator.
NEGATION_PHRASES = ("唔該", "唔好意思", "唔緊要")
NEGATION = ("唔", "不", "冇", "勿", "別", "别", "無", "无", "沒", "没", "未", "非",
            "don't", "dont", "do not", "not", "never", "without")

NUM = re.compile(r"\d+(?:\.\d+)?")


def has_negation(text: str) -> bool:
    flat = normalize(text)
    for phrase in NEGATION_PHRASES:
        flat = flat.replace(phrase, "")
    return any(token in flat for token in NEGATION)


def numeric_conflict(a: str, b: str) -> bool:
    """'每頁 3 個重點' and '每頁 5 個重點' are different values, not repeats."""
    na = set(NUM.findall(normalize(a)))
    nb = set(NUM.findall(normalize(b)))
    return bool(na and nb and na != nb)


def strip_negation(text: str) -> str:
    flat = normalize(text)
    for phrase in NEGATION_PHRASES:
        flat = flat.replace(phrase, "")
    for token in NEGATION:
        flat = flat.replace(token, "")
    return flat


def _dice(a: str, b: str) -> float:
    """Character-bigram-free overlap. Chinese inserts a negator mid-word, so the
    term tokeniser is too coarse to compare '回覆加emoji' with '回覆唔好加emoji'."""
    if not a or not b:
        return 0.0
    common = sum((Counter(a) & Counter(b)).values())
    return 2 * common / (len(a) + len(b))


def polarity_conflict(a: str, b: str) -> bool:
    """Same statement, opposite polarity or a different value: never a repeat."""
    if numeric_conflict(a, b):
        return True
    if has_negation(a) == has_negation(b):
        return False
    return _dice(strip_negation(a), strip_negation(b)) >= 0.6


@dataclass
class Signal:
    path: str
    kind: str
    text: str
    key: str = ""
    source: str = ""
    created: str = ""
    card: Card | None = None


@dataclass
class Cluster:
    rep: str
    key: str
    members: list[Signal] = field(default_factory=list)
    rule_path: str = ""
    conflicted: bool = False

    @property
    def support(self) -> int:
        """Independent occurrences: an identical signal on the same day counts once."""
        return len({(m.created[:10] or "", normalize(m.text)) for m in self.members})


@dataclass
class Report:
    date: str
    signals: int = 0
    rules_before: int = 0
    rules_after: int = 0
    promoted: list[dict] = field(default_factory=list)
    reinforced: list[dict] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)
    decayed: list[str] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    archived_signals: int = 0
    expired_signals: int = 0
    docs: int = 0
    dry_run: bool = False

    def as_dict(self) -> dict:
        return {
            "date": self.date,
            "signals": self.signals,
            "rules_before": self.rules_before,
            "rules_after": self.rules_after,
            "promoted": self.promoted,
            "reinforced": self.reinforced,
            "retired": self.retired,
            "decayed": self.decayed,
            "conflicts": self.conflicts,
            "archived_signals": self.archived_signals,
            "expired_signals": self.expired_signals,
            "docs": self.docs,
            "dry_run": self.dry_run,
        }

    def render(self) -> str:
        rows = [
            f"| 訊號讀取 | {self.signals} |",
            f"| 規則（之前 → 之後） | {self.rules_before} → {self.rules_after} |",
            f"| 新規則 | {len(self.promoted)} |",
            f"| 加固 | {len(self.reinforced)} |",
            f"| 退役 | {len(self.retired)} |",
            f"| 衰減 | {len(self.decayed)} |",
            f"| 矛盾（未自動升做規則） | {len(self.conflicts)} |",
            f"| 封存訊號 | {self.archived_signals} |",
            f"| 過期訊號 | {self.expired_signals} |",
            f"| 索引文件 | {self.docs} |",
        ]
        body = "\n".join(rows)
        detail = []
        for item in self.promoted:
            detail.append(f"- 新增 `{item['id']}`：{item['rule']}（支持 {item['support']}，信心 {item['confidence']:.2f}）")
        for item in self.reinforced:
            detail.append(f"- 加固 `{item['id']}`：信心 {item['confidence']:.2f}（證據 {item['evidence']}）")
        for r in self.retired:
            detail.append(f"- 退役 `{r}`（信心低於門檻，已移入 `_archive/`）")
        for d in self.decayed:
            detail.append(f"- 衰減 `{d}`（長期未被引用）")
        for c in self.conflicts:
            texts = " / ".join(c.get("texts") or [])
            detail.append(f"- 矛盾 `{c.get('key')}`：{texts} —— 需要人決定，已留在 inbox")
        return "# Dream report — {d}\n\n| 項目 | 數值 |\n|---|---|\n{b}\n".format(
            d=self.date, b=body) + ("\n" + "\n".join(detail) + "\n" if detail else "")


# ----------------------------------------------------------------- read side
def _signals(vault: Vault) -> list[Signal]:
    out: list[Signal] = []
    for card in vault.cards("inbox"):
        kind = str(card.meta.get("kind") or "correction")
        if kind not in KINDS:
            kind = "correction"
        text = str(card.meta.get("text") or "").strip()
        if not text:
            text = next((ln.strip() for ln in card.body.splitlines() if ln.strip() and not ln.startswith("#")), "")
        if not text:
            continue
        out.append(Signal(
            path=card.path,
            kind=kind,
            text=text,
            key=str(card.meta.get("key") or ""),
            source=str(card.meta.get("source") or ""),
            created=str(card.meta.get("created") or ""),
            card=card,
        ))
    out.sort(key=lambda s: (s.created, s.path))
    return out


def _rules(vault: Vault) -> list[Card]:
    return [c for c in vault.cards("preferences") if str(c.meta.get("status") or "active") == "active"]


def _cluster(signals: list[Signal], rules: list[Card], threshold: float) -> list[Cluster]:
    by_key: dict[str, Cluster] = {}
    clusters: list[Cluster] = []
    for rule in rules:
        key = str(rule.meta.get("key") or rule.meta.get("id") or rule.path)
        cluster = Cluster(rep=str(rule.meta.get("rule") or rule.title), key=key, rule_path=rule.path)
        clusters.append(cluster)
        by_key[key] = cluster
    for sig in signals:
        if sig.key and sig.key in by_key:
            cluster = by_key[sig.key]
            if polarity_conflict(sig.text, cluster.rep) or (
                    has_negation(sig.text) != has_negation(cluster.rep) and similarity(sig.text, cluster.rep) >= 0.5):
                cluster.conflicted = True
            cluster.members.append(sig)
            continue
        best, best_score = None, 0.0
        for cluster in clusters:
            if polarity_conflict(sig.text, cluster.rep):
                cluster.conflicted = True
                best, best_score = cluster, threshold
                break
            score = similarity(sig.text, cluster.rep)
            if score > best_score:
                best, best_score = cluster, score
        if best is not None and best_score >= threshold:
            # Same words with the opposite polarity ("加 emoji" / "唔好加 emoji")
            # is a contradiction, not a repeat: it must never be averaged into a rule.
            if has_negation(sig.text) != has_negation(best.rep):
                best.conflicted = True
            best.members.append(sig)
            if sig.key and sig.key not in by_key:
                by_key[sig.key] = best
            continue
        key = sig.key or slugify_key(sig.text)
        cluster = Cluster(rep=sig.text, key=key, members=[sig])
        clusters.append(cluster)
        by_key.setdefault(key, cluster)
    return clusters


def _confidence(evidence: int, applied: int, violated: int) -> float:
    return round((1 + evidence + applied) / (2 + evidence + applied + violated), 3)


def _evidence_dates(card: Card) -> list[str]:
    raw = card.meta.get("evidence") or []
    return [str(x) for x in raw]


def _rule_body(rule: str, members: list[Signal]) -> str:
    lines = [f"# {rule}", "", "## 來源訊號", ""]
    for sig in members:
        when = sig.created[:10] or "未註明日期"
        src = f" · {sig.source}" if sig.source else ""
        lines.append(f"- {when}{src} · {sig.text}")
    lines += ["", "## 應驗紀錄", "", "用 `hsb evidence <id> applied|violated` 追加；空表示未驗證。", ""]
    return "\n".join(lines)


def run(vault: Vault, dry_run: bool = False) -> Report:
    """One consolidation pass. Serialised against `capture` by the vault lock."""
    with vault.locked():
        return _run(vault, dry_run)


def _run(vault: Vault, dry_run: bool = False) -> Report:
    cfg = vault.config().get("dream", {})
    min_support = int(cfg.get("min_support", 2))
    threshold = float(cfg.get("similarity", 0.62))
    retire_below = float(cfg.get("retire_below", 0.45))
    stale_days = max(1, int(cfg.get("stale_days", 120)))
    stamp = today()
    report = Report(date=stamp, dry_run=dry_run)

    signals = _signals(vault)
    rules = _rules(vault)
    report.signals = len(signals)
    report.rules_before = len(rules)
    clusters = _cluster(signals, rules, threshold)

    used_paths: set[str] = set()
    for cluster in clusters:
        distinct_days = {s.created[:10] for s in cluster.members if s.created}

        if cluster.conflicted:
            report.conflicts.append({
                "key": cluster.key,
                "texts": [s.text for s in cluster.members][:4],
                "path": cluster.rule_path,
            })
            continue

        if cluster.rule_path:
            card = vault.card(cluster.rule_path)
            dates = _evidence_dates(card)
            added = sorted(d for d in distinct_days if d not in dates)
            if not added:
                continue
            dates = sorted(set(dates) | set(added))
            prior = int(card.meta.get("support") or 1)
            new_support = prior + len(added)
            applied = int(card.meta.get("applied") or 0)
            violated = int(card.meta.get("violated") or 0)
            conf = _confidence(new_support, applied, violated)
            for member in cluster.members:
                used_paths.add(member.path)
            if dry_run:
                report.reinforced.append({"id": str(card.meta.get("id") or cluster.rule_path),
                                          "confidence": conf, "evidence": len(dates)})
                continue
            newest = max(cluster.members, key=lambda s: (s.created, s.path))
            old_rule = str(card.meta.get("rule") or "")
            if normalize(newest.text) != normalize(old_rule):
                # The newest phrasing wins the displayed rule; the old one stays
                # in the body and in `superseded`, so the change is auditable.
                card.meta["rule"] = newest.text.strip()
                card.meta["title"] = newest.text.strip()[:80]
                if old_rule:
                    card.meta["superseded"] = list(card.meta.get("superseded") or []) + [old_rule]
            card.meta["evidence"] = dates
            card.meta["support"] = new_support
            card.meta["confidence"] = conf
            card.meta["updated"] = stamp
            card.meta["last_used"] = stamp
            vault.save_card(card.path, card.meta, _merge_body(card, cluster.members))
            report.reinforced.append({"id": str(card.meta.get("id") or card.path),
                                      "confidence": conf, "evidence": len(dates),
                                      "superseded": normalize(newest.text) != normalize(old_rule)})
            continue

        support = cluster.support
        if support < min_support:
            continue

        for member in cluster.members:
            used_paths.add(member.path)
        term_key = cluster.key or slugify_key(cluster.rep)
        rule_text = _rule_text(cluster)
        if dry_run:
            report.promoted.append({"id": f"(new) {rule_text[:40]}", "rule": rule_text,
                                    "support": support, "confidence": _confidence(support, 0, 0)})
            continue
        path, rid = _write_rule(vault, rule_text, term_key, cluster, support, stamp)
        cluster.rule_path = path
        report.promoted.append({"id": rid, "rule": rule_text, "support": support,
                                "confidence": _confidence(support, 0, 0), "path": path})

    # -- retire and decay ---------------------------------------------------
    # Confidence is a pure function of (support, applied, violated, age). Decay is
    # therefore recomputed, never compounded: running the pass twice on the same
    # day produces the same number, and a 120-day-old rule loses one step per
    # 120 days rather than one step per night.
    for card in _rules(vault):
        rid = str(card.meta.get("id") or os.path.basename(card.path))
        support = int(card.meta.get("support") or 1)
        applied = int(card.meta.get("applied") or 0)
        violated = int(card.meta.get("violated") or 0)
        last = str(card.meta.get("last_used") or card.meta.get("updated") or card.meta.get("created") or "")
        unused = _age_days(last) if last else 0
        base = _confidence(support, applied, violated)
        steps = unused // stale_days
        eff = round(base * max(0.0, 1 - 0.15 * steps), 3)
        prev = float(card.meta.get("confidence") or base)
        if eff < retire_below:
            report.retired.append(rid)
            if not dry_run:
                _archive(vault, card.path, {"status": "retired", "retired": stamp,
                                            "retire_reason": f"effective confidence {eff:.2f} < {retire_below}"})
            continue
        if round(eff - prev, 3) != 0:
            report.decayed.append(rid)
            if not dry_run:
                card.meta["confidence"] = eff
                card.meta["base_confidence"] = base
                card.meta["unused_days"] = unused
                card.meta["updated"] = stamp
                vault.save_card(card.path, card.meta, card.body)

    # -- signals: consumed, or expired -------------------------------------
    if not dry_run:
        for sig in signals:
            if sig.path in used_paths:
                meta = dict(sig.card.meta) if sig.card else {"kind": sig.kind, "text": sig.text}
                meta.update({"consumed": stamp, "status": "promoted"})
                _archive(vault, sig.path, meta, keep_body=sig.card.body if sig.card else "")
                report.archived_signals += 1
            elif sig.created and _age_days(sig.created) > SIGNAL_TTL_DAYS:
                meta = dict(sig.card.meta) if sig.card else {"kind": sig.kind, "text": sig.text}
                meta.update({"status": "expired", "expired": stamp})
                _archive(vault, sig.path, meta, keep_body=sig.card.body if sig.card else "")
                report.expired_signals += 1

    # -- outputs -----------------------------------------------------------
    from .index import build

    idx = build(vault)
    report.docs = len(idx.docs)
    report.rules_after = (len(rules) + len(report.promoted) - len(report.retired)
                          if dry_run else len(_rules(vault)))
    if not dry_run:
        vault.write("_meta/index.json", idx.to_json())
        digest.write_active(vault)
        vault.write(f"_meta/dream-{stamp}.md", report.render())
        vault.log("dream", f"signals={report.signals} promoted={len(report.promoted)} "
                           f"retired={len(report.retired)} conflicts={len(report.conflicts)}")
    return report


def _merge_body(card: Card, members: list[Signal]) -> str:
    """Append source lines for new members, skipping any already recorded."""
    body = card.body
    new_lines = []
    for sig in sorted(members, key=lambda s: (s.created, s.path)):
        when = sig.created[:10] or "未註明日期"
        src = f" · {sig.source}" if sig.source else ""
        line = f"- {when}{src} · {sig.text}"
        if sig.text in body:
            continue
        new_lines.append(line)
    if not new_lines:
        return body
    marker = "## 應驗紀錄"
    if marker in body:
        head, _, tail = body.partition(marker)
        return head.rstrip() + "\n" + "\n".join(new_lines) + "\n\n" + marker + tail
    return body.rstrip() + "\n\n" + "\n".join(new_lines) + "\n"


def _rule_text(cluster: Cluster) -> str:
    """The rule is the shortest signal that still carries every cluster member."""
    ordered = sorted(cluster.members, key=lambda s: (len(s.text), s.created))
    return ordered[0].text.strip() if ordered else cluster.rep.strip()


def _write_rule(vault: Vault, text: str, key: str, cluster: Cluster, support: int, stamp: str) -> tuple[str, str]:
    base = f"P-{stamp.replace('-', '')}-{slugify(key, 32)}"
    rid, n = base, 1
    while os.path.exists(vault.p(f"preferences/{rid}.md")):
        n += 1
        rid = f"{base}-{n}"
    path = f"preferences/{rid}.md"
    dates = sorted({s.created[:10] for s in cluster.members if s.created})
    meta = {
        "title": text[:80],
        "type": "preference",
        "id": rid,
        "rule": text,
        "key": key,
        "created": stamp,
        "updated": stamp,
        "last_used": stamp,
        "confidence": _confidence(support, 0, 0),
        "support": support,
        "evidence": dates,
        "applied": 0,
        "violated": 0,
        "status": "active",
        "sources": sorted({s.source for s in cluster.members if s.source}),
    }
    vault.save_card(path, meta, _rule_body(text, sorted(cluster.members, key=lambda s: s.created)))
    return path, rid


def mark_evidence(vault: Vault, rule_id: str, outcome: str) -> dict:
    if outcome not in ("applied", "violated"):
        raise ValueError("outcome must be 'applied' or 'violated'")
    for card in _rules(vault):
        if str(card.meta.get("id")) != rule_id and os.path.basename(card.path)[:-3] != rule_id:
            continue
        applied = int(card.meta.get("applied") or 0) + (1 if outcome == "applied" else 0)
        violated = int(card.meta.get("violated") or 0) + (1 if outcome == "violated" else 0)
        support = int(card.meta.get("support") or 1)
        conf = _confidence(support, applied, violated)
        card.meta.update({"applied": applied, "violated": violated, "confidence": conf,
                          "last_used": today(), "updated": today()})
        vault.save_card(card.path, card.meta, card.body)
        vault.log("evidence", f"{rule_id} {outcome} → {conf:.3f}")
        return {"id": rule_id, "applied": applied, "violated": violated, "confidence": conf}
    raise KeyError(f"rule not found: {rule_id}")


def _archive(vault: Vault, rel: str, meta: dict, keep_body: str = "") -> str:
    name = os.path.basename(rel)
    bucket = "signals" if rel.startswith("inbox/") else "preferences"
    target = vault.unique_rel(f"_archive/{bucket}/{name}")
    body = keep_body if keep_body else vault.card(rel).body
    meta = dict(meta)
    meta["archived"] = now_iso()
    vault.save_card(target, meta, body)
    try:
        os.unlink(vault.p(rel))
    except OSError:
        pass
    return target


def _age_days(stamp: str) -> int:
    text = stamp.strip()
    for fmt, size in (("%Y-%m-%d", 10), ("%Y-%m-%dT%H:%M:%S", 19),
                      ("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16)):
        try:
            then = datetime.strptime(text[:size], fmt).date()
            return (date.today() - then).days
        except ValueError:
            continue
    return 0
