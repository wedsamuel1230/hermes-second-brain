"""Keyword index over a vault, rebuilt from files and cached in ``_meta``.

Why not a vector database: this machine's own memory survey
(``docs/papers.md`` §LongMemEval, Mem0) shows retrieval buys latency and cost,
not accuracy, and pure vectors fail on numbers, proper nouns, negations and
aggregation. A deterministic keyword index over a few hundred notes is fast,
inspectable, and diffable — it also never runs a model, so it cannot drift.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass, field

from .store import Vault, parse_frontmatter
from .text import excerpt, term_set, terms, wikilinks

HEAD_BYTES = 3000
TITLE_WEIGHT = 3.0
LINK_WEIGHT = 1.15
MIN_QUERY_TERMS = 2


@dataclass
class Hit:
    path: str
    title: str
    score: float
    snippet: str = ""

    def line(self) -> str:
        return f"{self.path} — {self.title}"


@dataclass
class Index:
    built: float = 0.0
    signature: str = ""
    docs: list[dict] = field(default_factory=list)
    df: dict[str, int] = field(default_factory=dict)
    post: dict[str, list[int]] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> "Index":
        data = json.loads(raw)
        return cls(**{k: data.get(k, v) for k, v in {
            "built": 0.0, "signature": "", "docs": [], "df": {}, "post": {}
        }.items()})


def _sources(vault: Vault) -> list[tuple[str, str]]:
    """``(path, absolute path)`` for every file that should be searchable."""
    cfg = vault.config()
    out: list[tuple[str, str]] = []
    for rel in ("identity.md", "now.md", "decisions.md"):
        if os.path.exists(vault.p(rel)):
            out.append((rel, vault.p(rel)))
    for rel_dir in cfg.get("notes_dirs") or ["notes"]:
        for rel, _m, _s in vault.md_files(rel_dir):
            out.append((rel, vault.p(rel)))
    for rel_dir in ("preferences", "sources"):
        for rel, _m, _s in vault.md_files(rel_dir):
            out.append((rel, vault.p(rel)))
    for abs_dir in cfg.get("extra_dirs") or []:
        abs_dir = os.path.abspath(os.path.expanduser(abs_dir))
        if not os.path.isdir(abs_dir):
            continue
        for root, dirs, files in os.walk(abs_dir):
            dirs[:] = [d for d in dirs if not d.startswith((".", "_"))]
            for name in sorted(files):
                if name.endswith(".md"):
                    full = os.path.join(root, name)
                    out.append((full.replace(os.sep, "/"), full))
    return out


def signature(vault: Vault) -> str:
    h = hashlib.sha256()
    for path, full in _sources(vault):
        try:
            stat = os.stat(full)
        except OSError:
            continue
        h.update(f"{path}|{stat.st_mtime_ns}|{stat.st_size}\n".encode())
    return h.hexdigest()[:32]


def build(vault: Vault) -> Index:
    idx = Index(built=time.time(), signature=signature(vault))
    seen: set[str] = set()
    for path, full in _sources(vault):
        if path in seen:
            continue
        seen.add(path)
        try:
            with open(full, encoding="utf-8", errors="ignore") as fh:
                raw = fh.read(HEAD_BYTES)
        except OSError:
            continue
        meta, body = parse_frontmatter(raw)
        title = str(meta.get("title") or "")
        if not title:
            for line in body.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
        if not title:
            title = os.path.basename(path).rsplit(".", 1)[0]
        gt = term_set(title)
        counts: dict[str, int] = {}
        for term in terms(body):
            if term in gt:
                continue
            counts[term] = counts.get(term, 0) + 1
        i = len(idx.docs)
        idx.docs.append({
            "p": path,
            "t": title,
            "gt": sorted(gt),
            "tf": counts,
            "links": wikilinks(body),
            "kind": str(meta.get("type") or ""),
        })
        for term in gt | set(counts):
            idx.df[term] = idx.df.get(term, 0) + 1
            idx.post.setdefault(term, []).append(i)
    return idx


def load(vault: Vault) -> Index:
    """Cached index, rebuilt when any file's mtime/size changed."""
    try:
        with open(vault.index_cache, encoding="utf-8") as fh:
            cached = Index.from_json(fh.read())
        if cached.signature == signature(vault):
            return cached
    except (OSError, ValueError, TypeError):
        pass
    idx = build(vault)
    try:
        vault.write("_meta/index.json", idx.to_json())
    except OSError:
        pass
    return idx


def search(idx: Index, query: str, limit: int = 5, min_terms: int = MIN_QUERY_TERMS) -> list[Hit]:
    total = max(1, len(idx.docs))
    q = [t for t in dict.fromkeys(terms(query))]
    if not q:
        return []
    ceiling = max(3, int(total * 0.6))
    filtered = [t for t in q if idx.df.get(t, 0) <= ceiling]
    # A query made only of everywhere-words still deserves an answer: dropping
    # every term would return nothing for a vault whose prose is homogeneous.
    if filtered:
        q = filtered
    need = 1 if len(q) <= 1 else min_terms

    def idf(term: str) -> float:
        return math.log(1.0 + total / (1.0 + idx.df.get(term, 0)))

    # link graph: a note that is linked from a strong hit is probably related
    link_targets: set[str] = set()
    matched_count: dict[int, int] = {}
    for term in q:
        for i in idx.post.get(term, ()):
            matched_count[i] = matched_count.get(i, 0) + 1
    for i, n in matched_count.items():
        if n >= need:
            for target in idx.docs[i].get("links") or []:
                link_targets.add(target.strip().lower())

    ranked: list[Hit] = []
    for i, doc in enumerate(idx.docs):
        n = matched_count.get(i, 0)
        gt = set(doc["gt"])
        tf = doc["tf"]
        s = 0.0
        for term in q:
            w = idf(term)
            if term in gt:
                s += TITLE_WEIGHT * w
            elif term in tf:
                s += w * (1.0 + math.log(tf[term]))
        if n < need or s <= 0:
            continue
        stem = doc["p"].rsplit("/", 1)[-1].lower()
        slug = stem.rsplit(".", 1)[0]
        if slug in link_targets or doc["t"].lower() in link_targets:
            s *= LINK_WEIGHT
        ranked.append(Hit(path=doc["p"], title=doc["t"], score=round(s, 4)))

    if not ranked:
        return []
    ranked.sort(key=lambda h: (-h.score, h.path))
    floor = ranked[0].score * 0.55
    out = [h for h in ranked if h.score >= floor][:limit]
    for hit in out:
        hit.snippet = _snippet(hit.path, q)
    return out


def _snippet(path: str, q: list[str]) -> str:
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            body = fh.read(HEAD_BYTES)
    except OSError:
        return ""
    return excerpt(body, q)
