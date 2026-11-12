"""独立核对:抽样 → 打包「待核对条目 + 只给原文段落」→ 另一位读者给出裁决 → 汇总。

要点:
- 核对者只看到“条目文本 + 原文段落”,看不到别的笔记,避免被作者的思路带偏。
- 混入若干“故意写坏”的种子条目(改数字/张冠李戴/说过头/引错段),用来衡量这次核对到底靠不靠谱。
"""
from __future__ import annotations

import hashlib
import json
import random
import re

from . import schema as S
from .store import Work
from .text import detect_lang, weight

FAULTS = ("number", "voice", "overstate", "wrongref")


def h(s: str) -> str:
    return hashlib.sha1(s.encode("utf8")).hexdigest()[:10]


def items(w: Work) -> dict[str, dict]:
    """当前所有可核对的条目 {id: {kind, text, refs, voice, extra}}。"""
    out: dict[str, dict] = {}
    for key, n in w.load_notes().items():
        for c in n["cards"]:
            out[c["id"]] = {"kind": "card", "ckind": c.get("kind"), "text": c.get("text", ""), "refs": c.get("refs", []),
                            "voice": c.get("voice"), "tier": c.get("tier"), "waive": c.get("waive") or [], "ev": c.get("ev")}
    sy = w.read_json("synthesis.json") or {}
    for con in sy.get("concepts", []) or []:
        out[f"concept:{con.get('term')}"] = {"kind": "concept", "text": f"{con.get('term')}:{con.get('def')}", "refs": con.get("refs", []), "voice": "author"}
    for m in sy.get("misreadings", []) or []:
        out[f"mis:{h(m.get('wrong', ''))}"] = {"kind": "misreading", "text": f"常见误读:{m.get('wrong')}  正解:{m.get('right')}", "refs": m.get("refs", []), "voice": "author"}
    cr = w.read_json("critique.json") or {}
    for it in cr.get("items", []) or []:
        if it.get("source") == "book":
            out[it["id"]] = {"kind": "critique", "text": it.get("text", ""), "refs": it.get("refs", []), "voice": "author"}
    for q in w.read_json("questions.json") or []:
        if isinstance(q, dict) and q.get("id"):
            out[q["id"]] = {"kind": "question", "text": f"问:{q.get('q')}\n答:{q.get('a')}", "refs": q.get("refs", []), "voice": "author"}
    return out


def _context(w: Work, refs: list[str], pad: int = 1) -> list[tuple[str, str, bool]]:
    seen, out = set(), []
    for r in refs:
        p = w.paras.get(r)
        if not p:
            continue
        for n in range(p["n"] - pad, p["n"] + pad + 1):
            pid = f"{p['ch']}:{n}"
            if pid in w.paras and pid not in seen:
                seen.add(pid)
                out.append((pid, w.paras[pid]["text"], pid in refs))
    out.sort(key=lambda x: (x[0].split(":")[0], int(x[0].split(":")[1])))
    return out


def _fault(it: dict, kind: str, w: Work, rng: random.Random):
    """返回 (new_item, note) 或 None。"""
    t = it["text"]
    zh = detect_lang(t) == "zh"
    if kind == "number":
        nums = re.findall(r"\d+", t)
        nums = [x for x in nums if len(x) >= 2]
        if not nums:
            return None
        x = rng.choice(nums)
        y = str(int(x) + rng.choice([7, 13, 21])) if int(x) < 1000 else str(int(x) + 111)
        return dict(it, text=t.replace(x, y, 1)), f"数字 {x}→{y}"
    if kind == "voice":
        if it.get("voice") == "other":
            return dict(it, voice="author"), "他人观点被标成作者主张"
        return None
    if kind == "overstate":
        tail = "而且作者强调这一点适用于所有组织,没有任何例外。" if zh else " The author stresses that this holds for every organization without exception."
        return dict(it, text=t.rstrip("。.") + ("," if zh else ",") + tail), "加了“没有例外”"
    if kind == "wrongref":
        ch = it["refs"][0].split(":")[0]
        ps = w.ch_paras(ch)
        cur = {int(r.split(":")[1]) for r in it["refs"]}
        far = [p for p in ps if all(abs(p["n"] - c) >= 3 for c in cur)]
        if not far:
            return None
        return dict(it, refs=[rng.choice(far)["id"]]), "refs 指向无关段落"
    return None


