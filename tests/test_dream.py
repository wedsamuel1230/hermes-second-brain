import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hsb import dream  # noqa: E402
from hsb.store import Vault, today  # noqa: E402


def signal(vault, name, text, kind="correction", created=None, key=None, source="test"):
    meta = {"title": text[:60], "type": "signal", "kind": kind, "text": text,
            "created": created or today(), "source": source, "status": "new"}
    if key:
        meta["key"] = key
    vault.save_card(f"inbox/{name}.md", meta, f"# {text[:60]}\n")
    return f"inbox/{name}.md"


class DreamTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Vault(self.tmp.name).ensure()

    def tearDown(self):
        self.tmp.cleanup()

    def test_two_repeat_signals_become_one_rule(self):
        signal(self.vault, "s1", "回覆唔好加 emoji")
        signal(self.vault, "s2", "唔好加 emoji")
        report = dream.run(self.vault)
        self.assertEqual(len(report.promoted), 1)
        self.assertEqual(report.promoted[0]["support"], 2)
        self.assertAlmostEqual(report.promoted[0]["confidence"], 0.75, places=3)

        rules = self.vault.cards("preferences")
        self.assertEqual(len(rules), 1)
        rule = rules[0]
        self.assertIn("emoji", rule.meta["rule"])
        self.assertEqual(len(rule.meta["evidence"]), 1)   # both signals share one date
        self.assertEqual(rule.meta["status"], "active")

    def test_promoted_signals_are_archived_not_deleted(self):
        signal(self.vault, "s1", "唔好加 emoji")
        signal(self.vault, "s2", "回覆唔好加 emoji")
        report = dream.run(self.vault)
        self.assertEqual(report.archived_signals, 2)
        self.assertEqual(self.vault.md_files("inbox"), [])
        archived = os.listdir(self.vault.p("_archive/signals"))
        self.assertEqual(len(archived), 2)

    def test_single_signal_waits_for_support(self):
        signal(self.vault, "s1", "每頁簡報不超過三個重點")
        report = dream.run(self.vault)
        self.assertEqual(report.promoted, [])
        self.assertEqual(len(self.vault.md_files("inbox")), 1)
        self.assertEqual(self.vault.cards("preferences"), [])

    def test_same_key_merges_even_when_worded_differently(self):
        signal(self.vault, "s1", "用繁體中文回覆", key="reply-language")
        signal(self.vault, "s2", "英文技術詞保留原文", key="reply-language")
        report = dream.run(self.vault)
        self.assertEqual(len(report.promoted), 1)
        self.assertEqual(report.promoted[0]["support"], 2)

    def test_evidence_moves_confidence_both_ways(self):
        signal(self.vault, "s1", "唔好加 emoji")
        signal(self.vault, "s2", "回覆唔好加 emoji")
        report = dream.run(self.vault)
        rid = self.vault.cards("preferences")[0].meta["id"]

        up = dream.mark_evidence(self.vault, rid, "applied")
        self.assertGreater(up["confidence"], report.promoted[0]["confidence"])
        down = [dream.mark_evidence(self.vault, rid, "violated") for _ in range(4)]
        self.assertLess(down[-1]["confidence"], down[0]["confidence"])
        self.assertLess(down[-1]["confidence"], 0.45)

        second = dream.run(self.vault)
        self.assertIn(rid, second.retired)
        self.assertEqual(self.vault.cards("preferences"), [])
        self.assertTrue(os.path.exists(self.vault.p(f"_archive/preferences/")))

    def test_dry_run_writes_nothing(self):
        signal(self.vault, "s1", "唔好加 emoji")
        signal(self.vault, "s2", "回覆唔好加 emoji")
        before = sorted(os.listdir(self.vault.p("inbox")))
        report = dream.run(self.vault, dry_run=True)
        self.assertEqual(len(report.promoted), 1)
        self.assertEqual(sorted(os.listdir(self.vault.p("inbox"))), before)
        self.assertEqual(self.vault.cards("preferences"), [])
        self.assertFalse(os.path.exists(self.vault.active))

    def test_report_is_written(self):
        signal(self.vault, "s1", "唔好加 emoji")
        signal(self.vault, "s2", "唔好加 emoji")
        dream.run(self.vault)
        path = self.vault.p(f"_meta/dream-{today()}.md")
        self.assertTrue(os.path.exists(path))
        self.assertIn("新規則", self.vault.read(f"_meta/dream-{today()}.md"))
        self.assertTrue(os.path.exists(self.vault.active))

    def test_expired_signal_is_archived(self):
        signal(self.vault, "old", "很久以前的單次觀察", created="2026-01-01")
        report = dream.run(self.vault)
        self.assertEqual(report.expired_signals, 1)
        self.assertEqual(self.vault.md_files("inbox"), [])


if __name__ == "__main__":
    unittest.main()
