#!/usr/bin/env python3
"""book.json 独立校验器。只依赖标准库,规则与 book-graph 的 src/bookgraph/schema.py 一致。

用法:
    python scripts/validate_book.py book.json
    python scripts/validate_book.py book.json --strict

退出码: 0 通过 / 1 有错误(或 --strict 下有提示)
"""
from __future__ import annotations

import argparse
import json
import sys

CLAIM_BASIS = {"e", "x"}      # e=书中明确写出  x=作者经历/案例等外部依据
LINK_BASIS = {"e", "i"}       # e=书中明确写出  i=推断(页面中以虚线显示)
REQUIRED_TOP = ["title", "claimTypes", "relTypes", "chapters", "claims", "links", "outline"]


def validate(D: dict) -> tuple[list[str], list[str]]:
    errs: list[str] = []
    warns: list[str] = []
    for k in REQUIRED_TOP:
        if k not in D:
            errs.append(f"缺少顶层字段: {k}")
    if errs:
        return errs, warns

    ctypes, rtypes, chapters = D["claimTypes"], D["relTypes"], D["chapters"]
    ids: dict[str, dict] = {}
    for c in D["claims"]:
        cid = c.get("id")
        if not cid:
            errs.append(f"命题缺少 id: {c}")
            continue
        if cid in ids:
            errs.append(f"命题 id 重复: {cid}")
        ids[cid] = c
        for f in ("h", "t", "ty", "ch", "basis"):
            if f not in c:
                errs.append(f"{cid}: 缺少字段 {f}")
        if c.get("ty") not in ctypes:
            errs.append(f"{cid}: 未知命题类型 {c.get('ty')!r}")
        if c.get("ch") not in chapters:
            errs.append(f"{cid}: 未知章节 {c.get('ch')!r}")
        if c.get("basis") not in CLAIM_BASIS:
            errs.append(f"{cid}: basis 必须是 {sorted(CLAIM_BASIS)}")
        if len(c.get("h", "")) > 10:
            warns.append(f"{cid}: 短标签超过 10 字,图上可能放不下")
        if len(c.get("t", "")) < 10:
            warns.append(f"{cid}: 句子过短,是否只是个词?")

    seen = set()
    for i, l in enumerate(D["links"]):
        tag = f"link#{i} {l.get('s')}->{l.get('t')}"
        if l.get("s") not in ids or l.get("t") not in ids:
            errs.append(f"{tag}: 端点不存在")
            continue
        if l["s"] == l["t"]:
            errs.append(f"{tag}: 自环")
        if l.get("ty") not in rtypes:
            errs.append(f"{tag}: 未知关系类型 {l.get('ty')!r}")
        if l.get("basis") not in LINK_BASIS:
            errs.append(f"{tag}: basis 必须是 {sorted(LINK_BASIS)}")
        key = (l["s"], l["t"], l.get("ty"))
        if key in seen:
            warns.append(f"{tag}: 重复的边")
        seen.add(key)

    covered = set()
    for part in D["outline"]:
        for ch in part.get("chapters", []):
            if ch.get("k") not in chapters:
                errs.append(f"大纲章节 {ch.get('k')!r} 不在 chapters 中")
            for p in ch.get("points", []):
                for cid in p.get("claims", []):
                    if cid not in ids:
                        errs.append(f"大纲引用了不存在的命题: {cid}")
                    covered.add(cid)
    for cid in ids:
        if cid not in covered:
            warns.append(f"{cid}: 未出现在任何大纲要点中")

    linked = {x for l in D["links"] for x in (l.get("s"), l.get("t"))}
    for cid in ids:
        if cid not in linked:
            warns.append(f"{cid}: 孤立命题,没有任何关系")
    return errs, warns


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="校验 book.json")
    ap.add_argument("book")
    ap.add_argument("--strict", action="store_true", help="提示也算失败")
    a = ap.parse_args(argv)
    with open(a.book, encoding="utf8") as f:
        D = json.load(f)

    errs, warns = validate(D)
    for e in errs:
        print("错误:", e, file=sys.stderr)
    for w in warns:
        print("提示:", w, file=sys.stderr)
    ok = not errs and not (a.strict and warns)
    print("校验通过" if ok else f"校验失败: {len(errs)} 个错误, {len(warns)} 个提示")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
