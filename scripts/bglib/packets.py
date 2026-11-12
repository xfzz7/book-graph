"""给执行者(LLM)看的"上下文包":skim / context / digest / audit。
目的:任何一步都不需要把整本书或全部笔记留在上下文里——需要什么,脚本现算现给。"""
from __future__ import annotations

import json
import random
from pathlib import Path

from .checks import (KINDS, LINK_TYPES, WEIGHTS, Issues, all_claims, load_json, text_hash)
from .source import Source


def _load_note(src: Source, cid: str):
    p = src.work / "notes" / f"{cid}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def status(src: Source) -> str:
    m = src.manifest
    out = [f"《{m['title']}》 {m.get('author', '')} · 语言 {m['lang']} · 约 {m['chars']} 字 / {m['tokens']} tokens · 分章方式 {m['split_by']}", ""]
    out.append("  章    字数   段数  批次  笔记  标题")
    for c in m["chapters"]:
        note = "跳过" if c["skip"] else ("✓" if (src.work / "notes" / f"{c['id']}.json").exists() else "—")
        out.append(f"  {c['id']:<5} {c['chars']:>6} {c['paras']:>5} {len(c['parts']):>4}   {note:<3} {c['title'][:40]}"
                   + (f"   ← {c['skip_reason']}" if c["skip"] else ""))
    out.append("")
    out.append(f"brief.json: {'✓' if (src.work / 'notes' / 'brief.json').exists() else '—'}   "
               f"book.json: {'✓' if (src.work / 'book.json').exists() else '—'}   "
               f"audit: {'✓' if (src.work / 'audit' / 'verdicts.json').exists() else '—'}")
    return "\n".join(out)


def skim(src: Source, budget_tokens: int = 14000) -> str:
    """检视阅读包:目录 + 每章开头结尾。"""
    chs = src.active()
    per = max(300, min(900, int(budget_tokens / max(1, len(chs)) / 1.3)))
    is_zh = src.manifest["lang"] == "zh"
    if not is_zh:
        per *= 3
    out = [f"# 检视阅读包:《{src.manifest['title']}》", "",
           "下面是每章的开头和结尾(各取若干段)。用它形成对全书的**假设**,写入 notes/brief.json。",
           "序言/导论/结语通常直接陈述全书主张——如果有,请另外完整读一遍对应的 source/cNN.txt。", ""]
    for c in chs:
        paras = list(src.paras(c["id"]).items())
        out.append(f"## {c['id']} {c['title']}  ({c['chars']} 字, {c['paras']} 段)")
        head, used = [], 0
        for pid, t in paras:
            if used >= per * 0.6:
                break
            head.append((pid, t))
            used += len(t)
        tail, used = [], 0
        for pid, t in reversed(paras[len(head):]):
            if used >= per * 0.4:
                break
            tail.insert(0, (pid, t))
            used += len(t)
        for pid, t in head:
            out.append(f"[{pid}] {t}")
        if len(head) + len(tail) < len(paras):
            out.append(f"  …(中间 {len(paras) - len(head) - len(tail)} 段略)…")
        for pid, t in tail:
            out.append(f"[{pid}] {t}")
        out.append("")
    return "\n".join(out)


