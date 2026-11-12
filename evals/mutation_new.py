#!/usr/bin/env python3
"""对新版校验器做与 old_blindspots.py 同类的变异测试:往一份合格的笔记里注入缺陷,看静态校验能否发现。
语义类缺陷(说过头、立场错标、因果方向)静态校验无法判断,由独立核对 + 种子故障承担,这里单独列出。
用法: python mutation_new.py <工作目录(含 source/ 与合格的 notes/)>
"""
import copy
import json
import random
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from bklib.check import Checker  # noqa: E402
from bklib.store import Work  # noqa: E402

src = Path(sys.argv[1])
tmp = Path(tempfile.mkdtemp())
shutil.copytree(src / "source", tmp / "source")
rng = random.Random(1)
w0 = Work(str(src))
notes = {k: v for k, v in w0.load_notes().items()}
files = {k: json.loads((src / "notes" / f"{k}.json").read_text(encoding="utf8")) for k in notes if (src / "notes" / f"{k}.json").exists()}


def run(mut_files):
    nd = tmp / "notes"
    shutil.rmtree(nd, ignore_errors=True)
    nd.mkdir()
    for k, d in mut_files.items():
        (nd / f"{k}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf8")
    w = Work(str(tmp))
    ck = Checker(w)
    ck.check_notes()
    return [i for i in ck.issues if i.level in ("E", "W")]


base = run(files)
print(f"基线: {len(base)} 个 E/W(应为 0)")
all_cards = [(k, i, c) for k, d in files.items() for i, c in enumerate(d["cards"])]
res = {}


def record(name, found):
    res.setdefault(name, [0, 0])
    res[name][0] += int(found)
    res[name][1] += 1


def mutate(fn, pick):
    k, i, c = pick
    m = copy.deepcopy(files)
    fn(m[k]["cards"][i], m[k], k)
    return run(m)


# 1 改数字
for pick in [p for p in all_cards if re.search(r"\d{2}", p[2]["text"])][:12]:
    iss = mutate(lambda c, d, k: c.update(text=re.sub(r"(\d{2,})", lambda g: str(int(g.group(1)) + 17), c["text"], count=1)), pick)
    record("改数字", any(i.code == "numbers" and i.where == pick[2]["id"] for i in iss))
# 2 凭空编造(伪造 anchor 与引用)
for pick in rng.sample(all_cards, 8):
    iss = mutate(lambda c, d, k: c.update(text="作者在书中用一项随机对照实验证明了该结论,样本达到%d人。" % rng.randint(200, 900), anchor="随机对照实验证明"), pick)
    record("凭空编造", any(i.where == pick[2]["id"] and i.code in ("anchor_not_found", "numbers", "overlap") for i in iss))
# 3 整句照抄原文
for pick in rng.sample(all_cards, 8):
    k = pick[0]
    para = w0.paras[pick[2]["refs"][0]]["text"]
    s = max((x for x in re.split(r"[。！？]", para)), key=len)
    iss = mutate(lambda c, d, kk: c.update(text=s + "。"), pick)
    record("整句照抄原文", any(i.where == pick[2]["id"] and i.code == "copy" for i in iss))
# 4 引错段落
for pick in rng.sample(all_cards, 12):
    k = pick[0]
    n0 = w0.paras[pick[2]["refs"][0]]["n"]
    far = [p for p in w0.ch_paras(k) if abs(p["n"] - n0) >= 3]
    if not far:
        continue
    iss = mutate(lambda c, d, kk: c.update(refs=[rng.choice(far)["id"]]), pick)
    record("引错段落", any(i.where == pick[2]["id"] and i.code in ("overlap", "anchor_misplaced", "numbers") for i in iss))
# 5 结构类:父节点指向不存在 / 删掉 anchor
for pick in rng.sample(all_cards, 8):
    iss = mutate(lambda c, d, k: c.update(parent="c99.k1", rel="supports"), pick)
    record("悬空 parent", any(i.code == "parent_missing" for i in iss))
for pick in rng.sample(all_cards, 8):
    iss = mutate(lambda c, d, k: c.pop("anchor"), pick)
    record("缺 anchor", any(i.where == pick[2]["id"] for i in iss))
# 6 语义类(静态校验不做判断,需独立核对):说过头 / 立场错标 / 因果方向
for name in ("说过头(加“没有例外”)", "立场错标(other→author)", "关系方向反转"):
    for _ in range(8):
        record(name, False)
tot = [0, 0]
print(f"{'缺陷类型':<26}静态校验发现")
for k, (a, b) in res.items():
    print(f"{k:<26}{a}/{b}")
    tot[0] += a
    tot[1] += b
sem = sum(v[1] for k, v in res.items() if k.startswith(("说过头", "立场", "关系")))
print(f"合计 {tot[0]}/{tot[1]};其中语义类 {sem} 个静态校验设计上不覆盖,由独立核对(种子故障识别率)衡量")
shutil.rmtree(tmp, ignore_errors=True)
