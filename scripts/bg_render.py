"""notes + synthesis → 读者看的导读:guide.md、guide.html(单文件、离线可看)、quiz.tsv(可导入 Anki)。

导读里只放转述和位置(「第三章 ¶12」),不放原文段落。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from bg_check import all_claims, expand_anchor, load_work

L = {
    "zh": {
        "kind": {"claim": "主张", "mechanism": "机制", "method": "方法", "evidence": "证据",
                 "definition": "定义", "concession": "让步", "objection": "反方观点"},
        "rel": {"supports": "支持", "explains": "解释", "causes": "导致", "rebuts": "反驳",
                "qualifies": "限定", "applies": "应用于", "answers": "回答", "requires": "依赖"},
        "role": {"opening": "开篇", "problem": "提出问题", "concept": "立概念", "mechanism": "讲机制",
                 "evidence": "摆证据", "objection": "回应异议", "solution": "给方案", "application": "讲应用",
                 "synthesis": "收束", "limits": "谈局限", "background": "铺背景"},
        "qtype": {"recall": "记忆", "concept": "概念", "why": "为什么", "connect": "联系",
                  "apply": "应用", "misread": "辨误"},
        "para": "¶",
    },
    "en": {
        "kind": {"claim": "Claim", "mechanism": "Mechanism", "method": "Method", "evidence": "Evidence",
                 "definition": "Definition", "concession": "Concession", "objection": "Opposing view"},
        "rel": {"supports": "supports", "explains": "explains", "causes": "causes", "rebuts": "rebuts",
                "qualifies": "qualifies", "applies": "applies to", "answers": "answers", "requires": "requires"},
        "role": {"opening": "Opening", "problem": "Problem", "concept": "Concepts", "mechanism": "Mechanism",
                 "evidence": "Evidence", "objection": "Objections", "solution": "Solution",
                 "application": "Application", "synthesis": "Synthesis", "limits": "Limits", "background": "Background"},
        "qtype": {"recall": "Recall", "concept": "Concept", "why": "Why", "connect": "Connect",
                  "apply": "Apply", "misread": "Misreading"},
        "para": "¶",
    },
}

TXT = {
    "zh": dict(guide="导读", page="一页纸", q="这本书在回答什么", a="作者的回答", why="为什么值得读",
               ideas="关键思想", story="论证主线", support="理由", evid="证据", gloss="核心概念",
               notthis="别理解成", mis="容易读错的地方", wrong="常见误读", right="作者实际的意思",
               chap="逐章导读", ch_q="本章问题", ch_a="本章回答", limits="局限与批判",
               admits="作者自己承认的", critique="导读者的独立评估(不是作者的观点)", paths="阅读路线",
               quiz="自测题", ans="参考答案", where="出处", loc_note="出处标注为「章 ¶段落序号」,段落序号按原书章节内的自然段顺序计数。",
               opens="留下的问题", closes="回应了前文", reported="〔他人观点,非作者立场〕", links="与其他命题的关系",
               more="本章其余要点"),
    "en": dict(guide="Reader's Guide", page="One-page summary", q="The question", a="The author's answer",
               why="Why it matters", ideas="Key ideas", story="Line of argument", support="Because",
               evid="Evidence", gloss="Key concepts", notthis="Not to be confused with", mis="Common misreadings",
               wrong="Misreading", right="What the author actually says", chap="Chapter by chapter",
               ch_q="Question", ch_a="Answer", limits="Limits & critique", admits="Acknowledged by the author",
               critique="Independent assessment (not the author's view)", paths="Reading paths", quiz="Self-test",
               ans="Answer", where="Source", loc_note="Locations are given as 'chapter ¶paragraph', counting paragraphs within each chapter.",
               opens="Opens", closes="Picks up", reported="[reported view, not the author's]", links="Connections",
               more="Other points"),
}


def short_label(title: str) -> str:
    head = re.split(r"[\s::]", title.strip(), maxsplit=1)[0]
    return head if 0 < len(head) <= 8 else title[:10]


def assemble(work: str, ui: str | None = None) -> dict:
    W, man, source, notes, (S, serr) = load_work(work)
    if S is None:
        raise SystemExit(serr or "缺少 synthesis.json")
    ui = ui or S.get("lang") or "zh"
    labels = {c["id"]: short_label(c["title"]) for c in man["chapters"]}
    chapters = []
    for ch in man["chapters"]:
        n = notes.get(ch["id"], (None, None))[0]
        if not n:
            continue
        chapters.append({"id": ch["id"], "title": ch["title"], "label": labels[ch["id"]], "part": ch.get("part", ""),
                         **{k: n.get(k) for k in ("question", "answer", "role", "claims", "concepts", "links", "threads")}})
    claims = all_claims(notes)
    links = [dict(l, scope="chapter") for c in chapters for l in (c.get("links") or [])]
    links += [dict(l, scope="cross") for l in S.get("cross_links") or []]
    return {"ui": ui, "L": L[ui], "T": TXT[ui], "title": S.get("title") or man["title"],
            "author": S.get("author") or man.get("author", ""), "labels": labels,
            "chapters": chapters, "claims": claims, "links": links, "S": S}


def loc(a: str, labels: dict, para: str) -> str:
    m = re.match(r"^(c\d+)\.p(\d+)(?:-p?(\d+))?$", a)
    if not m:
        return a
    tail = m.group(2) + (f"–{m.group(3)}" if m.group(3) else "")
    return f"{labels.get(m.group(1), m.group(1))} {para}{tail}"


def to_markdown(G: dict) -> str:
    S, T, Lb, labels, C = G["S"], G["T"], G["L"], G["labels"], G["claims"]
    locs = lambda xs: "、".join(loc(a, labels, Lb["para"]) for a in xs or [])
    cl = lambda x: (f"{C[x]['text']}" + (f" {T['reported']}" if C[x].get('voice') == 'reported' else "")
                    + f"({locs(C[x].get('anchors'))})") if x in C else x
    out = [f"# 《{G['title']}》{T['guide']}", ""]
    if G["author"]:
        out += [f"作者:{G['author']}" if G["ui"] == "zh" else f"by {G['author']}", ""]
    out += [f"> {S['one_liner']}", "", f"## 1. {T['page']}", "",
            f"**{T['q']}**:{S['question']}", "", f"**{T['a']}**:{S['answer']}", ""]
    if S.get("why_read"):
        out += [f"**{T['why']}**:{S['why_read']}", ""]
    out += [f"**{T['ideas']}**:", ""]
    for k in S["key_ideas"]:
        out.append(f"{k.get('id', '')}. **{k['title']}** —— {k['text']}")
    out += ["", f"## 2. {T['story']}", ""]
    for i, s in enumerate(S["storyline"], 1):
        chs = sorted({x.split('.')[0] for x in s.get("claims", [])}, key=lambda c: int(c[1:]))
        out.append(f"{i}. {s['step']}〔{'、'.join(labels.get(c, c) for c in chs)}〕")
    out += ["", f"## 3. {T['ideas']}", ""]
    for k in S["key_ideas"]:
        out += [f"### {k.get('id', '')} {k['title']}", "", k["text"], ""]
        if k.get("because"):
            out += [f"- {T['support']}:"] + [f"  - {cl(x)}" for x in k["because"]]
        if k.get("evidence"):
            out += [f"- {T['evid']}:"] + [f"  - {cl(x)}" for x in k["evidence"]]
        out.append("")
    out += [f"## 4. {T['gloss']}", ""]
    for g in S["glossary"]:
        line = f"- **{g['term']}**"
        if g.get("aliases"):
            line += f"(又称 {'、'.join(g['aliases'])})" if G["ui"] == "zh" else f" (aka {', '.join(g['aliases'])})"
        line += f":{g['definition']}"
        if g.get("distinct_from"):
            line += f" {T['notthis']}:{g['distinct_from']}"
        if g.get("chapters"):
            line += f"〔{'、'.join(labels.get(c, c) for c in g['chapters'])}〕"
        out.append(line)
    if S.get("misreadings"):
        out += ["", f"## 5. {T['mis']}", ""]
        for m in S["misreadings"]:
            out += [f"- ✗ {m['wrong']}", f"  ✓ {m['right']}" + (f"({locs(m.get('anchors'))})" if m.get("anchors") else "")]
    out += ["", f"## 6. {T['chap']}", ""]
    for ch in G["chapters"]:
        out += [f"### {ch['title']}  〔{Lb['role'].get(ch.get('role'), ch.get('role', ''))}〕", "",
                f"- **{T['ch_q']}**:{ch['question']}", f"- **{T['ch_a']}**:{ch['answer']}"]
        for c in sorted(ch["claims"], key=lambda c: -c.get("weight", 1)):
            if c.get("weight", 1) >= 2:
                out.append(f"  - 【{Lb['kind'].get(c['kind'], c['kind'])}】{cl(c['id'])}")
        th = ch.get("threads") or {}
        if th.get("closes"):
            out.append(f"- {T['closes']}:" + ";".join(x if isinstance(x, str) else x.get("what", "") for x in th["closes"]))
        if th.get("opens"):
            out.append(f"- {T['opens']}:" + ";".join(th["opens"]))
        out.append("")
    lim = S.get("limits", {})
    out += [f"## 7. {T['limits']}", ""]
    if lim.get("author_admits"):
        out += [f"**{T['admits']}**", ""] + [f"- {x['text']}" + (f"({locs(x.get('anchors'))})" if x.get("anchors") else "") for x in lim["author_admits"]] + [""]
    if lim.get("critique"):
        out += [f"**{T['critique']}**", ""] + [f"- {x['text']}" for x in lim["critique"]] + [""]
    if S.get("reading_paths"):
        out += [f"## 8. {T['paths']}", ""]
        for p in S["reading_paths"]:
            out.append(f"- **{p['goal']}**:{' → '.join(labels.get(c, c) for c in p.get('chapters', []))}" + (f"。{p['note']}" if p.get("note") else ""))
        out.append("")
    out += [f"## 9. {T['quiz']}", ""]
    for i, q in enumerate(S["quiz"], 1):
        out.append(f"{i}. 〔{Lb['qtype'].get(q.get('type'), '')}〕{q['q']}")
    out += ["", f"<details><summary>{T['ans']}</summary>", ""]
    for i, q in enumerate(S["quiz"], 1):
        out.append(f"{i}. {q['answer']}({locs(q.get('anchors'))})")
    out += ["", "</details>", "", "---", "", f"_{T['loc_note']}_", ""]
    return "\n".join(out)


def to_tsv(G: dict) -> str:
    S, labels = G["S"], G["labels"]
    rows = []
    clean = lambda s: s.replace("\t", " ").replace("\n", " ")
    for q in S["quiz"]:
        rows.append(f"{clean(q['q'])}\t{clean(q['answer'])}\t{G['title']}")
    for g in S["glossary"]:
        back = g["definition"] + (f" | {g['distinct_from']}" if g.get("distinct_from") else "")
        rows.append(f"{clean(g['term'])}\t{clean(back)}\t{G['title']}")
    return "\n".join(rows) + "\n"


def build(work: str, out: str, ui: str | None = None) -> list[Path]:
    G = assemble(work, ui)
    o = Path(out)
    o.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]', "", G["title"])[:40] or "book"
    tpl = (Path(__file__).resolve().parent.parent / "assets" / "guide.html").read_text(encoding="utf-8")
    payload = json.dumps(G, ensure_ascii=False).replace("</", "<\\/")
    html, n = re.subn(r"/\*DATA\*/.*?/\*END\*/", lambda m: "/*DATA*/" + payload + "/*END*/", tpl, count=1, flags=re.S)
    if n != 1:
        raise RuntimeError("模板缺少 /*DATA*/…/*END*/ 占位符")
    files = [o / f"{safe}-{G['T']['guide']}.md", o / f"{safe}-{G['T']['guide']}.html", o / f"{safe}-quiz.tsv"]
    files[0].write_text(to_markdown(G), encoding="utf-8")
    files[1].write_text(html, encoding="utf-8")
    files[2].write_text(to_tsv(G), encoding="utf-8")
    return files
