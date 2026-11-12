"""脚本的自动化测试:python -m unittest discover tests"""
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from bg_check import longest_copied, build_shingles, overlap, run_check  # noqa: E402
from bg_render import build  # noqa: E402
from bg_text import prepare, load_source  # noqa: E402

EX = ROOT / "references" / "example"


def make_work(tmp: Path) -> Path:
    w = tmp / "work"
    prepare(str(EX / "book.txt"), str(w), min_chars=50)
    shutil.copytree(EX / "notes", w / "notes")
    shutil.copy(EX / "synthesis.json", w / "synthesis.json")
    shutil.copytree(EX / "verify", w / "verify")
    return w


class TestPrepare(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_txt_chapters_and_anchors(self):
        m = prepare(str(EX / "book.txt"), str(self.tmp / "w"), min_chars=50)
        self.assertEqual([c["title"][:3] for c in m["chapters"]], ["第一章", "第二章", "第三章"])
        self.assertEqual(m["title"], "计划为什么总是落空")
        self.assertEqual(m["author"], "周砚")
        src = load_source(str(self.tmp / "w"))
        self.assertIn("c2.p2", src["c2"])
        self.assertTrue(src["c2"]["c2.p2"].startswith("在那家公司里"))

    def test_epub_with_headings_as_paragraphs_and_toc(self):
        ep = self.tmp / "b.epub"
        z = zipfile.ZipFile(ep, "w")
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="o.opf"/></rootfiles></container>')
        z.writestr("o.opf", '<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>T</dc:title><dc:creator>A 著</dc:creator></metadata><manifest><item id="toc" href="toc.xhtml" media-type="application/xhtml+xml"/><item id="a" href="a.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="toc"/><itemref idref="a"/></spine></package>')
        z.writestr("toc.xhtml", "<html><body><p>第一章 甲</p><p>第二章 乙</p><p>第三章 丙</p></body></html>")
        body = "".join(f"<p>第{n}章 标题{n}</p>" + "<p>" + "正文内容。" * 60 + "</p><p>第1节 小节</p><p>" + "更多。" * 30 + "</p>" for n in "一二三")
        z.writestr("a.xhtml", f"<html><body>{body}</body></html>")
        z.close()
        m = prepare(str(ep), str(self.tmp / "w"))
        self.assertEqual(len(m["chapters"]), 3)       # 目录页被跳过,"第1节"不切
        self.assertEqual(m["author"], "A")

    def test_english_markdown_and_backmatter(self):
        md = self.tmp / "b.md"
        md.write_text("# Introduction\n" + "Intro text here. " * 30 + "\n# Chapter 1 Trust\n" + "Body. " * 80
                      + "\n## Notes\n" + "Note 1. " * 40 + "\n", encoding="utf-8")
        m = prepare(str(md), str(self.tmp / "w"))
        self.assertEqual(m["lang"], "en")
        self.assertEqual([c["kind"] for c in m["chapters"]], ["front", "chap", "matter"])
        self.assertTrue(m["chapters"][2]["skip_hint"])

    def test_chunks_and_long_paragraph_split(self):
        t = self.tmp / "b.txt"
        t.write_text("书名\n第一章 长\n" + "\n".join("这是一段比较长的话,用来测试分块。" * 20 for _ in range(30)) + "\n", encoding="utf-8")
        m = prepare(str(t), str(self.tmp / "w"), chunk_chars=2000)
        self.assertGreater(len(m["chapters"][0]["chunks"]), 3)
        t.write_text("书名\n第一章 长\n" + "很长的句子。" * 400 + "\n", encoding="utf-8")
        m = prepare(str(t), str(self.tmp / "w"))
        self.assertGreater(m["chapters"][0]["paras"], 2)  # 超长段落按句切开


class TestCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.w = make_work(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def edit(self, rel, fn):
        p = self.w / rel
        d = json.loads(p.read_text(encoding="utf-8"))
        fn(d)
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    def test_example_passes(self):
        R = run_check(str(self.w))
        self.assertEqual(R.errors, [])
        self.assertEqual(R.warns, [])

    def test_copy_detected(self):
        self.edit("notes/c1.json", lambda d: d["claims"][0].update(
            text="我在一家软件公司收集了三百个任务的估计和实际耗时,所以拖延不是原因。"))
        R = run_check(str(self.w))
        self.assertTrue(any("[照抄]" in e for e in R.errors), R.errors)

    def test_bad_anchor_and_missing_anchor(self):
        self.edit("notes/c2.json", lambda d: (d["claims"][0].update(anchors=["c2.p99"]), d["claims"][1].update(anchors=[])))
        R = run_check(str(self.w), chapter="c2")
        self.assertTrue(any("c2.p99" in e for e in R.errors))
        self.assertTrue(any("没有出处锚点" in e for e in R.errors))

    def test_low_overlap_flagged(self):
        self.edit("notes/c2.json", lambda d: d["claims"][1].update(text="量子计算机将在十年内取代所有传统服务器硬件。"))
        R = run_check(str(self.w), chapter="c2")
        self.assertTrue(any("[出处]" in w and "c2.2" in w for w in R.warns))

    def test_unread_chunk_flagged(self):
        man = json.loads((self.w / "manifest.json").read_text(encoding="utf-8"))
        man["chapters"][0]["chunks"] = ["p1-p2", "p3-p3"]
        (self.w / "manifest.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
        self.edit("notes/c1.json", lambda d: d["claims"][2].update(anchors=["c1.p2"]))
        R = run_check(str(self.w), chapter="c1")
        self.assertTrue(any("p3-p3" in w for w in R.warns))

    def test_glossary_consistency_and_refs(self):
        self.edit("synthesis.json", lambda d: (d["glossary"].pop(), d["key_ideas"][0]["because"].append("c9.9")))
        R = run_check(str(self.w))
        self.assertTrue(any("参照估计" in w for w in R.warns))
        self.assertTrue(any("c9.9" in e for e in R.errors))

    def test_verification_loop(self):
        self.edit("verify/verdicts.json", lambda d: d[0].update(verdict="wrong", reason="x", fix="y"))
        R = run_check(str(self.w))
        self.assertTrue(any("[核查]" in e for e in R.errors))
        bad = json.loads((self.w / "verify/verdicts.json").read_text(encoding="utf-8"))[0]["id"]
        ch = bad.split(".")[0]
        self.edit(f"notes/{ch}.json", lambda d: [c.update(text=c["text"] + "(已修正)") for c in d["claims"] if c["id"] == bad])
        R = run_check(str(self.w))
        self.assertFalse(any("[核查]" in e for e in R.errors), R.errors)

    def test_build(self):
        files = build(str(self.w), str(self.tmp / "out"))
        html = files[1].read_text(encoding="utf-8")
        self.assertIn("顺境锚", html)
        self.assertNotIn("/*DATA*/null", html)
        md = files[0].read_text(encoding="utf-8")
        self.assertIn("容易读错的地方", md)
        self.assertIn("第一章 ¶2", md)
        self.assertEqual(len(files[2].read_text(encoding="utf-8").strip().splitlines()), 8 + 2)


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.w = make_work(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_cli(self, *args):
        import io
        from contextlib import redirect_stdout
        import bookguide
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = bookguide.main([str(x) for x in args])
        return rc, buf.getvalue()

    def test_broken_notes_are_loud(self):
        (self.w / "notes" / "c1.json").write_text('{"chapter": "c1", "question": "坏"引号"}', encoding="utf-8")
        rc, out = self.run_cli("brief", self.w, "c3")
        self.assertEqual(rc, 1)
        self.assertIn("无法解析", out)
        rc, out = self.run_cli("status", self.w)
        self.assertIn("✗", out)

    def test_threads_closed_and_partial(self):
        rc, out = self.run_cli("brief", self.w, "c3")
        self.assertNotIn("c1#1", out)                       # c2 已完整回应
        p = self.w / "notes" / "c2.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d["threads"]["closes"] = ["c1#1(部分): 只回答了一半"]
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        rc, out = self.run_cli("brief", self.w, "c3")
        self.assertIn("c1#1", out)

    def test_verify_sheet_batches(self):
        rc, out = self.run_cli("verify-sheet", self.w, "--batch", "5")
        parts = sorted((self.w / "verify").glob("sheet-*.md"))
        n = len(json.loads((self.w / "verify" / "sheet.json").read_text(encoding="utf-8")))
        self.assertEqual(len(parts), -(-n // 5))
        self.assertIn("S:K1", (self.w / "verify" / "sheet.md").read_text(encoding="utf-8"))


class TestPrimitives(unittest.TestCase):
    def test_longest_copied_zh_ignores_punct(self):
        src = {"c1": {"c1.p1": "甲乙丙丁戊己庚辛壬癸,子丑寅卯辰巳午未申酉戌亥。"}}
        sh = build_shingles(src, 10, "zh")
        self.assertEqual(longest_copied("前缀甲乙丙丁戊己庚辛壬癸子丑后缀", sh, 10, "zh"), "甲乙丙丁戊己庚辛壬癸子丑")
        self.assertEqual(longest_copied("完全不同的句子内容在这里出现", sh, 10, "zh"), "")

    def test_longest_copied_en(self):
        src = {"c1": {"c1.p1": "The quick brown fox jumps over the lazy dog near the old river bank today."}}
        sh = build_shingles(src, 5, "en")
        self.assertTrue(longest_copied("Note: the quick brown fox jumps over it.", sh, 5, "en").startswith("the quick brown fox jumps"))

    def test_overlap(self):
        self.assertGreater(overlap("信任会随人员流动而折旧", "人员流动会让信任折旧", "zh"), 0.3)
        self.assertLess(overlap("火星上有水", "人员流动会让信任折旧", "zh"), 0.1)


if __name__ == "__main__":
    unittest.main()
