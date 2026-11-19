"""Tokenising and similarity, tuned for mixed Chinese/English notes.

FTS5 in this environment has no CJK tokenizer and whitespace splitting returns
nothing for Chinese, so text is matched on CJK character bigrams plus lowercase
ASCII words. This is the approach already proven in this machine's wiki-recall
hook (~147 ms per lookup over 125 notes), and it survives numbers, product
names and negations far better than embeddings do.
"""

from __future__ import annotations

import re
from collections import Counter

CJK = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002ffff"
CJK_RUN = re.compile(f"[{CJK}]+")
ASCII_WORD = re.compile(r"[a-z0-9][a-z0-9_+#.-]{1,}")
PUNCT = re.compile(r"[\s，。、；：！？「」『』（）()\[\]{}<>《》\"'`,.!?;:|/\\~@#$%^&*_+=—-]+")
WORD = re.compile(f"[{CJK}]+|[a-z0-9][a-z0-9_+#.-]*")


def terms(text: str) -> list[str]:
    """Ordered term list: CJK bigrams (unigrams for single characters) + ASCII words."""
    out: list[str] = []
    low = text.lower()
    for run in CJK_RUN.findall(low):
        if len(run) == 1:
            out.append(run)
        else:
            out.extend(run[i:i + 2] for i in range(len(run) - 1))
    out.extend(m.group(0) for m in ASCII_WORD.finditer(low))
    return out


def term_set(text: str) -> set[str]:
    return set(terms(text))


def normalize(text: str) -> str:
    """Whitespace- and punctuation-insensitive form, used to spot repeat signals."""
    return PUNCT.sub("", text.lower()).strip()


def similarity(a: str, b: str) -> float:
    """Symmetric-ish closeness of two short texts.

    Jaccard alone punishes the common case where one signal restates another
    with extra words ("記住：唔好加 emoji" vs "唔好加 emoji"), so the score is
    max(jaccard, containment). Containment needs a minimum overlap so a very
    short string cannot swallow a long one.
    """
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        shorter = min(len(terms(na)), len(terms(nb)))
        if shorter >= 3:
            return 0.9
    sa, sb = term_set(na), term_set(nb)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    if inter < 2:
        return 0.0
    union = len(sa | sb)
    return max(inter / union, inter / min(len(sa), len(sb)) * 0.85)


def top_terms(text: str, limit: int = 6) -> list[str]:
    """Most useful terms of a text, longest first — used to build rule keys."""
    counts = Counter(terms(text))
    if not counts:
        return []
    ranked = sorted(counts.items(), key=lambda kv: (-len(kv[0]), -kv[1], kv[0]))
    return [term for term, _n in ranked[:limit]]


def slugify_key(text: str, limit: int = 24) -> str:
    """Readable deterministic key: CJK runs and ASCII words joined by hyphens."""
    parts = [m.group(0) for m in WORD.finditer(text.lower())]
    key = re.sub(r"-{2,}", "-", "-".join(parts)).strip("-")
    return key[:limit].strip("-") or "rule"


def excerpt(text: str, needles: list[str], width: int = 140) -> str:
    """One-line excerpt centred on the first needle hit, for search output."""
    flat = " ".join(text.split())
    low = flat.lower()
    for needle in needles:
        pos = low.find(needle)
        if pos >= 0:
            start = max(0, pos - width // 3)
            piece = flat[start:start + width]
            return ("…" if start else "") + piece + ("…" if start + width < len(flat) else "")
    return flat[:width] + ("…" if len(flat) > width else "")


def wikilinks(text: str) -> list[str]:
    return [m.group(1).split("|")[0].strip() for m in re.finditer(r"\[\[([^\]]+)\]\]", text)]
