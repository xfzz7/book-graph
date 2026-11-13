#!/usr/bin/env python3
"""零成本的事实覆盖对比:评测题参考答案里出现的数字和专名,有多少能在产出物里找到。
用法: python3 evals/fact_coverage.py <questions.json> <产出物文件>...
只衡量"信息在不在",不衡量好不好找、对不对——后者需要读者答题评测。"""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from bglib.textutil import number_forms, numbers

qs = json.load(open(sys.argv[1], encoding="utf-8"))
for f in sys.argv[2:]:
    text = Path(f).read_text(encoding="utf-8")
    have = number_forms(text)
    tot = hit = 0
    miss = []
    for q in qs:
        for n in sorted(numbers(q["gold"])):
            tot += 1
            if n in have or n.rstrip("%") in have:
                hit += 1
            else:
                miss.append(f"{q['id']}:{n}")
    names = ["柏昭南", "车以岚", "温特", "岑牧野", "裴南乔", "栖霞", "雾岛", "麦垛", "沅水", "禾灶", "泷川"]
    nh = [n for n in names if n in text]
    print(f"{Path(f).name}: 数字 {hit}/{tot} ({hit*100//tot}%), 专名 {len(nh)}/{len(names)}; 缺:{' '.join(miss[:14])}")
