# hermes-second-brain

A second brain **Hermes reads before it answers**. Plain Markdown, one Python CLI, no server, no
database, no embeddings, and no model inside the consolidation loop.

```bash
./bin/hsb init --name "My Brain"                 # → ~/brain, seeded with identity / now / decisions
./bin/hsb capture --kind correction "stop adding emoji to replies"
./bin/hsb dream                                  # repeated signals become a rule with a confidence
./bin/hsb context "help me plan tomorrow"        # what a hook would inject into the turn
```

47 unit tests. Search over this machine's 162 real notes: 0.43 s to build, 2.4 ms median per query,
40/40 correct on exact titles. Digest: 700–1200 characters, rebuilt from files every turn.

## The problem it solves

The reel that started this (`@your.engineer.ben`, 2026‑11‑18) shows the same failure twice: you ask an
agent to plan your afternoon, it asks who you are, what your projects are, what you already decided —
and tomorrow it asks again. The fix in the reel is Garry Tan's open second brain: a `CLAUDE.md` plus a
folder of notes about who you are, what is in flight, and what has been decided, read before the agent
starts.

That works until the instruction file grows past the point where anyone maintains it, and until the next
session starts from a frozen copy of it. This repo keeps the idea and fixes the two weak points:
the context is **rebuilt from files on every turn**, and what the agent learns **flows back into those
files** instead of into a chat log.

## What it adds over a static instruction file

| Failure of `CLAUDE.md` | Mechanism here |
|---|---|
| Frozen at session start; mid-session learning is lost | `pre_llm_call` hook renders the digest from disk every turn |
| Grows without limit until nobody reads it | Hard character budget, sections ranked, overflow dropped by priority |
| The agent forgets to write anything down | `hsb capture` is one command, and the skill says when to run it |
| Corrections are repeated forever | A nightly pass promotes repeat corrections to rules with evidence and confidence |
| Rules never die, or die silently | Confidence falls on violations, decays with disuse, archives below 0.45 |
| Everything blows up when the model changes | Files, not a vendor's memory API |

## The loop

```
        capture                 dream (nightly, deterministic)          digest (every turn)
 work ──────────► inbox/*.md ──────────────────────────► preferences/*.md ──────────────────► hook
                    │  repeat + similarity ≥ 0.62          │ confidence, evidence
                    │  support ≥ 2                         │ applied / violated
                    └──────────► _archive/ (never deleted) └── retire below 0.45
```

1. **capture** — during work, one line: a correction, a preference, a decision, a fact, with a source.
2. **dream** — clusters signals, promotes clusters with support ≥ 2 into rules, recomputes confidence,
   retires weak rules, decays unused ones, archives consumed signals, rebuilds the index and digest,
   writes a dated report.
3. **digest** — identity → now → rules by confidence → newest decisions → notes matching this message,
   cut to budget.
4. **evidence** — when a rule is followed or broken, `hsb evidence <id> applied|violated` moves its
   confidence. That is the only way a rule gets stronger than its promoting signals.

## Commands

| Command | What it does |
|---|---|
| `hsb init [--name N] [--extra-dir PATH]` | create the vault, seed the three files only a human can write |
| `hsb capture --kind K --source S "text"` | record a signal (`correction`, `preference`, `decision`, `fact`) |
| `hsb dream [--dry-run] [--json]` | consolidate; `--dry-run` prints the plan and writes nothing |
| `hsb digest [--write]` | render the digest, or write `active.md` |
| `hsb context "message"` | exactly what the hook injects for this message |
| `hsb search "query" [-k N]` | keyword search, one line per hit with score and excerpt |
| `hsb evidence ID applied\|violated` | confirm or refute a rule |
| `hsb note --title … --type … --link …` | atomic note with frontmatter and wikilinks |
| `hsb source --url … --file …` | immutable source with `sha256` |
| `hsb lint [--json]` | frontmatter, broken wikilinks, orphan notes, inbox backlog |
| `hsb stats [--json]` | counts, median rule confidence, digest size, index size |
| `hsb config [key=value …]` | read or set `_meta/config.json` |

`--vault` (or `HSB_VAULT`) points any command at another vault. Default: `~/brain`.