def context(src: Source, cid: str) -> str:
    """读某一章之前的滚动记忆:全书假设 + 已读各章的主干 + 已有概念表。"""
    if cid not in src.chapters:
        raise SystemExit(f"没有章节 {cid}")
    ch = src.chapters[cid]
    out = [f"# 读 {cid}《{ch['title']}》之前的上下文", ""]
    bp = src.work / "notes" / "brief.json"
    if bp.exists():
        try:
            b = json.loads(bp.read_text(encoding="utf-8"))
            out += ["## 全书假设(来自检视阅读,可能有误,读的时候留意修正)",
                    f"- 核心问题:{b.get('question', '')}", f"- 暂定论点:{b.get('thesis', '')}",
                    f"- 书的类型:{b.get('book_type', '')}"]
            for s in b.get("structure") or []:
                if isinstance(s, dict):
                    out.append(f"- 结构猜测 {s.get('chapters', '')}:{s.get('role', '')}")
            if b.get("watch"):
                out.append("- 阅读时留意:" + ";".join(map(str, b["watch"])))
            out.append("")
        except json.JSONDecodeError:
            out += ["(brief.json 语法有误,先修好)", ""]
    else:
        out += ["(还没有 notes/brief.json——先做检视阅读)", ""]
    order = [c["id"] for c in src.active()]
    prev = [c for c in order if c != cid and _load_note(src, c)]
    if prev:
        out.append("## 已读各章的主干(引用它们时用这些 id)")
        terms = []
        for c in prev:
            n = _load_note(src, c)
            out.append(f"### {c} {src.chapters[c]['title']} —— {n.get('role', '')}")
            for k in n.get("claims") or []:
                if isinstance(k, dict) and k.get("weight") == "core":
                    out.append(f"- {k.get('id')} [{KINDS.get(k.get('kind'), '?')}] {k.get('text')}")
            for cp in n.get("concepts") or []:
                if isinstance(cp, dict):
                    terms.append(f"- {cp.get('term')}({c}):{cp.get('def')}")
        if terms:
            out += ["", "## 已出现的概念(沿用同一术语;若本章改变了它的含义,在本章 concepts 里用 note 写明)"] + terms
        out.append("")
    out.append("## 本章")
    out.append(f"- 文件:source/{cid}.txt(每行一段,行首是段落编号);共 {ch['paras']} 段、约 {ch['chars']} 字。")
    if len(ch["parts"]) > 1:
        out.append(f"- 本章较长,请分 {len(ch['parts'])} 批读,每读完一批就把这一批的笔记记下来再读下一批:")
        for i, p in enumerate(ch["parts"], 1):
            out.append(f"  - 第 {i} 批:第 {p['lines'][0]}–{p['lines'][1]} 行({p['from']} … {p['to']})")
    else:
        out.append("- 一次读完即可。")
    out.append(f"- 写入:notes/{cid}.json,然后运行 check {cid}。")
    return "\n".join(out)


def digest(src: Source, level: str = "all") -> str:
    """全部章节笔记的紧凑视图,供综合阶段使用(不需要再读原文)。"""
    out = [f"# 全书笔记摘要:《{src.manifest['title']}》", ""]
    for c in src.active():
        n = _load_note(src, c["id"])
        out.append(f"## {c['id']} {c['title']}({c['chars']} 字)")
        if not n:
            out += ["(无笔记)", ""]
            continue
        out.append(f"作用:{n.get('role', '')}")
        out.append(f"概要:{n.get('summary', '')}")
        for k in n.get("claims") or []:
            if not isinstance(k, dict):
                continue
            if level == "core" and k.get("weight") == "detail":
                continue
            ev = f"/{k.get('ev')}" if k.get("ev") else ""
            out.append(f"- {k.get('id')} [{KINDS.get(k.get('kind'), '?')}{ev}·{WEIGHTS.get(k.get('weight'), '?')}] {k.get('text')}")
        ls = [l for l in (n.get("links") or []) if isinstance(l, dict)]
        if ls:
            out.append("关系:" + ";".join(f"{l.get('from')} {LINK_TYPES.get(l.get('type'), '?')} {l.get('to')}" for l in ls))
        for cp in n.get("concepts") or []:
            if isinstance(cp, dict):
                extra = f"({cp['note']})" if cp.get("note") else ""
                out.append(f"· 概念 {cp.get('term')}:{cp.get('def')}{extra}  refs={','.join(cp.get('refs') or [])}")
        out.append("")
    return "\n".join(out)


