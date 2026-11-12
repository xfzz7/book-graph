import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import fixtures as F  # noqa: E402
from bklib import ingest  # noqa: E402


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_ingest(self, path, **kw):
        return ingest.build_source(str(path), str(self.tmp / "w"), **kw)

    def titles(self, m):
        return [c["title"] for c in m["chapters"]]

    def test_canary_epub(self):
        p = self.tmp / "c.epub"
        F.make_canary_epub(p)
        m = self.run_ingest(p)
        self.assertEqual(m["lang"], "zh")
        self.assertEqual(len(m["chapters"]), 10)  # 序 + 8 章 + 附录
        self.assertIn("第三章 排队的非线性", self.titles(m))
        self.assertEqual(m["chapters"][0]["kind"], "front")
        self.assertEqual(m["chapters"][-1]["kind"], "back")
        # 小节被识别
        self.assertTrue(any(s["title"] == "85%线" for c in m["chapters"] for s in c["sections"]))
        # 段落 id 稳定、连续
        paras = [json.loads(l) for l in (self.tmp / "w/source/paras.jsonl").read_text(encoding="utf8").splitlines()]
        c4 = [x for x in paras if x["ch"] == "c04"]
        self.assertEqual([x["n"] for x in c4], list(range(1, len(c4) + 1)))
        # 书名页不残留
        self.assertFalse(any(x["text"] == "沈既明" for x in paras))

    def test_flat_epub_without_h1(self):
        p = self.tmp / "flat.epub"
        F.make_flat_epub(p, chapters=5)
        m = self.run_ingest(p)
        ch = [c for c in m["chapters"] if c["kind"] != "meta"]
        self.assertEqual(len(ch), 5)
        self.assertTrue(ch[0]["title"].startswith("第一章"))

    def test_zh_txt_with_parts(self):
        p = self.tmp / "a.txt"
        F.make_zh_txt(p)
        m = self.run_ingest(p)
        body = [c for c in m["chapters"] if c["kind"] == "body"]
        self.assertEqual(len(body), 6)
        self.assertTrue(body[0]["part"].startswith("第一部分"))
        self.assertTrue(body[3]["part"].startswith("第二部分"))
        self.assertIn("标题1", body[0]["title"])  # 「第一章」+ 下一行短标题 被并起来

    def test_en_txt_hardwrapped_noise(self):
        p = self.tmp / "en.txt"
        F.make_en_txt(p, chapters=6)
        m = self.run_ingest(p)
        self.assertEqual(m["lang"], "en")
        ch = [c for c in m["chapters"] if c["kind"] in ("body", "front")]
        self.assertGreaterEqual(len([c for c in m["chapters"] if c["title"].upper().startswith("CHAPTER")]), 6)
        text = (self.tmp / "w/source/paras.jsonl").read_text(encoding="utf8")
        self.assertNotIn("ON SLACK AND SPEED\\n", text)
        # 折行被接起来:段落里没有硬换行
        paras = [json.loads(l) for l in text.splitlines()]
        self.assertTrue(all("\n" not in p["text"] for p in paras))

    def test_markdown(self):
        p = self.tmp / "a.md"
        F.make_md(p)
        m = self.run_ingest(p)
        self.assertEqual(len([c for c in m["chapters"] if c["kind"] == "body"]), 4)
        self.assertEqual(len(m["chapters"][0]["sections"]), 2)

    def test_heading_regex_override(self):
        p = self.tmp / "b.txt"
        p.write_text("\n".join(["开篇" * 40] + ["§1 甲"] + ["正文内容很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长。" * 3] * 3 +
                               ["§2 乙"] + ["另一章的正文也很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长。" * 3] * 3), encoding="utf8")
        m = self.run_ingest(p, heading_regex=r"^§\d")
        self.assertEqual([c["title"] for c in m["chapters"] if c["title"].startswith("§")], ["§1 甲", "§2 乙"])

    def test_no_headings_falls_back_with_warning(self):
        p = self.tmp / "c.txt"
        p.write_text("\n".join("这是一段没有任何标题的很长的文字,重复很多次用来触发按长度切分的回退逻辑。" * 4 for _ in range(300)), encoding="utf8")
        m = self.run_ingest(p)
        self.assertGreaterEqual(len(m["chapters"]), 2)
        self.assertTrue(any("自动切分" in w for w in m["warnings"]))

    def test_pdf(self):
        txt = self.tmp / "en.txt"
        F.make_en_txt(txt, chapters=5, running_header=False)
        pdf = self.tmp / "en.pdf"
        if not F.make_pdf_from_en(txt, pdf):
            self.skipTest("没有 libreoffice")
        m = self.run_ingest(pdf)
        self.assertGreaterEqual(len([c for c in m["chapters"] if c["title"].upper().startswith("CHAPTER")]), 4)

    def test_big_book_performance(self):
        p = self.tmp / "big.txt"
        F.make_big_zh(p, chapters=60, per=40)
        t = time.time()
        m = self.run_ingest(p)
        dt = time.time() - t
        self.assertEqual(len(m["chapters"]), 60)
        self.assertGreater(m["total_weight"], 300000)
        self.assertLess(dt, 30, f"摄入过慢: {dt:.1f}s")

    def test_kangxi_radicals_normalized(self):
        self.assertEqual(ingest.clean("⼀个"), "一个")
        self.assertEqual(ingest.clean("你好,世界。"), "你好,世界。")  # 全角标点不动


if __name__ == "__main__":
    unittest.main()
