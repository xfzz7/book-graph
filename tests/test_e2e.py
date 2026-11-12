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
import mini_gold  # noqa: E402
from bklib import audit, build, ingest  # noqa: E402
from bklib.check import Checker  # noqa: E402
from bklib.store import Work  # noqa: E402


class E2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        epub = cls.tmp / "c.epub"
        F.make_canary_epub(epub)
        ingest.build_source(str(epub), str(cls.tmp / "w"))
        cls.w = Work(str(cls.tmp / "w"))
        mini_gold.build_gold(cls.w)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_gold_checks_clean(self):
        ck = Checker(Work(str(self.tmp / "w")))
        ck.run(full=True)
        bad = [i for i in ck.issues if i.level == "E" and i.code != "audit_missing"]
        self.assertEqual(bad, [], "\n".join(map(str, bad)))

    def test_audit_plan_and_apply_roundtrip(self):
        w = Work(str(self.tmp / "w"))
        ck = Checker(w)
        ck.run(full=True)
        r = audit.plan(w, ck.issues, rate=0.5, seed=1, seeds=4)
        self.assertGreater(r["batches"], 0)
        seeds = json.loads((w.audit_dir / "_seeds.json").read_text(encoding="utf8"))
        self.assertGreaterEqual(len(seeds), 3)
        # 模拟一位“完美核对者”:种子都标不通过,其余 ok
        packets = "".join(p.read_text(encoding="utf8") for p in sorted(w.audit_dir.glob("batch_*.md")))
        import re
        ids = re.findall(r"^## 条目 (\S+)", packets, re.M)
        verdicts = [{"id": i, "verdict": "distorted" if i in seeds else "ok", "note": "x"} for i in ids]
        (w.audit_dir / "verdicts_01.json").write_text(json.dumps(verdicts), encoding="utf8")
        res = audit.apply(Work(str(self.tmp / "w")))
        self.assertEqual(res["seed"]["caught"], res["seed"]["total"])
        self.assertEqual(res["flagged"], 0)
        # 种子文本不应进入 log
        log = json.loads((w.audit_dir / "log.json").read_text(encoding="utf8"))
        self.assertFalse(any(k.startswith("s0") for k in log))

    def test_build_outputs_and_no_source_leak(self):
        w = Work(str(self.tmp / "w"))
        out = self.tmp / "dist"
        files = build.build(w, str(out))
        self.assertEqual({f.suffix for f in files}, {".html", ".md", ".tsv"})
        blob = "".join(f.read_text(encoding="utf8") for f in files)
        # 交付物里不应出现原文的长片段(用 CopyIndex 逐段检查所有输出文本)
        from bklib.text import CopyIndex, copy_threshold
        src = w.book_text()
        idx = CopyIndex(src, copy_threshold(src))
        md = next(f for f in files if f.suffix == ".md").read_text(encoding="utf8")
        worst = max((idx.longest_shared(line) for line in md.splitlines() if line.strip()), default=0)
        # anchor 在 md 里以「检索」形式出现,允许;但任何一行的最长公共片段不应超过 anchor 上限
        self.assertLess(worst, 40, f"交付物里有疑似原文长片段: {worst}")
        book = json.loads((w.root / "book.json").read_text(encoding="utf8"))
        self.assertNotIn("paras", book)

    def test_stale_audit_after_edit(self):
        w = Work(str(self.tmp / "w"))
        log = json.loads((w.audit_dir / "log.json").read_text(encoding="utf8")) if (w.audit_dir / "log.json").exists() else None
        if not log:
            self.skipTest("需先跑 roundtrip")
        k = next(iter(log))
        log[k]["verdict"] = "unsupported"
        (w.audit_dir / "log.json").write_text(json.dumps(log), encoding="utf8")
        ck = Checker(Work(str(self.tmp / "w")))
        ck.run(full=True)
        self.assertTrue(any(i.code == "audit_unresolved" and i.where == k for i in ck.issues))


if __name__ == "__main__":
    unittest.main()
