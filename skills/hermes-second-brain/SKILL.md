---
name: hermes-second-brain
description: Use when reading from or writing to the second-brain vault.
version: 1.0.0
---

# Hermes second brain

A folder of Markdown that Hermes reads before answering and writes to after learning. The CLI is `hsb`;
vault path from `$HSB_VAULT`, default `~/brain`.

Load this skill when: a turn starts with a digest block `[Second Brain]`, the user corrects you, the user
says "remember", or you are about to claim you know the user's projects, preferences or past decisions.

## Read before answering

If the digest is present, it is the answer to "who is this user, what is in flight, what has been
decided". Do not ask the user for facts the digest already states. If a hit is listed under `命中筆記`,
open that file before answering; the digest gives paths, not content.

No digest in the prompt? Ask the CLI directly:

```bash
hsb context "<the user's message>"        # what the hook would inject
hsb search "<two or three terms>" -k 5    # scored hits with excerpts
```

## Write after learning

One command, one line, immediately — not at the end of the session:

```bash
hsb capture --kind correction --source discord "回覆唔好加 emoji"
hsb capture --kind decision   --source meeting "用 LVGL 8，唔用 9"
hsb capture --kind fact       --source <url> "GPIO45 係 strapping pin"
```

Rules for capture:

- `kind` is `correction` (you were told you were wrong), `preference` (stated taste or convention),
  `decision` (a choice with a reason), or `fact` (something checkable).
- Quote the user's wording, not your paraphrase. `dream` builds rules out of these lines.
- Pass `--key <slug>` when the same intent will come back in different words
  (`--key reply-language`, `--key no-emoji`). Without a key, merging depends on string similarity.
- One signal per command. Three corrections in one sentence is three signals.
- Never capture a secret, a token, a password or a card number. Not in the vault, not anywhere.

## Confirm or refute a rule

When a promoted rule is followed by the user, or breaks:

```bash
hsb evidence P-20261119-唔好加-emoji applied
hsb evidence P-20261119-唔好加-emoji violated
```

This is the only thing that moves a rule's confidence. Skipping it leaves every rule at the strength of
its first two signals forever.

## Long-lived knowledge

A fact worth citing later is a note, not a signal:

```bash
hsb note --title "LVGL partial redraw" --type concept --tags hardware --link esp32-s3
hsb source --url https://example.com/page --file /tmp/page.md
```

- One idea per note. Two `[[wikilinks]]` minimum, or `hsb lint` reports an orphan.
- `hsb source` stores the raw text with a `sha256`; cite the source page from the note rather than
  pasting the whole article into it.
- Distinguish what the user confirmed from what a page or tool output claimed. Put the latter under
  `sources` and say "unconfirmed" in the body.

## Consolidation

`hsb dream` runs nightly. Run it by hand after a heavy correction session, then read the report:

```bash
hsb dream --dry-run    # what would happen, writes nothing
hsb dream
```

Never hand-write a rule into `preferences/`. If a rule is wrong, mark it violated or edit its `rule:`
field deliberately and say so. If a promoted rule's wording is clumsy, edit `rule:` — the frontmatter is
the contract, the body is provenance.

## Checks

```bash
hsb lint      # exit 1 on errors: missing frontmatter, duplicate slug, rule without confidence
hsb stats     # indexed count, signals waiting, rule confidence, digest size
```

If `signals_waiting` is above ~20 for more than a week, the capture rate is outrunning consolidation:
run `dream` and check that signals are clustering (lower `dream.similarity` if they are not).

## Pitfalls

- Injecting the whole vault "for context" defeats the point. The digest is 700–1200 characters; keep it.
- Writing a new rule by hand instead of capturing a signal means no evidence, so no confidence, so the
  rule never dies when it stops being true.
- Chinese text is matched on character bigrams. Two-character queries return noise; use three or more
  characters, or a term plus an ASCII word.
- `active.md` is generated. Edit `identity.md`, `now.md`, `decisions.md` instead.
- The vault is Markdown for a reason: `git diff` before committing, so a bad dream pass is reviewable.
