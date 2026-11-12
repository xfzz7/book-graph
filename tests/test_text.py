import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from bklib import text as T  # noqa: E402

SRC = "调度员平均利用率超过90%的公司,其配送延误时间的波动幅度,是利用率低于80%的公司的2.6倍。注意我说的是波动幅度,不是平均延误。"
EN = "The committee observed that delays grew faster than demand did, and that the slack managers remove is the slack that absorbs surprises."


class TextTests(unittest.TestCase):
    def test_norm_strips_punct_and_width(self):
        self.assertEqual(T.norm("A, B！ c"), "abc")
        self.assertEqual(T.norm("利用率，超过"), "利用率超过")

    def test_lang(self):
        self.assertEqual(T.detect_lang(SRC), "zh")
        self.assertEqual(T.detect_lang(EN), "en")

    def test_copy_detected_zh(self):
        idx = T.CopyIndex(SRC, T.copy_threshold(SRC))
        self.assertGreaterEqual(idx.longest_shared("他说:配送延误时间的波动幅度,是利用率低于80%的公司的2.6倍,这很重要"), 16)
        # 改写后不触发
        self.assertEqual(idx.longest_shared("高负荷公司的延误起伏程度大约是低负荷公司的两点六倍"), 0)

    def test_copy_detected_en(self):
        idx = T.CopyIndex(EN, T.copy_threshold(EN))
        self.assertGreater(idx.longest_shared("Notes: the slack managers remove is the slack that absorbs surprises, said the author."), 40)
        self.assertEqual(idx.longest_shared("Managers who cut reserves lose their buffer against the unexpected."), 0)

    def test_overlap_discriminates(self):
        good = "利用率超过90%的公司,其延误的波动幅度是低于80%公司的2.6倍。"
        bad = "急诊科的床位使用率从78%上升到91%,平均等待时间显著增加。"
        self.assertGreater(T.overlap(good, SRC), 0.5)
        self.assertLess(T.overlap(bad, SRC), 0.3)

    def test_numbers(self):
        self.assertEqual(T.numbers("增长了1,200人,占2.6%,共14家"), {"1200", "2.6", "14"})

    def test_weight_monotonic(self):
        self.assertGreater(T.weight("汉字" * 100), T.weight("ab" * 50))


if __name__ == "__main__":
    unittest.main()
