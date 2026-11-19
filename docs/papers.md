# Where the ideas came from

Every claim below was checked against the source on 2026‑11‑19: arXiv IDs resolved through the arXiv API,
repos through `gh api repos/<name>`, star counts and last push dates read at that moment. Nothing here is
quoted from memory.

## The reel that started it

`@your.engineer.ben` (Instagram, 2026‑11‑18) demonstrating a thread by `@imryven`: Y Combinator's CEO
Garry Tan open-sourced his second brain. The recipe in the thread is one `CLAUDE.md` plus a notes folder
— who you are, projects in progress, decisions already made — that the agent reads before starting.
Without the notes the agent asks a pile of questions and produces a generic schedule; with them it says
"no meetings on Wednesday", "only renew the annual plan", "remember those two bugs".

Repos named in the post: `gbrain`, `ai-memory`, `open-second-brain`, `npx claude-second-brain`.

## Repositories

| Source | What it is | Taken | Rejected | Licence |
|---|---|---|---|---|
| [garrytan/gbrain](https://github.com/garrytan/gbrain) | Garry Tan's agent brain, 33.3k stars, pushed 2026‑11‑19. Bun + PGlite/Postgres, MCP memory verbs, `gbrain setup hermes` writes a marked brain-first block into `SOUL.md` and adds a per-turn `pre_llm_call` hook | read-before-answer as a *standing contract*, not a suggestion; a `doctor`/lint habit; a stability channel for a tool agents depend on | the MCP server and the engine: Bun and a database are not available on a Home Assistant OS add-on | MIT |
| [itechmeat/open-second-brain](https://github.com/itechmeat/open-second-brain) | Local-first memory in an Obsidian vault, 604 stars. `Brain/inbox` → `preferences` → `active.md`, evidence `applied`/`violated`, a deterministic `dream` pass that runs no model, MCP + plugin + CLI clients | the whole signal → rule → active lifecycle, evidence semantics, and the "no model inside the dream" rule | the Bun runtime and the MCP surface | MIT |
| [karpathy/llm-wiki.md](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) | A pattern, not code: compile sources into maintained wiki pages, revise summaries, flag contradictions, keep provenance. "You rarely write the wiki yourself." | compiled pages over retrieval-on-read; frontmatter with `confidence`, `contested`, `sources`; wikilinks between pages | the assumption that compilation always beats retrieval — measured evidence says retrieval wins on cost, not accuracy | gist |
| [AgriciDaniel/claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian) | Self-organising second brain for Obsidian + Claude Code, 16.6k stars, built on the LLM Wiki pattern | proof that the pattern scales to a real vault; frontmatter conventions | Obsidian-plugin-first design; last push 2026‑10‑25 | MIT |
| [swarmclawai/swarmvault](https://github.com/swarmclawai/swarmvault) | Local-first LLM Wiki: knowledge graph, RAG store, agent memory, 737 stars | the "vault is the product, the index is disposable" split | last push 2026‑06‑30; RAG-first architecture | MIT |
| [coleam00/second-brain-skills](https://github.com/coleam00/second-brain-skills) | Claude Skills that turn Claude Code into a second brain, 850 stars | skills as the delivery mechanism for the workflow | no licence file; last push 2026‑01‑24 | none found |
| [jessepinkman9900/claude-second-brain](https://github.com/jessepinkman9900/claude-second-brain) | `npx` scaffold: Obsidian + Claude Code + qmd + git, 173 stars | the one-command setup expectation this repo's `hsb init` copies | scaffold only, no consolidation loop | MIT |

## Papers

| Paper | Core idea | What this repo took | What it rejected |
|---|---|---|---|
| [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560) (2023) | Treat context like RAM and the store like disk: a small always-resident core, everything else paged in on demand by the agent's own function calls | a fixed-size core (the digest) that is always present, with detail left on disk | agent-driven paging: each page-in costs a turn, and Hermes already compresses long context through LCM |
| [Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory](https://arxiv.org/abs/2504.19413) (2025) | A separate extraction + consolidation pipeline with explicit ADD/UPDATE/DELETE/NOOP operations, evaluated against full-context baselines | consolidation as a scheduled, first-class step rather than something the chat turn does | the vector-first store and LLM-judged UPDATE/DELETE; here consolidation is arithmetic over recorded signals |
| [Zep: A Temporal Knowledge Graph Architecture for Agent Memory](https://arxiv.org/abs/2501.13956) (2025) | Bi-temporal validity: a fact is invalidated with a timestamp, never overwritten | retire and archive with dates; superseded rules keep their history | the graph database — at 162 notes a dict of postings is enough |
| [A-MEM: Agentic Memory for LLM Agents](https://arxiv.org/abs/2502.12110) (2025) | Zettelkasten-style linked notes; new memories generate links to related ones | atomic notes with `[[wikilinks]]`, and a link boost in retrieval | model-generated link graphs on every insert: cost, and a graph that cannot be diffed |
| [HippoRAG: Neurobiologically Inspired Long-Term Memory for LLMs](https://arxiv.org/abs/2405.14831) (2024) | Hippocampal indexing: a knowledge graph plus PageRank for multi-hop retrieval | one hop of link expansion when scoring | PageRank over a small vault |
| [Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442) (2023) | A memory stream retrieved by recency × importance × relevance, with periodic reflection | recency and confidence as the ranking signal for rules; decay for unused ones | LLM reflection loops: two model calls a night to rephrase what is already written down |
| [MemoryBank: Enhancing LLMs with Long-Term Memory](https://arxiv.org/abs/2305.10250) (2023) | Forgetting modelled on Ebbinghaus: unused memories fade | confidence −15% for a rule untouched past `stale_days` (default 120) | a full forgetting curve fitted per user |
| [LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory](https://arxiv.org/abs/2410.10813) (2024) | Five abilities that long-term memory has to get right: information extraction, multi-session reasoning, temporal reasoning, knowledge updates, abstention | the signal kinds and the dated evidence lines exist to make those five testable; abstention is why a single unmatched signal stays in the inbox instead of becoming a rule | running the benchmark: it needs a model in the loop |
| [AgentPoison: Red-teaming LLM Agents via Poisoning Memory or Knowledge Bases](https://arxiv.org/abs/2407.12784) (2024) | Under 0.1% poisoned memory entries can push attack success above 80% while benign performance drops under 1% — poisoning is nearly invisible from the outside | every signal carries `source`; promoted rules list their source signals in the body; nothing scraped from a web page becomes a rule without a second, independent signal | treating tool output and page content as trustworthy as a statement from the user |
| [Lost in the Middle: How Language Models Use Long Contexts](https://arxiv.org/abs/2307.03172) (2023) | Recall is worst for information in the middle of a long context | a hard digest budget and a fixed priority order, so the important lines sit at the top rather than buried | "just put everything in the context window" |

## Confidence model

The Beta posterior and the 0.45 retirement threshold are this repo's own choice, not lifted from a
paper. It is a heuristic: counts in, a bounded number out, monotone in the direction a human would
expect. It is not calibrated and the docs say so.

## Licence hygiene

Every repo above was checked for a real SPDX licence before its ideas were used. Code was not copied:
the implementation here is stdlib Python written for this project. `coleam00/second-brain-skills` has no
licence file, so only its general shape (skills as the delivery mechanism) informed the skill in
`skills/hermes-second-brain/`.
