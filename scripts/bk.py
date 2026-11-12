#!/usr/bin/env python3
"""nonfiction-book-companion 命令行。只用标准库(PDF 需要系统的 pdftotext)。

  bk ingest BOOK -w work          摄入:切章、给段落编号
  bk skeleton -w work             全书骨架(第 0 步用)
  bk read c03 [N] -w work         按块读一章(带段落 id)
  bk brief c03 -w work            章前简报(滚动记忆 + 下一个可用 id)
  bk digest [--max-tier 2]        把所有章笔记压成一份清单(综合/审读/出题用)
  bk find "关键词" -w work         在原文里检索段落
  bk check [c03] [--full] -w work 校验;带章键只查那一章
  bk status -w work               进度与下一步
  bk skip c01 [--undo] -w work    标记某章不读(版权页、索引等)
  bk audit-plan / audit-apply     独立核对
  bk build -o dist -w work        合并 + 渲染(HTML / Markdown / Anki)

退出码: 0 通过 / 1 有错误(或 --strict 下有警告) / 2 用法错误
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bklib import audit, brief, build, ingest  # noqa: E402
from bklib.check import Checker  # noqa: E402
from bklib.store import Work  # noqa: E402


def _print_issues(issues, only: str | None = None, show_info=False, limit=200):
    shown = 0
    for lv in ("E", "W", "I"):
        if lv == "I" and not show_info:
            continue
        for i in issues:
            if i.level != lv:
                continue
            if only and not (i.where.startswith(only) or i.where in ("synthesis", "全书") and False):
                continue
            print(i)
            shown += 1
            if shown >= limit:
                print(f"... 还有更多,用 --all 查看")
                return


def cmd_ingest(a):
    meta = ingest.build_source(a.book, a.work, a.heading_regex, a.min_weight)
    print(f"《{meta['title'] or '(无书名元数据)'}》 {meta['author']} · 语种 {meta['lang']} · 格式 {meta['format']} · 约 {meta['total_weight']} tokens")
    print(f"{'键':<5}{'类型':<6}{'段':>5}{'tokens':>8}  {'部':<10}标题")
    for c in meta["chapters"]:
        print(f"{c['key']:<5}{c['kind'] + ('*' if c['skip'] else ''):<6}{c['n_paras']:>5}{c['weight']:>8}  {c['part'][:9]:<10}{c['title']}")
    for wr in meta["warnings"]:
        print("⚠", wr)
    print("\n* = 默认跳过(版权页/索引等)。核对章列表是否与目录一致:不对就用 --heading-regex 重跑,或 bk skip 调整。")
    print(f"原文在 {a.work}/source/ 下——只作临时工作文件,不要提交或交付。")
    return 0


def cmd_skeleton(a):
    print(brief.skeleton(Work(a.work)))
    return 0


def cmd_read(a):
    w = Work(a.work)
    print(brief.render_chunk(w, a.chapter, a.part, a.budget))
    return 0


def cmd_brief(a):
    print(brief.brief(Work(a.work), a.chapter))
    return 0


def cmd_digest(a):
    print(brief.digest(Work(a.work), a.max_tier, a.ch))
    return 0


def cmd_find(a):
    print(brief.find(Work(a.work), a.query, a.top, a.ch))
    return 0


def cmd_check(a):
    w = Work(a.work)
    ck = Checker(w)
    ck.run(full=a.full or not a.chapter)
    issues = ck.issues
    if a.chapter:
        issues = [i for i in issues if i.where.startswith(a.chapter)]
    _print_issues(issues, show_info=a.all, limit=10 ** 6 if a.all else 60)
    e = sum(1 for i in issues if i.level == "E")
    wn = sum(1 for i in issues if i.level == "W")
    print(f"\n{'通过' if not e and not (a.strict and wn) else '未通过'}: {e} 个错误, {wn} 个警告" + ("" if a.all else "(--all 看全部与信息项)"))
    return 0 if not e and not (a.strict and wn) else 1


def cmd_status(a):
    txt, nxt = brief.status(Work(a.work))
    print(txt)
    print("\n下一步:", nxt)
    return 0


def cmd_skip(a):
    w = Work(a.work)
    c = w.chapter(a.chapter)
    c["skip"] = not a.undo
    w.save_meta()
    print(f"{a.chapter}《{c['title']}》 skip={c['skip']}")
    return 0


def cmd_audit_plan(a):
    w = Work(a.work)
    ck = Checker(w)
    ck.run(full=True)
    r = audit.plan(w, ck.issues, a.rate, a.seed, a.seeds, a.retry)
    print(f"待核对 {r['items']} 项 + 种子 {r['seeds']} 项,分 {r['batches']} 批 → {a.work}/audit/batch_*.md")
    print("把每批交给独立的核对者(新会话/子代理),按 references/prompts/05_audit.md 写 audit/verdicts_NN.json;不要让核对者看 _seeds.json。")
    return 0


def cmd_audit_apply(a):
    r = audit.apply(Work(a.work))
    print(f"通过 {r['ok']} 项,不通过 {r['flagged']} 项;累计已审 {r['total_logged']} 项")
    s = r["seed"]
    if s["total"]:
        print(f"种子故障识别率: {s['caught']}/{s['total']}" + (("  漏掉: " + "; ".join(s["missed"])) if s["missed"] else ""))
        if s["caught"] / s["total"] < 0.6:
            print("⚠ 识别率偏低:这次核对不够严,建议换一位核对者或加大抽样再来一轮。")
    if r["unanswered_seeds"]:
        print("⚠ 有种子条目没有被回答:", ", ".join(r["unanswered_seeds"]), "——核对者可能漏做了整批。")
    if r["flagged"]:
        print("下一步: bk check --full 查看哪些条目要修;修完 bk audit-plan --retry 重审。")
    return 0


def cmd_build(a):
    w = Work(a.work)
    ck = Checker(w)
    ck.run(full=True)
    errs = [i for i in ck.issues if i.level == "E"]
    warns = [i for i in ck.issues if i.level == "W"]
    if errs and not a.force:
        for i in errs[:40]:
            print(i)
        print(f"\n有 {len(errs)} 个错误,先修完再出图(不得已可 --force,但交付物会带着已知问题)。")
        return 1
    if warns:
        print(f"注意: 仍有 {len(warns)} 个警告(bk check --full 查看);它们会如实写进“可靠性说明”之外的你的交付说明里。")
    for p in build.build(w, a.out):
        print("已生成", p)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bk", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-w", "--work", default="work", help="工作目录(默认 work)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("ingest"); s.add_argument("book"); s.add_argument("--heading-regex"); s.add_argument("--min-weight", type=int, default=150); s.set_defaults(f=cmd_ingest)
    s = sub.add_parser("skeleton"); s.set_defaults(f=cmd_skeleton)
    s = sub.add_parser("read"); s.add_argument("chapter"); s.add_argument("part", nargs="?", type=int, default=1); s.add_argument("--budget", type=int, default=7000); s.set_defaults(f=cmd_read)
    s = sub.add_parser("brief"); s.add_argument("chapter"); s.set_defaults(f=cmd_brief)
    s = sub.add_parser("digest"); s.add_argument("--max-tier", type=int, default=3); s.add_argument("--ch"); s.set_defaults(f=cmd_digest)
    s = sub.add_parser("find"); s.add_argument("query"); s.add_argument("--top", type=int, default=8); s.add_argument("--ch"); s.set_defaults(f=cmd_find)
    s = sub.add_parser("check"); s.add_argument("chapter", nargs="?"); s.add_argument("--full", action="store_true"); s.add_argument("--strict", action="store_true"); s.add_argument("--all", action="store_true"); s.set_defaults(f=cmd_check)
    s = sub.add_parser("status"); s.set_defaults(f=cmd_status)
    s = sub.add_parser("skip"); s.add_argument("chapter"); s.add_argument("--undo", action="store_true"); s.set_defaults(f=cmd_skip)
    s = sub.add_parser("audit-plan"); s.add_argument("--rate", type=float, default=0.25); s.add_argument("--seed", type=int, default=7); s.add_argument("--seeds", type=int, default=6); s.add_argument("--retry", action="store_true"); s.set_defaults(f=cmd_audit_plan)
    s = sub.add_parser("audit-apply"); s.set_defaults(f=cmd_audit_apply)
    s = sub.add_parser("build"); s.add_argument("-o", "--out", default="dist"); s.add_argument("--force", action="store_true"); s.set_defaults(f=cmd_build)
    a = ap.parse_args(argv)
    try:
        return a.f(a)
    except (RuntimeError, FileNotFoundError) as e:
        print("错误:", e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
