# How it works

Four files, one index, one nightly pass. Nothing here needs a network connection.

## 1. Files and frontmatter

Every page is Markdown with a small frontmatter block:

```markdown
---
title: 回覆唔好加 emoji
type: preference
id: P-20261119-唔好加-emoji
rule: 回覆唔好加 emoji
key: 唔好加-emoji
created: 2026-11-19
updated: 2026-11-19
last_used: 2026-11-19
confidence: 0.75
support: 2
evidence: [2026-11-19, 2026-11-21]
applied: 3
violated: 1
status: active
sources: [discord]
---

## 來源訊號
- 2026-11-19 · discord · 回覆唔好加 emoji
- 2026-11-21 · discord · 唔好加 emoji
```

The parser handles scalars, inline lists and `- ` block lists. That is the whole grammar, on purpose: a
hand-edited vault must never fail to load because of an indentation mistake.

## 2. Signals

A signal is one thing the agent learned during work. `kind` is one of:

| kind | Example | Becomes |
|---|---|---|
| `correction` | "don't add emoji to replies" | a rule about style or behaviour |
| `preference` | "reply in Traditional Chinese" | a rule |
| `decision` | "we are using LVGL 8, not 9" | a rule, and worth a line in `decisions.md` too |
| `fact` | "GPIO45 is a strapping pin" | usually a note, not a rule — a fact is not an instruction |

`created` is the date the signal was captured; `source` is where it came from (`discord`, `code-review`,
a URL). Both are load-bearing: the date becomes promotion evidence, and the source is what makes a
poisoned entry traceable.

## 3. The dream pass

Deterministic. Same vault plus same clock gives the same result, which is what makes the report
reviewable.

1. **Read** every card in `inbox/`, sorted by creation date.
2. **Cluster.** A signal with `key` joins the cluster or rule with the same key. Otherwise it joins the
   cluster with the highest `similarity()`, if that reaches `dream.similarity` (default 0.62). Otherwise
   it starts a new cluster.
3. **Promote.** A cluster with `support >= dream.min_support` (default 2) and no existing rule becomes a
   rule. `support = max(distinct dates, number of signals)`. The rule text is the shortest signal in the
   cluster; every member signal is listed in the body.
4. **Reinforce.** New dates on an existing rule raise `support`, and confidence is recomputed.
5. **Retire.** A rule with confidence below `dream.retire_below` (0.45) moves to `_archive/preferences/`
   with `status: retired` and a reason.
6. **Decay.** A rule untouched for `dream.stale_days` (120) loses 15% confidence.
7. **Archive signals.** Consumed signals move to `_archive/signals/` with `status: promoted`; unmatched
   signals older than 30 days move with `status: expired`.
8. **Rebuild** the index, rewrite `active.md`, write `_meta/dream-YYYY-MM-DD.md`, append to `log.md`.

`--dry-run` performs steps 1–3 and 4's arithmetic without writing, and reports the same numbers.

### Similarity

```
similarity(a, b) = max( jaccard(terms), 0.85 * |a ∩ b| / min(|a|, |b|) )
similarity = 0.9     if one normalized text contains the other and the shorter has >= 3 terms
```

Containment is there because a repeat usually restates the first signal with extra words. Containment is
capped at 0.85 so it cannot beat a true match, and it needs three terms so a two-character string cannot
swallow a paragraph.

### Confidence

```
confidence = (1 + support + applied) / (2 + support + applied + violated)
```

| support | applied | violated | confidence |
|---|---|---|---|
| 2 | 0 | 0 | 0.75 |
| 2 | 1 | 0 | 0.80 |
| 2 | 1 | 4 | 0.44 → retired |
| 4 | 0 | 0 | 0.83 |

## 4. Retrieval

Build: every file in `identity.md`, `now.md`, `decisions.md`, `notes/`, `preferences/`, `sources/` and
`extra_dirs` is read once (first 3000 bytes) and indexed. Cache: `_meta/index.json`, invalidated by a
sha256 over `(path, mtime_ns, size)`.

Query:

1. Tokenise: CJK bigrams (single characters for one-character runs) plus ASCII words.
2. Drop terms present in more than 60% of documents — unless that would drop everything.
3. A document must match at least two query terms (one if the query is a single usable term).
4. Score: `idf(t) × 3` in the title, `idf(t) × (1 + ln(tf))` in the body.
5. Multiply 1.15 when the document is a wikilink target of another matched document.
6. Keep hits at ≥55% of the top score, then cut to `-k`.

`idf(t) = ln(1 + N / (1 + df(t)))`.

## 5. Digest

Priority order, truncated at the budget:

| Order | Section | Source |
|---|---|---|
| 1 | `你是誰` | first three bullets of `identity.md` |
| 2 | `現在` | first three bullets of `now.md` |
| 3 | `規則` | active rules, highest confidence first, max 5 |
| 4 | `最近決定` | newest three `## date — decision` headings plus their reason line |
| 5 | `命中筆記` | top three search hits for the message, path + title only |

Budgets: `digest_budget` 1200 for `hsb digest`, `hook_budget` 700 for the hook. A line that does not fit
is replaced by `…（其餘略）`; the truncation never cuts mid-character.

## 6. Config

`_meta/config.json`:

| Key | Default | Meaning |
|---|---|---|
| `name` | `Second Brain` | capsule name in the digest header |
| `notes_dirs` | `["notes"]` | folders indexed as notes |
| `extra_dirs` | `[]` | absolute folders indexed read-only (an existing wiki, an Obsidian vault) |
| `digest_budget` | 1200 | characters for `hsb digest` |
| `hook_budget` | 700 | characters injected per turn |
| `dream.min_support` | 2 | signals required to promote |
| `dream.similarity` | 0.62 | clustering threshold |
| `dream.retire_below` | 0.45 | confidence that retires a rule |
| `dream.stale_days` | 120 | days without use before decay |

Set with `hsb config dream.retire_below=0.4` style key/value or edit the file directly.

## 7. Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Rules multiply, each slightly different | signals restate an instruction with new wording | pass `--key` on capture so they merge |
| Nothing gets promoted | signals are too dissimilar for 0.62 | lower `dream.similarity`, or fix the key |
| A rule keeps firing after it stopped being true | nobody marked violations | `hsb evidence <id> violated`; the pass retires it at 0.45 |
| Digest is 4 KB | too many decisions and rules | lower the budget; the sections are ranked, so the tail is what goes |
| Search returns nothing | query has a single uncommon term and the vault is small | use two terms, or read `index.md`-style manual notes |
| Hook silent | `HSB_VAULT` unset, path wrong, or the hook is not approved | `hermes hooks doctor` shows exec bit, allowlist and timing |
