#!/usr/bin/env python3
"""从 quiz.json 生成不含答案的题目文件(给“只看交付物作答”的答题者)。
用法: python blind_quiz.py OUT.json
"""
import json
import sys
from pathlib import Path

qs = json.loads((Path(__file__).parent / "quiz.json").read_text(encoding="utf8"))
Path(sys.argv[1]).write_text(json.dumps([{"id": q["id"], "q": q["q"]} for q in qs], ensure_ascii=False, indent=1), encoding="utf8")
print(f"{len(qs)} 题 → {sys.argv[1]}")
