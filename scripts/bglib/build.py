"""把校验过的笔记组装成读者用的导读:一个自包含 HTML + 一份 Markdown。原文不进入产物。"""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

from .checks import (CRIT_TYPES, EV_TYPES, KINDS, LINK_TYPES, PRIORITIES, Q_LEVELS, WEIGHTS,
                     all_claims, all_links, reach_pillars)
from .source import Source
from .textutil import units

TEMPLATE = Path(__file__).resolve().parents[2] / "assets" / "guide.html"


def assemble(src: Source, notes: dict, book: dict, issues, audit: dict) -> dict:
    claims = all_claims(notes)
    links = [{"from": l.get("from"), "to": l.get("to"), "type": l.get("type"), "note": l.get("note", "")}
             for l in all_links(notes, book) if l.get("from") in claims and l.get("to") in claims]
    reach = reach_pillars(claims, links, book)
    guide = {g.get("id"): g for g in (book.get("chapters") or []) if isinstance(g, dict)}
    chapters = []
    for ch in src.manifest["chapters"]:
        cid = ch["id"]
        n = notes.get(cid)
        if ch["skip"] or not n:
            chapters.append({"id": cid, "title": ch["title"], "chars": ch["chars"], "skip": True,
                             "why": ch.get("skip_reason", "")})
            continue
        ids = list(src.paras(cid))
        pos = {pid: i / max(1, len(ids) - 1) for i, pid in enumerate(ids)}
        cl = []
        for c in n.get("claims") or []:
            refs = [r for r in c.get("refs") or [] if r in pos]
            cl.append({"id": c["id"], "kind": c.get("kind"), "weight": c.get("weight"), "text": c.get("text"),
                       "quote": c.get("quote", ""), "ev": c.get("ev", ""),
                       "pos": round(min(pos[r] for r in refs), 2) if refs else None,
                       "pillars": sorted(reach.get(c["id"], []))})
        g = guide.get(cid, {})
        chapters.append({
            "id": cid, "title": ch["title"], "chars": ch["chars"], "skip": False,
            "priority": g.get("priority", ""), "why": g.get("why", ""),
            "role": n.get("role", ""), "summary": n.get("summary", ""), "claims": cl,
            "concepts": [cp.get("term") for cp in n.get("concepts") or [] if isinstance(cp, dict)],
            "skipped": [s.get("why", "") for s in n.get("skipped") or [] if isinstance(s, dict)],
        })
    pillars = []
    for p in book.get("pillars") or []:
        mine = [k for k, r in reach.items() if p["id"] in r]
        prof: dict[str, int] = {}
        for k in mine:
            if claims[k].get("kind") == "evidence":
                prof[claims[k].get("ev", "")] = prof.get(claims[k].get("ev", ""), 0) + 1
        pillars.append({**{f: p.get(f, "") for f in ("id", "title", "statement", "how")},
                        "claims": [k for k in p.get("claims") or [] if k in claims],
                        "depends_on": p.get("depends_on") or [],
                        "chapters": sorted({claims[k]["chapter"] for k in mine}),
                        "evidence": prof})
    concepts = []
    for cp in book.get("concepts") or []:
        concepts.append({"term": cp.get("term"), "def": cp.get("def"), "aka": cp.get("aka") or [],
                         "evolution": cp.get("evolution", ""), "vs": cp.get("vs") or [],
                         "chapters": sorted({r.split("-")[0] for r in cp.get("refs") or []})})
    qtot = sum(units(c.get("quote") or "") for c in claims.values())
    btot = max(1, sum(units(" ".join(src.paras(c["id"]).values())) for c in src.active()))
    return {
        "meta": {"title": book.get("title") or src.manifest["title"],
                 "author": book.get("author") or src.manifest.get("author", ""),
                 "chars": src.manifest["chars"], "generated": datetime.date.today().isoformat(),
                 "stats": {"claims": len(claims), "links": len(links), "concepts": len(concepts),
                           "chapters": len(notes), "warnings": len(issues.warnings),
                           "quote_pct": round(qtot * 100 / btot, 2), "audit": audit}},
        "labels": {"kind": KINDS, "weight": WEIGHTS, "ev": EV_TYPES, "link": LINK_TYPES,
                   "priority": PRIORITIES, "crit": CRIT_TYPES, "level": Q_LEVELS},
        "book": {"question": book.get("question", ""), "thesis": book.get("thesis", ""),
                 "abstract": book.get("abstract", ""), "book_type": book.get("book_type", ""),
                 "pillars": pillars, "concepts": concepts,
                 "critique": book.get("critique") or [], "questions": book.get("questions") or [],
                 "takeaways": book.get("takeaways") or []},
        "chapters": chapters, "links": links,
    }


