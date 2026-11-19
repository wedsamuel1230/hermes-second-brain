"""Regression tests for the five council blockers (round 1).

Each test names the defect it locks down, so a future change that reintroduces
the behaviour fails here instead of in production.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hsb import cli, digest, dream, index  # noqa: E402
from hsb.store import Vault, today  # noqa: E402


def signal(vault, name, text, created=None, key=None, kind="correction"):
    meta = {"title": text[:60], "type": "signal", "kind": kind, "text": text,
            "created": created or today(), "source": "test", "status": "new"}
    if key:
        meta["key"] = key
    vault.save_card(f"inbox/{name}.md", meta, f"# {text[:60]}\n")
    return f"inbox/{name}.md"


def rule(vault, rid, text, support=2, applied=0, violated=0, last_used=None, key=None):
    meta = {"title": text, "type": "preference", "id": rid, "rule": text, "key": key or rid,
            "confidence": dream._confidence(support, applied, violated), "support": support,
            "applied": applied, "violated": violated, "status": "active",
            "created": "2026-01-01", "updated": "2026-01-01",
            "last_used": last_used or today(), "evidence": ["2026-01-01"]}
    vault.save_card(f"preferences/{rid}.md", meta, f"# {text}\n\n## 來源訊號\n\n- 2026-01-01 · test · {text}\n")


class SupportAndDuplicateTest(unittest.TestCase):
    """B2: `max(dates, signals)` ignored duplicates. Support now counts units."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Vault(self.tmp.name).ensure()

    def tearDown(self):
        self.tmp.cleanup()

    def test_identical_same_day_capture_is_one_occurrence(self):
        signal(self.vault, "s1", "唔好加 emoji")
        signal(self.vault, "s2", "唔好加 emoji")
        report = dream.run(self.vault)
        self.assertEqual(report.promoted, [])
        self.assertEqual(len(self.vault.md_files("inbox")), 2)

    def test_two_different_wordings_promote(self):
        signal(self.vault, "s1", "回覆唔好加 emoji")
        signal(self.vault, "s2", "唔好加 emoji")
        report = dream.run(self.vault)
        self.assertEqual(len(report.promoted), 1)
        self.assertEqual(report.promoted[0]["support"], 2)

    def test_same_text_across_two_days_counts_twice(self):
        signal(self.vault, "s1", "用繁體中文回覆", created="2026-11-01")
        signal(self.vault, "s2", "用繁體中文回覆", created="2026-11-05")
        report = dream.run(self.vault)
        self.assertEqual(len(report.promoted), 1)
        self.assertEqual(report.promoted[0]["support"], 2)


class NegationConflictTest(unittest.TestCase):
    """B4: lexical similarity must not merge opposite statements."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Vault(self.tmp.name).ensure()

    def tearDown(self):
        self.tmp.cleanup()

    def test_opposite_polarity_never_promotes(self):
        signal(self.vault, "s1", "回覆加 emoji")
        signal(self.vault, "s2", "回覆唔好加 emoji")
        report = dream.run(self.vault)
        self.assertEqual(report.promoted, [])
        self.assertEqual(len(report.conflicts), 1)
        self.assertEqual(self.vault.cards("preferences"), [])
        self.assertEqual(len(self.vault.md_files("inbox")), 2)

    def test_conflict_reported_in_report_file(self):
        signal(self.vault, "s1", "回覆加 emoji")
        signal(self.vault, "s2", "回覆唔好加 emoji")
        dream.run(self.vault)
        text = self.vault.read(f"_meta/dream-{today()}.md")
        self.assertIn("矛盾", text)

    def test_politeness_is_not_negation(self):
        signal(self.vault, "s1", "唔該幫我出報告")
        signal(self.vault, "s2", "幫我出報告")
        report = dream.run(self.vault)
        self.assertEqual(report.conflicts, [])
        self.assertEqual(len(report.promoted), 1)


class DecayTest(unittest.TestCase):
    """B1: decay was applied nightly and then recomputed away."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Vault(self.tmp.name).ensure()

    def tearDown(self):
        self.tmp.cleanup()

    def test_decay_is_one_step_per_stale_period_and_idempotent(self):
        old = "2026-05-01"                     # > 120 days before today
        rule(self.vault, "P-old", "舊規則", support=2, last_used=old)
        first = dream.run(self.vault)
        self.assertIn("P-old", first.decayed)
        conf_after_first = float(self.vault.card("preferences/P-old.md").meta["confidence"])
        self.assertAlmostEqual(conf_after_first, round(dream._confidence(2, 0, 0) * 0.85, 3), places=3)

        second = dream.run(self.vault)
        self.assertEqual(second.decayed, [])
        conf_after_second = float(self.vault.card("preferences/P-old.md").meta["confidence"])
        self.assertEqual(conf_after_first, conf_after_second)

    def test_fully_unused_rule_finally_retires(self):
        rule(self.vault, "P-ancient", "極舊規則", support=1, last_used="2020-01-01")
        report = dream.run(self.vault)
        self.assertIn("P-ancient", report.retired)
        self.assertEqual(self.vault.cards("preferences"), [])


