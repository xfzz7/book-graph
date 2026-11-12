#!/usr/bin/env python3
"""bookguide:把一本非虚构书做成"帮读者真正读懂"的导读。脚本只做确定性的事,读和写由 LLM 完成。

    python scripts/bookguide.py prepare  book.epub -o work      # 分章 + 段落锚点 + 阅读分块
    python scripts/bookguide.py status   work                   # 进度与下一步(断点续做从这里开始)
    python scripts/bookguide.py brief    work c4                # 读第 c4 章前要看的简报(前情 + 已有概念 + 未解线索)
    python scripts/bookguide.py check    work --chapter c4      # 校验单章笔记
    python scripts/bookguide.py digest   work                   # 全书综合的输入:所有章节笔记的压缩版
    python scripts/bookguide.py verify-sheet work               # 生成事实核查单
    python scripts/bookguide.py check    work                   # 全量校验(交付前必须 0 错误)
    python scripts/bookguide.py build    work -o out            # 生成 导读.md / 导读.html / quiz.tsv

只依赖 Python ≥3.9 标准库(读 PDF 需要 pypdf)。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bg_check import load_work, make_verify_sheet, run_check  # noqa: E402
from bg_render import build  # noqa: E402
from bg_text import prepare  # noqa: E402

SKILL = Path(__file__).resolve().parent.parent
PY = Path(sys.executable).name or "python3"


def _print_report(R, quiet_info=False) -> int:
    for m in R.errors:
        print("错误:", m)
    for m in R.warns:
        print("提示:", m)
    if not quiet_info:
        for m in R.info:
            print("信息:", m)
    print(f"\n{'通过' if not R.errors else '未通过'}:{len(R.errors)} 个错误,{len(R.warns)} 个提示")
    return 0 if not R.errors else 1


def cmd_prepare(a):
    m = prepare(a.input, a.out, a.chunk_chars, a.min_chars, a.heading_regex, a.title, a.author)
    print(f"《{m['title']}》 {m['author']}  语言={m['lang']}  共 {m['total_chars']} 字符,{len(m['chapters'])} 章\n")
    print(f"{'id':<5}{'字符':>7}{'段':>5}  分块              标题")
    for c in m["chapters"]:
        flag = "  (附属内容,可跳过)" if c["skip_hint"] else ""
        print(f"{c['id']:<5}{c['chars']:>7}{c['paras']:>5}  {','.join(c['chunks']):<16}  {c['title']}{flag}")
    n = len(m["chapters"])
    if n == 1:
        print("\n警告:只切出 1 章。先看 source/c1.txt 里的章标题长什么样,再用 --heading-regex 重切。")
    big = [c for c in m["chapters"] if c["chars"] > 8 * m["chunk_chars"]]
    if big:
        print(f"\n警告:{','.join(c['id'] for c in big)} 特别长,可能是几章被并在了一起,请检查标题格式。")
    print(f"\n下一步:核对上表的章数和标题是否与原书目录一致;无误后运行 status {a.out}")
    return 0


def cmd_status(a):
    W, man, source, notes, (S, _) = load_work(a.work)
    todo = [c for c in man["chapters"] if c["id"] not in notes and not c.get("skip_hint")]
    print(f"《{man['title']}》 章节笔记 {len(notes)}/{len(man['chapters'])}")
    for c in man["chapters"]:
        mark = "✓" if c["id"] in notes else ("-" if c.get("skip_hint") else " ")
        print(f"  [{mark}] {c['id']:<4} {c['title']}")
    if todo:
        nxt = todo[0]["id"]
        print(f"\n下一步:{PY} {SKILL}/scripts/bookguide.py brief {a.work} {nxt}")
    elif S is None:
        print(f"\n下一步:章节笔记已齐。运行 {PY} {SKILL}/scripts/bookguide.py digest {a.work},按 references/synthesis.md 写 work/synthesis.json")
    elif not (W / "verify" / "verdicts.json").exists():
        print(f"\n下一步:运行 verify-sheet {a.work},按 references/verify.md 完成事实核查")
    else:
        print(f"\n下一步:运行 check {a.work};0 错误后 build")
    return 0


def cmd_brief(a):
    W, man, source, notes, _ = load_work(a.work)
    chs = man["chapters"]
    idx = next((i for i, c in enumerate(chs) if c["id"] == a.chapter), None)
    if idx is None:
        print(f"没有章节 {a.chapter}")
        return 1
    me = chs[idx]
    out = [f"# 章节简报:{me['id']} {me['title']}", "",
           f"书:《{man['title']}》 {man.get('author', '')}。全书 {len(chs)} 章,这是第 {idx + 1} 章。", "",
           "## 全书目录", ""]
    for c in chs:
        mark = "←当前" if c["id"] == me["id"] else ("已完成" if c["id"] in notes else "")
        out.append(f"- {c['id']} {c['title']}({c['chars']} 字符){' ' + mark if mark else ''}")
    prev = [c for c in chs[:idx] if c["id"] in notes and notes[c["id"]][0]]
    if prev:
        out += ["", "## 前情(已完成章节的问题、回答与核心命题)", ""]
        for c in prev:
            n = notes[c["id"]][0]
            out.append(f"### {c['id']} {c['title']}〔{n.get('role')}〕")
            out.append(f"问:{n.get('question')}  答:{n.get('answer')}")
            for cl in n.get("claims", []):
                if cl.get("weight") == 3:
                    out.append(f"- {cl['id']} {cl['text']}")
            out.append("")
    concepts = [(c["id"], x) for c in prev for x in notes[c["id"]][0].get("concepts", [])]
    if concepts:
        out += ["## 已登记的概念(本章再出现时沿用同一个 term,不要另起名字)", ""]
        out += [f"- {x['term']}({cid}):{x['definition']}" for cid, x in concepts]
        out.append("")
    closed = set()
    for c in prev:
        for x in (notes[c["id"]][0].get("threads") or {}).get("closes", []):
            m = re.match(r"^\s*(c\d+#\d+)", x if isinstance(x, str) else "")
            if m:
                closed.add(m.group(1))
    opens = [(f"{c['id']}#{i}", c["title"], o) for c in prev
             for i, o in enumerate((notes[c["id"]][0].get("threads") or {}).get("opens", []), 1)]
    opens = [x for x in opens if x[0] not in closed]
    if opens:
        out += ["## 前文留下、尚未回应的线索", "",
                "本章若回应了其中某条,在 threads.closes 里写 \"编号: 怎么回应的\",如 \"c1#2: 本章说明了……\"。", ""]
        out += [f"- {tid}({title}){o}" for tid, title, o in opens]
        out.append("")
    out += ["## 本章阅读安排", "",
            f"原文:{W / me['file']}(共 {me['paras']} 段)",
            f"按分块依次读:{', '.join(me['chunks'])}(每块读完先把命题记下,再读下一块)", "",
            f"写入:{W / 'notes' / (me['id'] + '.json')}(格式见 references/chapter-pass.md)",
            f"写完运行:{PY} {SKILL}/scripts/bookguide.py check {a.work} --chapter {me['id']}"]
    print("\n".join(out))
    return 0


def cmd_digest(a):
    W, man, source, notes, _ = load_work(a.work)
    out = [f"# 《{man['title']}》章节笔记汇编(全书综合的输入)", ""]
    for c in man["chapters"]:
        n = notes.get(c["id"], (None, None))[0]
        if not n:
            continue
        out += [f"## {c['id']} {c['title']}〔{n.get('role')}〕", f"问:{n.get('question')}", f"答:{n.get('answer')}"]
        for cl in n.get("claims", []):
            v = " [他人观点]" if cl.get("voice") == "reported" else ""
            out.append(f"- {cl['id']} w{cl.get('weight')} {cl.get('kind')}{v}:{cl['text']}  @{','.join(cl.get('anchors', []))}")
        for x in n.get("concepts", []):
            out.append(f"* 概念 {x['term']}:{x['definition']}" + (f"|区别:{x['distinct_from']}" if x.get("distinct_from") else ""))
        for l in n.get("links", []):
            out.append(f"> {l['from']} {l['rel']} {l['to']}")
        th = n.get("threads") or {}
        for o in th.get("opens", []):
            out.append(f"? 留下:{o}")
        for o in th.get("closes", []):
            out.append(f"! 回应:{o if isinstance(o, str) else json.dumps(o, ensure_ascii=False)}")
        out.append("")
    text = "\n".join(out)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"已写入 {a.out}({len(text)} 字符)")
    else:
        print(text)
    return 0


def cmd_check(a):
    return _print_report(run_check(a.work, a.chapter, a.copy_n))


def cmd_verify_sheet(a):
    p = make_verify_sheet(a.work, a.random)
    print(f"已生成 {p}\n请按 references/verify.md 逐条核对,结论写入 {Path(a.work) / 'verify' / 'verdicts.json'}")
    return 0


def cmd_build(a):
    R = run_check(a.work)
    if R.errors and not a.force:
        _print_report(R, quiet_info=True)
        print("先修完错误再生成(确有必要可加 --force,但交付物会带着问题)。")
        return 1
    for f in build(a.work, a.out, a.ui):
        print("已生成", f)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="非虚构书导读工具")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("prepare")
    p.add_argument("input")
    p.add_argument("-o", "--out", default="work")
    p.add_argument("--chunk-chars", type=int, default=12000, help="每个阅读分块的字符上限")
    p.add_argument("--min-chars", type=int, default=200, help="短于此的块并入前一章")
    p.add_argument("--heading-regex", help="自定义章标题正则(匹配到的行作为章标题)")
    p.add_argument("--title")
    p.add_argument("--author")
    p.set_defaults(f=cmd_prepare)
    p = sp.add_parser("status")
    p.add_argument("work")
    p.set_defaults(f=cmd_status)
    p = sp.add_parser("brief")
    p.add_argument("work")
    p.add_argument("chapter")
    p.set_defaults(f=cmd_brief)
    p = sp.add_parser("digest")
    p.add_argument("work")
    p.add_argument("-o", "--out")
    p.set_defaults(f=cmd_digest)
    p = sp.add_parser("check")
    p.add_argument("work")
    p.add_argument("--chapter")
    p.add_argument("--copy-n", type=int, help="照抄阈值(中文字数/英文词数),默认 20/12")
    p.set_defaults(f=cmd_check)
    p = sp.add_parser("verify-sheet")
    p.add_argument("work")
    p.add_argument("--random", type=int, default=10, help="随机抽查条数")
    p.set_defaults(f=cmd_verify_sheet)
    p = sp.add_parser("build")
    p.add_argument("work")
    p.add_argument("-o", "--out", default="out")
    p.add_argument("--ui", choices=["zh", "en"], help="导读界面语言,默认取 synthesis.lang")
    p.add_argument("--force", action="store_true")
    p.set_defaults(f=cmd_build)
    a = ap.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    raise SystemExit(main())
