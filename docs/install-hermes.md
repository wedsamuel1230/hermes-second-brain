# Installing into Hermes

Three pieces: a shell hook (puts the digest in front of every turn), a skill (tells the agent when to
write back), and a nightly cron job (runs the consolidation). The CLI works without any of them.

Assumes Hermes is installed and `hermes` is on `PATH`. `$HERMES_HOME` is normally `~/.hermes`.

## 1. Vault

```bash
git clone https://github.com/wedsamuel1230/hermes-second-brain ~/hermes-second-brain
cd ~/hermes-second-brain
./bin/hsb init --name "Second Brain" --extra-dir ~/wiki     # --extra-dir is optional
```

Edit three files. This is the only part that cannot be automated, and the only part that makes the digest
worth injecting:

```bash
$EDITOR ~/brain/identity.md    # 3 bullets: who you are, long-term goal, how you want replies
$EDITOR ~/brain/now.md         # 3 bullets: what is in flight, written so anyone could pick it up
$EDITOR ~/brain/decisions.md   # dated decisions with the reason and the rejected option
```

Put the vault somewhere that survives container rebuilds. On a Home Assistant OS add-on, `/config` or
`/share` — not `/tmp`.

## 2. Hook

```bash
chmod +x ~/hermes-second-brain/hooks/brain-context.py
hermes config get hooks.pre_llm_call          # see what is already there
```

Append one entry, keeping the existing ones:

```bash
hermes config set hooks.pre_llm_call '[
  {"command":"/config/.hermes/agent-hooks/disclosure.py","timeout":10},
  {"command":"/config/.hermes/agent-hooks/task-contract.py","timeout":10},
  {"command":"/config/.hermes/agent-hooks/wiki-recall.py","timeout":5},
  {"command":"/config/projects/hermes-second-brain/hooks/brain-context.py","timeout":5}
]'
```

Use absolute paths. The hook reads the vault from `$HSB_VAULT`, then from the payload, then `~/brain`. If
the vault lives elsewhere, export it where the gateway can see it:

```bash
echo 'export HSB_VAULT=/config/brain' >> ~/.hermes/.env
```

First run asks for consent and records it in `$HERMES_HOME/shell-hooks-allowlist.json`. Check the result:

```bash
hermes hooks list
hermes hooks test pre_llm_call      # fires every hook with a synthetic payload and times it
hermes hooks doctor                 # exec bit, allowlist, mtime drift, JSON validity
```

Hooks are registered at gateway start: restart the gateway (or open a new CLI session) before expecting
the digest to appear.

Manual check, same content the hook would return:

```bash
echo '{"user_message":"幫我排下畫嘅工作"}' | HSB_VAULT=~/brain ~/hermes-second-brain/hooks/brain-context.py
```

## 3. Skill

```bash
mkdir -p $HERMES_HOME/skills/productivity
cp -r ~/hermes-second-brain/skills/hermes-second-brain $HERMES_HOME/skills/productivity/
```

The skill tells the agent to read the digest before answering, to capture a signal when it is corrected,
to mark evidence when a rule is confirmed or broken, and to write a note when it learns something with a
source. Without the skill the hook still injects context, but nothing gets written back.

## 4. Nightly consolidation

Through Hermes (survives restarts, delivers into chat):

```text
cronjob_manage action=create
name="brain dream"
schedule="0 3 * * *"
prompt="Run `hsb --vault /config/brain dream`, then read the report it printed. "
       "If promoted rules > 0, list each rule in one line. If retired > 0, name them. "
       "Do not invent rules; do not edit files by hand."
enabled_toolsets=["terminal"]
delivery="local"
```

Or with cron, no Hermes involved:

```cron
0 3 * * * HSB_VAULT=/config/brain /config/projects/hermes-second-brain/bin/hsb dream >> ~/brain/_meta/cron.log 2>&1
```

Keep the cadence nightly even if nothing changes: the pass is also what rebuilds the index and the digest,
and an empty report is one line.

## 5. One line in AGENTS.md

So a future session knows the vault exists without loading a skill:

```markdown
- 第二大腦：`/config/brain`（identity／now／decisions／preferences）。答之前睇 digest，學到嘢就 `hsb capture`。
```

## 6. Verify

```bash
hsb --vault ~/brain stats
hsb --vault ~/brain context "test message"
hsb --vault ~/brain lint
echo '{"user_message":"test message"}' | HSB_VAULT=~/brain ~/hermes-second-brain/hooks/brain-context.py
```

`stats` should show `indexed > 0`. If `digest_chars` is 71 on a real vault, the seed files are still
placeholders — write `identity.md`.

## 7. Rollback

```bash
hermes config unset hooks.pre_llm_call          # or set the array back to the original three
hermes hooks revoke /config/projects/hermes-second-brain/hooks/brain-context.py
rm -rf $HERMES_HOME/skills/productivity/hermes-second-brain
```

The vault itself needs no rollback: it is Markdown. `rm -rf ~/brain/_meta/index.json` and the next call
rebuilds it.