class IdempotenceTest(unittest.TestCase):
    """B3: a reviewable pass must be stable when run twice on the same input."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Vault(self.tmp.name).ensure()

    def tearDown(self):
        self.tmp.cleanup()

    def test_second_run_changes_no_content(self):
        signal(self.vault, "s1", "回覆唔好加 emoji")
        signal(self.vault, "s2", "唔好加 emoji")
        dream.run(self.vault)
        before = {rel: self.vault.read(rel) for rel in
                  [p for p, _m, _s in self.vault.md_files("preferences")]
                  + ["active.md", "now.md", "decisions.md"]}
        dream.run(self.vault)
        after = {rel: self.vault.read(rel) for rel in before}
        self.assertEqual(before, after)


class SupersedeTest(unittest.TestCase):
    """B1 (kimi): a newer wording for the same key must win, with history kept."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Vault(self.tmp.name).ensure()

    def tearDown(self):
        self.tmp.cleanup()

    def test_newest_phrasing_becomes_the_rule(self):
        rule(self.vault, "P-lang", "用中文回覆", key="reply-language", last_used=today())
        signal(self.vault, "s1", "用繁體中文回覆，英文技術詞保留原文",
               created=today(), key="reply-language")
        report = dream.run(self.vault)
        self.assertEqual(len(report.reinforced), 1)
        card = self.vault.card("preferences/P-lang.md")
        self.assertIn("繁體中文", card.meta["rule"])
        self.assertEqual(card.meta["superseded"], ["用中文回覆"])
        self.assertIn("用中文回覆", card.body)


