import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hsb import digest  # noqa: E402
from hsb.index import build  # noqa: E402
from hsb.store import Vault, today  # noqa: E402


class DigestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Vault(self.tmp.name).ensure()
        self.vault.save_card("identity.md", {"title": "Identity", "type": "identity"},
                             "# 你是誰\n\n- 電子工程學生\n- 目標：嵌入式工程師\n")
        self.vault.save_card("now.md", {"title": "Now", "type": "now"},
                             "# 現在\n\n- BottleSumo 無線調參\n- 智能垃圾桶 UI 改版\n")
        self.vault.save_card("decisions.md", {"title": "Decisions", "type": "log"},
                             "# 已決定的事\n\n## 2026-11-10 — 用 LVGL 8\n\n官方 8.x 分支穩定。\n\n"
                             "## 2026-11-12 — 角色改名綠豆\n\n舊名對外不可再用。\n")
        for rid, text, conf in (("P-1", "回覆用繁體中文", 0.82), ("P-2", "唔好加 emoji", 0.75),
                                ("P-3", "簡報每頁三個重點", 0.61)):
            self.vault.save_card(f"preferences/{rid}.md",
                                 {"title": text, "type": "preference", "id": rid, "rule": text,
                                  "confidence": conf, "applied": 2, "violated": 0, "status": "active"},
                                 f"# {text}\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_sections_present(self):
        text = digest.render(self.vault)
        self.assertIn("你是誰", text)
        self.assertIn("電子工程學生", text)
        self.assertIn("現在", text)
        self.assertIn("BottleSumo", text)
        self.assertIn("規則", text)
        self.assertIn("最近決定", text)

    def test_rules_sorted_by_confidence(self):
        text = digest.render(self.vault)
        self.assertLess(text.index("回覆用繁體中文"), text.index("簡報每頁三個重點"))

    def test_decisions_ordered_by_heading_date(self):
        text = digest.render(self.vault)
        self.assertLess(text.index("2026-11-12"), text.index("2026-11-10"))

    def test_long_bullet_is_clamped(self):
        self.vault.save_card("identity.md", {"title": "Identity", "type": "identity"},
                             "# 你是誰\n\n- " + "長" * 400 + "\n")
        text = digest.render(self.vault)
        self.assertLess(text.count("長"), 120)

    def test_budget_is_respected(self):
        text = digest.render(self.vault, budget=200)
        self.assertLessEqual(len(text), 200)
        self.assertIn("你是誰", text)

    def test_message_adds_matching_notes(self):
        self.vault.save_card("notes/lvgl-perf.md", {"title": "LVGL 效能", "type": "concept"},
                             "# LVGL 效能\n\npartial redraw 令更新變快。\n")
        text = digest.render(self.vault, "LVGL 更新點解咁慢")
        self.assertIn("notes/lvgl-perf.md", text)

    def test_write_active(self):
        digest.write_active(self.vault)
        raw = self.vault.read("active.md")
        self.assertTrue(raw.startswith("---\ntitle: Active"))
        self.assertIn(today(), raw)

    def test_empty_vault_still_renders(self):
        with tempfile.TemporaryDirectory() as other:
            vault = Vault(other).ensure()
            text = digest.render(vault)
            self.assertTrue(text.startswith("[Second Brain]"))


if __name__ == "__main__":
    unittest.main()
