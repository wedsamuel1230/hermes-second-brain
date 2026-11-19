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
from dataclasses import dataclass, field
from datetime import date, datetime

from . import digest
from .store import Card, Vault, slugify, today, now_iso
from .text import similarity, slugify_key

KINDS = ("correction", "preference", "decision", "fact")
SIGNAL_TTL_DAYS = 30


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

    @property
    def support(self) -> int:
        return len({m.created[:10] for m in self.members}) or len(self.members)


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
            by_key[sig.key].members.append(sig)
            continue
        best, best_score = None, 0.0
        for cluster in clusters:
            score = similarity(sig.text, cluster.rep)
            if score > best_score:
                best, best_score = cluster, score
        if best is not None and best_score >= threshold:
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
    cfg = vault.config().get("dream", {})
    min_support = int(cfg.get("min_support", 2))
    threshold = float(cfg.get("similarity", 0.62))
    retire_below = float(cfg.get("retire_below", 0.45))
    stale_days = int(cfg.get("stale_days", 120))
    stamp = today()
    report = Report(date=stamp, dry_run=dry_run)

    signals = _signals(vault)
    rules = _rules(vault)
    report.signals = len(signals)
    report.rules_before = len(rules)
    clusters = _cluster(signals, rules, threshold)

    used_paths: set[str] = set()
    touched_rules: set[str] = set()
    for cluster in clusters:
        distinct_days = {s.created[:10] for s in cluster.members if s.created}
        support = max(len(distinct_days), len(cluster.members))

        if cluster.rule_path:
            card = vault.card(cluster.rule_path)
            dates = _evidence_dates(card)
            added = sorted(d for d in distinct_days if d not in dates)
            if not added:
                continue
            dates = sorted(set(dates) | added)
            prior = int(card.meta.get("support") or len(dates) or 1)
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
            card.meta["evidence"] = dates
            card.meta["support"] = new_support
            card.meta["confidence"] = conf
            card.meta["updated"] = stamp
            card.meta["last_used"] = stamp
            vault.save_card(card.path, card.meta, card.body)
            touched_rules.add(card.path)
            report.reinforced.append({"id": str(card.meta.get("id") or card.path),
                                      "confidence": conf, "evidence": len(dates)})
            continue

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
        touched_rules.add(path)
        report.promoted.append({"id": rid, "rule": rule_text, "support": support,
                                "confidence": _confidence(support, 0, 0), "path": path})

    # -- retire and decay ---------------------------------------------------
    for card in _rules(vault):
        if card.path in touched_rules:
            continue
        rid = str(card.meta.get("id") or os.path.basename(card.path))
        conf = float(card.meta.get("confidence") or 0.5)
        last = str(card.meta.get("last_used") or card.meta.get("updated") or card.meta.get("created") or "")
        if conf < retire_below:
            report.retired.append(rid)
            if not dry_run:
                _archive(vault, card.path, {"status": "retired", "retired": stamp,
                                            "retire_reason": f"confidence {conf:.2f} < {retire_below}"})
            continue
        if last and _age_days(last) > stale_days:
            report.decayed.append(rid)
            if not dry_run:
                card.meta["confidence"] = round(conf * 0.85, 3)
                card.meta["updated"] = stamp
                card.meta["decay_note"] = f"no use for >{stale_days}d, confidence -15%"
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
                           f"retired={len(report.retired)}")
    return report


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
    target = f"_archive/{bucket}/{name}"
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
