#!/usr/bin/env python3
"""nonfiction-book-graph 命令行。只依赖 Python ≥ 3.9 标准库。

  bg.py prepare <书> -w <work>      原书 → 按章按段编号的 source/
  bg.py status  -w <work>           进度与分章核对
  bg.py mark c00 --skip "原因" | --keep     标记/取消跳过某章
  bg.py skim    -w <work>           检视阅读包(每章首尾)→ 写 notes/brief.json
  bg.py context c03 -w <work>       读某章前的滚动记忆
  bg.py check [c03] -w <work> [--final]     校验一章 / 全书
  bg.py digest  -w <work>           全部笔记的紧凑视图 → 写 book.json
  bg.py audit   -w <work>           生成独立核查包
  bg.py build   -w <work>           生成导读(HTML + Markdown)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bglib import checks, packets, source  # noqa: E402
from bglib import build as builder  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, **kw):
        p = sub.add_parser(name, **kw)
        p.add_argument("-w", "--work", default="work", help="工作目录(默认 ./work)")
        return p

    p = add("prepare")
    p.add_argument("book", help="epub / txt / md / pdf,或一个每章一个 txt 的目录")
    p.add_argument("--by", choices=["auto", "toc", "heading", "file"], default="auto", help="EPUB 分章依据")
    p.add_argument("--toc-depth", type=int, help="EPUB 目录用到第几层")
    p.add_argument("--heading-regex", help="自定义章标题正则(匹配整行)")
    p.add_argument("--min-chars", type=int, default=150, help="短于此字数的\"章\"(如目录页里的标题行)并入前一章")
    p.add_argument("--part-tokens", type=int, default=9000, help="长章分批阅读时每批的 token 上限")
    p.add_argument("--title")
    p.add_argument("--author")
    add("status")
    p = add("mark")
    p.add_argument("chapters", nargs="+")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--skip", metavar="原因")
    g.add_argument("--keep", action="store_true")
    add("skim")
    p = add("context")
    p.add_argument("chapter")
    p = add("digest")
    p.add_argument("--core", action="store_true", help="只看主干和支撑,省略细节")
    p = add("check")
    p.add_argument("chapter", nargs="?")
    p.add_argument("--final", action="store_true", help="交付前的最终校验:要求已完成独立核查")
    p = add("audit")
    p.add_argument("-n", type=int, default=30, help="抽查条数(支柱命题与对手观点必查,其余随机)")
    p.add_argument("--renew", action="store_true", help="丢弃旧结果,重新抽样")
    p = add("build")
    p.add_argument("-o", "--out", help="输出目录(默认 <work>/guide)")
    p.add_argument("--draft", action="store_true", help="允许在未做独立核查时出草稿")
    a = ap.parse_args(argv)

    if a.cmd == "prepare":
        man = source.prepare(a.book, a.work, by=a.by, toc_depth=a.toc_depth, heading_regex=a.heading_regex,
                             min_chars=a.min_chars, part_tokens=a.part_tokens, title=a.title, author=a.author)
        src = source.Source(a.work)
        print(packets.status(src))
        ws = source.split_warnings(man)
        for w in ws:
            print("注意:", w)
        print("\n下一步:核对上面的分章是否与书的目录一致(章数、标题、有没有把正文误标为跳过),然后运行 skim。")
        return 0

    src = source.Source(a.work)
    if a.cmd == "status":
        print(packets.status(src))
        for w in source.split_warnings(src.manifest):
            print("注意:", w)
    elif a.cmd == "mark":
        for cid in a.chapters:
            if cid not in src.chapters:
                print(f"没有章节 {cid}", file=sys.stderr)
                return 1
            src.chapters[cid]["skip"] = not a.keep
            src.chapters[cid]["skip_reason"] = "" if a.keep else a.skip
        src.save_manifest()
        print(packets.status(src))
    elif a.cmd == "skim":
        print(packets.skim(src))
    elif a.cmd == "context":
        print(packets.context(src, a.chapter))
    elif a.cmd == "digest":
        print(packets.digest(src, "core" if a.core else "all"))
    elif a.cmd == "check":
        if a.chapter:
            iss = checks.Issues()
            note = checks.load_json(src.work / "notes" / f"{a.chapter}.json", iss, a.chapter)
            if note is not None:
                checks.check_chapter(src, a.chapter, note, iss)
            n = len(note.get("claims") or []) if isinstance(note, dict) else 0
        else:
            iss, _ = checks.check_all(a.work, final=a.final)
            n = None
        if iss.items:
            print(iss.render())
        print(f"\n{'通过' if not iss.errors else '未通过'}:错误 {len(iss.errors)},提示 {len(iss.warnings)}"
              + (f"({n} 条笔记)" if n is not None else ""))
        if iss.warnings and not iss.errors:
            print("提示不阻塞,但每一条都要处理:改掉,或确认无碍。未处理的提示数会写进导读的可靠性说明。")
        return 1 if iss.errors else 0
    elif a.cmd == "audit":
        pp, vp, pending = packets.audit_packet(src, n=a.n, renew=a.renew)
        print(f"核查包:{pp}\n结论表:{vp}(待填 {pending} 条)")
        print("请按 references/audit.md 核查:最好交给一个没读过笔记的子代理;做不到就自己逐条对照原文重读。")
    elif a.cmd == "build":
        iss, ctx = checks.check_all(a.work, final=not a.draft)
        if iss.errors:
            print(iss.render())
            print(f"\n还有 {len(iss.errors)} 个错误,不能出导读。" + ("" if a.draft else "(只想先看效果可加 --draft 跳过独立核查的要求)"))
            return 1
        out = Path(a.out) if a.out else src.work / "guide"
        for f in builder.build(src, ctx["notes"], ctx["book"], iss, ctx["audit"], out):
            print("已生成", f)
        if iss.warnings:
            print(f"(仍有 {len(iss.warnings)} 条提示未处理,已如实写入可靠性说明)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