def audit_packet(src: Source, n: int = 30, seed: int = 7, renew: bool = False) -> tuple[Path, Path, int]:
    iss = Issues()
    notes = {c["id"]: _load_note(src, c["id"]) for c in src.active()}
    notes = {k: v for k, v in notes.items() if v}
    claims = all_claims(notes)
    book = load_json(src.work / "book.json", iss, "book") if (src.work / "book.json").exists() else None
    adir = src.work / "audit"
    adir.mkdir(exist_ok=True)
    vp, pp = adir / "verdicts.json", adir / "packet.md"
    old = []
    if vp.exists() and not renew:
        try:
            old = json.loads(vp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            old = []
    chosen: list[str] = []
    if renew or not old:
        pillar_claims = []
        if isinstance(book, dict):
            for p in book.get("pillars") or []:
                if isinstance(p, dict):
                    pillar_claims += [k for k in p.get("claims") or [] if k in claims]
        rnd = random.Random(seed)
        # 必查:支柱所依据的命题、所有 counter(最容易把立场搞反);其余随机
        must = list(dict.fromkeys(pillar_claims + [k for k, c in claims.items() if c.get("kind") == "counter"]))
        rest = [k for k in claims if k not in must]
        rnd.shuffle(rest)
        nums = [k for k in rest if any(ch.isdigit() for ch in claims[k].get("text", ""))]
        chosen = must + nums[: max(0, n - len(must)) // 2]
        chosen += [k for k in rest if k not in chosen][: max(0, n - len(chosen))]
    else:
        # 复核:上次未通过且已改写的条目
        cur = {k: text_hash(c.get("text", "")) for k, c in claims.items()}
        chosen = [v["id"] for v in old if isinstance(v, dict) and v.get("verdict") not in (None, "", "ok")
                  and v.get("id") in cur and cur[v["id"]] != v.get("hash")]
    lines = ["# 独立核查包", "",
             "核查方法见 references/audit.md。逐条对照下面给出的**原文段落**判断笔记是否忠实,把结论填进 verdicts.json。", ""]
    verdicts = []
    if isinstance(book, dict) and (renew or not old):
        lines += ["## A. 全书层面", "", f"### thesis", f"核心论点:{book.get('thesis', '')}", f"核心问题:{book.get('question', '')}",
                  "核对依据:请完整阅读序言/导论与结语所在的 source 文件,判断这是否是**作者自己**的中心主张。", ""]
        verdicts.append({"id": "thesis", "hash": text_hash(book.get("thesis", "")), "verdict": "", "note": ""})
        for p in book.get("pillars") or []:
            if not isinstance(p, dict):
                continue
            lines += [f"### {p.get('id')} {p.get('title', '')}", f"支柱陈述:{p.get('statement', '')}", "它声称建立在这些命题上:"]
            lines += [f"- {k}: {claims[k].get('text')}" for k in p.get("claims") or [] if k in claims]
            lines += ["核对:支柱陈述有没有超出这些命题实际说的内容(夸大、偷换、加入书里没有的东西)?", ""]
            verdicts.append({"id": p.get("id"), "hash": text_hash(p.get("statement", "")), "verdict": "", "note": ""})
    lines += ["## B. 命题层面", ""]
    for k in chosen:
        c = claims[k]
        lines += [f"### {k}", f"类型:{c.get('kind')}({KINDS.get(c.get('kind'), '?')})"
                  + (" —— 注意:这表示笔记认为这是**作者引述并反对**的观点" if c.get("kind") == "counter" else ""),
                  f"笔记:{c.get('text')}", "所引原文:"]
        for r in c.get("refs") or []:
            t = src.para(r)
            lines.append(f"> [{r}] {t if t is not None else '(段落不存在)'}")
        lines.append("")
        verdicts.append({"id": k, "hash": text_hash(c.get("text", "")), "verdict": "", "note": ""})
    pp.write_text("\n".join(lines), encoding="utf-8")
    if old and not renew:
        ids = {v["id"] for v in verdicts}
        verdicts = [v for v in old if isinstance(v, dict) and v.get("id") not in ids] + verdicts
    vp.write_text(json.dumps(verdicts, ensure_ascii=False, indent=1), encoding="utf-8")
    return pp, vp, len([v for v in verdicts if not v.get("verdict")])
