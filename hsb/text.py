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


# --- contradiction detection -------------------------------------------------
# Two signals that look alike but mean opposite things must never be averaged into
# one rule. Three mechanisms, all deterministic:
#   * polarity: one side carries a negator the other lacks
#   * numeric: both carry numbers and the numbers differ
#   * antonym: one side holds one member of a known opposite pair
# The antonym table is closed on purpose. Anything outside it is a documented gap,
# visible in the dream report, rather than a guess made by the agent.

NEGATION_PHRASES = ("唔該", "唔好意思", "唔緊要")
NEGATION = ("唔", "不", "冇", "勿", "別", "别", "無", "无", "沒", "没", "未", "非",
            "don't", "dont", "do not", "not", "never", "without")

NUM = re.compile(r"\d+(?:\.\d+)?")

ANTONYMS: tuple[tuple[str, str], ...] = (
    ("dark", "light"), ("on", "off"), ("enable", "disable"), ("enabled", "disabled"),
    ("high", "low"), ("fast", "slow"), ("increase", "decrease"), ("add", "remove"),
    ("always", "never"), ("more", "less"), ("up", "down"), ("before", "after"),
    ("開", "關"), ("亮", "暗"), ("大", "小"), ("快", "慢"), ("多", "少"),
    ("前", "後"), ("上", "下"), ("左", "右"), ("新", "舊"), ("遠", "近"),
    ("內", "外"), ("冷", "熱"), ("早", "晚"), ("加", "減"), ("繁", "簡"),
)

WORDS = re.compile(r"[a-z][a-z0-9']*")


def has_negation(text: str) -> bool:
    flat = normalize(text)
    for phrase in NEGATION_PHRASES:
        flat = flat.replace(phrase, "")
    return any(token in flat for token in NEGATION)


def strip_negation(text: str) -> str:
    flat = normalize(text)
    for phrase in NEGATION_PHRASES:
        flat = flat.replace(phrase, "")
    for token in NEGATION:
        flat = flat.replace(token, "")
    return flat


def _dice(a: str, b: str) -> float:
    """Character overlap. Chinese inserts a negator inside the phrase, so the
    bigram tokeniser is too coarse to compare '回覆加emoji' with '回覆唔好加emoji'."""
    if not a or not b:
        return 0.0
    common = sum((Counter(a) & Counter(b)).values())
    return 2 * common / (len(a) + len(b))


def numeric_conflict(a: str, b: str) -> bool:
    """'每頁 3 個重點' and '每頁 5 個重點' are different values, not repeats."""
    na = set(NUM.findall(normalize(a)))
    nb = set(NUM.findall(normalize(b)))
    return bool(na and nb and na != nb)


def _words(text: str) -> set[str]:
    """ASCII words from the raw text: normalize() strips spaces, which would fuse
    'prefer dark mode' into one token and hide the antonym."""
    return set(WORDS.findall(text.lower()))


def _antonym_hit(a: str, b: str, one: str, two: str) -> bool:
    """True when each text holds exactly one member of the pair."""
    if one.isascii():
        wa, wb = _words(a), _words(b)
        if one in wa and two in wb and one not in wb and two not in wa:
            rest_a = " ".join(sorted(wa - {one}))
            rest_b = " ".join(sorted(wb - {two}))
            return _dice(rest_a, rest_b) >= 0.7
        return False
    na, nb = normalize(a), normalize(b)
    if one in na and two in nb and one not in nb and two not in na:
        return _dice(na.replace(one, ""), nb.replace(two, "")) >= 0.72
    return False


def antonym_conflict(a: str, b: str) -> bool:
    for one, two in ANTONYMS:
        if _antonym_hit(a, b, one, two) or _antonym_hit(a, b, two, one):
            return True
    return False


def conflicts(a: str, b: str) -> bool:
    """Any reason these two statements contradict each other."""
    if numeric_conflict(a, b):
        return True
    if antonym_conflict(a, b):
        return True
    if has_negation(a) == has_negation(b):
        return False
    return _dice(strip_negation(a), strip_negation(b)) >= 0.6
