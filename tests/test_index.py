import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hsb import index  # noqa: E402
from hsb.store import Vault  # noqa: E402


def make_vault(root):
    vault = Vault(root).ensure()
    vault.save_card(
        "notes/lvgl-widget-perf.md",
        {"title": "LVGL 元件效能", "type": "concept", "tags": ["product"]},
        "# LVGL 元件效能\n\n垃圾桶 UI 在 ESP32-S3 上面更新太慢，改用 partial redraw。\n",
    )
    vault.save_card(
        "notes/bottlesumo-rule.md",
        {"title": "BottleSumo 比賽規則", "type": "concept", "tags": ["product"]},
        "# BottleSumo 比賽規則\n\n3 分鐘一局，出界即負。見 [[lvgl-widget-perf]]。\n",
    )
    vault.save_card(
        "notes/esp32-pinout.md",
        {"title": "ESP32-S3 pinout", "type": "concept", "tags": ["hardware"]},
        "# ESP32-S3 pinout\n\nGPIO45 是 strapping pin，開機時不要拉低。\n",
    )
    return vault


class IndexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = make_vault(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_counts_every_file(self):
        idx = index.build(self.vault)
        paths = {d["p"] for d in idx.docs}
        self.assertIn("identity.md", paths)
        self.assertIn("notes/lvgl-widget-perf.md", paths)
        self.assertEqual(len(idx.docs), 6)

    def test_cjk_query_hits_right_note(self):
        idx = index.build(self.vault)
        hits = index.search(idx, "LVGL 更新太慢")
        self.assertTrue(hits)
        self.assertEqual(hits[0].path, "notes/lvgl-widget-perf.md")

    def test_ascii_query(self):
        idx = index.build(self.vault)
        hits = index.search(idx, "strapping pin GPIO45")
        self.assertEqual(hits[0].path, "notes/esp32-pinout.md")

    def test_unrelated_query_returns_nothing(self):
        idx = index.build(self.vault)
        self.assertEqual(index.search(idx, "今日天氣點呀"), [])

    def test_both_matching_notes_come_back(self):
        idx = index.build(self.vault)
        hits = index.search(idx, "元件效能 比賽規則")
        paths = [h.path for h in hits]
        self.assertIn("notes/lvgl-widget-perf.md", paths)
        self.assertIn("notes/bottlesumo-rule.md", paths)

    def test_cache_is_reused_then_invalidated(self):
        first = index.load(self.vault)
        self.assertTrue(os.path.exists(self.vault.index_cache))
        second = index.load(self.vault)
        self.assertEqual(first.signature, second.signature)
        self.vault.save_card("notes/new-note.md",
                             {"title": "新筆記", "type": "concept"},
                             "# 新筆記\n\n關於 hermes 的 cron 排程。\n")
        third = index.load(self.vault)
        self.assertNotEqual(first.signature, third.signature)
        self.assertEqual(len(third.docs), len(first.docs) + 1)


if __name__ == "__main__":
    unittest.main()