## Vault layout

```
brain/
  identity.md      who the user is — you write this, the agent only reads it
  now.md           what is in flight, one line each
  decisions.md     append-only log: heading = date + decision, then the reason
  preferences/     rules promoted by dream (frontmatter: confidence, evidence, applied, violated)
  inbox/           signals waiting for the next dream
  notes/           atomic notes, [[wikilinks]]
  sources/         captured sources, immutable, sha256 in frontmatter
  _meta/           config.json, index cache, dream reports
  _archive/        retired rules and expired signals — kept, never deleted
  active.md        generated digest
  log.md           append-only action log
```

Nothing in the format is Hermes-specific: it is a folder of Markdown that Obsidian, grep and git all
understand. The Hermes part is the hook, the skill and the cron job.

## Measured

| Measurement | Value | Environment |
|---|---|---|
| Unit tests | 47 passed | Python 3.14, stdlib only |
| Index build, 162 real notes | 0.43 s | `/config/wiki`, mixed Chinese/English |
| Search median / p95, prefix query | 2.4 ms / 9.3 ms | same corpus, 40 queries |
| Exact-title query | 40/40 top-1, 0.45 ms | same corpus |
| Prefix query, same note family | 40/40 top-1 in the family, 29/40 exact identity | the 11 others are dated siblings (`… 2026-07-08` vs `… 2026-07-01`) |
| Index size, 162 notes | 780 KB | body term counts included |
| Index build, 1003 synthetic notes | 0.64 s | uniform random text |
| Digest length | 700–1200 chars | `hook_budget` / `digest_budget` |

Uniform random corpora score worse (13/50 at 1000 notes) because every document shares the same two
words; real notes are sparse. Treat the synthetic row as a latency test, not an accuracy one.

## Installation into Hermes

Hook, skill and nightly cron, with the exact commands and a rollback: [`docs/install-hermes.md`](docs/install-hermes.md).

```bash
git clone https://github.com/wedsamuel1230/hermes-second-brain
cd hermes-second-brain
./bin/hsb init --name "Second Brain" --extra-dir ~/wiki
python3 -m unittest discover -s tests -t .     # 28 pass
```

## Why not just adopt gbrain or open-second-brain

Both are real, MIT-licensed, and closer to the reel than this repo:

- [`garrytan/gbrain`](https://github.com/garrytan/gbrain) — 33k stars, a "brain-first" instruction block
  written into `SOUL.md`, MCP memory verbs, a per-turn `pre_llm_call` hook, and a documented Hermes
  path. Needs Bun and PGlite or Postgres.
- [`itechmeat/open-second-brain`](https://github.com/itechmeat/open-second-brain) — 604 stars, the
  nightly dream pass this repo's consolidation is modelled on, plugin hooks and an MCP server. Needs Bun.

On a Home Assistant OS add-on there is no Bun and no Postgres; adding a runtime to get a memory layer is
the wrong trade. So the **patterns** were taken, with the sources named in every doc, and the runtime is
Python's standard library. If you already run Bun, use gbrain — it is more complete than this. The
decision record is in [`DESIGN.md`](DESIGN.md#d10-why-build-rather-than-adopt).

## Honest limits

- Keyword retrieval only. Synonyms and paraphrase miss; there is no embedding fallback by design.
- The tokenizer is CJK bigrams plus ASCII words. No stemming, no lemmatisation.
- Confidence is a heuristic posterior over counts, not a calibrated probability.
- One vault per machine, no sync, no encryption, no multi-user access control.
- `dream` cannot invent a rule: a rule is a restatement of the shortest signal that represents its
  cluster. If the signals are bad, the rule is bad.
- The digest is only useful if it stays small. A 12,000-character digest is a context tax, not a brain.

## Inspiration

Full table with what was taken and what was rejected: [`docs/papers.md`](docs/papers.md).

Repos: gbrain, open-second-brain, Karpathy's LLM Wiki gist, claude-obsidian, swarmvault.
Papers: MemGPT, Mem0, Zep, A-MEM, HippoRAG, Generative Agents, MemoryBank, LongMemEval, AgentPoison,
Lost in the Middle.

## Licence

MIT. See [`LICENSE`](LICENSE).
