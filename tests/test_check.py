"""校验器的变异测试:从一份合格的笔记出发,逐个注入典型缺陷,确认校验器抓得到(且不误报合格笔记)。"""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import fixtures as F  # noqa: E402
from bklib import ingest  # noqa: E402
from bklib.check import Checker  # noqa: E402
from bklib.store import Work  # noqa: E402


def pid(w, needle):
    for p in w.paras.values():
        if needle in p["text"]:
            return p["id"]
    raise KeyError(needle)


class CheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        epub = cls.tmp / "c.epub"
        F.make_canary_epub(epub)
        ingest.build_source(str(epub), str(cls.tmp / "w"))
        cls.w = Work(str(cls.tmp / "w"))
        cls.ch = next(c["key"] for c in cls.w.meta["chapters"] if "排队" in c["title"])
        p_er = pid(cls.w, "78%上升到91%")
        p_rule = pid(cls.w, "当利用率超过85%之后")
        p_other = pid(cls.w, "三个检验问题") if False else pid(cls.w, "怎么判断眼前的东西属于哪一类")
        k = cls.ch
        cls.base = {
            "chapter": k,
            "meta": {"role": "解释为什么利用率接近满载时等待急剧上升", "summary": "本章用排队论的直觉、85%线与急诊科数据说明非线性,并指出波动才是主角。",
                     "takeaway": "接近满载时等待非线性上升,根源是波动。", "priority": "must", "reading_questions": ["为什么差一点点就差很多?"]},
            "cards": [
                {"id": f"{k}.k1", "text": "作者提出的“85%线”是经验法则:利用率超过85%后,需求小幅增加会让等待时间增加一倍以上,但它不是精确定律。",
                 "label": "85%线", "kind": "claim", "voice": "author", "tier": 1, "parent": None, "rel": None, "refs": [p_rule], "anchor": "经验法则"},
                {"id": f"{k}.k2", "text": "某二甲医院急诊床位使用率在一个冬季从78%升到91%,患者平均等待时间从42分钟增加到117分钟。",
                 "label": "急诊科数据", "kind": "evidence", "voice": "author", "tier": 2, "parent": f"{k}.k1", "rel": "supports", "refs": [p_er],
                 "anchor": "42分钟增加到117分钟",
                 "ev": {"type": "case", "strength": "illustrative", "limit": "单一医院的跟踪案例,没有给出样本与方法"}},
            ],
            "concepts": [], "links": [],
        }
        cls.p_other = p_other
        cls.p_er = p_er

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_notes(self, notes, only_notes=True):
        w = Work(str(self.tmp / "w"))
        nd = self.tmp / "w" / "notes"
        if nd.exists():
            shutil.rmtree(nd)
        nd.mkdir()
        (nd / f"{self.ch}.json").write_text(json.dumps(notes, ensure_ascii=False), encoding="utf8")
        ck = Checker(w)
        ck.check_notes()
        return [i for i in ck.issues if i.code != "chapter_missing"]

    def codes(self, issues, level=None):
        return {i.code for i in issues if level is None or i.level == level}

    def mutate(self, fn):
        n = copy.deepcopy(self.base)
        fn(n)
        return n

    # ---- 合格样本不应误报 E/W
    def test_clean_notes_pass(self):
        iss = self.run_notes(self.base)
        bad = [i for i in iss if i.level in ("E", "W")]
        self.assertEqual(bad, [], "\n".join(map(str, bad)))

    # ---- 各种缺陷
    def test_missing_ref(self):
        iss = self.run_notes(self.mutate(lambda n: n["cards"][0].update(refs=[self.ch + ":99"])))
        self.assertIn("ref_missing", self.codes(iss, "E"))

    def test_ref_wrong_chapter(self):
        iss = self.run_notes(self.mutate(lambda n: n["cards"][0].update(refs=[self.p_other])))
        self.assertIn("ref_wrong_chapter", self.codes(iss, "E"))

    def test_fabricated_anchor(self):
        iss = self.run_notes(self.mutate(lambda n: n["cards"][0].update(anchor="作者强调这是铁律")))
        self.assertIn("anchor_not_found", self.codes(iss, "E"))

    def test_anchor_in_wrong_paragraph(self):
        iss = self.run_notes(self.mutate(lambda n: n["cards"][1].update(anchor="经验法则")))
        self.assertIn("anchor_misplaced", self.codes(iss, "E"))

    def test_anchor_too_long(self):
        long = "排队论早就证明当一个系统的利用率接近100%时等待时间并不是线性增长而是急剧上升直觉上我们以为"
        iss = self.run_notes(self.mutate(lambda n: n["cards"][0].update(anchor=long)))
        self.assertIn("anchor_long", self.codes(iss, "E"))

    def test_fabricated_number(self):
        iss = self.run_notes(self.mutate(lambda n: n["cards"][1].update(text=n["cards"][1]["text"].replace("117分钟", "171分钟"))))
        self.assertIn("numbers", self.codes(iss, "W"))

    def test_waive_numbers_is_visible(self):
        iss = self.run_notes(self.mutate(lambda n: n["cards"][1].update(text=n["cards"][1]["text"].replace("117分钟", "171分钟"), waive=["numbers"])))
        self.assertNotIn("numbers", self.codes(iss, "W"))
        self.assertIn("waived", self.codes(iss, "I"))

    def test_copying_original(self):
        src = self.w.paras[self.base["cards"][1]["refs"][0]]["text"]
        i = src.index("该院急诊床位的使用率")
        copied = src[i:i + 40]
        iss = self.run_notes(self.mutate(lambda n: n["cards"][1].update(text=copied + "。")))
        self.assertIn("copy", self.codes(iss, "W"))

    def test_wrong_paragraph_low_overlap(self):
        # 内容写的是急诊科,却引用“怎么判断属于哪一类”的段落(同章里找一个无关段)
        far = next(p["id"] for p in self.w.ch_paras(self.ch) if "超市" in p["text"] and p["id"] != self.p_er)
        far2 = [p["id"] for p in self.w.ch_paras(self.ch)]
        # 选与 p_er 距离≥3 的段落,避免被 ±1 窗口覆盖
        n_er = self.w.paras[self.p_er]["n"]
        cand = [p for p in self.w.ch_paras(self.ch) if abs(p["n"] - n_er) >= 3]
        if not cand:
            self.skipTest("本章段落太少")
        iss = self.run_notes(self.mutate(lambda n: n["cards"][1].update(refs=[cand[0]["id"]])))
        self.assertTrue({"overlap", "anchor_misplaced"} & self.codes(iss))

    def test_parent_missing_and_cycle(self):
        iss = self.run_notes(self.mutate(lambda n: n["cards"][1].update(parent=f"{self.ch}.k9")))
        self.assertIn("parent_missing", self.codes(iss, "E"))
        def cyc(n):
            n["cards"][0].update(parent=f"{self.ch}.k2", rel="supports")
        iss = self.run_notes(self.mutate(cyc))
        self.assertIn("parent_cycle", self.codes(iss, "E"))

    def test_rel_required_with_parent(self):
        iss = self.run_notes(self.mutate(lambda n: n["cards"][1].update(rel=None)))
        self.assertIn("rel_missing", self.codes(iss, "E"))

    def test_evidence_needs_ev(self):
        def f(n):
            n["cards"][1].pop("ev")
        iss = self.run_notes(self.mutate(f))
        self.assertIn("ev_missing", self.codes(iss, "E"))

    def test_bad_enums(self):
        def f(n):
            n["cards"][0].update(kind="opinion", voice="narrator", tier=5)
        iss = self.run_notes(self.mutate(f))
        self.assertGreaterEqual(sum(1 for i in iss if i.code == "schema"), 3)

    def test_duplicate_id_and_wrong_prefix(self):
        def f(n):
            n["cards"][1]["id"] = n["cards"][0]["id"]
        self.assertIn("id_dup", self.codes(self.run_notes(self.mutate(f)), "E"))
        def g(n):
            n["cards"][1]["id"] = "c99.k1"
        self.assertIn("id_format", self.codes(self.run_notes(self.mutate(g)), "E"))

    def test_missing_meta_and_cards(self):
        iss = self.run_notes(self.mutate(lambda n: n.pop("meta")))
        self.assertIn("meta_count", self.codes(iss, "E"))
        iss = self.run_notes(self.mutate(lambda n: n.update(cards=[])))
        self.assertIn("no_cards", self.codes(iss, "E"))

    def test_split_parts_merge(self):
        w = Work(str(self.tmp / "w"))
        nd = self.tmp / "w" / "notes"
        if nd.exists():
            shutil.rmtree(nd)
        nd.mkdir()
        a = copy.deepcopy(self.base)
        b = {"chapter": self.ch, "cards": [a["cards"].pop()]}
        (nd / f"{self.ch}.json").write_text(json.dumps(a, ensure_ascii=False), encoding="utf8")
        (nd / f"{self.ch}.2.json").write_text(json.dumps(b, ensure_ascii=False), encoding="utf8")
        ck = Checker(w)
        ck.check_notes()
        bad = [i for i in ck.issues if i.level == "E" and i.where.startswith(self.ch)]
        self.assertEqual(bad, [], "\n".join(map(str, bad)))

    def test_objection_by_author_warns(self):
        def f(n):
            n["cards"][0].update(kind="objection")
        self.assertIn("voice", self.codes(self.run_notes(self.mutate(f)), "W"))

    def test_invalid_json_reported(self):
        w = Work(str(self.tmp / "w"))
        nd = self.tmp / "w" / "notes"
        if nd.exists():
            shutil.rmtree(nd)
        nd.mkdir()
        (nd / f"{self.ch}.json").write_text('{"chapter": "%s", "cards": [ {"id": }', encoding="utf8")
        ck = Checker(w)
        ck.check_notes()
        self.assertTrue(w.load_errors and "JSON 解析失败" in w.load_errors[0])


if __name__ == "__main__":
    unittest.main()
