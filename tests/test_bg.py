#!/usr/bin/env python3
"""脚本自测。运行:python3 tests/test_bg.py

重点是"变异测试":拿一份正确的工作目录(examples/mini),逐个注入 LLM 常犯的错误,
确认校验器每一种都能拦住。"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from bglib import checks, packets, source, textutil  # noqa: E402
from bglib import build as builder  # noqa: E402

MINI = ROOT / "examples" / "mini"


class Work:
    """mini 示例的临时副本。"""
    def __enter__(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(MINI / "work", self.tmp / "work")
        self.w = self.tmp / "work"
        checks.ChapterCtx._cache.clear()
        return self

    def __exit__(self, *a):
        shutil.rmtree(self.tmp)

    def edit(self, rel: str, fn):
        p = self.w / rel
        d = json.loads(p.read_text(encoding="utf-8"))
        fn(d)
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    def check(self, final=False):
        iss, ctx = checks.check_all(self.w, final=final)
        return iss, ctx


def claim(d, cid):
    return next(c for c in d["claims"] if c["id"] == cid)


def has(items, where, frag):
    return any(w == where and frag in m for _, w, m in items)


class TestText(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(textutil.numbers("四百一十二家,百分之三十七,二〇一九年,1,200 人,3 个步骤,12.50%"),
                         {"412", "37%", "2019", "1200", "12.5%"})
        self.assertEqual(textutil.cn_to_number("三万五千"), "35000")

    def test_norm_ignores_punct(self):
        self.assertIn(textutil.norm("厌倦不是原因,而是结果"), textutil.norm("所以厌倦不是原因,而是结果,是报警"))

    def test_shared_run_en(self):
        src = textutil.tokens("the quick brown fox jumps over the lazy dog near the quiet river bank today")
        g = textutil.ngram_set(src, 8)
        run, seg = textutil.longest_shared_run("He said the quick brown fox jumps over the lazy dog near home", g, 8)
        self.assertEqual(run, 10)
        self.assertEqual(textutil.longest_shared_run("a quick fox jumped over a dog", g, 8)[0], 0)


class TestPrepare(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_txt_with_toc_page(self):
        body = "这是正文的一段话,用来凑够字数。" * 30
        txt = "某书\n\n版权所有\n\n目录\n\n序言\n\n第一章 起点\n\n第二章 转折\n\n后记\n\n" \
              f"序言\n\n{body}\n\n第一章 起点\n\n{body}\n\n{body}\n\n第二章 转折\n\n{body}\n\n后记\n\n{body}\n"
        f = self.tmp / "b.txt"
        f.write_text(txt, encoding="utf-8")
        man = source.prepare(str(f), str(self.tmp / "w"))
        titles = [c["title"] for c in man["chapters"] if not c["skip"]]
        self.assertEqual(titles, ["序言", "第一章 起点", "第二章 转折", "后记"])   # 目录页里的标题行没有被切成章
        self.assertTrue(man["chapters"][0]["skip"])
        self.assertEqual(man["lang"], "zh")
        ch1 = next(c for c in man["chapters"] if c["title"] == "第一章 起点")
        self.assertEqual(ch1["paras"], 2)

    def test_hard_wrapped_english(self):
        para = ("This is a sentence that keeps going for a while so the line\nhas to wrap around and continue "
                "on the next line like old\nplain text files usually do.")
        txt = "\n\n".join(["CHAPTER I\nThe Beginning"] + [para] * 12 + ["CHAPTER II\nThe End"] + [para] * 12)
        f = self.tmp / "e.txt"
        f.write_text(txt, encoding="utf-8")
        man = source.prepare(str(f), str(self.tmp / "w"))
        act = [c for c in man["chapters"] if not c["skip"]]
        self.assertEqual(len(act), 2)
        self.assertEqual(act[0]["title"], "CHAPTER I The Beginning")
        self.assertEqual(act[0]["paras"], 12)
        self.assertEqual(man["lang"], "en")
        first = next(iter(source.Source(self.tmp / "w").paras(act[0]["id"]).values()))
        self.assertIn("the line has to wrap", first)

    def _epub(self, one_file: bool) -> Path:
        body = "".join(f"<p>正文段落{i},这里有一些内容用来凑字数,保证每章都足够长。</p>" for i in range(20))
        chs = [("前言", "pre"), ("第一章 甲", "c1"), ("第二章 乙", "c2"), ("第三章 丙", "c3")]
        p = self.tmp / ("one.epub" if one_file else "multi.epub")
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                       '<rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
            if one_file:
                html = "<html><body>" + "".join(f'<p id="{i}">{t}</p>{body}' for t, i in chs) + "</body></html>"
                z.writestr("OEBPS/all.xhtml", html)
                items = '<item id="all" href="all.xhtml" media-type="application/xhtml+xml"/>'
                spine = '<itemref idref="all"/>'
                nav = "".join(f'<navPoint><navLabel><text>{t}</text></navLabel><content src="all.xhtml#{i}"/></navPoint>' for t, i in chs)
            else:
                for t, i in chs:
                    z.writestr(f"OEBPS/{i}.xhtml", f"<html><body><h1>{t}</h1>{body}</body></html>")
                z.writestr("OEBPS/c1b.xhtml", f"<html><body>{body}</body></html>")   # 第一章的续页,目录里没有
                ids = ["pre", "c1", "c1b", "c2", "c3"]
                items = "".join(f'<item id="{i}" href="{i}.xhtml" media-type="application/xhtml+xml"/>' for i in ids)
                spine = "".join(f'<itemref idref="{i}"/>' for i in ids)
                nav = "".join(f'<navPoint><navLabel><text>{t}</text></navLabel><content src="{i}.xhtml"/></navPoint>' for t, i in chs)
            z.writestr("OEBPS/toc.ncx", f'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>{nav}</navMap></ncx>')
            z.writestr("OEBPS/content.opf", '<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                       '<metadata><dc:title>测试书</dc:title><dc:creator>某人</dc:creator></metadata>'
                       f'<manifest>{items}<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>'
                       f'<spine>{spine}</spine></package>')
        return p

    def test_epub_multi_file(self):
        man = source.prepare(str(self._epub(False)), str(self.tmp / "w"))
        self.assertEqual(man["title"], "测试书")
        self.assertEqual([c["title"] for c in man["chapters"]], ["前言", "第一章 甲", "第二章 乙", "第三章 丙"])
        self.assertEqual(man["chapters"][1]["paras"], 40)       # 续页并入第一章

    def test_epub_single_file(self):
        man = source.prepare(str(self._epub(True)), str(self.tmp / "w"))
        self.assertEqual([c["title"] for c in man["chapters"]], ["前言", "第一章 甲", "第二章 乙", "第三章 丙"])
        self.assertEqual([c["paras"] for c in man["chapters"]], [20, 20, 20, 20])

    def test_long_chapter_parts(self):
        txt = "第一章 长\n\n" + "\n\n".join("这是一段比较长的正文内容。" * 20 for _ in range(120)) + \
              "\n\n第二章 短\n\n" + "短章正文。" * 100
        f = self.tmp / "l.txt"
        f.write_text(txt, encoding="utf-8")
        man = source.prepare(str(f), str(self.tmp / "w"), part_tokens=9000)
        long = man["chapters"][0]
        self.assertGreater(len(long["parts"]), 2)
        self.assertTrue(all(p["tokens"] <= 9000 for p in long["parts"]))
        self.assertEqual(long["parts"][-1]["lines"][1], long["paras"])
        self.assertIn("分", packets.context(source.Source(self.tmp / "w"), long["id"]))


class TestMutations(unittest.TestCase):
    """每个用例 = 一种 LLM 常犯的错误。"""

    def test_baseline_clean(self):
        with Work() as w:
            iss, _ = w.check(final=True)
            self.assertEqual(iss.items, [])

    def test_fabricated_quote(self):
        with Work() as w:
            w.edit("notes/c02.json", lambda d: claim(d, "c02-k1").update(quote="厌倦其实是一种结果而非原因"))
            iss, _ = w.check()
            self.assertTrue(has(iss.errors, "c02-k1", "找不到"))

    def test_wrong_anchor(self):
        with Work() as w:
            w.edit("notes/c02.json", lambda d: claim(d, "c02-k1").update(refs=["c02-p001"]))
            iss, _ = w.check()
            self.assertTrue(has(iss.errors, "c02-k1", "出现在 c02-p003"))

    def test_nonexistent_paragraph(self):
        with Work() as w:
            w.edit("notes/c02.json", lambda d: claim(d, "c02-k1").update(refs=["c02-p099"]))
            self.assertTrue(has(w.check()[0].errors, "c02-k1", "不是 c02 的段落编号"))

    def test_copied_text(self):
        with Work() as w:
            w.edit("notes/c02.json", lambda d: claim(d, "c02-k2").update(
                text="每一次被打断、每一次强迫自己集中,都在支出;而长期加班意味着只有支出。"))
            self.assertTrue(has(w.check()[0].errors, "c02-k2", "连续"))

    def test_wrong_number(self):
        with Work() as w:
            w.edit("notes/c02.json", lambda d: claim(d, "c02-k5").update(
                text="作者访谈的 74 位程序员中,有 39 位在高强度加班期出现过对什么都提不起劲的状态。"))
            iss, _ = w.check()
            self.assertTrue(has(iss.warnings, "c02-k5", "74"))
            self.assertFalse(has(iss.warnings, "c02-k5", "39("))

    def test_counter_presented_as_unrebutted(self):
        with Work() as w:
            w.edit("notes/c02.json", lambda d: d.update(links=[l for l in d["links"] if l["type"] != "rebuts"]))
            self.assertTrue(has(w.check()[0].warnings, "c02-k6", "counter"))

    def test_pillar_built_on_counter(self):
        with Work() as w:
            w.edit("book.json", lambda d: d["pillars"][0]["claims"].append("c02-k6"))
            self.assertTrue(has(w.check()[0].errors, "P1", "counter"))

    def test_everything_core(self):
        with Work() as w:
            w.edit("notes/c02.json", lambda d: [c.update(weight="core") for c in d["claims"]])
            self.assertTrue(has(w.check()[0].warnings, "c02", "太多"))

    def test_dangling_and_missing_ev(self):
        with Work() as w:
            def f(d):
                d["links"] = [l for l in d["links"] if "c03-k3" not in (l["from"], l["to"])]
                claim(d, "c03-k4").pop("ev")
            w.edit("notes/c03.json", f)
            iss, _ = w.check()
            self.assertTrue(has(iss.warnings, "c03-k3", "悬空"))
            self.assertTrue(has(iss.errors, "c03-k4", "ev"))

    def test_broken_cross_reference(self):
        with Work() as w:
            w.edit("notes/c04.json", lambda d: d["links"].append({"from": "c04-k1", "to": "c02-k99", "type": "applies"}))
            self.assertTrue(any("c02-k99" in m for _, _, m in w.check()[0].errors))

    def test_core_not_in_any_pillar(self):
        with Work() as w:
            w.edit("book.json", lambda d: d["pillars"].pop())
            self.assertTrue(has(w.check()[0].warnings, "book", "没有连到任何支柱"))

    def test_missing_chapter_notes(self):
        with Work() as w:
            (w.w / "notes" / "c03.json").unlink()
            self.assertTrue(has(w.check()[0].errors, "c03", "还没有笔记"))

    def test_bad_json_is_reported_not_crash(self):
        with Work() as w:
            (w.w / "notes" / "c03.json").write_text('{"chapter": "c03", "role": "他说"不"的时候"}', encoding="utf-8")
            self.assertTrue(has(w.check()[0].errors, "c03", "JSON 语法错误"))

    def test_critique_without_target_and_shallow_quiz(self):
        with Work() as w:
            def f(d):
                d["critique"][0]["targets"] = []
                d["questions"] = [q for q in d["questions"] if q["level"] == "recall"] * 4
            w.edit("book.json", f)
            iss, _ = w.check()
            self.assertTrue(any("靶子" in m for _, _, m in iss.errors))
            self.assertTrue(has(iss.warnings, "book", "层次单一"))

    def test_term_enumeration_is_not_copying(self):
        with Work() as w:
            # 原文里并列出现的两个术语,按原顺序罗列 + 原文措辞,未登记时会撞线,登记为概念后不算抄录
            def f(d):
                claim(d, "c03-k2").update(text="关键在于区分两种专注。被迫的专注要不断压制想逃开的冲动。")
            w.edit("notes/c03.json", f)
            self.assertTrue(has(w.check()[0].errors, "c03-k2", "连续"))
            w.edit("notes/c03.json", lambda d: claim(d, "c03-k2").update(text="作者把专注分成自发的专注与被迫的专注,前者不耗神,后者耗神。"))
            self.assertFalse(has(w.check()[0].errors, "c03-k2", "连续"))

    def test_single_char_numeral_no_false_alarm(self):
        self.assertIn("10", textutil.number_forms("十票赞成、一票反对"))

    def test_thesis_claims_and_aside_exempt(self):
        with Work() as w:
            w.edit("book.json", lambda d: d["pillars"].pop())
            self.assertTrue(has(w.check()[0].warnings, "book", "没有连到任何支柱"))
            w.edit("book.json", lambda d: d.update(thesis_claims=["c04-k1"], aside=[{"claims": ["c04-k2"], "why": "测试"}]))
            self.assertFalse(has(w.check()[0].warnings, "book", "没有连到任何支柱"))
            w.edit("book.json", lambda d: d.update(aside=[{"claims": ["c04-k9"], "why": "x"}]))
            self.assertTrue(any("c04-k9" in m for _, _, m in w.check()[0].errors))

    def test_coverage_gap(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            filler = "\n\n".join(f"这是第{i}段铺垫文字,讲了一些与论点关系不大的事情,篇幅不短但也不算太长。" * 3 for i in range(60))
            txt = f"第一章 甲\n\n开头提出了一个重要的观点需要记录下来。\n\n{filler}\n\n结尾总结了另外一个重要的观点。\n\n第二章 乙\n\n" + "凑数的正文。" * 80
            (tmp / "b.txt").write_text(txt, encoding="utf-8")
            man = source.prepare(str(tmp / "b.txt"), str(tmp / "w"))
            cid = man["chapters"][0]["id"]
            last = f"{cid}-p{man['chapters'][0]['paras']:03d}"
            note = {"chapter": cid, "role": "测试用的章节作用描述文字", "summary": "测试用的章节概要描述文字若干",
                    "claims": [
                        {"id": f"{cid}-k1", "kind": "claim", "weight": "core", "text": "作者在本章起始处给出一个要紧的看法。",
                         "refs": [f"{cid}-p001"], "quote": "重要的观点需要记录"},
                        {"id": f"{cid}-k2", "kind": "claim", "weight": "core", "text": "作者在本章末尾又归纳出第二个要紧的看法。",
                         "refs": [last], "quote": "另外一个重要的观点"}], "links": []}
            src = source.Source(tmp / "w")
            checks.ChapterCtx._cache.clear()
            iss = checks.Issues()
            checks.check_chapter(src, cid, note, iss)
            self.assertTrue(has(iss.warnings, cid, "没有任何笔记引用"))
            note["skipped"] = [{"from": f"{cid}-p002", "to": f"{cid}-p061", "why": "铺垫"}]
            iss = checks.Issues()
            checks.check_chapter(src, cid, note, iss)
            self.assertFalse(has(iss.warnings, cid, "没有任何笔记引用"))
        finally:
            shutil.rmtree(tmp)


class TestAuditAndBuild(unittest.TestCase):
    def test_audit_lifecycle(self):
        with Work() as w:
            shutil.rmtree(w.w / "audit")
            self.assertTrue(has(w.check(final=True)[0].errors, "audit", "还没有做独立核查"))
            self.assertEqual(w.check(final=False)[0].errors, [])
            src = source.Source(w.w)
            _, vp, pending = packets.audit_packet(src, n=30)
            self.assertGreater(pending, 10)
            v = json.loads(vp.read_text(encoding="utf-8"))
            ids = [x["id"] for x in v]
            self.assertIn("thesis", ids)
            self.assertIn("c02-k6", ids)             # counter 必查
            self.assertIn("c02-k1", ids)             # 支柱命题必查
            packet = (w.w / "audit" / "packet.md").read_text(encoding="utf-8")
            self.assertIn("热爱可以战胜疲劳", packet)  # 核查包附原文
            self.assertTrue(has(w.check(final=True)[0].errors, "audit", "没填"))
            for x in v:
                x["verdict"] = "ok"
            next(x for x in v if x["id"] == "c02-k6").update(verdict="misattributed", note="其实是作者观点")
            vp.write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
            iss, ctx = w.check(final=True)
            self.assertTrue(has(iss.errors, "c02-k6", "misattributed"))
            # 修改该条后,校验识别为"已修正"
            w.edit("notes/c02.json", lambda d: claim(d, "c02-k6").update(text="一种流行说法主张,只要足够热爱工作,人就不会因劳累而生厌。"))
            iss, ctx = w.check(final=True)
            self.assertEqual(iss.errors, [])
            self.assertEqual(ctx["audit"]["fixed"], 1)
            # 复核包只含改过的那条
            _, vp, pending = packets.audit_packet(src)
            self.assertEqual(pending, 1)

    def test_build_contains_no_source_text(self):
        with Work() as w:
            iss, ctx = w.check(final=True)
            out = builder.build(ctx["src"], ctx["notes"], ctx["book"], iss, ctx["audit"], w.w / "guide2")
            html = out[0].read_text(encoding="utf-8")
            md = out[1].read_text(encoding="utf-8")
            self.assertIn("厌倦是透支的结果", html)
            self.assertNotIn("/*DATA*/null", html)
            src = ctx["src"]
            for ch in src.active():
                g = checks.ChapterCtx.get(src, ch["id"])
                for name, text in (("html", html), ("md", md)):
                    # 产物里任何一处都不应与原文连续 31 字以上相同(quote 上限 30)
                    run, seg = textutil.longest_shared_run(text, textutil.ngram_set(
                        textutil.tokens(" ".join(g.paras.values())), 31), 31)
                    self.assertEqual(run, 0, f"{name} 含原文:{seg}")
            self.assertIn("c02-k1", html)
            self.assertNotIn("c02-p003", html)       # 段落编号对读者无意义,不进产物

    def test_packets(self):
        with Work() as w:
            src = source.Source(w.w)
            self.assertIn("c02-k1", packets.digest(src))
            self.assertIn("透支模型", packets.context(src, "c04"))
            self.assertNotIn("c04-k1", packets.context(src, "c02").split("## 本章")[0].replace("c04《", ""))
            self.assertIn("[c02-p001]", packets.skim(src))


if __name__ == "__main__":
    unittest.main(verbosity=1)
