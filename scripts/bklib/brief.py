"""读书时的上下文管理:分块阅读、章前简报(滚动记忆)、检索、进度。"""
from __future__ import annotations

import re

from .store import Work
from .text import clip, ngrams, norm, weight, words_stems, cjk_ratio


def chunks_for(w: Work, key: str, budget: int = 7000) -> list[list[dict]]:
    """把一章按预算切块。块边界尽量落在小节标题处;绝不切开段落。"""
    ps = w.ch_paras(key)
    total = sum(weight(p["text"]) for p in ps)
    if total <= budget * 1.3:
        return [ps]
    n = max(2, round(total / budget))
    target = total / n
    out, cur, acc = [], [], 0
    for i, p in enumerate(ps):
        new_sec = bool(p["sec"]) and (i == 0 or ps[i - 1]["sec"] != p["sec"])
        if cur and len(out) < n - 1 and (acc >= target * 1.15 or (acc >= target * 0.8 and new_sec)):
            out.append(cur)
            cur, acc = [], 0
        cur.append(p)
        acc += weight(p["text"])
    if cur:
        out.append(cur)
    return out


def render_chunk(w: Work, key: str, idx: int, budget: int = 7000) -> str:
    ch = w.chapter(key)
    cs = chunks_for(w, key, budget)
    if idx < 1 or idx > len(cs):
        raise SystemExit(f"{key} 只有 {len(cs)} 块")
    ps = cs[idx - 1]
    lines = [f"=== {key}《{ch['title']}》 第 {idx}/{len(cs)} 块 · 段 {ps[0]['id']} … {ps[-1]['id']} · 约 {sum(weight(p['text']) for p in ps)} tokens ==="]
    sec = None
    for p in ps:
        if p["sec"] != sec:
            sec = p["sec"]
            if sec:
                lines.append(f"\n## {sec}")
        lines.append(f"[{p['id']}] {p['text']}")
    if idx < len(cs):
        lines.append(f"\n(本章还有第 {idx + 1}/{len(cs)} 块:bk read {key} {idx + 1};笔记请继续用下一个 id)")
    else:
        lines.append(f"\n(本章读完。下一个可用卡片 id: {w.next_card_id(key)})")
    return "\n".join(lines)


def n_chunks(w: Work, key: str, budget: int = 7000) -> int:
    return len(chunks_for(w, key, budget))


def skeleton(w: Work, per: int = 260) -> str:
    """第 0 步用:全书骨架——每章标题、规模、小节标题、开头与结尾各一段的摘录。"""
    m = w.meta
    out = [f"《{m['title'] or '(无书名)'}》 {m['author']} · 语种 {m['lang']} · 共 {len(m['chapters'])} 个单元 · 约 {m['total_weight']} tokens", ""]
    part = None
    for c in m["chapters"]:
        if c["part"] != part:
            part = c["part"]
            if part:
                out.append(f"\n##### {part}")
        flag = " [跳过]" if c.get("skip") else ""
        out.append(f"\n--- {c['key']}《{c['title']}》{flag} [{c['kind']}] {c['n_paras']} 段 / {c['weight']} tokens")
        if c.get("sections"):
            out.append("  小节: " + " | ".join(s["title"] for s in c["sections"][:12]))
        if c.get("skip"):
            continue
        ps = w.ch_paras(c["key"])
        if ps:
            out.append(f"  开头 [{ps[0]['id']}] {clip(ps[0]['text'], per)}")
            if len(ps) > 2:
                out.append(f"  结尾 [{ps[-1]['id']}] {clip(ps[-1]['text'], per)}")
    return "\n".join(out)


def brief(w: Work, key: str, cap: int = 3000) -> str:
    """章前简报:全书定向 + 前面各章摘要 + 已定义术语 + 本章位置 + 下一个可用 id。"""
    ch = w.chapter(key)
    chs = w.chapters()
    keys = [c["key"] for c in chs]
    i = keys.index(key) if key in keys else 0
    orient = w.read_json("orient.json") or {}
    notes = w.load_notes()
    L = [f"# 章前简报:{key}《{ch['title']}》", ""]
    if orient:
        L += ["## 全书定向(假设,读到与之不符的地方要写进 caveat/修正,不要硬凑)",
              f"- 要回答的问题: {orient.get('question', '?')}",
              f"- 论点假设: {orient.get('thesis_guess', '?')}",
              f"- 体裁: {orient.get('genre', '?')}  读者: {orient.get('audience', '?')}"]
        for r in orient.get("risks", [])[:4]:
            L.append(f"- 易误读: {r}")
        L.append("")
    L.append(f"## 本章位置: 第 {i + 1}/{len(chs)} 个单元" + (f" · {ch['part']}" if ch["part"] else ""))
    if i > 0:
        L.append(f"- 上一章: {chs[i - 1]['key']}《{chs[i - 1]['title']}》")
    if i + 1 < len(chs):
        L.append(f"- 下一章: {chs[i + 1]['key']}《{chs[i + 1]['title']}》")
    L.append("")
    # 前面各章摘要:越近越详细
    done = [(c["key"], notes[c["key"]]) for c in chs[:i] if c["key"] in notes]
    if done:
        L.append("## 前面各章(只列要点;需要细节时 bk find / 直接看 notes/)")
        budget = cap
        for dk, n in reversed(done):
            meta = n.get("meta") or {}
            t1 = [c for c in n["cards"] if c.get("tier") == 1][:4]
            line = f"- {dk}《{w.chapter(dk)['title']}》: {meta.get('takeaway', '')}"
            if budget > 900 and t1:
                line += "  ‖ 关键卡: " + ";".join(f"{c['id']} {c.get('label', '')}" for c in t1)
            budget -= weight(line)
            L.append(line)
            if budget <= 0:
                L.append("- (更早的章略)")
                break
        L.append("")
    terms = []
    for dk, n in done:
        for c in n["concepts"]:
            terms.append(f"- {c['term']}({dk}): {clip(c.get('def', ''), 50)}")
    if terms:
        L += ["## 已出现的术语(沿用同一写法;意思变了就新开一条并写 not)"] + terms[:40] + [""]
    L.append(f"## 记账\n- 下一个可用卡片 id: {w.next_card_id(key)}")
    L.append(f"- 本章分块: {n_chunks(w, key)} 块(bk read {key} 1 …)")
    return "\n".join(L)


