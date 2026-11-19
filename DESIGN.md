# Design decisions

Each entry: the decision, the alternative that was rejected, and the evidence. Numbers are from this
machine unless stated.

## D1 — Files are the source of truth

Markdown with YAML frontmatter in a folder. No database holds state; `_meta/index.json` is a cache that
can be deleted at any time and rebuilt.

*Rejected:* SQLite as the primary store. It is faster to query and worse to inspect, diff, back up and
edit by hand. A brain is edited by a person, read by an agent, and versioned by git — files win.
*Evidence:* `hsb dream` rebuilds the index from 162 files in 0.37 s. Nothing depends on the cache.

## D2 — Keyword retrieval, no embeddings

CJK character bigrams plus lowercase ASCII words, idf-weighted, title boosted 3×, one hop of
`[[wikilink]]` boost 1.15×, a document must match two query terms, and results below 55% of the top
score are dropped.

*Rejected:* a vector store. On this machine, full context with prompt caching scored better than
retrieval in the published comparison (Mem0: full context 72.90 with 26,031 tokens and p95 17.1 s, vs
Mem0's own 66.88 with 1,764 tokens and p95 0.2 s). Retrieval buys latency and cost, not accuracy, and
pure vectors degrade on numbers, proper nouns, negations and aggregate questions.
*Evidence:* 2.5 ms median query over 162 real notes; the same tokeniser has been running in this
machine's wiki-recall hook since 2026‑11‑14 at ~147 ms per turn including cache checks.

## D3 — The consolidation pass runs no model

`dream` clusters by string similarity and support count, then does arithmetic. Given the same vault and
the same clock it produces the same rules and the same report.

*Rejected:* an LLM summarising the inbox each night. It invents rules nobody asked for, deletes things
that look redundant, and cannot be diffed between runs. A small model managing memory autonomously makes
memory worse over time, which is the opposite of the goal.
*Evidence:* the promotion path is `similarity() + Counter`. Every rule keeps the exact signals that
created it, so a bad rule is traceable to a sentence someone actually said.

## D4 — Confidence is a Beta posterior, and rules retire at 0.45

```
confidence = (1 + support + applied) / (2 + support + applied + violated)
```

`support` counts the independent signals that promoted the rule (two on one day counts as two), `applied`
counts confirmed uses, `violated` counts refutations. Two signals: 0.75. One application: 0.80. Five
violations after that: below 0.45, which retires the rule at the next pass.

*Rejected:* a plain "seen 3 times = keep" counter. It never falls, so a rule that was true in March and
false in November stays at full strength.
*Evidence:* `tests/test_dream.py::test_evidence_moves_confidence_both_ways` walks the whole curve.

## D5 — The digest is generated, not written

`active.md` is rebuilt on every dream and on demand. The hook renders the same content for a message,
with the matching note paths appended.

*Rejected:* a curated `MEMORY.md`-style file maintained by hand. It drifts, it is never pruned, and it
cannot include "what is in flight right now" without manual editing.
*Evidence:* the digest's priority order is fixed — identity, now, rules, decisions, matching notes — so
truncation removes the least useful part first. Budget: 1200 chars for `digest`, 700 for the hook.

## D6 — The hook fails open

Any exception prints nothing and the turn continues. No retry, no error text in the prompt.

*Rejected:* failing loudly so a broken brain is noticed. A memory layer that can block a turn is worse
than one that forgets a turn; the `dream` report and `hsb lint` are where breakage is meant to surface.

## D7 — Archive instead of delete

Retired rules move to `_archive/preferences/`, expired and consumed signals to `_archive/signals/`, with
`archived`, `retired` or `promoted` in the frontmatter.

*Rejected:* deleting weak rules. Deletion destroys the reason a rule existed, and the next agent
relearns the same wrong thing from the same signal.

## D8 — Existing note folders are indexed read-only

`extra_dirs` adds absolute paths to the index; nothing in `dream` writes there. On this machine the
existing `/config/wiki` (162 files) is indexed this way instead of being migrated.

*Rejected:* telling the user to move 125 notes into `brain/notes`. Migration costs a day, breaks inbound
wikilinks and yields nothing the index does not already give.

## D9 — The rule is the shortest signal in its cluster

`_rule_text()` picks the member with the fewest characters. This is the only place a phrase is chosen
without a human, and it is why the report prints every promoted rule with its support count — reading
four lines of the report is cheaper than trusting the picker.

## D10 — Why build rather than adopt

Prior-art probe (2026‑11‑19, per the `prior-art-first` budget: 3 sources, 8 candidates):

| Repo | Stars | Pushed | Licence | Verdict |
|---|---|---|---|---|
| `garrytan/gbrain` | 33,290 | 2026‑11‑19 | MIT | Best overall; needs Bun + PGlite/Postgres |
| `garrytan/gstack` | 142,042 | 2026‑11‑19 | MIT | Claude Code tool suite, not a memory layer |
| `AgriciDaniel/claude-obsidian` | 16,601 | 2026‑10‑25 | MIT | Obsidian plugin-first, 25 days stale |
| `itechmeat/open-second-brain` | 604 | 2026‑11‑19 | MIT | Closest lifecycle; needs Bun + MCP |
| `swarmclawai/swarmvault` | 737 | 2026‑06‑30 | MIT | 5 months stale |
| `coleam00/second-brain-skills` | 850 | 2026‑01‑24 | none | 10 months stale, no licence |
| `jessepinkman9900/claude-second-brain` | 173 | 2026‑04‑20 | MIT | Scaffold + Obsidian, 7 months stale |
| `avenoxai/avenoxbeyin` | 482 | 2026‑11‑18 | MIT | Scaffold + Obsidian, hosted hook |

Environment: Home Assistant OS add-on, Python 3.14, no Bun, no Postgres, 14 GB free disk. Both finalists
require a runtime that is not present and cannot be installed cleanly. Decision: **build the thin
layer, reuse the data model and the lifecycle from both, cite them.** If the machine ever runs Bun,
gbrain is the better product and this repo should be retired into it.

## D11 — Stable keys for merging signals

`capture --key reply-language` merges signals that are worded differently but mean the same thing.
Without a key, similarity decides.

*Rejected:* relying on similarity alone. "用繁體中文回覆" and "英文技術詞保留原文" score near zero against
each other and belong to one rule; only the agent knows they are the same intent.
