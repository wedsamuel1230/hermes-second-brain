"""Filesystem layer for a second-brain vault.

Everything the brain knows is plain Markdown on disk. The only structured data
is a small YAML frontmatter subset (scalars, inline lists, block lists) so a
vault stays readable, greppable and portable. Deliberately no PyYAML, no
database, no daemon.

Layout created by ``Vault.ensure``::

    brain/
      identity.md        stable facts about the person
      now.md             what is in flight right now
      decisions.md       append-only decision log with reasons
      preferences/       rules promoted from repeated signals
      inbox/             raw signals captured during work
      notes/             atomic notes, [[wikilinks]] between them
      sources/           immutable captured sources
      _meta/             config.json, index cache, dream reports
      _archive/          retired rules and expired signals
      active.md          generated digest, rebuilt by ``hsb digest``
      log.md             append-only action log
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime

FM = "---"
DIRS = (
    "preferences",
    "inbox",
    "notes",
    "sources",
    "_meta",
    "_archive/preferences",
    "_archive/signals",
)

DEFAULT_CONFIG = {
    "name": "Second Brain",
    "notes_dirs": ["notes"],
    "extra_dirs": [],
    "digest_budget": 1200,
    "dream": {"min_support": 2, "similarity": 0.62, "retire_below": 0.45, "stale_days": 120},
}

_IDENTITY = """---
title: Identity
type: identity
updated: {today}
---

# 你是誰

- （一句：身份／角色）
- （一句：長期目標）
- （一句：溝通偏好）
"""

_NOW = """---
title: Now
type: now
updated: {today}
---

# 現在

- （進行中的事，每行一項，寫到可以即刻接手）
"""

_DECISIONS = """---
title: Decisions
type: log
updated: {today}
---

# 已決定的事

格式：`## YYYY-MM-DD — 決定`，下面一行寫理由，再一行寫被否決的選項。
"""

_LOG = "# Brain log\n"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def today() -> str:
    return date.today().isoformat()


def _coerce(value: str):
    v = value.strip()
    if not v:
        return ""
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_coerce(part) for part in _split_inline(inner)]
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none", "~"):
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def _split_inline(inner: str) -> list[str]:
    out, buf, quote = [], [], ""
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf).strip())
    return out


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split ``---`` frontmatter from body. Unparseable frontmatter is ignored."""
    if not text.startswith(FM):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != FM:
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == FM:
            end = i
            break
    if end is None:
        return {}, text
    meta: dict = {}
    key = ""
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        stripped = raw.strip()
        if stripped.startswith("- ") and key:
            if not isinstance(meta.get(key), list):
                meta[key] = []
            meta[key].append(_coerce(stripped[2:]))
            continue
        body = raw.lstrip()
        if ":" not in body:
            continue
        key, _, value = body.partition(":")
        key = key.strip()
        meta[key] = _coerce(value)
    tail = "\n".join(lines[end + 1:])
    return meta, tail.lstrip("\n")


def _render_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    text = str(value)
    if text == "" or re.search(r"^[\s]|[\s]$|[:#\[\]]|^-", text):
        return '"' + text.replace('"', "'") + '"'
    return text


def dump_frontmatter(meta: dict) -> str:
    lines = [FM]
    for key, value in meta.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            inner = ", ".join(_render_scalar(v) for v in value)
            lines.append(f"{key}: [{inner}]")
        else:
            lines.append(f"{key}: {_render_scalar(value)}")
    lines.append(FM)
    return "\n".join(lines) + "\n"


def slugify(text: str, limit: int = 48) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^\w\u3400-\u4dbf\u4e00-\u9fff]+", "-", text, flags=re.UNICODE)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return (text[:limit].strip("-") or "untitled")


@dataclass
class Card:
    """One parsed Markdown file."""

    path: str            # relative to the vault root (absolute for extra dirs)
    meta: dict = field(default_factory=dict)
    body: str = ""

    @property
    def title(self) -> str:
        if self.meta.get("title"):
            return str(self.meta["title"])
        for line in self.body.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return os.path.basename(self.path).rsplit(".", 1)[0]

    @property
    def kind(self) -> str:
        return str(self.meta.get("type") or "")