def render_html(data: dict) -> str:
    tpl = TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    if "/*DATA*/null/*END*/" not in tpl:
        raise RuntimeError("模板里找不到 /*DATA*/null/*END*/ 占位符")
    return tpl.replace("/*DATA*/null/*END*/", payload).replace("__TITLE__", data["meta"]["title"].replace("<", "&lt;"))


def render_md(d: dict) -> str:
    L, b, m = d["labels"], d["book"], d["meta"]
    cmap = {c["id"]: c for ch in d["chapters"] if not ch["skip"] for c in ch["claims"]}
    chmap = {ch["id"]: ch for ch in d["chapters"]}
    o = [f"# 《{m['title']}》导读", "", f"{m['author']} · 原书约 {m['chars']} 字 · 导读生成于 {m['generated']}", "",
         "> 这是 AI 生成的导读:所有内容都是对原书的转述与分析,不能替代原书。「定位」后的短语是原文片段,可在你自己的书里搜索找到出处。", "",
         "## 一、速览", "", f"**这本书要回答的问题**:{b['question']}", "", f"**核心论点**:{b['thesis']}", "", b["abstract"], "",
         "### 论证的支柱", ""]
    for p in b["pillars"]:
        dep = f"(以 {'、'.join(p['depends_on'])} 为前提)" if p["depends_on"] else ""
        ev = "、".join(f"{L['ev'].get(k, k)}×{v}" for k, v in p["evidence"].items()) or "笔记中未记录到直接证据"
        o += [f"- **{p['id']} {p['title']}**{dep}:{p['statement']}", f"  - 如何支撑论点:{p['how']}",
              f"  - 证据构成:{ev};主要章节:{'、'.join(chmap[c]['title'] for c in p['chapters'])}"]
    o += ["", "### 怎么读原书", "", "| 章 | 建议 | 作用 | 理由 |", "|---|---|---|---|"]
    for ch in d["chapters"]:
        if not ch["skip"]:
            o.append(f"| {ch['title']} | {L['priority'].get(ch['priority'], '')} | {ch['role']} | {ch['why']} |")
    if b["takeaways"]:
        o += ["", "### 读完可以带走的", ""] + [f"- {t}" for t in b["takeaways"]]
    o += ["", "## 二、逐章", ""]
    for ch in d["chapters"]:
        if ch["skip"]:
            continue
        o += [f"### {ch['title']}", "", f"*{ch['role']}*", "", ch["summary"], ""]
        for c in ch["claims"]:
            if c["weight"] == "detail":
                continue
            tag = L["kind"].get(c["kind"], "") + (f"·{L['ev'].get(c['ev'], '')}" if c["ev"] else "")
            bold = "**" if c["weight"] == "core" else ""
            o.append(f"- [{tag}] {bold}{c['text']}{bold}(定位:「{c['quote']}」)")
        o.append("")
    o += ["## 三、概念", ""]
    for cp in b["concepts"]:
        o.append(f"- **{cp['term']}**:{cp['def']}" + (f" 演变:{cp['evolution']}" if cp["evolution"] else ""))
        for v in cp["vs"]:
            if isinstance(v, dict):
                o.append(f"  - 与「{v.get('term')}」的区别:{v.get('diff')}")
    o += ["", "## 四、审视(以下是导读的分析,不是作者的观点)", ""]
    for c in b["critique"]:
        o.append(f"- [{L['crit'].get(c.get('type'), '')}] {c.get('text')}(针对:{'、'.join(c.get('targets') or [])})")
    o += ["", "## 五、自测", ""]
    for i, q in enumerate(b["questions"], 1):
        o += [f"{i}. [{L['level'].get(q.get('level'), '')}] {q.get('q')}", "",
              f"   <details><summary>参考答案</summary>{q.get('a')}</details>", ""]
    a = m["stats"]["audit"]
    o += ["---", "", f"可靠性说明:共 {m['stats']['claims']} 条笔记,每条都带原文锚点并经机器核对;"
          + (f"独立核查 {a['total']} 条,{a['ok']} 条通过,{a['fixed']} 条经修正,{a['open']} 条未解决;" if a.get("total") else "未做独立核查;")
          + f"未处理的校验提示 {m['stats']['warnings']} 条;原文片段合计占原书 {m['stats']['quote_pct']}%。"]
    return "\n".join(o)


def build(src: Source, notes: dict, book: dict, issues, audit: dict, out: Path) -> list[Path]:
    data = assemble(src, notes, book, issues, audit)
    out.mkdir(parents=True, exist_ok=True)
    name = re.sub(r'[\\/:*?"<>|\s]+', "_", data["meta"]["title"]).strip("_") or "book"
    h, md = out / f"{name}_导读.html", out / f"{name}_导读.md"
    h.write_text(render_html(data), encoding="utf-8")
    md.write_text(render_md(data), encoding="utf-8")
    return [h, md]