def find(w: Work, query: str, top: int = 8, ch: str | None = None) -> str:
    """在原文段落里检索(汉字 2-gram / 拉丁词干)。用于核对、回答追问。"""
    zh = cjk_ratio(query) > 0.3
    q = ngrams(query, 2) if zh else words_stems(query)
    qn = norm(query)
    scored = []
    for p in w.paras.values():
        if ch and p["ch"] != ch:
            continue
        s = ngrams(p["text"], 2) if zh else words_stems(p["text"])
        if not s or not q:
            continue
        sc = len(q & s) / len(q)
        if qn and qn in norm(p["text"]):
            sc += 1
        scored.append((sc, p))
    scored.sort(key=lambda x: -x[0])
    out = []
    for sc, p in scored[:top]:
        if sc <= 0.05:
            break
        out.append(f"[{p['id']}] ({sc:.2f}) {('§' + p['sec'] + ' ') if p['sec'] else ''}{clip(p['text'], 220)}")
    return "\n".join(out) if out else "(没有命中)"


def status(w: Work) -> tuple[str, str]:
    """返回 (报告文本, 下一步建议)。"""
    from .check import Checker
    m = w.meta
    chs = w.chapters()
    L = [f"《{m['title']}》 · {len(chs)} 个待读单元(另有 {len(m['chapters']) - len(chs)} 个已跳过) · 约 {m['total_weight']} tokens"]
    nxt = ""
    for wr in m.get("warnings", []):
        L.append(f"  ⚠ 摄入: {wr}")
    has_orient = (w.root / "orient.json").exists()
    L.append(f"[{'x' if has_orient else ' '}] 0 定向 orient.json")
    if not has_orient:
        nxt = "bk skeleton → 读骨架,写 orient.json(见 references/prompts/00_orient.md)"
    notes = w.load_notes()
    todo = [c["key"] for c in chs if c["key"] not in notes]
    L.append(f"[{'x' if not todo else ' '}] 1 章笔记 {len(chs) - len(todo)}/{len(chs)}" + (f"  待做: {' '.join(todo)}" if todo else ""))
    if has_orient and todo and not nxt:
        nxt = f"bk brief {todo[0]} && bk read {todo[0]} 1 → 写 notes/{todo[0]}.json → bk check {todo[0]}"
    for name, rel, step in (("综合", "synthesis.json", "2"), ("审读", "critique.json", "3"), ("自测题", "questions.json", "4")):
        ok = (w.root / rel).exists()
        L.append(f"[{'x' if ok else ' '}] {step} {name} {rel}")
        if not ok and not todo and has_orient and not nxt:
            nxt = f"按 references/prompts/0{step}_*.md 写 {rel}"
    log = w.read_json("audit/log.json") or {}
    L.append(f"[{'x' if log else ' '}] 5 独立核对 audit/log.json({len(log)} 条已审)")
    if not todo and not nxt and not log:
        nxt = "bk audit-plan → 让独立的读者按 05_audit.md 核对 → bk audit-apply"
    ck = Checker(w)
    ck.run(full=True)
    e = [i for i in ck.issues if i.level == "E"]
    wn = [i for i in ck.issues if i.level == "W"]
    L.append(f"校验: {len(e)} 个错误, {len(wn)} 个警告")
    if not nxt:
        nxt = "bk fix-list 看要修的问题" if (e or wn) else "bk build → 交付"
    return "\n".join(L), nxt


def digest(w: Work, max_tier: int = 3, ch: str | None = None) -> str:
    """把所有章笔记压成一份紧凑清单,供第 2~4 步(综合/审读/自测)使用。"""
    notes = w.load_notes()
    L = []
    for c in w.chapters():
        n = notes.get(c["key"])
        if not n or (ch and c["key"] != ch):
            continue
        meta = n.get("meta") or {}
        L.append(f"\n### {c['key']}《{c['title']}》{(' · ' + c['part']) if c['part'] else ''}  〔{meta.get('priority', '')}〕")
        L.append(f"作用: {meta.get('role', '')}")
        L.append(f"一句话: {meta.get('takeaway', '')}")
        for x in n["cards"]:
            if x.get("tier", 3) > max_tier:
                continue
            par = f" ←{x['rel']}:{x['parent']}" if x.get("parent") else ""
            v = "" if x.get("voice") == "author" else f"〔{x.get('voice')}〕"
            ev = f" {{证据:{x['ev']['type']}/{x['ev']['strength']};局限:{x['ev']['limit']}}}" if isinstance(x.get("ev"), dict) else ""
            L.append(f"- {x['id']} T{x.get('tier')} {x.get('kind')}{v}{par} 「{x.get('label')}」{x.get('text')}{ev}")
        for k in n["concepts"]:
            L.append(f"  · 概念 {k.get('term')}({k.get('origin')}): {k.get('def')}")
        for lk in n["links"]:
            L.append(f"  ~ {lk.get('from')} --{lk.get('type')}--> {lk.get('to')}: {lk.get('note')}")
    return "\n".join(L)
