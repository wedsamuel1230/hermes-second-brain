#!/usr/bin/env python3
"""Hermes ``pre_llm_call`` hook: put the brain in front of the model every turn.

Hermes pipes a JSON object on stdin and reads ``{"context": "..."}`` on stdout.
This script injects:

1. the current digest — who the user is, what is in flight, promoted rules and
   the newest decisions, capped at ``hook_budget`` characters (default 700);
2. the two best matching note paths for this message, never their text.

Why a hook and not a file in the system prompt: memory and SOUL.md are frozen at
session start, so anything learned mid-session is invisible until the next one.
The digest is rebuilt from the files on every call and stays a fixed size.

Fail-open by design: any error prints nothing and the turn continues. A drop of
30 ms beats a refused turn.

Install (see docs/install-hermes.md):

    HSB_VAULT=~/brain  hsb init
    hermes config set hooks.pre_llm_call '[…,{"command":"…/hooks/brain-context.py","timeout":5}]'
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

DEFAULT_VAULT = "~/brain"
MIN_MESSAGE_CHARS = 3
DEFAULT_BUDGET = 700


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    message = (payload.get("user_message") or payload.get("prompt") or "").strip()
    if len(message) < MIN_MESSAGE_CHARS or message.startswith("/"):
        return

    vault_path = os.environ.get("HSB_VAULT") or payload.get("vault") or DEFAULT_VAULT
    vault_path = os.path.abspath(os.path.expanduser(vault_path))
    if not os.path.isdir(vault_path):
        return

    try:
        from hsb import digest
        from hsb.store import Vault

        vault = Vault(vault_path)
        cfg = vault.config()
        budget = int(cfg.get("hook_budget") or DEFAULT_BUDGET)
        text = digest.render(vault, message, budget=budget)
    except Exception:
        return
    if not text.strip():
        return
    sys.stdout.write(json.dumps({"context": text}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