class ArchiveCollisionTest(unittest.TestCase):
    """B3: two archived files with one basename must both survive."""

    def test_colliding_basenames_are_kept(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Vault(d).ensure()
            os.makedirs(vault.p("_archive/signals"), exist_ok=True)
            vault.write("_archive/signals/x.md", "old")
            signal(vault, "x", "唔好加 emoji")
            signal(vault, "y", "回覆唔好加 emoji")
            dream.run(vault)
            files = os.listdir(vault.p("_archive/signals"))
            self.assertIn("x.md", files)
            self.assertIn("x-2.md", files)
            self.assertEqual(vault.read("_archive/signals/x.md").strip(), "old")


class RetrievalGateTest(unittest.TestCase):
    """B5: short/CJK/exact-title queries must not be rejected by the 2-term gate."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Vault(self.tmp.name).ensure()
        self.vault.save_card("notes/lvgl.md", {"title": "LVGL 效能", "type": "concept"},
                             "# LVGL 效能\n\npartial redraw 令更新變快。\n")
        self.vault.save_card("notes/pin.md", {"title": "ESP32-S3 pinout", "type": "concept"},
                             "# ESP32-S3 pinout\n\nGPIO45 係 strapping pin。\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_title_short_circuits(self):
        idx = index.build(self.vault)
        hits = index.search(idx, "LVGL 效能")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].path, "notes/lvgl.md")
        self.assertEqual(hits[0].score, 999.0)

    def test_single_rare_term_matches(self):
        idx = index.build(self.vault)
        hits = index.search(idx, "GPIO45")
        self.assertTrue(hits)
        self.assertEqual(hits[0].path, "notes/pin.md")


class LockAndCaptureTest(unittest.TestCase):
    """B3 + degenerate input."""

    def test_second_writer_times_out(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Vault(d).ensure()
            with vault.locked():
                other = Vault(d)
                with self.assertRaises(TimeoutError):
                    with other.locked(timeout=0.2):
                        pass

    def test_punctuation_only_capture_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            code = cli.main(["--vault", d, "init"])
            self.assertEqual(code, 0)
            code = cli.main(["--vault", d, "capture", "。"])
            self.assertEqual(code, 2)
            self.assertEqual(Vault(d).md_files("inbox"), [])


class NumericConflictTest(unittest.TestCase):
    """B11 (grok): a changed number is a new value, not a repeat."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Vault(self.tmp.name).ensure()

    def tearDown(self):
        self.tmp.cleanup()

    def test_different_numbers_never_promote(self):
        signal(self.vault, "s1", "簡報每頁 3 個重點")
        signal(self.vault, "s2", "簡報每頁 5 個重點")
        report = dream.run(self.vault)
        self.assertEqual(report.promoted, [])
        self.assertEqual(len(report.conflicts), 1)

    def test_same_number_still_promotes(self):
        signal(self.vault, "s1", "簡報每頁 3 個重點")
        signal(self.vault, "s2", "每頁簡報 3 個重點")
        report = dream.run(self.vault)
        self.assertEqual(len(report.promoted), 1)
        self.assertEqual(report.conflicts, [])

    def test_chinese_negators_beyond_wu(self):
        signal(self.vault, "s1", "要開冷氣")
        signal(self.vault, "s2", "不要開冷氣")
        report = dream.run(self.vault)
        self.assertEqual(report.promoted, [])
        self.assertEqual(len(report.conflicts), 1)


class HookFailOpenTest(unittest.TestCase):
    """B13 (grok): the hook must exit 0 and stay silent when anything breaks."""

    HOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "hooks", "brain-context.py")

    def _run(self, payload, vault):
        env = dict(os.environ, HSB_VAULT=vault)
        return subprocess.run([sys.executable, self.HOOK], input=payload, text=True,
                              capture_output=True, env=env, timeout=30)

    def test_invalid_stdin_exits_zero(self):
        proc = self._run("{not json", "/nonexistent")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")

    def test_corrupt_config_still_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Vault(d).ensure()
            os.remove(vault.config_path)
            os.makedirs(vault.config_path)          # a directory where a file belongs
            proc = self._run('{"user_message":"hello there"}', d)
            self.assertEqual(proc.returncode, 0)
            if proc.stdout.strip():
                data = json.loads(proc.stdout)
                self.assertLessEqual(len(data["context"]), 700)

    def test_missing_vault_is_silent(self):
        proc = self._run('{"user_message":"hello there"}', "/nonexistent/vault")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")


