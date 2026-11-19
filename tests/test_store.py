import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hsb.store import (  # noqa: E402
    Vault,
    dump_frontmatter,
    parse_frontmatter,
    slugify,
)


class FrontmatterTest(unittest.TestCase):
    def test_roundtrip_scalars_and_lists(self):
        meta = {
            "title": "Rule: no emoji",
            "type": "preference",
            "confidence": 0.75,
            "applied": 3,
            "evidence": ["2026-11-01", "2026-11-02"],
            "status": "active",
            "blank": "",
        }
        body = "# body\ntext\n"
        parsed, rest = parse_frontmatter(dump_frontmatter(meta) + "\n" + body)
        self.assertEqual(parsed["title"], "Rule: no emoji")
        self.assertAlmostEqual(parsed["confidence"], 0.75)
        self.assertEqual(parsed["applied"], 3)
        self.assertEqual(parsed["evidence"], ["2026-11-01", "2026-11-02"])
        self.assertEqual(rest.strip(), body.strip())

    def test_block_list(self):
        text = "---\ntitle: x\ntags:\n  - ai\n  - memory\n---\nbody\n"
        meta, body = parse_frontmatter(text)
        self.assertEqual(meta["tags"], ["ai", "memory"])
        self.assertEqual(body.strip(), "body")

    def test_missing_frontmatter(self):
        meta, body = parse_frontmatter("# plain\n")
        self.assertEqual(meta, {})
        self.assertEqual(body, "# plain\n")

    def test_unterminated_frontmatter_is_body(self):
        meta, body = parse_frontmatter("---\ntitle: x\n")
        self.assertEqual(meta, {})
        self.assertIn("title: x", body)


class VaultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Vault(self.tmp.name).ensure()

    def tearDown(self):
        self.tmp.cleanup()

    def test_seeds(self):
        for rel in ("identity.md", "now.md", "decisions.md", "log.md"):
            self.assertTrue(os.path.exists(self.vault.p(rel)), rel)
        self.assertTrue(os.path.isdir(self.vault.p("inbox")))

    def test_write_is_atomic_and_overwrites(self):
        self.vault.write("notes/a.md", "one")
        self.vault.write("notes/a.md", "two")
        self.assertEqual(self.vault.read("notes/a.md"), "two\n")

    def test_append_and_log(self):
        self.vault.append("log.md", "- first")
        self.vault.append("log.md", "- second")
        text = self.vault.read("log.md")
        self.assertIn("- first", text)
        self.assertIn("- second", text)
        self.vault.log("test", "detail")
        self.assertIn("test · detail", self.vault.read("log.md"))

    def test_slugify(self):
        self.assertEqual(slugify("Hello World!"), "hello-world")
        self.assertEqual(slugify("記憶 系統"), "記憶-系統")
        self.assertEqual(slugify(""), "untitled")
        self.assertLessEqual(len(slugify("x" * 200)), 48)


if __name__ == "__main__":
    unittest.main()
