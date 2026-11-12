#!/usr/bin/env python3
"""book.json → 外部工具格式:Markdown 大纲 / CSV(Gephi) / GraphML / Obsidian 仓库。

用法:
    python scripts/export_formats.py book.json --format md       -o export/md
    python scripts/export_formats.py book.json --format csv      -o export/csv
    python scripts/export_formats.py book.json --format graphml  -o export/graphml
    python scripts/export_formats.py book.json --format obsidian -o export/obsidian

行为与 book-graph 仓库的 src/bookgraph/export.py 保持一致;只依赖标准库。
注意: csv 固定输出 nodes.csv / edges.csv,obsidian 直接平铺笔记,所以每本书请用独立的 -o 目录。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from validate_book import validate


def _safe(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|#^\[\]]', "", s).strip()


def to_markdown(D: dict) -> str:
    byid = {c["id"]: c for c in D["claims"]}
    tn = D["claimTypes"]
    L = [f"# {D['title']}", ""]
    if D.get("subtitle") or D.get("author"):
        L += [f"> {D.get('subtitle', '')} {('· ' + D['author']) if D.get('author') else ''}".strip(), ""]
    if D.get("thesis"):
        L += [f"**主张**:{D['thesis']}", ""]
    for part in D["outline"]:
        L += [f"## {part['label']}" + (f"  {part['sub']}" if part.get("sub") else ""), ""]
        if part.get("thesis"):
            L += [f"_{part['thesis']}_", ""]
        for ch in part["chapters"]:
            L += [f"### {ch['title']}", ""]
            if ch.get("takeaway"):
                L += [f"> {ch['takeaway']}", ""]
            for p in ch["points"]:
                L.append(f"- {p['text']}")
                for cid in p.get("claims", []):
                    c = byid[cid]
                    L.append(f"  - 【{tn[c['ty']]}】{c['t']}")
            L.append("")
    return "\n".join(L)


def to_csv(D: dict, outdir: Path) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    nodes, edges = outdir / "nodes.csv", outdir / "edges.csv"
    with nodes.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Id", "Label", "Type", "Chapter", "Basis", "Sentence"])
        for c in D["claims"]:
            w.writerow([c["id"], c["h"], D["claimTypes"][c["ty"]], c["ch"], c["basis"], c["t"]])
    with edges.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Source", "Target", "Type", "Label", "Basis", "Note"])
        for l in D["links"]:
            w.writerow([l["s"], l["t"], l["ty"], D["relTypes"][l["ty"]], l["basis"], l.get("note", "")])
    return [nodes, edges]


def to_graphml(D: dict) -> str:
    X = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">']
    for i, (n, d) in enumerate([("label", "node"), ("type", "node"), ("chapter", "node"),
                                ("sentence", "node"), ("reltype", "edge"), ("basis", "edge")]):
        X.append(f'<key id="k{i}" for="{d}" attr.name="{n}" attr.type="string"/>')
    X.append('<graph id="G" edgedefault="directed">')
    for c in D["claims"]:
        X.append(f'<node id="{escape(c["id"])}"><data key="k0">{escape(c["h"])}</data>'
                 f'<data key="k1">{escape(D["claimTypes"][c["ty"]])}</data>'
                 f'<data key="k2">{escape(c["ch"])}</data><data key="k3">{escape(c["t"])}</data></node>')
    for l in D["links"]:
        X.append(f'<edge source="{escape(l["s"])}" target="{escape(l["t"])}">'
                 f'<data key="k4">{escape(D["relTypes"][l["ty"]])}</data>'
                 f'<data key="k5">{escape(l["basis"])}</data></edge>')
    X += ["</graph>", "</graphml>"]
    return "\n".join(X)


def to_obsidian(D: dict, outdir: Path) -> int:
    """每个命题一页,frontmatter 带属性;关系用 Dataview 行内字段 + wikilink。"""
    outdir.mkdir(parents=True, exist_ok=True)
    byid = {c["id"]: c for c in D["claims"]}
    name = {cid: f"{cid} {_safe(c['h'])}" for cid, c in byid.items()}
    out_l, in_l = {}, {}
    for l in D["links"]:
        out_l.setdefault(l["s"], []).append(l)
        in_l.setdefault(l["t"], []).append(l)
    for cid, c in byid.items():
        F = ["---", f"id: {cid}", f"type: {D['claimTypes'][c['ty']]}", f"chapter: \"{c['ch']}\"",
             f"basis: {c['basis']}", "tags: [claim]", "---", "", c["t"], ""]
        if cid in out_l:
            F += ["## 指向", ""]
            for l in out_l[cid]:
                mark = "(推断)" if l["basis"] == "i" else ""
                F.append(f"- {l['ty']}:: [[{name[l['t']]}]] {mark}")
            F.append("")
        if cid in in_l:
            F += ["## 被指向", ""]
            for l in in_l[cid]:
                mark = "(推断)" if l["basis"] == "i" else ""
                F.append(f"- {l['ty']}-by:: [[{name[l['s']]}]] {mark}")
            F.append("")
        (outdir / f"{name[cid]}.md").write_text("\n".join(F), encoding="utf8")
    return len(byid)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="book.json → md / csv / graphml / obsidian")
    ap.add_argument("book")
    ap.add_argument("--format", choices=["md", "csv", "graphml", "obsidian"], required=True)
    ap.add_argument("-o", "--out", default="export")
    a = ap.parse_args(argv)

    with open(a.book, encoding="utf8") as f:
        D = json.load(f)
    errs, _ = validate(D)
    if errs:
        for e in errs:
            print("错误:", e, file=sys.stderr)
        print("先修完错误再导出。", file=sys.stderr)
        return 1

    out = Path(a.out)
    if a.format == "md":
        out.mkdir(parents=True, exist_ok=True)
        f = out / f"{D['title']}_大纲.md"
        f.write_text(to_markdown(D), encoding="utf8")
        print("已生成", f)
    elif a.format == "csv":
        for f in to_csv(D, out):
            print("已生成", f)
    elif a.format == "graphml":
        out.mkdir(parents=True, exist_ok=True)
        f = out / f"{D['title']}.graphml"
        f.write_text(to_graphml(D), encoding="utf8")
        print("已生成", f)
    else:
        print(f"已生成 {to_obsidian(D, out)} 个笔记 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
