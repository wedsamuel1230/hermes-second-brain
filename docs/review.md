# Council review — 2026-11-19

Five independent models reviewed this repository before publication. They were given the design, the
constraints, the measured numbers and the known limits — not the code, not this file, and not each other's
answers. Each round was a fresh, isolated request; a model that voted BLOCK had to name a defect, the
condition that triggers it, and a fix that fits the constraints.

| Role | Model | Access |
|---|---|---|
| Voter 1 | `gemini-4-hydrogen` | brief only |
| Voter 2 | `kimi-k3.1-pro` | brief only |
| Voter 3 | `grok-4.6` | brief only |
| Voter 4 | `gpt-5.4` | brief only |
| Voter 5 | `qwen3.8-2.4t-a95b` | brief only |

`INIT` meant "safe to publish and run nightly". `BLOCK` meant "not yet".

## Result

| Round | INIT | BLOCK | What the blockers were about |
|---|---|---|---|
| 1 | 0 | 5 | decay compounding; support counting; no locking/atomicity; negation-blind clustering; retrieval gate; digest budget |
| 2 | 4 | 1 | grok: extend negators, numeric values, hook fail-open untested |
| 3 | 4 | 1 | grok: non-negated antonyms each become a rule |
| 4 | 4 | 1 | grok: ASCII antonym false positives; a clash cannot displace a live rule |
| 5 | **5** | **0** | — |

Final vote: **5 INIT, 0 BLOCK**.

## What changed because of the review

| Finding | Fix | Test |
|---|---|---|
| Decay either compounded every night or was recomputed away | confidence is a pure function `base × max(0, 1 − 0.15 × (unused_days // 120))` | `DecayTest` |
| `support = max(dates, signals)` was always the signal count, so a double capture promoted a rule | support counts independent occurrences `{(date, normalized text)}` | `SupportAndDuplicateTest` |
| Writes could tear; two writers could interleave; archived names could collide | temp + `fsync` + `os.replace`; `flock` on `_meta/.lock`; `unique_rel()` suffixes | `LockAndCaptureTest`, `ArchiveCollisionTest` |
| Negation treated as agreement, shortest signal wins | polarity check on negator-stripped text (Dice ≥ 0.6) | `NegationConflictTest` |
| A changed number was treated as a repeat | `numeric_conflict()` | `NumericConflictTest` |
| Non-negated opposites each became their own rule | closed 27-pair antonym table + promotion-time clash check | `AntonymConflictTest` |
| A contradiction could never replace a live rule | later statement supersedes: new rule written, old archived as `superseded` | `SupersedeLiveRuleTest` |
| ≥2-term gate rejected short CJK and exact names | exact-title short-circuit; one rare term (≤5% of docs) qualifies | `RetrievalGateTest`, `SmallVaultRetrievalTest` |
| Digest budget asserted, not tested | block-fitting + hard cap | `DigestBudgetTest` |
| Hook fail-open asserted, not tested | three subprocess tests | `HookFailOpenTest` |
| Not demonstrably idempotent | stable ordering; second run writes nothing | `IdempotenceTest` |
| Punctuation-only capture could poison the inbox | rejected at `capture`, exit 2 | `LockAndCaptureTest` |
| A dead nightly job was invisible | digest header warns `⚠ dream 已 N 日未跑` | `DigestBudgetTest` |

Test count went from 30 to 62 across the review. Two claimed defects did not reproduce and were answered
with counter-evidence instead of a code change: a `ZeroDivisionError` on empty input (already guarded,
`similarity()` returns 0.0) and ASCII antonym false positives (the remainder test already applies; two
unrelated sentences are asserted not to conflict).

## What the council did not settle

The antonym table is closed. An unlisted opposite (`prefer tea` / `prefer coffee`) produces two separate
low-support rules rather than a conflict. That is a safe failure — nothing is merged incorrectly, no rule
is promoted from a single mention — and it is visible in `hsb stats`. Closing it requires semantics, which
the "keyword only, stdlib only" constraint excludes.

Confidence is a heuristic posterior over counts, not a calibrated probability. No model in the loop means
no model to fool, but also no semantic understanding: the digest is only as good as the signals captured.