class Vault:
    def __init__(self, root: str):
        self.root = os.path.abspath(os.path.expanduser(root))

    # -- paths ---------------------------------------------------------
    def p(self, rel: str) -> str:
        return os.path.join(self.root, rel)

    @property
    def identity(self) -> str:
        return self.p("identity.md")

    @property
    def now_file(self) -> str:
        return self.p("now.md")

    @property
    def decisions(self) -> str:
        return self.p("decisions.md")

    @property
    def active(self) -> str:
        return self.p("active.md")

    @property
    def log_file(self) -> str:
        return self.p("log.md")

    @property
    def index_cache(self) -> str:
        return self.p("_meta/index.json")

    @property
    def config_path(self) -> str:
        return self.p("_meta/config.json")

    # -- io ------------------------------------------------------------
    def read(self, rel: str) -> str:
        try:
            with open(self.p(rel), encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""

    def write(self, rel: str, text: str) -> str:
        """Atomic write: same-directory temp file, fsync, then os.replace.

        A reader — the per-turn hook, or `git diff` — sees either the old file or
        the new one, never a half-written one.
        """
        path = self.p(rel)
        os.makedirs(os.path.dirname(path) or self.root, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or self.root, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text if text.endswith("\n") else text + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return path

    @contextlib.contextmanager
    def locked(self, timeout: float = 15.0):
        """Exclusive vault lock, so `capture` and `dream` cannot interleave.

        flock on a file in `_meta/`; released when the process dies, so a crash
        cannot leave a stuck lock.
        """
        os.makedirs(self.p("_meta"), exist_ok=True)
        handle = open(self.p("_meta/.lock"), "a+")
        deadline = time.time() + timeout
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() > deadline:
                    handle.close()
                    raise TimeoutError(f"vault busy: another writer holds {self.p('_meta/.lock')}")
                time.sleep(0.05)
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def unique_rel(self, rel: str) -> str:
        """``rel`` if free, else the first ``-2``, ``-3`` … variant. Never overwrite."""
        if not os.path.exists(self.p(rel)):
            return rel
        base, ext = os.path.splitext(rel)
        n = 2
        while os.path.exists(self.p(f"{base}-{n}{ext}")):
            n += 1
        return f"{base}-{n}{ext}"

    def append(self, rel: str, text: str) -> None:
        current = self.read(rel)
        if current and not current.endswith("\n"):
            current += "\n"
        self.write(rel, current + (text if text.endswith("\n") else text + "\n"))

    def log(self, action: str, detail: str = "") -> None:
        line = f"- {now_iso()} · {action}" + (f" · {detail}" if detail else "")
        if not os.path.exists(self.log_file):
            self.write("log.md", _LOG)
        self.append("log.md", line)

    # -- config --------------------------------------------------------
    def config(self) -> dict:
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        try:
            with open(self.config_path, encoding="utf-8") as fh:
                stored = json.load(fh)
        except (OSError, ValueError):
            return cfg
        for key, value in stored.items():
            if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
        return cfg

    def set_config(self, **changes) -> dict:
        cfg = self.config()
        cfg.update(changes)
        self.write("_meta/config.json", json.dumps(cfg, ensure_ascii=False, indent=2))
        return cfg

    # -- scanning ------------------------------------------------------
    def ensure(self) -> "Vault":
        for rel in DIRS:
            os.makedirs(self.p(rel), exist_ok=True)
        seeds = {
            "identity.md": _IDENTITY,
            "now.md": _NOW,
            "decisions.md": _DECISIONS,
            "log.md": _LOG,
        }
        for name, body in seeds.items():
            if not os.path.exists(self.p(name)):
                self.write(name, body.format(today=today()))
        if not os.path.exists(self.config_path):
            self.write("_meta/config.json", json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2))
        return self

    def md_files(self, rel_dir: str) -> list[tuple[str, float, int]]:
        """``(relpath, mtime, size)`` for every Markdown file under ``rel_dir``."""
        base = self.p(rel_dir)
        out: list[tuple[str, float, int]] = []
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                if not name.endswith(".md"):
                    continue
                full = os.path.join(root, name)
                try:
                    stat = os.stat(full)
                except OSError:
                    continue
                out.append((os.path.relpath(full, self.root).replace(os.sep, "/"), stat.st_mtime, stat.st_size))
        out.sort()
        return out

    def card(self, rel: str) -> Card:
        meta, body = parse_frontmatter(self.read(rel))
        return Card(path=rel, meta=meta, body=body)

    def cards(self, rel_dir: str) -> list[Card]:
        return [self.card(rel) for rel, _m, _s in self.md_files(rel_dir)]

    def save_card(self, rel: str, meta: dict, body: str) -> None:
        self.write(rel, dump_frontmatter(meta) + "\n" + body.strip() + "\n")
