#!/usr/bin/env python3
"""汇总评分。输入:评分文件(grades.json)= [{"id":"Q01","score":0|1|2,"note":""}],满分每题 2。
用法: python score.py grades.json [交付物字符数]
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

quiz = {q["id"]: q for q in json.loads((Path(__file__).parent / "quiz.json").read_text(encoding="utf8"))}
grades = {g["id"]: g for g in json.loads(Path(sys.argv[1]).read_text(encoding="utf8"))}
by = defaultdict(lambda: [0, 0])
tot = [0, 0]
for qid, q in quiz.items():
    s = grades.get(qid, {}).get("score", 0)
    by[q["type"]][0] += s
    by[q["type"]][1] += 2
    tot[0] += s
    tot[1] += 2
print(f"总分 {tot[0]}/{tot[1]} = {tot[0] / tot[1]:.1%}")
for t, (a, b) in sorted(by.items()):
    print(f"  {t:<10} {a:>3}/{b:<3} {a / b:.0%}")
if len(sys.argv) > 2:
    n = int(sys.argv[2])
    print(f"交付物 {n} 字符;每万字符得分 {tot[0] / n * 10000:.1f}")
