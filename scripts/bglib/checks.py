"""校验:结构 + 原文锚点 + 防抄录 + 数字 + 覆盖度 + 论证结构 + 审计结果。

错误(E)必须修;提示(W)必须逐条处理——要么改,要么确认无碍。未处理的提示数会如实写进导读页的"可靠性说明"。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .source import Source
from .textutil import longest_shared_run, ngram_set, norm, number_forms, numbers, tokens, units, est_tokens

KINDS = {"claim": "主张", "reason": "理由", "evidence": "证据", "method": "方法",
         "caveat": "限定", "counter": "对手观点"}
WEIGHTS = {"core": "主干", "support": "支撑", "detail": "细节"}
EV_TYPES = {"study": "对照研究/实验", "data": "统计数据", "case": "案例", "anecdote": "轶事/个人经历",
            "authority": "引用权威", "analogy": "类比", "reasoning": "推演/思想实验"}
LINK_TYPES = {"supports": "支持", "causes": "导致", "requires": "以…为前提", "refines": "细化/修订",
              "rebuts": "反驳", "limits": "限定", "applies": "落实"}
PRIORITIES = {"must": "精读", "skim": "略读", "skip": "可跳过"}
CRIT_TYPES = {"strength": "扎实之处", "assumption": "隐含假设", "gap": "论证缺口",
              "objection": "可能的反驳", "scope": "适用边界"}
Q_LEVELS = {"recall": "回忆", "explain": "解释", "apply": "应用", "evaluate": "评判"}
VERDICTS = {"ok", "distorted", "unsupported", "misattributed"}

COPY_N = {"zh": 13, "en": 8}     # 与原文连续相同达到这个长度(汉字数 / 英文词数)即视为抄录
QUOTE_MAX = 30                    # 定位片段上限(单位:汉字或英文词)
QUOTE_MIN = 4
QUOTE_BUDGET = 0.05               # 全部定位片段合计不超过原书的 5%


class Issues:
    def __init__(self):
        self.items: list[tuple[str, str, str]] = []

    def e(self, where: str, msg: str):
        self.items.append(("E", where, msg))

    def w(self, where: str, msg: str):
        self.items.append(("W", where, msg))

    @property
    def errors(self):
        return [i for i in self.items if i[0] == "E"]

    @property
    def warnings(self):
        return [i for i in self.items if i[0] == "W"]

    def render(self) -> str:
        lines = []
        for lv, where, msg in sorted(self.items, key=lambda x: (x[0] != "E", x[1])):
            lines.append(f"{'错误' if lv == 'E' else '提示'} [{where}] {msg}")
        return "\n".join(lines)


def text_hash(s: str) -> str:
    return hashlib.sha1(norm(s).encode("utf-8")).hexdigest()[:10]


def load_json(path: Path, iss: Issues, where: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as ex:
        iss.e(where, f"JSON 语法错误:第 {ex.lineno} 行第 {ex.colno} 列,{ex.msg}。常见原因:字符串里的英文双引号没转义(改用「」或 \\\"),或多/少了逗号。")
    except FileNotFoundError:
        iss.e(where, f"文件不存在:{path}")
    return None


def _para_num(pid: str) -> int:
    m = re.search(r"-p(\d+)$", pid)
    return int(m.group(1)) if m else -1


class ChapterCtx:
    """一章原文的检索结构(惰性构建、可复用)。"""
    _cache: dict[tuple[str, str], "ChapterCtx"] = {}

    def __init__(self, src: Source, cid: str):
        self.paras = src.paras(cid)
        self.ids = list(self.paras)
        self.lang = src.manifest.get("lang", "zh")
        self.n = COPY_N.get(self.lang, 13)
        self.grams = ngram_set(tokens(" ".join(self.paras.values())), self.n)
        self.norm = {pid: norm(t) for pid, t in self.paras.items()}

    @classmethod
    def get(cls, src: Source, cid: str) -> "ChapterCtx":
        key = (str(src.work), cid)
        if key not in cls._cache:
            cls._cache[key] = cls(src, cid)
        return cls._cache[key]


def mask_terms(text: str, terms) -> str:
    """把已登记的概念术语换成分隔符:术语本身(以及按原顺序罗列术语)不算抄录。"""
    for t in sorted((t for t in terms if t and len(t) >= 2), key=len, reverse=True):
        text = text.replace(t, " \u2016 ")
    return text


def terms_of(note: dict) -> set[str]:
    out = set()
    for cp in (note or {}).get("concepts") or []:
        if isinstance(cp, dict):
            out.add(str(cp.get("term") or ""))
            out.update(str(a) for a in cp.get("aka") or [])
    return out


def _check_copy(iss: Issues, where: str, text: str, ctx: ChapterCtx, field: str, terms=()):
    run, seg = longest_shared_run(mask_terms(text, terms), ctx.grams, ctx.n)
    if run:
        ns = norm(seg)
        at = next((pid for pid, t in ctx.norm.items() if ns in t), None)
        iss.e(where, f"{field} 与原文{f'({at})' if at else ''}连续 {run} 个字/词相同:「{seg[:40]}」。产出物必须转述,请换自己的话重写"
                     "(已登记在 concepts 里的术语不计入;其余请调整语序或换词)。")


def _check_refs(iss: Issues, where: str, refs, cid: str, ctx: ChapterCtx, max_refs: int = 6) -> list[str]:
    if not isinstance(refs, list) or not refs:
        iss.e(where, "缺少 refs(原文段落编号)。每条笔记都必须能指回原文。")
        return []
    good = []
    for r in refs:
        if r in ctx.paras:
            good.append(r)
        else:
            iss.e(where, f"refs 里的 {r!r} 不是 {cid} 的段落编号(格式如 {cid}-p012,且只能引用本章段落)。")
    if len(refs) > max_refs:
        iss.w(where, f"refs 多达 {len(refs)} 段。锚点应指向最能支撑这句话的 1–3 段,而不是一大片。")
    return good


def check_chapter(src: Source, cid: str, note: dict, iss: Issues, known_claims: set[str] | None = None) -> None:
    """known_claims: 其他章已有的命题 id(用于跨章 link 校验);None 表示只查本章。"""
    if cid not in src.chapters:
        iss.e(cid, "manifest 里没有这一章。")
        return
    ctx = ChapterCtx.get(src, cid)
    ch = src.chapters[cid]
    if not isinstance(note, dict):
        iss.e(cid, "笔记顶层必须是 JSON 对象。")
        return
    if note.get("chapter") != cid:
        iss.e(cid, f"chapter 字段应为 {cid!r},实际是 {note.get('chapter')!r}。")
    terms = terms_of(note)
    for f, lim in (("role", 80), ("summary", 260)):
        v = note.get(f)
        if not isinstance(v, str) or units(v) < 8:
            iss.e(cid, f"缺少 {f}(或过短)。")
        else:
            if units(v) > lim:
                iss.w(cid, f"{f} 有 {units(v)} 字,超过建议的 {lim}。它是给读者的浓缩,不是复述。")
            _check_copy(iss, cid, v, ctx, f, terms)

    claims = note.get("claims")
    if not isinstance(claims, list) or not claims:
        iss.e(cid, "claims 为空。")
        claims = []
    seen: dict[str, dict] = {}
    covered: set[str] = set()
    for i, c in enumerate(claims):
        if not isinstance(c, dict):
            iss.e(cid, f"claims[{i}] 不是对象。")
            continue
        k = c.get("id") or f"{cid}#claims[{i}]"
        if not re.fullmatch(re.escape(cid) + r"-k\d+", str(c.get("id", ""))):
            iss.e(k, f"id 格式应为 {cid}-k<序号>,如 {cid}-k1。")
        if k in seen:
            iss.e(k, "id 重复。")
        seen[k] = c
        if c.get("kind") not in KINDS:
            iss.e(k, f"kind 必须是 {'/'.join(KINDS)} 之一,实际是 {c.get('kind')!r}。")
        if c.get("weight") not in WEIGHTS:
            iss.e(k, f"weight 必须是 {'/'.join(WEIGHTS)} 之一,实际是 {c.get('weight')!r}。")
        if c.get("kind") == "evidence" and c.get("ev") not in EV_TYPES:
            iss.e(k, f"证据必须用 ev 标明类型:{'/'.join(EV_TYPES)}。")
        text = c.get("text")
        if not isinstance(text, str) or units(text) < 8:
            iss.e(k, "text 缺失或过短。它必须是一个能独立读懂的完整句子。")
            text = ""
        elif units(text) > 110:
            iss.w(k, f"text 有 {units(text)} 字。一条只说一件事,考虑拆成两条。")
        refs = _check_refs(iss, k, c.get("refs"), cid, ctx)
        covered.update(refs)
        if text:
            _check_copy(iss, k, text, ctx, "text", terms)
        # 定位片段:必须逐字出现在所引段落里
        q = c.get("quote")
        if isinstance(q, str) and 0 < units(q) < QUOTE_MIN:
            iss.e(k, f"quote 只有 {units(q)} 字,太短(至少 {QUOTE_MIN} 字),在书里搜不出唯一位置。")
        elif not isinstance(q, str) or not q:
            iss.e(k, f"缺少 quote:从所引段落里逐字摘一个 {QUOTE_MIN}–{QUOTE_MAX} 字的片段,供读者在自己的书里搜索定位,也供机器核对锚点。")
        else:
            if units(q) > QUOTE_MAX:
                iss.e(k, f"quote 有 {units(q)} 字,超过上限 {QUOTE_MAX}。它只是定位用的短片段,不是摘抄。")
            nq = norm(q)
            if refs and not any(nq in ctx.norm[r] for r in refs):
                joined = "".join(ctx.norm[r] for r in refs)
                if nq in joined:
                    pass   # 跨两段相邻,也算
                else:
                    elsewhere = [pid for pid, t in ctx.norm.items() if nq in t]
                    if elsewhere:
                        iss.e(k, f"quote 不在所引段落里,但出现在 {elsewhere[0]}。请把 refs 改成真正的出处。")
                    else:
                        iss.e(k, "quote 在本章原文里找不到。它必须是逐字摘录(不要凭记忆写、不要改字、不要用省略号拼接)。请回到原文重新摘。")
        # 数字核对
        if text and refs:
            src_nums = number_forms(" ".join(ctx.paras[r] for r in refs))
            missing = sorted(n for n in numbers(text) if n not in src_nums and n.rstrip("%") not in src_nums)
            if missing:
                where_else = []
                for n in missing:
                    hit = next((pid for pid, t in ctx.paras.items() if n in number_forms(t)), None)
                    where_else.append(f"{n}(本章 {hit} 出现过)" if hit else f"{n}(本章原文中未出现)")
                iss.w(k, f"数字未在所引段落中出现:{'、'.join(where_else)}。核对是否记错,或补上包含该数字的段落到 refs。")

    # 关系
    links = note.get("links") or []
    link_seen = set()
    touched: dict[str, list[tuple[str, str]]] = {k: [] for k in seen}   # id -> [(方向, 类型)]
    for i, l in enumerate(links):
        w = f"{cid}#links[{i}]"
        if not isinstance(l, dict):
            iss.e(w, "不是对象。")
            continue
        a, b, t = l.get("from"), l.get("to"), l.get("type")
        if t not in LINK_TYPES:
            iss.e(w, f"type 必须是 {'/'.join(LINK_TYPES)} 之一,实际是 {t!r}。")
        if a == b:
            iss.e(w, "from 和 to 相同。")
        if a not in seen and b not in seen:
            iss.e(w, f"{a} → {b}:至少一端必须是本章的命题。")
        for end in (a, b):
            if end not in seen:
                if known_claims is not None and end not in known_claims:
                    iss.e(w, f"端点 {end!r} 不存在。")
                elif known_claims is None and not re.fullmatch(r"c\d+-k\d+", str(end)):
                    iss.e(w, f"端点 {end!r} 不是合法的命题 id。")
        if (a, b, t) in link_seen:
            iss.w(w, f"重复的关系 {a} → {b}。")
        link_seen.add((a, b, t))
        if a in touched:
            touched[a].append(("out", t))
        if b in touched:
            touched[b].append(("in", t))

    # 论证结构
    core = [k for k, c in seen.items() if c.get("weight") == "core"]
    if claims and not core:
        iss.e(cid, "没有任何 weight=core 的命题。每章至少要有 1 条主干。")
    if len(core) > 6 or (len(seen) >= 6 and len(core) > 0.5 * len(seen)):
        iss.w(cid, f"core 有 {len(core)}/{len(seen)} 条,太多了。主干是\"删掉它本章论证就塌\"的那 1–5 条,其余降为 support/detail。")
    for k, c in seen.items():
        t = touched[k]
        kind = c.get("kind")
        if kind == "counter" and ("in", "rebuts") not in t:
            iss.w(k, "kind=counter(作者引述并反对的观点)却没有任何命题 rebuts 它。请确认:它真是作者反对的吗?如果是,补上作者的反驳并连 rebuts;如果其实是作者自己的观点,改 kind。")
        elif kind == "evidence" and not any(d == "out" for d, _ in t):
            iss.w(k, "证据没有连到它所支持的命题(supports)。")
        elif kind == "caveat" and ("out", "limits") not in t:
            iss.w(k, "限定没有连到它所限定的命题(limits)。")
        elif c.get("weight") != "core" and not t:
            iss.w(k, "这条非主干命题没有任何关系,悬空了。说明它支撑/细化/限定了谁;如果说不出,它可能不值得记。")

    # 概念
    for i, cp in enumerate(note.get("concepts") or []):
        w = f"{cid}#concepts[{i}]"
        if not isinstance(cp, dict) or not cp.get("term") or units(str(cp.get("def", ""))) < 6:
            iss.e(w, "概念需要 term 和 def(作者在本章的用法,转述)。")
            continue
        covered.update(_check_refs(iss, w, cp.get("refs"), cid, ctx))
        _check_copy(iss, w, cp["def"], ctx, "def", terms)

    # 明确跳过的范围
    for i, sk in enumerate(note.get("skipped") or []):
        w = f"{cid}#skipped[{i}]"
        a, b = (sk or {}).get("from"), (sk or {}).get("to")
        if a not in ctx.paras or b not in ctx.paras or not (sk or {}).get("why"):
            iss.e(w, "skipped 需要 from/to(本章段落编号)和 why。")
            continue
        ia, ib = ctx.ids.index(a), ctx.ids.index(b)
        covered.update(ctx.ids[min(ia, ib):max(ia, ib) + 1])

    # 覆盖度:最长的"无任何笔记锚点"的连续段落
    if claims:
        total = max(1, ch["tokens"])
        best, cur, cur_start, best_rng = 0, 0, None, None
        for pid in ctx.ids + [None]:
            if pid is not None and pid not in covered:
                if cur_start is None:
                    cur_start = pid
                cur += est_tokens(ctx.paras[pid])
                last = pid
            else:
                if cur > best:
                    best, best_rng = cur, (cur_start, last)
                cur, cur_start = 0, None
        if best > max(2200, 0.3 * total) and best_rng:
            iss.w(cid, f"{best_rng[0]} 到 {best_rng[1]}(约占本章 {best * 100 // total}%)没有任何笔记引用。"
                       "长章最常见的失误是只记了开头和结尾。请重读这一段:有论点就补笔记;确实只是铺垫/重复,就在 skipped 里写明范围和原因。")
        qsum = sum(units(c.get("quote") or "") for c in seen.values())
        csum = max(1, units(" ".join(ctx.paras.values())))
        if csum > 2000 and qsum / csum > QUOTE_BUDGET * 1.2:
            iss.w(cid, f"本章定位片段合计占原文 {qsum * 100 / csum:.1f}%(全书预算 {QUOTE_BUDGET * 100:.0f}%)。quote 通常 6–15 字就够定位,请缩短。")
        lo, hi = max(3, total // 2400), max(14, total // 200)
        if len(seen) < lo:
            iss.w(cid, f"本章约 {ch['chars']} 字,只有 {len(seen)} 条笔记,偏稀(参考下限 {lo})。检查是否漏了理由、证据或限定。")
        if len(seen) > hi:
            iss.w(cid, f"本章约 {ch['chars']} 字,却有 {len(seen)} 条笔记,偏密(参考上限 {hi})。合并重复、删掉不影响理解的细节。")


# ---------------------------------------------------------------- 全书
def load_notes(src: Source, iss: Issues) -> dict[str, dict]:
    notes = {}
    for ch in src.active():
        p = src.work / "notes" / f"{ch['id']}.json"
        if not p.exists():
            iss.e(ch["id"], f"还没有笔记({p.name})。如果这章确实不是正文,用 mark --skip 标记。")
            continue
        n = load_json(p, iss, ch["id"])
        if isinstance(n, dict):
            notes[ch["id"]] = n
    return notes


def all_claims(notes: dict[str, dict]) -> dict[str, dict]:
    out = {}
    for cid, n in notes.items():
        for c in n.get("claims") or []:
            if isinstance(c, dict) and c.get("id"):
                out[c["id"]] = {**c, "chapter": cid}
    return out


def all_links(notes: dict[str, dict], book: dict | None) -> list[dict]:
    out = []
    for n in notes.values():
        out.extend(l for l in (n.get("links") or []) if isinstance(l, dict))
    if book:
        out.extend(l for l in (book.get("links") or []) if isinstance(l, dict))
    seen, uniq = set(), []
    for l in out:
        key = (l.get("from"), l.get("to"), l.get("type"))
        if key not in seen:
            seen.add(key)
            uniq.append(l)
    return uniq


def reach_pillars(claims: dict, links: list[dict], book: dict) -> dict[str, set[str]]:
    """每条命题通过关系链能到达哪些支柱。"""
    up: dict[str, set[str]] = {}
    for l in links:
        a, b, t = l.get("from"), l.get("to"), l.get("type")
        if t in ("requires", "applies"):     # 论证之间的依赖,不算"为它提供支撑",不向上归属
            continue
        if t == "rebuts":                    # 被反驳的对手观点挂在反驳它的命题之下
            up.setdefault(b, set()).add(a)
        else:
            up.setdefault(a, set()).add(b)
    reach: dict[str, set[str]] = {k: set() for k in claims}
    for p in book.get("pillars") or []:
        if not isinstance(p, dict):
            continue
        for k in p.get("claims") or []:
            if k in reach:
                reach[k].add(p.get("id"))
    changed = True
    while changed:
        changed = False
        for k in claims:
            for parent in up.get(k, ()):
                extra = reach.get(parent, set()) - reach[k]
                if extra:
                    reach[k] |= extra
                    changed = True
    return reach


def check_book(src: Source, notes: dict[str, dict], book: dict, iss: Issues) -> None:
    W = "book"
    claims = all_claims(notes)
    lang = src.manifest.get("lang", "zh")
    for f, lo, hi in (("question", 6, 80), ("thesis", 10, 120), ("abstract", 40, 420)):
        v = book.get(f)
        if not isinstance(v, str) or units(v) < lo:
            iss.e(W, f"缺少 {f}(或过短)。")
        elif units(v) > hi:
            iss.w(W, f"{f} 有 {units(v)} 字,超过 {hi}。说不短,往往是还没想清楚。")

    pillars = book.get("pillars")
    pids: set[str] = set()
    if not isinstance(pillars, list) or not (2 <= len(pillars) <= 7):
        iss.e(W, "pillars 应有 2–7 个:它们是撑起核心论点的几根柱子,不是章节列表。")
        pillars = pillars if isinstance(pillars, list) else []
    for i, p in enumerate(pillars):
        w = (p or {}).get("id") or f"pillars[{i}]"
        if not isinstance(p, dict) or not re.fullmatch(r"P\d+", str(p.get("id", ""))):
            iss.e(w, "支柱 id 格式应为 P1、P2…")
            continue
        if p["id"] in pids:
            iss.e(w, "支柱 id 重复。")
        pids.add(p["id"])
        for f in ("title", "statement", "how"):
            if not isinstance(p.get(f), str) or not p[f].strip():
                iss.e(w, f"支柱缺少 {f}。(how = 它如何支撑核心论点)")
        pc = p.get("claims")
        if not isinstance(pc, list) or not pc:
            iss.e(w, "支柱必须列出它建立在哪些章节命题之上(claims)。")
            pc = []
        for k in pc:
            if k not in claims:
                iss.e(w, f"claims 里的 {k!r} 不存在。")
            elif claims[k].get("kind") == "counter":
                iss.e(w, f"{k} 是 counter(作者反对的观点),不能作为支柱的基础。")
            elif claims[k].get("weight") != "core":
                iss.w(w, f"{k} 不是 core。支柱应建立在各章主干之上;要么把它升为 core,要么换一条。")
        if len({claims[k]["chapter"] for k in pc if k in claims}) == 1 and len(notes) >= 6 and len(pc) >= 1:
            pass  # 单章支柱是允许的
    for p in pillars:
        if isinstance(p, dict):
            for d in p.get("depends_on") or []:
                if d not in pids or d == p.get("id"):
                    iss.e(p.get("id", "pillar"), f"depends_on 里的 {d!r} 不是另一个支柱的 id。")

    # 跨章关系
    for i, l in enumerate(book.get("links") or []):
        w = f"book#links[{i}]"
        if not isinstance(l, dict) or l.get("type") not in LINK_TYPES:
            iss.e(w, f"type 必须是 {'/'.join(LINK_TYPES)} 之一。")
            continue
        for end in (l.get("from"), l.get("to")):
            if end not in claims:
                iss.e(w, f"端点 {end!r} 不存在。")
        if not l.get("note"):
            iss.w(w, "跨章关系请写 note,说明两章之间为什么有这层关系。")
    links = all_links(notes, book)
    for cid, n in notes.items():
        for i, l in enumerate(n.get("links") or []):
            if isinstance(l, dict):
                for end in (l.get("from"), l.get("to")):
                    if end not in claims:
                        iss.e(f"{cid}#links[{i}]", f"端点 {end!r} 不存在。")

    # 主干是否都进了全书论证
    if pids:
        reach = reach_pillars(claims, links, book)
        exempt = set(book.get("thesis_claims") or [])
        for a in book.get("aside") or []:
            if isinstance(a, dict):
                exempt.update(a.get("claims") or [])
        loose = [k for k, c in claims.items() if c.get("weight") == "core" and c.get("kind") != "counter"
                 and not reach[k] and k not in exempt]
        if loose:
            iss.w(W, f"{len(loose)} 条 core 命题没有连到任何支柱:{'、'.join(loose[:12])}{'…' if len(loose) > 12 else ''}。"
                     "处理办法:①属于某根支柱的,直接列入该支柱的 claims,或用 supports/refines/causes/limits 连到支柱里的命题"
                     "(requires/applies 表示论证间的依赖,不算归属);②它本身就是全书论点的表述(常见于序言、结语),列入 thesis_claims;"
                     "③背景、题外话等不承担论证的,列入 aside 并写 why。")
        if len(notes) >= 4:
            ch_in = {claims[k]["chapter"] for k, r in reach.items() if r}
            out = [c for c in notes if c not in ch_in]
            if len(out) > len(notes) / 3:
                iss.w(W, f"有 {len(out)} 章({'、'.join(out[:8])})没有任何命题进入支柱。支柱可能只概括了书的一部分。")

    for k in book.get("thesis_claims") or []:
        if k not in claims:
            iss.e(W, f"thesis_claims 里的 {k!r} 不存在。")
    for i, a in enumerate(book.get("aside") or []):
        if not isinstance(a, dict) or not a.get("why") or not isinstance(a.get("claims"), list):
            iss.e(f"book#aside[{i}]", "aside 需要 claims(命题 id 列表)和 why。")
        else:
            for k in a["claims"]:
                if k not in claims:
                    iss.e(f"book#aside[{i}]", f"{k!r} 不存在。")

    # 阅读建议
    guide = {g.get("id"): g for g in (book.get("chapters") or []) if isinstance(g, dict)}
    for cid in notes:
        g = guide.get(cid)
        if not g or g.get("priority") not in PRIORITIES or not g.get("why"):
            iss.e(W, f"chapters 里缺少 {cid} 的阅读建议(priority: {'/'.join(PRIORITIES)} + why)。")
    if guide and len(notes) >= 5 and all(g.get("priority") == "must" for g in guide.values()):
        iss.w(W, "所有章都标成了 must。读者时间有限:哪些章是论证的承重墙,哪些可以略读?请分出层次。")

    # 概念表
    terms = set()
    for i, cp in enumerate(book.get("concepts") or []):
        w = f"book#concepts[{i}]"
        if not isinstance(cp, dict) or not cp.get("term") or units(str(cp.get("def", ""))) < 6:
            iss.e(w, "概念需要 term 和 def。")
            continue
        if cp["term"] in terms:
            iss.e(w, f"概念 {cp['term']!r} 重复;同一概念在不同章的说法请合并成一条,用 evolution 说明演变。")
        terms.add(cp["term"])
        refs = cp.get("refs")
        if not isinstance(refs, list) or not refs:
            iss.e(w, "概念缺少 refs。")
        else:
            for r in refs:
                if src.para(r) is None:
                    iss.e(w, f"refs 里的 {r!r} 不存在。")
    note_terms = {cp.get("term") for n in notes.values() for cp in (n.get("concepts") or []) if isinstance(cp, dict)}
    if note_terms and not terms:
        iss.e(W, "各章笔记里有概念,但 book.json 没有合并后的 concepts。")

    # 审视
    crit = book.get("critique")
    targets_ok = set(claims) | pids | {"thesis"}
    if not isinstance(crit, list) or len(crit) < 3:
        iss.e(W, "critique 至少 3 条(类型:" + "/".join(CRIT_TYPES) + ")。")
        crit = crit if isinstance(crit, list) else []
    for i, c in enumerate(crit):
        w = f"book#critique[{i}]"
        if not isinstance(c, dict) or c.get("type") not in CRIT_TYPES or not c.get("text"):
            iss.e(w, f"需要 type({'/'.join(CRIT_TYPES)})和 text。")
            continue
        tg = c.get("targets")
        if not isinstance(tg, list) or not tg:
            iss.e(w, "需要 targets:这条审视针对哪个支柱/命题(P1、c03-k2 或 thesis)。没有靶子的批评是空话。")
        else:
            for t in tg:
                if t not in targets_ok:
                    iss.e(w, f"targets 里的 {t!r} 不存在。")
    if crit and not any(isinstance(c, dict) and c.get("type") in ("gap", "assumption", "objection") for c in crit):
        iss.w(W, "critique 里没有 gap/assumption/objection。只有赞扬的审视对读者没用。")

    # 自测题
    qs = book.get("questions")
    if not isinstance(qs, list) or len(qs) < 8:
        iss.e(W, "questions 至少 8 道。")
        qs = qs if isinstance(qs, list) else []
    levels = set()
    for i, q in enumerate(qs):
        w = f"book#questions[{i}]"
        if not isinstance(q, dict) or q.get("level") not in Q_LEVELS or not q.get("q") or not q.get("a"):
            iss.e(w, f"需要 level({'/'.join(Q_LEVELS)})、q、a。")
            continue
        levels.add(q["level"])
        tg = q.get("claims")
        if not isinstance(tg, list) or not tg:
            iss.e(w, "需要 claims:答案依据哪些命题/支柱(读者答错时可以跳回去看)。")
        else:
            for t in tg:
                if t not in targets_ok:
                    iss.e(w, f"claims 里的 {t!r} 不存在。")
    if qs and len(levels) < 3:
        iss.w(W, "自测题层次单一。至少覆盖 recall/explain/apply/evaluate 中的三种;只考记忆的题检验不了理解。")

    if not isinstance(book.get("takeaways"), list) or not book.get("takeaways"):
        iss.w(W, "缺少 takeaways(读完之后可以带走/去做的 2–5 件事)。")

    # 全书级文字的防抄录(对所有章)
    fields = [("thesis", book.get("thesis")), ("abstract", book.get("abstract")), ("question", book.get("question"))]
    fields += [(f"{p.get('id')}.statement", p.get("statement")) for p in pillars if isinstance(p, dict)]
    fields += [(f"concepts[{i}].def", c.get("def")) for i, c in enumerate(book.get("concepts") or []) if isinstance(c, dict)]
    fields += [(f"questions[{i}].a", q.get("a")) for i, q in enumerate(qs) if isinstance(q, dict)]
    bterms = terms_of(book)
    for n in notes.values():
        bterms |= terms_of(n)
    for cid in notes:
        ctx = ChapterCtx.get(src, cid)
        for name, v in fields:
            if isinstance(v, str) and v:
                run, seg = longest_shared_run(mask_terms(v, bterms), ctx.grams, ctx.n)
                if run:
                    iss.e(W, f"{name} 与 {cid} 原文连续 {run} 个字/词相同:「{seg[:40]}」。请转述。")

    # 定位片段总量
    qtot = sum(units(c.get("quote") or "") for c in claims.values())
    btot = max(1, sum(units(" ".join(src.paras(c["id"]).values())) for c in src.active())) if claims else 1
    if btot > 20000 and qtot / btot > QUOTE_BUDGET:
        iss.w(W, f"定位片段合计占原书 {qtot * 100 / btot:.2f}%,超过 {QUOTE_BUDGET * 100:.0f}%。把 quote 缩短到刚好能搜索定位的长度。")


# ---------------------------------------------------------------- 审计
def check_audit(src: Source, notes: dict, book: dict | None, iss: Issues, final: bool) -> dict:
    """读取 audit/verdicts.json,返回统计。未通过且未修改的条目是错误。"""
    p = src.work / "audit" / "verdicts.json"
    stats = {"done": False, "total": 0, "ok": 0, "fixed": 0, "open": 0}
    if not p.exists():
        if final:
            iss.e("audit", "还没有做独立核查。运行 audit 生成核查包,按 references/audit.md 完成后再 --final。")
        return stats
    data = load_json(p, iss, "audit")
    if not isinstance(data, list):
        return stats
    claims = all_claims(notes)
    current = {k: text_hash(c.get("text", "")) for k, c in claims.items()}
    if book:
        current["thesis"] = text_hash(book.get("thesis", ""))
        for pl in book.get("pillars") or []:
            if isinstance(pl, dict):
                current[pl.get("id")] = text_hash(pl.get("statement", ""))
    pending = 0
    for v in data:
        if not isinstance(v, dict):
            continue
        vid, verdict = v.get("id"), v.get("verdict")
        if not verdict:
            pending += 1
            continue
        stats["total"] += 1
        if verdict not in VERDICTS:
            iss.e("audit", f"{vid}: verdict 必须是 {'/'.join(sorted(VERDICTS))}。")
        elif verdict == "ok":
            stats["ok"] += 1
        elif vid not in current:
            stats["fixed"] += 1                      # 已删除
        elif current[vid] != v.get("hash"):
            stats["fixed"] += 1                      # 已改写
        else:
            stats["open"] += 1
            iss.e(vid, f"独立核查判定为 {verdict}:{v.get('note', '')}。请对照原文改写或删除这条(改完无需改 verdicts.json,校验会识别文本已变)。")
    if pending:
        (iss.e if final else iss.w)("audit", f"verdicts.json 里还有 {pending} 条没填 verdict。")
    stats["done"] = stats["total"] > 0 and pending == 0
    return stats


def check_all(work: str | Path, final: bool = False) -> tuple[Issues, dict]:
    src = Source(work)
    iss = Issues()
    notes = load_notes(src, iss)
    known = set(all_claims(notes))
    for cid, n in notes.items():
        check_chapter(src, cid, n, iss, known_claims=known)
    book = None
    bp = src.work / "book.json"
    if bp.exists():
        book = load_json(bp, iss, "book")
        if isinstance(book, dict):
            check_book(src, notes, book, iss)
        else:
            book = None
    else:
        iss.e("book", "还没有 book.json(全书综合)。")
    astats = check_audit(src, notes, book, iss, final)
    return iss, {"audit": astats, "notes": notes, "book": book, "src": src}