class SmallVaultRetrievalTest(unittest.TestCase):
    """B12 (grok): the rare-term gate must work on a 10-note vault, not only ≥20."""

    def test_hapax_matches_in_small_vault(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Vault(d).ensure()
            for i in range(9):
                vault.save_card(f"notes/n{i}.md", {"title": f"一般筆記 {i}", "type": "concept"},
                                 f"# 一般筆記 {i}\n\n普通內容。\n")
            vault.save_card("notes/zed.md", {"title": "歷史人物", "type": "concept"},
                            "# 歷史人物\n\nZedekiah 係猶大王。\n")
            idx = index.build(vault)
            hits = index.search(idx, "Zedekiah")
            self.assertTrue(hits)
            self.assertEqual(hits[0].path, "notes/zed.md")


class AntonymConflictTest(unittest.TestCase):
    """B14 (grok): opposite values that share no negator must not become two rules."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Vault(self.tmp.name).ensure()

    def tearDown(self):
        self.tmp.cleanup()

    def test_dark_and_light_never_both_promote(self):
        signal(self.vault, "d1", "prefer dark mode")
        signal(self.vault, "d2", "dark mode preferred")
        signal(self.vault, "l1", "prefer light mode")
        signal(self.vault, "l2", "light mode preferred")
        report = dream.run(self.vault)
        self.assertLessEqual(len(report.promoted), 1)
        self.assertGreaterEqual(len(report.conflicts), 1)
        self.assertEqual(len(self.vault.cards("preferences")), len(report.promoted))

    def test_kai_and_gwun_conflict(self):
        signal(self.vault, "s1", "客廳要開冷氣")
        signal(self.vault, "s2", "客廳要開冷氣啦")
        signal(self.vault, "s3", "客廳要關冷氣")
        signal(self.vault, "s4", "客廳要關冷氣啦")
        report = dream.run(self.vault)
        self.assertLessEqual(len(report.promoted), 1)
        self.assertGreaterEqual(len(report.conflicts), 1)

    def test_unrelated_characters_do_not_conflict(self):
        signal(self.vault, "s1", "開會準備資料")
        signal(self.vault, "s2", "關門時間確認")
        report = dream.run(self.vault)
        self.assertEqual(report.conflicts, [])

    def test_english_word_boundaries(self):
        # "on" must not match inside "content" or "only"
        signal(self.vault, "s1", "turn on the cache")
        signal(self.vault, "s2", "cache only content")
        report = dream.run(self.vault)
        self.assertEqual(report.conflicts, [])


class DigestConflictFilterTest(unittest.TestCase):
    """B14: even if two opposite rules exist on disk, the digest carries one."""

    def test_newest_of_a_contradiction_wins(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Vault(d).ensure()
            vault.save_card("preferences/P-a.md",
                            {"title": "客廳要開冷氣", "type": "preference", "id": "P-a",
                             "rule": "客廳要開冷氣", "confidence": 0.8, "applied": 2, "violated": 0,
                             "status": "active", "last_used": "2026-10-01"}, "# 客廳要開冷氣\n")
            vault.save_card("preferences/P-b.md",
                            {"title": "客廳要關冷氣", "type": "preference", "id": "P-b",
                             "rule": "客廳要關冷氣", "confidence": 0.7, "applied": 1, "violated": 0,
                             "status": "active", "last_used": "2026-11-01"}, "# 客廳要關冷氣\n")
            text = digest.render(vault)
            self.assertIn("客廳要關冷氣", text)
            self.assertNotIn("客廳要開冷氣", text)


class SupersedeLiveRuleTest(unittest.TestCase):
    """B16 (grok): a later opposite must be able to replace a live rule."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Vault(self.tmp.name).ensure()

    def tearDown(self):
        self.tmp.cleanup()

    def test_later_statement_replaces_live_rule(self):
        rule(self.vault, "P-cold", "客廳要開冷氣", last_used="2026-10-01")
        signal(self.vault, "s1", "客廳要關冷氣")
        signal(self.vault, "s2", "客廳要關冷氣啦")
        report = dream.run(self.vault)
        self.assertEqual(len(report.promoted), 1)
        self.assertEqual(len(report.superseded), 1)
        live = [c for c in self.vault.cards("preferences")]
        self.assertEqual(len(live), 1)
        self.assertIn("關冷氣", live[0].meta["rule"])
        self.assertIn("客廳要關冷氣", digest.render(self.vault))

    def test_same_day_clash_waits_for_a_human(self):
        rule(self.vault, "P-cold", "客廳要開冷氣", last_used=today())
        signal(self.vault, "s1", "客廳要關冷氣")
        signal(self.vault, "s2", "客廳要關冷氣啦")
        report = dream.run(self.vault)
        self.assertEqual(report.promoted, [])
        self.assertEqual(report.superseded, [])
        self.assertEqual(len(report.conflicts), 1)
        self.assertEqual(len(self.vault.cards("preferences")), 1)

    def test_ascii_unrelated_sentences_do_not_clash(self):
        signal(self.vault, "s1", "keep the porch light on after sunset")
        signal(self.vault, "s2", "turn off notifications at 22:00")
        report = dream.run(self.vault)
        self.assertEqual(report.conflicts, [])


class DigestBudgetTest(unittest.TestCase):
    """B2 (gpt): the budget holds for CJK text, not just ASCII."""

    def test_cjk_budget_never_exceeded(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Vault(d).ensure()
            vault.save_card("identity.md", {"title": "Identity", "type": "identity"},
                             "# 你是誰\n\n- " + "測試中文內容" * 60 + "\n")
            vault.save_card("now.md", {"title": "Now", "type": "now"},
                             "# 現在\n\n- " + "進行中的事情" * 40 + "\n")
            for budget in (40, 80, 120, 200, 700):
                text = digest.render(vault, "查詢", budget=budget)
                self.assertLessEqual(len(text), budget, f"budget {budget}")

    def test_stale_dream_is_announced(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Vault(d).ensure()
            digest.write_active(vault)
            old = time.time() - 3 * 86400
            os.utime(vault.active, (old, old))
            text = digest.render(vault)
            self.assertIn("dream 已 3 日未跑", text)


if __name__ == "__main__":
    unittest.main()
