#!/usr/bin/env python3
"""对旧版(v0.1)的 validate_book.py 做变异测试:往一份合格的 book.json 注入典型缺陷,看它能不能发现。
用法: python old_blindspots.py <旧版 scripts 目录> <旧版产出的 book.json> <原书文本 txt>
"""
import copy
import json
import random
import re
import sys

sys.path.insert(0, sys.argv[1])
from validate_book import validate  # noqa: E402

D = json.load(open(sys.argv[2], encoding="utf8"))
SRC = open(sys.argv[3], encoding="utf8").read()
rng = random.Random(1)


def detected(M):
    errs, warns = validate(M)
    return bool(errs or warns)


base_e, base_w = validate(D)
print(f"基线: {len(base_e)} 错误 {len(base_w)} 提示(应为 0/0 才公平)")
cases = []
# 1 改数字
for c in D["claims"]:
    if re.search(r"\d{2}", c["t"]):
        M = copy.deepcopy(D)
        m = next(x for x in M["claims"] if x["id"] == c["id"])
        m["t"] = re.sub(r"(\d{2,})", lambda g: str(int(g.group(1)) + 17), m["t"], count=1)
        cases.append(("改数字", detected(M)))
# 2 把观点方的命题 basis 改成 x/e(来源标注与事实不符)——无法被识别的语义错误:边方向反转
for l in rng.sample(D["links"], 12):
    M = copy.deepcopy(D)
    ml = next(x for x in M["links"] if x is not None and x["s"] == l["s"] and x["t"] == l["t"] and x["ty"] == l["ty"])
    ml["s"], ml["t"] = ml["t"], ml["s"]
    cases.append(("边方向反转", detected(M)))
# 3 凭空编造一条命题(并放进大纲)
for i in range(8):
    M = copy.deepcopy(D)
    ch = rng.choice(list(M["chapters"]))
    cid = f"zz{i}"
    M["claims"].append({"id": cid, "h": "编造", "t": f"作者在书中用一项随机对照实验证明了该结论,样本达到{rng.randint(200, 900)}人。", "ty": "E", "ch": ch, "basis": "e"})
    M["links"].append({"s": cid, "t": M["claims"][0]["id"], "ty": "support", "basis": "e", "note": "编造"})
    M["outline"][0]["chapters"][0]["points"].append({"text": "编造要点", "claims": [cid]})
    cases.append(("凭空编造", detected(M)))
# 4 整句照抄原文
sents = [s for s in re.split(r"[。\n]", SRC) if len(s) > 25]
for i in range(8):
    M = copy.deepcopy(D)
    M["claims"][i]["t"] = rng.choice(sents) + "。"
    cases.append(("整句照抄原文", detected(M)))
# 5 把“他人观点”写成作者主张:无对应字段,不可能被发现——这里用“把一条 V 的文本前缀改成‘作者认为’”模拟立场错标
for c in rng.sample([c for c in D["claims"] if c["ty"] == "V"], 8):
    M = copy.deepcopy(D)
    m = next(x for x in M["claims"] if x["id"] == c["id"])
    m["t"] = "作者坚决主张:" + m["t"]
    cases.append(("说过头/立场错标", detected(M)))
from collections import defaultdict
agg = defaultdict(lambda: [0, 0])
for k, d in cases:
    agg[k][0] += int(d)
    agg[k][1] += 1
tot = [sum(v[0] for v in agg.values()), sum(v[1] for v in agg.values())]
for k, (a, b) in agg.items():
    print(f"{k:<12} 发现 {a}/{b}")
print(f"合计 发现 {tot[0]}/{tot[1]}")
