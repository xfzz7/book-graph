"""把各步产物合并成 book.json,并渲染 HTML / Markdown / Anki 卡片。

交付物里不含原文段落,只有:转述的命题、定位信息(章/小节/大致位置)、以及短的“检索短语”(anchor,
用来在电子书里 Ctrl+F 回到原处)。
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date
from pathlib import Path

from . import schema as S
from .audit import items as audit_items
from .store import Work
from .text import norm, weight

TPL = Path(__file__).resolve().parent.parent.parent / "assets" / "guide.html"
_DATA = re.compile(r"/\*DATA\*/.*?/\*END\*/", re.S)


def merge(w: Work) -> dict:
    m = w.meta
    notes = w.load_notes()
    sy = w.read_json("synthesis.json") or {}
    cr = w.read_json("critique.json") or {}
    qs = w.read_json("questions.json") or []
    log = w.read_json("audit/log.json") or {}
    seed = w.read_json("audit/seed_result.json") or {}
    chmeta = {c["key"]: c for c in m["chapters"]}

    cards = {}
    for key, n in notes.items():
        c = chmeta[key]
        for cd in n["cards"]:
            p0 = w.paras[cd["refs"][0]]
            a = log.get(cd["id"])
            cards[cd["id"]] = {
                "id": cd["id"], "text": cd["text"], "label": cd["label"], "kind": cd["kind"], "voice": cd["voice"],
                "tier": cd["tier"], "parent": cd.get("parent"), "rel": cd.get("rel"), "ch": key,
                "ev": cd.get("ev"), "waived": cd.get("waive") or [],
                "loc": {"ch": key, "chTitle": c["title"], "sec": p0.get("sec", ""), "pos": round(100 * p0["n"] / max(1, c["n_paras"])),
                        "para": p0["n"], "of": c["n_paras"], "anchor": cd["anchor"]},
                "audit": (a["verdict"] if a else None),
            }
    chapters = []
    for c in w.chapters():
        n = notes.get(c["key"])
        if not n:
            continue
        meta = n["meta"] or {}
        chapters.append({"key": c["key"], "title": c["title"], "part": c["part"], "kind": c["kind"], "role": meta.get("role", ""),
                         "summary": meta.get("summary", ""), "takeaway": meta.get("takeaway", ""), "priority": meta.get("priority", "normal"),
                         "readingQuestions": meta.get("reading_questions", []), "cards": [x["id"] for x in n["cards"]],
                         "weight": c["weight"]})
    concepts = []
    for con in sy.get("concepts", []) or []:
        loc = None
        if con.get("refs") and con["refs"][0] in w.paras:
            p = w.paras[con["refs"][0]]
            ch = chmeta[p["ch"]]
            loc = {"ch": p["ch"], "chTitle": ch["title"], "sec": p.get("sec", ""), "pos": round(100 * p["n"] / max(1, ch["n_paras"]))}
        concepts.append(dict(con, loc=loc))
    links = []
    for key, n in notes.items():
        for lk in n["links"]:
            links.append({"from": lk["from"], "to": lk["to"], "type": lk["type"], "note": lk["note"]})
    ai = audit_items(w)
    audited = [k for k in log if k in ai]
    ok = [k for k in audited if log[k]["verdict"] == "ok"]
    quality = {
        "cards": len(cards), "audited": len(audited), "auditOk": len(ok),
        "seeds": seed, "waived": sum(1 for c in cards.values() if c["waived"]),
        "outside": sum(1 for it in cr.get("items", []) if it.get("source") == "outside"),
        "anchorChars": sum(len(c["loc"]["anchor"]) for c in cards.values()), "sourceWeight": m["total_weight"],
        "date": str(date.today()),
    }
    reading_plan = sy.get("reading_plan", {})
    return {
        "meta": {"title": m["title"], "author": m["author"], "lang": m["lang"], "sourceFile": m["source_file"],
                 "genre": S.GENRES.get(sy.get("genre"), sy.get("genre", "")), "weight": m["total_weight"]},
        "brief": {k: sy.get(k) for k in ("one_liner", "question", "thesis", "audience", "parts", "misreadings")} | {"readingPlan": reading_plan},
        "pillars": sy.get("pillars", []), "attach": sy.get("attach", {}), "chains": sy.get("chains", []),
        "cards": cards, "chapters": chapters, "concepts": concepts, "links": links,
        "critique": cr, "questions": qs, "quality": quality,
        "enums": {"kinds": S.KINDS, "rels": S.RELS, "voices": S.VOICES, "evTypes": S.EV_TYPES, "evStrength": S.EV_STRENGTH,
                  "critTypes": S.CRIT_TYPES, "qKinds": S.Q_KINDS, "priority": S.PRIORITY, "origin": S.CONCEPT_ORIGIN,
                  "linkTypes": S.LINK_TYPES, "severity": S.SEVERITY},
    }


def render_html(book: dict) -> str:
    tpl = TPL.read_text(encoding="utf8")
    payload = json.dumps(book, ensure_ascii=False).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    out, n = _DATA.subn(lambda m: "/*DATA*/" + payload + "/*END*/", tpl, count=1)
    if n != 1:
        raise RuntimeError("模板里找不到 /*DATA*/…/*END*/")
    return out.replace("<title>阅读指南</title>", f"<title>{book['meta']['title']} · 阅读指南</title>")


def _loc(c: dict) -> str:
    l = c["loc"]
    s = f"{l['chTitle']}"
    if l["sec"]:
        s += f" › {l['sec']}"
    return s + f" · 约 {l['pos']}% · 检索「{l['anchor']}」"


def render_md(b: dict) -> str:
    E = b["enums"]
    cards = b["cards"]
    kids: dict[str, list] = {}
    for c in cards.values():
        if c["parent"]:
            kids.setdefault(c["parent"], []).append(c)
    ch_order = {c["key"]: i for i, c in enumerate(b["chapters"])}
    L = [f"# {b['meta']['title']} · 阅读指南", ""]
    if b["meta"]["author"]:
        L.append(f"> {b['meta']['author']} · {b['meta']['genre']}")
        L.append("")
    br = b["brief"]
    L += ["## 一页读懂", "", f"**一句话**:{br['one_liner']}", "", f"**这本书在回答**:{br['question']}", "", f"**它的答案**:{br['thesis']}", "",
          f"**适合谁读**:{br['audience']}", ""]
    rp = br.get("readingPlan") or {}
    ct = {c["key"]: c["title"] for c in b["chapters"]}
    if rp:
        L.append("**怎么读**:" + (rp.get("why") or ""))
        for fld, name in (("must", "精读"), ("skim", "略读"), ("skip", "可跳过")):
            if rp.get(fld):
                L.append(f"- {name}:" + "、".join(ct.get(k, k) for k in rp[fld]))
        L.append("")
    if br.get("misreadings"):
        L += ["### 容易读错的地方", ""]
        for m in br["misreadings"]:
            L.append(f"- ✗ {m['wrong']}  → ✓ {m['right']}")
        L.append("")
    L += ["## 论证地图", "", f"**全书主张**:{br['thesis']}", ""]
    att: dict[str, list] = {}
    for cid, pid in b["attach"].items():
        att.setdefault(pid, []).append(cid)

    def node(c, depth):
        voice = "" if c["voice"] == "author" else f"〔{E['voices'][c['voice']]}〕"
        rel = f"({E['rels'][c['rel']]}) " if c.get("rel") else ""
        ev = ""
        if c.get("ev"):
            ev = f" 〔证据:{E['evStrength'][c['ev']['strength']]};{c['ev']['limit']}〕"
        pad = "  " * depth
        L.append(f"{pad}- {rel}**{c['label']}**{voice}:{c['text']}{ev}")
        L.append(f"{pad}  _{_loc(c)}_")
        for k in sorted(kids.get(c["id"], []), key=lambda x: (ch_order.get(x["ch"], 0), x["id"])):
            if k["tier"] <= 2:
                node(k, depth + 1)

    for p in b["pillars"]:
        L += [f"### {p['id']} {p['label']}", "", p["text"], ""]
        for cid in att.get(p["id"], []):
            node(cards[cid], 0)
        L.append("")
    if b["chains"]:
        L += ["### 因果链 / 回路", ""]
        for ch in b["chains"]:
            arrow = " → ".join(cards[s]["label"] for s in ch["steps"]) + (" ↺" if ch.get("loop") else "")
            L.append(f"- **{ch['name']}**:{arrow}" + (f"  ({ch['note']})" if ch.get("note") else ""))
        L.append("")
    rev = [l for l in b["links"] if l["type"] in ("revises", "tension")]
    if rev:
        L += ["### 书中的自我修正与张力", ""]
        for l in rev:
            L.append(f"- {cards[l['from']]['label']} ⇄ {cards[l['to']]['label']}:{l['note']}")
        L.append("")
    L += ["## 章节导读", ""]
    for c in b["chapters"]:
        L += [f"### {c['title']}  〔{E['priority'][c['priority']]}〕", "", f"- 在全书中的作用:{c['role']}", f"- 内容:{c['summary']}",
              f"- 一句话带走:{c['takeaway']}", "- 读之前想想:" + ";".join(c["readingQuestions"]), ""]
    L += ["## 概念表", ""]
    for k in b["concepts"]:
        s = f"- **{k['term']}**〔{E['origin'][k['origin']]}〕:{k['def']}"
        if k.get("not"):
            s += f"(区别:{k['not']})"
        L.append(s)
    L.append("")
    cr = b["critique"]
    L += ["## 审读", "", f"**总评**:{cr.get('verdict', '')}", ""]
    for s in cr.get("strengths", []):
        L.append(f"- ✓ {s}")
    L.append("")
    for it in cr.get("items", []):
        src = "书中自述" if it["source"] == "book" else "外部判断·需自行核实"
        L.append(f"- [{E['critTypes'][it['type']]}·{E['severity'][it['severity']]}·{src}] {it['text']}")
    L += ["", "### 证据账本", "", "| 证据 | 类型 | 强度 | 局限 | 位置 |", "|---|---|---|---|---|"]
    for c in cards.values():
        if c.get("ev"):
            L.append(f"| {c['label']} | {E['evTypes'][c['ev']['type']]} | {E['evStrength'][c['ev']['strength']]} | {c['ev']['limit']} | {c['loc']['chTitle']} |")
    L += ["", "## 自测", ""]
    for i, q in enumerate(b["questions"], 1):
        L += [f"{i}. 〔{E['qKinds'][q['kind']]}〕{q['q']}", f"   - 答:{q['a']}"]
    meths = [c for c in cards.values() if c["kind"] == "method"]
    if meths:
        L += ["", "## 行动清单", ""]
        for c in meths:
            L.append(f"- **{c['label']}**:{c['text']}")
            for k in kids.get(c["id"], []):
                if k["kind"] in ("caveat",) or k.get("rel") == "qualifies":
                    L.append(f"  - 注意:{k['text']}")
    q = b["quality"]
    L += ["", "## 可靠性说明", "",
          f"- 共 {q['cards']} 张卡片,每张都带定位与检索短语;{q['audited']} 项经独立核对,其中 {q['auditOk']} 项通过。",
          f"- 审读里 {q['outside']} 条是外部判断(不在书中),已单独标注。"]
    sd = q.get("seeds") or {}
    if sd.get("total"):
        L.append(f"- 核对者在 {sd['total']} 个故意写坏的条目中识别出 {sd['caught']} 个。")
    return "\n".join(L) + "\n"


def render_anki(b: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter="\t", lineterminator="\n")
    title = re.sub(r"\s+", "_", b["meta"]["title"])
    cards = b["cards"]
    for q in b["questions"]:
        loc = ""
        if q.get("cards") and q["cards"][0] in cards:
            loc = " ‖ 出处:" + _loc(cards[q["cards"][0]])
        w.writerow([q["q"], q["a"] + loc, f"{title} {q['kind']}"])
    for k in b["concepts"]:
        w.writerow([f"《{b['meta']['title']}》里的「{k['term']}」是什么意思?", k["def"] + (f"(区别:{k['not']})" if k.get("not") else ""), f"{title} 概念"])
    for m in b["brief"].get("misreadings", []) or []:
        w.writerow([f"常见误读:“{m['wrong']}”——书里实际怎么说?", m["right"], f"{title} 易错"])
    return buf.getvalue()


def build(w: Work, outdir: str) -> list[Path]:
    b = merge(w)
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    w.write_json("book.json", b)
    safe = re.sub(r'[\\/:*?"<>|]', "", b["meta"]["title"]).strip() or "book"
    files = []
    for name, content in ((f"{safe}_阅读指南.html", render_html(b)), (f"{safe}_阅读指南.md", render_md(b)), (f"{safe}_记忆卡片.tsv", render_anki(b))):
        p = out / name
        p.write_text(content, encoding="utf8")
        files.append(p)
    return files
