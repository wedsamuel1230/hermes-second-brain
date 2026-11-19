"""``hsb`` — command line for the Hermes second brain.

Every command works on one folder of Markdown, has a ``--json`` escape hatch
where it matters, and never calls a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime

from . import digest, dream, index, lint
from .store import DEFAULT_CONFIG, Vault, parse_frontmatter, slugify, today

DEFAULT_VAULT = "~/brain"


def _vault(args) -> Vault:
    root = args.vault or os.environ.get("HSB_VAULT") or DEFAULT_VAULT
    return Vault(root)


def _out(text: str) -> None:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")


# --------------------------------------------------------------------- commands
def cmd_init(args) -> int:
    vault = _vault(args)
    if os.path.exists(vault.p("_meta/config.json")) and not args.force:
        _out(f"already initialised: {vault.root} (use --force to reseed missing files)")
    vault.ensure()
    if args.name:
        vault.set_config(name=args.name)
    for extra in args.extra_dir or []:
        cfg = vault.config()
        extras = list(cfg.get("extra_dirs") or [])
        if os.path.abspath(os.path.expanduser(extra)) not in extras:
            extras.append(os.path.abspath(os.path.expanduser(extra)))
        vault.set_config(extra_dirs=extras)
    idx = index.build(vault)
    vault.write("_meta/index.json", idx.to_json())
    digest.write_active(vault)
    vault.log("init", f"docs={len(idx.docs)}")
    _out(
        f"brain ready: {vault.root}\n"
        f"  {len(idx.docs)} file(s) indexed\n"
        "next:\n"
        "  1) edit identity.md, now.md, decisions.md — that is the part only you can write\n"
        "  2) hsb capture --kind correction \"…\"  during work\n"
        "  3) hsb dream                            consolidate, then read active.md"
    )
    return 0


def cmd_capture(args) -> int:
    vault = _vault(args)
    vault.ensure()
    text = " ".join(args.text).strip()
    if not text:
        _out("nothing to capture")
        return 2
    stamp = datetime.now().astimezone()
    name = f"inbox/{stamp.strftime('%Y%m%d-%H%M%S')}-{slugify(text, 32)}.md"
    suffix = 1
    while os.path.exists(vault.p(name)):
        suffix += 1
        name = f"inbox/{stamp.strftime('%Y%m%d-%H%M%S')}-{slugify(text, 32)}-{suffix}.md"
    meta = {
        "title": text[:80],
        "type": "signal",
        "kind": args.kind,
        "text": text,
        "created": stamp.strftime("%Y-%m-%d"),
        "source": args.source or "cli",
        "status": "new",
    }
    if args.key:
        meta["key"] = args.key
    if args.note_id:
        meta["note_id"] = args.note_id
    vault.save_card(name, meta, f"# {text[:80]}\n\n{args.detail or ''}".strip())
    vault.log("capture", f"{args.kind}: {text[:60]}")
    _out(f"captured → {name}")
    return 0


def cmd_search(args) -> int:
    vault = _vault(args)
    idx = index.load(vault)
    hits = index.search(idx, " ".join(args.query), limit=args.limit)
    if args.json:
        _out(json.dumps([h.__dict__ for h in hits], ensure_ascii=False, indent=2))
        return 0
    if not hits:
        _out("no match")
        return 1
    for hit in hits:
        _out(f"{hit.score:6.2f}  {hit.line()}")
        if hit.snippet:
            _out(f"        {hit.snippet}")
    return 0


def cmd_context(args) -> int:
    vault = _vault(args)
    if not os.path.isdir(vault.root):
        return 1
    _out(digest.render(vault, " ".join(args.query or []), budget=args.budget))
    return 0


def cmd_digest(args) -> int:
    vault = _vault(args)
    text = digest.write_active(vault, budget=args.budget) if args.write else digest.render(vault, budget=args.budget)
    _out(f"→ {vault.active}" if args.write else text)
    return 0


def cmd_dream(args) -> int:
    vault = _vault(args)
    report = dream.run(vault, dry_run=args.dry_run)
    if args.json:
        _out(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        _out(report.render())
    return 0


def cmd_evidence(args) -> int:
    vault = _vault(args)
    try:
        result = dream.mark_evidence(vault, args.rule, args.outcome)
    except KeyError as exc:
        _out(str(exc))
        return 1
    _out(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_note(args) -> int:
    vault = _vault(args)
    vault.ensure()
    title = args.title.strip()
    if not title:
        _out("--title required")
        return 2
    body = args.body or ""
    if body == "-":
        body = sys.stdin.read()
    name = f"notes/{slugify(title, 60)}.md"
    if os.path.exists(vault.p(name)) and not args.force:
        _out(f"exists: {name} (use --force)")
        return 1
    links = " ".join(f"[[{l}]]" for l in (args.link or []))
    meta = {
        "title": title,
        "type": args.type,
        "tags": [t for t in (args.tags or "").split(",") if t],
        "created": today(),
        "updated": today(),
        "sources": [],
    }
    text = body.strip() or ""
    if links:
        text = (text + "\n\n" if text else "") + "相關：" + links
    vault.save_card(name, meta, f"# {title}\n\n{text}")
    vault.log("note", name)
    _out(f"note → {name}")
    return 0


def cmd_source(args) -> int:
    vault = _vault(args)
    vault.ensure()
    if args.file:
        with open(os.path.expanduser(args.file), encoding="utf-8", errors="ignore") as fh:
            body = fh.read()
    else:
        body = sys.stdin.read()
    if not body.strip():
        _out("empty source")
        return 2
    digest_hex = hashlib.sha256(body.encode("utf-8")).hexdigest()
    name = f"sources/{today()}-{slugify(args.title or args.url or 'source', 48)}.md"
    meta = {"title": args.title or args.url or "source", "type": "source",
            "source_url": args.url or "", "ingested": today(), "sha256": digest_hex}
    vault.save_card(name, meta, body)
    vault.log("source", f"{name} sha256={digest_hex[:12]}")
    _out(f"source → {name} ({digest_hex[:12]})")
    return 0


def cmd_lint(args) -> int:
    vault = _vault(args)
    issues = lint.check(vault)
    if args.json:
        _out(json.dumps(issues, ensure_ascii=False, indent=2))
    else:
        _out(lint.render(issues))
    return 1 if any(i["level"] == "error" for i in issues) else 0


def cmd_stats(args) -> int:
    vault = _vault(args)
    cfg = vault.config()
    idx = index.load(vault)
    rules = [c for c in vault.cards("preferences") if str(c.meta.get("status") or "active") == "active"]
    confs = sorted(float(c.meta.get("confidence") or 0) for c in rules)
    data = {
        "vault": vault.root,
        "indexed": len(idx.docs),
        "notes": len(vault.md_files("notes")),
        "signals_waiting": len(vault.md_files("inbox")),
        "rules": len(rules),
        "rules_median_confidence": confs[len(confs) // 2] if confs else None,
        "sources": len(vault.md_files("sources")),
        "extra_dirs": cfg.get("extra_dirs") or [],
        "digest_chars": len(digest.render(vault)),
        "index_bytes": os.path.getsize(vault.index_cache) if os.path.exists(vault.index_cache) else 0,
    }
    if args.json:
        _out(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        _out("\n".join(f"{k}: {v}" for k, v in data.items()))
    return 0


def cmd_config(args) -> int:
    vault = _vault(args)
    cfg = vault.config()
    if not args.pairs:
        _out(json.dumps(cfg, ensure_ascii=False, indent=2))
        return 0
    for pair in args.pairs:
        if "=" not in pair:
            _out(f"ignoring {pair!r}; use key=value")
            continue
        key, _, raw = pair.partition("=")
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw
        node = cfg
        parts = key.split(".")
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value
    vault.write("_meta/config.json", json.dumps(cfg, ensure_ascii=False, indent=2))
    _out(json.dumps(cfg, ensure_ascii=False, indent=2))
    return 0


# ------------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hsb", description="Hermes second brain — plain Markdown, deterministic loop")
    parser.add_argument("--vault", help=f"brain folder (default: $HSB_VAULT or {DEFAULT_VAULT})")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create the folder layout and seed files")
    p.add_argument("--name", help="capsule name shown in the digest")
    p.add_argument("--extra-dir", action="append", help="additional read-only notes folder to index")
    p.add_argument("--force", action="store_true", help="reseed missing files in an existing vault")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("capture", help="record a signal (correction / preference / decision / fact)")
    p.add_argument("text", nargs="+")
    p.add_argument("--kind", default="correction", choices=list(dream.KINDS))
    p.add_argument("--key", help="stable key to merge this signal with earlier ones")
    p.add_argument("--source", help="where it came from (discord, code-review, …)")
    p.add_argument("--detail", help="extra context kept in the body")
    p.add_argument("--note-id", dest="note_id", help="link to a note or rule id")
    p.set_defaults(func=cmd_capture)

    p = sub.add_parser("search", help="keyword search over the vault")
    p.add_argument("query", nargs="+")
    p.add_argument("-k", "--limit", type=int, default=5)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("context", help="print the per-turn context block")
    p.add_argument("query", nargs="*")
    p.add_argument("--budget", type=int)
    p.set_defaults(func=cmd_context)

    p = sub.add_parser("digest", help="render or write active.md")
    p.add_argument("--write", action="store_true")
    p.add_argument("--budget", type=int)
    p.set_defaults(func=cmd_digest)

    p = sub.add_parser("dream", help="consolidate signals into rules, retire, decay, rebuild")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_dream)

    p = sub.add_parser("evidence", help="mark a rule applied or violated")
    p.add_argument("rule")
    p.add_argument("outcome", choices=["applied", "violated"])
    p.set_defaults(func=cmd_evidence)

    p = sub.add_parser("note", help="create an atomic note")
    p.add_argument("--title", required=True)
    p.add_argument("--type", default="concept")
    p.add_argument("--tags", default="")
    p.add_argument("--link", action="append", help="wikilink target (repeatable)")
    p.add_argument("--body", default="", help="note body, or - to read stdin")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_note)

    p = sub.add_parser("source", help="store an immutable source with its sha256")
    p.add_argument("--url")
    p.add_argument("--title")
    p.add_argument("--file", help="read body from this file instead of stdin")
    p.set_defaults(func=cmd_source)

    p = sub.add_parser("lint", help="check frontmatter, links, orphans, backlog")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("stats", help="one-screen state of the brain")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("config", help="show or set _meta/config.json")
    p.add_argument("pairs", nargs="*", help="key=value")
    p.set_defaults(func=cmd_config)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