def plan(w: Work, issues, rate: float = 0.25, seed: int = 7, seeds: int = 6, retry: bool = False,
         batch_budget: int = 9000, cap: int = 150) -> dict:
    rng = random.Random(seed)
    cur = items(w)
    log = w.read_json("audit/log.json") or {}
    flagged = {i.where for i in issues if i.level in ("W", "E") and i.code in ("numbers", "overlap", "copy", "anchor_short", "term_not_in_refs", "term_not_in_book")}
    picked: list[str] = []
    musts: set[str] = set()
    for iid, it in cur.items():
        prev = log.get(iid)
        must = (it["kind"] == "card" and (it.get("tier") == 1 or it.get("waive") or it.get("voice") in ("other", "hedged")
                                           or (it.get("ckind") == "evidence")))
        must = must or it["kind"] in ("concept", "misreading", "critique") or iid in flagged
        if retry:
            if prev and (prev["verdict"] != "ok" or prev.get("hash") != h(it["text"])):
                picked.append(iid)
                if must:
                    musts.add(iid)
            elif not prev and must:  # 新增/改写后换了 id 的必审项
                picked.append(iid)
                musts.add(iid)
            continue
        if prev and prev.get("hash") == h(it["text"]) and prev["verdict"] == "ok":
            continue
        if must:
            musts.add(iid)
        if must or rng.random() < rate:
            picked.append(iid)
    if len(picked) > cap:  # 超出预算:必审项优先,其余随机
        rest = [i for i in picked if i not in musts]
        rng.shuffle(rest)
        picked = [i for i in picked if i in musts][:cap] + rest[:max(0, cap - len(musts))]
    # 种子:按故障类型轮流挑“适合这类故障”的条目,保证类型均衡
    seeded = {}
    pool = [i for i in picked if cur[i]["kind"] in ("card", "question") and cur[i]["refs"]]
    rng.shuffle(pool)
    used = set()
    order = list(FAULTS)
    guard = 0
    while len(seeded) < seeds and guard < seeds * 4:
        kind = order[guard % len(order)]
        guard += 1
        for iid in pool:
            if iid in used:
                continue
            r = _fault(cur[iid], kind, w, rng)
            if r:
                sid = f"s{len(seeded) + 1:02d}"
                seeded[sid] = {"of": iid, "fault": kind, "note": r[1], "item": r[0]}
                used.add(iid)
                break
    entries = [(iid, cur[iid]) for iid in picked] + [(sid, s["item"]) for sid, s in seeded.items()]
    rng.shuffle(entries)
    # 打包
    w.audit_dir.mkdir(parents=True, exist_ok=True)
    for f in w.audit_dir.glob("batch_*.md"):
        f.unlink()
    batches, buf, acc = [], [], 0
    for iid, it in entries:
        block = _render_entry(w, iid, it)
        wt = weight(block)
        if buf and acc + wt > batch_budget:
            batches.append(buf)
            buf, acc = [], 0
        buf.append(block)
        acc += wt
    if buf:
        batches.append(buf)
    for i, b in enumerate(batches, 1):
        head = (f"# 核对批次 {i}/{len(batches)}\n\n你是独立核对者。对每个条目,只依据其下给出的原文段落判断,"
                "把结果写进 audit/verdicts_%02d.json(格式见 references/prompts/05_audit.md)。\n\n" % i)
        (w.audit_dir / f"batch_{i:02d}.md").write_text(head + "\n\n".join(b), encoding="utf8")
    w.write_json("audit/_seeds.json", seeded)
    return {"items": len(picked), "seeds": len(seeded), "batches": len(batches)}


def _render_entry(w: Work, iid: str, it: dict) -> str:
    voice = S.VOICES.get(it.get("voice") or "author", "")
    stance = f"  标注立场: {voice}" if it["kind"] == "card" else "  (非卡片条目:只核对内容是否忠实于原文;若条目把他人观点说成作者主张,算 misattributed)"
    lines = [f"## 条目 {iid}  〔{it['kind']}" + (f"/{it.get('ckind')}" if it.get("ckind") else "") + f"〕{stance}",
             f"待核对文本: {it['text']}", "原文段落(★ 为被引用的段落,其余为上下文):"]
    for pid, text, hit in _context(w, it["refs"]):
        title = w.chapter(pid.split(":")[0])["title"]
        lines.append(f"{'★' if hit else ' '} [{pid}·{title[:30]}] {text}")
    return "\n".join(lines)


def apply(w: Work) -> dict:
    cur = items(w)
    log = w.read_json("audit/log.json") or {}
    seeds = w.read_json("audit/_seeds.json") or {}
    files = sorted(w.audit_dir.glob("verdicts*.json"))
    got = {}
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf8"))
        except json.JSONDecodeError as e:
            raise SystemExit(f"{f.name} 不是合法 JSON: {e}")
        for v in d:
            if v.get("verdict") not in S.AUDIT_VERDICTS:
                raise SystemExit(f"{f.name}: {v.get('id')} 的 verdict 必须是 {sorted(S.AUDIT_VERDICTS)}")
            got[v["id"]] = v
    seed_res = {"caught": 0, "total": 0, "missed": []}
    for sid, s in seeds.items():
        if sid in got:
            seed_res["total"] += 1
            if got[sid]["verdict"] != "ok":
                seed_res["caught"] += 1
            else:
                seed_res["missed"].append(f"{sid}({s['fault']}: {s['note']})")
    n_ok = n_bad = 0
    for iid, v in got.items():
        if iid.startswith("s") and iid in seeds:
            continue
        if iid not in cur:
            continue
        log[iid] = {"verdict": v["verdict"], "note": v.get("note", ""), "fix": v.get("fix", ""), "hash": h(cur[iid]["text"])}
        if v["verdict"] == "ok":
            n_ok += 1
        else:
            n_bad += 1
    w.write_json("audit/log.json", log)
    # 种子识别率按“轮”累计(轮 = 种子文件内容的哈希),重复 apply 同一轮不会重复计数
    prev = w.read_json("audit/seed_result.json") or {}
    rounds = prev.get("rounds", {})
    if not rounds and prev.get("total"):  # 兼容旧格式
        rounds = {"legacy": {k: prev[k] for k in ("caught", "total", "missed")}}
    if seed_res["total"]:
        rounds[h(json.dumps(seeds, sort_keys=True))] = seed_res
    tot = {"caught": sum(r["caught"] for r in rounds.values()), "total": sum(r["total"] for r in rounds.values()),
           "missed": [m for r in rounds.values() for m in r["missed"]], "rounds": rounds}
    w.write_json("audit/seed_result.json", tot)
    seed_res = tot
    missing = [i for i in seeds if i not in got]
    return {"ok": n_ok, "flagged": n_bad, "seed": seed_res, "unanswered_seeds": missing, "total_logged": len(log)}
