"""规模测试:60 章、约 57 万字符的合成书——摄入、简报大小、digest 大小、全量校验耗时都要可控。"""
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
from bklib import audit, brief, ingest  # noqa: E402
from bklib.check import Checker  # noqa: E402
from bklib.store import Work  # noqa: E402
from bklib.text import weight  # noqa: E402


class Scale(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        F.make_big_zh(cls.tmp / "big.txt", chapters=60, per=40)
        ingest.build_source(str(cls.tmp / "big.txt"), str(cls.tmp / "w"))
        cls.w = Work(str(cls.tmp / "w"))
        nd = cls.tmp / "w" / "notes"
        nd.mkdir()
        for c in cls.w.chapters():
            k = c["key"]
            ps = cls.w.ch_paras(k)
            cards = []
            for i in range(12):
                p = ps[i % len(ps)]
                cards.append({"id": f"{k}.k{i + 1}", "text": f"第{k}章的第{i + 1}个论断,说明容量被全部分配之后意外只能靠挤占别的工作消化。", "label": f"论断{i + 1}",
                              "kind": "claim", "voice": "author", "tier": 1 if i == 0 else 2, "parent": None if i == 0 else f"{k}.k1", "rel": None if i == 0 else "supports",
                              "refs": [p["id"]], "anchor": p["text"][2:12]})
            (nd / f"{k}.json").write_text(json.dumps({"chapter": k, "meta": {"role": "本章在全书中的作用说明文字", "summary": "本章的概要说明文字,需要足够长才能通过校验。",
                                                      "takeaway": "本章一句话要点说明", "priority": "normal", "reading_questions": ["问题?"]},
                                                      "cards": cards, "concepts": [{"term": f"术语{k}", "def": "这是一个术语的定义说明文字。", "origin": "coined", "refs": [ps[0]["id"]], "anchor": ps[0]["text"][2:12]}]},
                                                     ensure_ascii=False), encoding="utf8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_brief_size_is_bounded(self):
        b_first = brief.brief(self.w, "c02")
        b_last = brief.brief(self.w, "c60")
        self.assertLess(weight(b_last), 6000, f"最后一章的简报过大: {weight(b_last)}")
        mid = brief.brief(self.w, "c30")
        self.assertLess(weight(b_last), weight(mid) * 2.5)  # 增长被预算封顶,不随章数线性膨胀

    def test_chunks_respect_budget_and_paragraphs(self):
        for k in ("c01", "c30"):
            cs = brief.chunks_for(self.w, k, budget=3000)
            self.assertEqual(sum(len(c) for c in cs), len(self.w.ch_paras(k)))
            self.assertTrue(all(weight(" ".join(p["text"] for p in c)) < 3000 * 1.8 for c in cs))
            ids = [p["id"] for c in cs for p in c]
            self.assertEqual(ids, [p["id"] for p in self.w.ch_paras(k)])

    def test_check_runtime(self):
        t = time.time()
        ck = Checker(self.w)
        ck.check_notes()
        self.assertLess(time.time() - t, 20)
        self.assertEqual([i for i in ck.issues if i.level == "E"], [])

    def test_digest_tier_filter_shrinks(self):
        full = brief.digest(self.w, 3)
        t1 = brief.digest(self.w, 1)
        self.assertLess(len(t1), len(full) * 0.5)

    def test_audit_cap(self):
        ck = Checker(self.w)
        ck.check_notes()
        r = audit.plan(self.w, ck.issues, rate=0.25, seeds=0, cap=100)
        self.assertLessEqual(r["items"], 100)


if __name__ == "__main__":
    unittest.main()
