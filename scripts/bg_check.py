"""校验:结构、出处锚点、照抄检测、出处贴合度、覆盖度、事实核查闭环。只依赖标准库。

错误(error)必须修;提示(warn)要逐条看过,判断后可以保留。
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path

from bg_text import load_source

CLAIM_KINDS = {"claim", "mechanism", "method", "evidence", "definition", "concession", "objection"}
VOICES = {"author", "reported"}
RELS = {"supports", "explains", "causes", "rebuts", "qualifies", "applies", "answers", "requires"}
ROLES = {"opening", "problem", "concept", "mechanism", "evidence", "objection", "solution",
         "application", "synthesis", "limits", "background"}
QUIZ_TYPES = {"recall", "concept", "why", "connect", "apply", "misread"}
ANCHOR_RE = re.compile(r"^(c\d+)\.p(\d+)(?:-p?(\d+))?$")
CLAIM_ID_RE = re.compile(r"^(c\d+)\.(\d+)$")


# ---------- 工具 ----------

def load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, f"缺少文件 {p}"
    except json.JSONDecodeError as e:
        return None, f"{p.name} 不是合法 JSON:第 {e.lineno} 行 {e.msg}"


def expand_anchor(a: str, source: dict) -> list[str] | None:
    m = ANCHOR_RE.match(a or "")
    if not m:
        return None
    cid, s = m.group(1), int(m.group(2))
    e = int(m.group(3) or s)
    if e < s or e - s > 12:
        return None
    keys = [f"{cid}.p{i}" for i in range(s, e + 1)]
    paras = source.get(cid, {})
    return keys if all(k in paras for k in keys) else None


def anchor_text(anchors: list[str], source: dict) -> str:
    out = []
    for a in anchors or []:
        for k in expand_anchor(a, source) or []:
            out.append(source[k.split(".")[0]][k])
    return "\n".join(out)


_PUNCT = re.compile(r"[\s\W_]+", re.U)


def _units(text: str, lang: str) -> list[str]:
    """照抄检测与贴合度的基本单位:中文按字,英文按词。"""
    if lang == "zh":
        return [ch for ch in _PUNCT.sub("", text)]
    return re.findall(r"[a-z0-9']+", text.lower())


def build_shingles(source: dict, n: int, lang: str) -> set:
    sh = set()
    for paras in source.values():
        u = _units("".join(paras.values()) if lang == "zh" else " ".join(paras.values()), lang)
        for i in range(len(u) - n + 1):
            sh.add(hash(tuple(u[i:i + n])))
    return sh


def longest_copied(text: str, shingles: set, n: int, lang: str) -> str:
    """返回与原文重合、长度 ≥ n 的最长片段(没有则空串)。"""
    u = _units(text, lang)
    best: list[str] = []
    run_start = None
    for i in range(len(u) - n + 2):
        hit = i <= len(u) - n and hash(tuple(u[i:i + n])) in shingles
        if hit and run_start is None:
            run_start = i
        elif not hit and run_start is not None:
            seg = u[run_start:i - 1 + n]
            if len(seg) > len(best):
                best = seg
            run_start = None
    return ("" if lang == "zh" else " ").join(best)


def overlap(claim: str, ref: str, lang: str) -> float:
    """命题与其出处的词面贴合度(中文用字二元组,英文用词),0~1。转述正常在 0.2 以上。"""
    a, b = _units(claim, lang), _units(ref, lang)
    if lang == "zh":
        A = {x + y for x, y in zip(a, a[1:])}
        B = {x + y for x, y in zip(b, b[1:])}
    else:
        stop = {"the", "a", "an", "of", "to", "and", "in", "is", "that", "it", "for", "on", "as", "be", "by", "this", "are", "with"}
        A, B = set(a) - stop, set(b) - stop
    return len(A & B) / len(A) if A else 0.0


_IDLIKE = re.compile(r"^(c\d+(\.\d+|\.p\d+(-p?\d+)?)?|K\d+)$")


def text_fields(obj, path=""):
    """遍历所有要显示给读者的文字字段(跳过 id、锚点、枚举值、术语名)。"""
    skip = {"kind", "voice", "rel", "role", "type", "lang", "hash", "term", "aliases", "weight", "verdict"}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k not in skip:
                yield from text_fields(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from text_fields(v, f"{path}[{i}]")
    elif isinstance(obj, str) and obj.strip() and not _IDLIKE.match(obj.strip()):
        yield path, obj


# ---------- 主校验 ----------

class Report:
    def __init__(self):
        self.errors, self.warns, self.info = [], [], []

    def e(self, m):
        self.errors.append(m)

    def w(self, m):
        self.warns.append(m)

    def i(self, m):
        self.info.append(m)


def load_work(work: str):
    W = Path(work)
    man, err = load_json(W / "manifest.json")
    if err:
        raise SystemExit(err + "(先运行 prepare)")
    source = load_source(work)
    notes = {}
    for ch in man["chapters"]:
        p = W / "notes" / f"{ch['id']}.json"
        if p.exists():
            notes[ch["id"]] = load_json(p)
    syn = load_json(W / "synthesis.json") if (W / "synthesis.json").exists() else (None, None)
    return W, man, source, notes, syn


def all_claims(notes: dict) -> dict:
    out = {}
    for cid, (n, err) in notes.items():
        if n:
            for c in n.get("claims", []):
                if isinstance(c, dict) and c.get("id"):
                    out[c["id"]] = c
    return out


def check_chapter(cid: str, n: dict, man_ch: dict, source: dict, R: Report, lang: str):
    tag = f"[{cid}]"
    if n.get("chapter") != cid:
        R.e(f"{tag} chapter 字段应为 {cid!r}")
    for f in ("question", "answer", "role", "claims"):
        if not n.get(f):
            R.e(f"{tag} 缺少 {f}")
    if n.get("role") and n["role"] not in ROLES:
        R.e(f"{tag} role {n['role']!r} 不在 {sorted(ROLES)}")
    ids = set()
    for c in n.get("claims", []):
        cl = c.get("id", "?")
        m = CLAIM_ID_RE.match(cl)
        if not m or m.group(1) != cid:
            R.e(f"{tag} 命题 id {cl!r} 应形如 {cid}.1")
        if cl in ids:
            R.e(f"{tag} 命题 id 重复 {cl}")
        ids.add(cl)
        if c.get("kind") not in CLAIM_KINDS:
            R.e(f"{tag} {cl} kind {c.get('kind')!r} 不在 {sorted(CLAIM_KINDS)}")
        if c.get("voice", "author") not in VOICES:
            R.e(f"{tag} {cl} voice 只能是 author/reported")
        if c.get("weight") not in (1, 2, 3):
            R.e(f"{tag} {cl} weight 必须是 1/2/3")
        t = c.get("text", "")
        if len(t) < (12 if lang == "zh" else 30):
            R.w(f"{tag} {cl} 句子太短,可能只是个短语:{t!r}")
        if not c.get("anchors"):
            R.e(f"{tag} {cl} 没有出处锚点")
        for a in c.get("anchors", []):
            if expand_anchor(a, source) is None:
                R.e(f"{tag} {cl} 锚点 {a!r} 不存在或格式错误(形如 {cid}.p12 或 {cid}.p12-p14,跨度≤12)")
    if ids and not any(c.get("weight") == 3 for c in n.get("claims", [])):
        R.w(f"{tag} 没有任何 weight=3 的命题:这一章的核心是什么?")
    for x in n.get("concepts", []):
        if not x.get("term") or not x.get("definition"):
            R.e(f"{tag} 概念缺 term 或 definition: {x}")
        for a in x.get("anchors", []):
            if expand_anchor(a, source) is None:
                R.e(f"{tag} 概念 {x.get('term')} 锚点 {a!r} 不存在")
    # 覆盖度:每个阅读分块至少被引用一次,防止只读了开头
    cited = set()
    for c in n.get("claims", []):
        for a in c.get("anchors", []):
            for k in expand_anchor(a, source) or []:
                cited.add(int(k.split(".p")[1]))
    for ch in man_ch.get("chunks", []):
        a, b = (int(x) for x in ch.replace("p", "").split("-"))
        if not any(a <= p <= b for p in cited):
            R.w(f"{tag} 分块 {ch} 没有任何命题引用——这一段读了吗?")


def check_links(links, claims, where, R: Report, cross=False):
    for i, l in enumerate(links or []):
        s, t = l.get("from"), l.get("to")
        tag = f"{where} link#{i} {s}->{t}"
        if s not in claims or t not in claims:
            R.e(f"{tag}: 端点不存在")
            continue
        if s == t:
            R.e(f"{tag}: 自环")
        if l.get("rel") not in RELS:
            R.e(f"{tag}: rel {l.get('rel')!r} 不在 {sorted(RELS)}")
        if cross and not l.get("note"):
            R.e(f"{tag}: 跨章关系必须写 note 说明理由")


def check_synthesis(S: dict, claims: dict, notes: dict, man: dict, source: dict, R: Report):
    chap_ids = {c["id"] for c in man["chapters"]}
    for f in ("one_liner", "question", "answer", "key_ideas", "storyline", "glossary", "quiz", "limits"):
        if not S.get(f):
            R.e(f"[synthesis] 缺少 {f}")

    def refs(ids, where):
        for x in ids or []:
            if x not in claims:
                R.e(f"[synthesis] {where} 引用了不存在的命题 {x}")

    kis = S.get("key_ideas", [])
    if kis and not 3 <= len(kis) <= 7:
        R.w(f"[synthesis] key_ideas 有 {len(kis)} 条,建议 3–7 条(太多就不是'关键'了)")
    for k in kis:
        refs(k.get("because"), f"key_idea {k.get('id')}.because")
        refs(k.get("evidence"), f"key_idea {k.get('id')}.evidence")
        if not k.get("because") and not k.get("evidence"):
            R.e(f"[synthesis] key_idea {k.get('id')} 没有挂任何命题")
        for x in k.get("evidence") or []:
            if x in claims and claims[x].get("kind") not in ("evidence", "method"):
                R.w(f"[synthesis] {k.get('id')}.evidence 里的 {x} 类型是 {claims[x].get('kind')},不是证据")
    st = S.get("storyline", [])
    if st and not 3 <= len(st) <= 12:
        R.w(f"[synthesis] storyline 有 {len(st)} 步,建议 4–12 步")
    for i, s in enumerate(st):
        refs(s.get("claims"), f"storyline[{i}]")
        if not s.get("claims"):
            R.e(f"[synthesis] storyline[{i}] 没有挂命题")
    check_links(S.get("cross_links"), claims, "[synthesis]", R, cross=True)
    # 概念一致性:章节里出现的每个术语都要进入总词表(作为 term 或 aliases)
    gl_terms = set()
    for g in S.get("glossary", []):
        gl_terms.add(g.get("term", ""))
        gl_terms.update(g.get("aliases", []))
        if not g.get("definition"):
            R.e(f"[synthesis] 词条 {g.get('term')} 缺 definition")
        for c in g.get("chapters", []):
            if c not in chap_ids:
                R.e(f"[synthesis] 词条 {g.get('term')} 的章节 {c} 不存在")
    for cid, (n, _) in notes.items():
        for x in (n or {}).get("concepts", []):
            if x.get("term") and x["term"] not in gl_terms:
                R.w(f"[synthesis] 概念 {x['term']}({cid})没有进入 glossary,也不是任何词条的别名")
    for m in S.get("misreadings", []):
        if not (m.get("wrong") and m.get("right")):
            R.e("[synthesis] misreadings 每条需要 wrong 和 right")
        for a in m.get("anchors", []):
            if expand_anchor(a, source) is None:
                R.e(f"[synthesis] misreading 锚点 {a!r} 不存在")
    if not S.get("misreadings"):
        R.w("[synthesis] 没有 misreadings:这本书真的没有容易读错的地方吗?")
    lim = S.get("limits", {})
    for x in lim.get("author_admits", []) + lim.get("critique", []):
        for a in x.get("anchors", []):
            if expand_anchor(a, source) is None:
                R.e(f"[synthesis] limits 锚点 {a!r} 不存在")
    if not lim.get("critique"):
        R.w("[synthesis] limits.critique 为空:没有任何独立评估")
    qz = S.get("quiz", [])
    if qz and len(qz) < 8:
        R.w(f"[synthesis] quiz 只有 {len(qz)} 题,建议 8–15 题")
    types = set()
    for i, q in enumerate(qz):
        types.add(q.get("type"))
        if q.get("type") not in QUIZ_TYPES:
            R.e(f"[synthesis] quiz[{i}] type {q.get('type')!r} 不在 {sorted(QUIZ_TYPES)}")
        if not q.get("q") or not q.get("answer"):
            R.e(f"[synthesis] quiz[{i}] 需要 q 和 answer")
        if not q.get("anchors"):
            R.e(f"[synthesis] quiz[{i}] 答案没有出处锚点")
        for a in q.get("anchors", []):
            if expand_anchor(a, source) is None:
                R.e(f"[synthesis] quiz[{i}] 锚点 {a!r} 不存在")
    if qz and len(types & {"why", "connect", "apply", "misread"}) < 2:
        R.w("[synthesis] 自测题几乎都是记忆题;至少要有 why/connect/apply/misread 中的两类")
    for p in S.get("reading_paths", []):
        for c in p.get("chapters", []):
            if c not in chap_ids:
                R.e(f"[synthesis] reading_paths 章节 {c} 不存在")
    # 主线覆盖:每个非附属章节至少有一条命题进入 key_ideas / storyline
    used = {x for k in kis for x in (k.get("because") or []) + (k.get("evidence") or [])}
    used |= {x for s in st for x in s.get("claims", [])}
    used_ch = {x.split(".")[0] for x in used}
    for ch in man["chapters"]:
        if ch["id"] in notes and not ch.get("skip_hint") and ch["id"] not in used_ch:
            R.w(f"[synthesis] {ch['id']} {ch['title']} 在全书主线和关键思想里完全没出现,确认它真的不重要?")


def run_check(work: str, chapter: str | None = None, copy_n: int | None = None) -> Report:
    W, man, source, notes, (S, serr) = load_work(work)
    lang = man.get("lang", "zh")
    n_copy = copy_n or (20 if lang == "zh" else 12)
    R = Report()
    targets = [c for c in man["chapters"] if chapter in (None, c["id"])]
    for ch in targets:
        if ch["id"] not in notes:
            if ch.get("skip_hint"):
                R.i(f"[{ch['id']}] 附属内容({ch['title']}),未做笔记")
            else:
                R.e(f"[{ch['id']}] 缺少 notes/{ch['id']}.json({ch['title']})")
            continue
        n, err = notes[ch["id"]]
        if err:
            R.e(err)
            continue
        check_chapter(ch["id"], n, ch, source, R, lang)
    claims = all_claims({k: v for k, v in notes.items() if chapter in (None, k)})
    for ch in targets:
        n = notes.get(ch["id"], (None, None))[0]
        if n:
            check_links(n.get("links"), claims if chapter else all_claims(notes), f"[{ch['id']}]", R)

    # 出处贴合度
    low = []
    for cl, c in claims.items():
        ref = anchor_text(c.get("anchors", []), source)
        if ref:
            ov = overlap(c.get("text", ""), ref, lang)
            if ov < (0.12 if lang == "zh" else 0.15):
                low.append((ov, cl))
    for ov, cl in sorted(low):
        R.w(f"[出处] {cl} 与所引段落几乎没有共同内容(贴合度 {ov:.2f}):锚点引错了,还是这条不是书里说的?")

    # 照抄检测
    shingles = build_shingles(source, n_copy, lang)
    objs = [(f"notes/{k}", v[0]) for k, v in notes.items() if v[0] and chapter in (None, k)]
    if S and chapter is None:
        objs.append(("synthesis", S))
    for name, obj in objs:
        for path, txt in text_fields(obj):
            seg = longest_copied(txt, shingles, n_copy, lang)
            if seg:
                R.e(f"[照抄] {name}:{path} 与原文连续重合 {len(seg) if lang == 'zh' else len(seg.split())} "
                    f"{'字' if lang == 'zh' else '词'}:「{seg[:40]}…」——请改写")

    if chapter is None:
        if serr:
            R.e(serr)
        elif S is None:
            R.e("缺少 synthesis.json(全书综合还没做)")
        else:
            check_synthesis(S, all_claims(notes), notes, man, source, R)
            check_verification(W, all_claims(notes), R)
        # 篇幅:导读是帮人读书的,不是重写这本书
        gen = sum(len(t) for _, o in objs for _, t in text_fields(o))
        ratio = gen / max(1, man["total_chars"])
        R.i(f"生成文字约 {gen} 字符,为原书的 {ratio:.0%}")
        if man["total_chars"] > 50000 and ratio > 0.30:
            R.w(f"生成内容达到原书的 {ratio:.0%}:导读在复述全书,请压缩")
    R.i(f"命题 {len(claims)} 条")
    return R


# ---------- 事实核查闭环 ----------

def claim_hash(c: dict) -> str:
    return hashlib.sha1((c.get("text", "") + "|" + ",".join(c.get("anchors", []))).encode()).hexdigest()[:10]


def make_verify_sheet(work: str, n_random: int = 10, seed: int = 7) -> Path:
    """抽出需要回到原文核对的命题:全书骨架上的全部 + 贴合度最低的 + 随机抽样。"""
    W, man, source, notes, (S, _) = load_work(work)
    lang = man.get("lang", "zh")
    claims = all_claims(notes)
    pick: dict[str, str] = {}
    if S:
        for k in S.get("key_ideas", []):
            for x in (k.get("because") or []) + (k.get("evidence") or []):
                pick.setdefault(x, "关键思想")
        for s in S.get("storyline", []):
            for x in s.get("claims", []):
                pick.setdefault(x, "论证主线")
    for c in claims.values():
        if c.get("voice") == "reported":
            pick.setdefault(c["id"], "他人观点(核对是否误归给作者)")
    scored = sorted(claims, key=lambda x: overlap(claims[x]["text"], anchor_text(claims[x].get("anchors"), source), lang))
    for x in scored[:5]:
        pick.setdefault(x, "贴合度最低")
    rest = [x for x in claims if x not in pick]
    random.Random(seed).shuffle(rest)
    for x in rest[:n_random]:
        pick.setdefault(x, "随机抽查")
    items = [{"id": x, "why": why, "hash": claim_hash(claims[x])} for x, why in pick.items() if x in claims]
    (W / "verify").mkdir(exist_ok=True)
    (W / "verify" / "sheet.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# 事实核查单", "",
             "对每一条:只根据下面给出的原文段落判断命题是否成立。把结论写进 work/verify/verdicts.json。", ""]
    for it in items:
        c = claims[it["id"]]
        lines += [f"## {it['id']}({it['why']})", "",
                  f"- 命题:{c['text']}",
                  f"- 类型:{c.get('kind')} / 声音:{c.get('voice', 'author')}",
                  f"- 锚点:{', '.join(c.get('anchors', []))}", "", "原文:", ""]
        for a in c.get("anchors", []):
            for k in expand_anchor(a, source) or []:
                lines.append(f"> [{k}] {source[k.split('.')[0]][k]}")
        lines.append("")
    p = W / "verify" / "sheet.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def check_verification(W: Path, claims: dict, R: Report):
    sheet_p, ver_p = W / "verify" / "sheet.json", W / "verify" / "verdicts.json"
    if not sheet_p.exists():
        R.e("还没有生成事实核查单:运行 bookguide.py verify-sheet")
        return
    sheet, _ = load_json(sheet_p)
    ver, err = load_json(ver_p)
    if err:
        R.e(f"事实核查未完成:{err}")
        return
    vmap = {v.get("id"): v for v in ver}
    bad = 0
    for it in sheet:
        v = vmap.get(it["id"])
        if not v:
            R.e(f"[核查] {it['id']} 没有核查结论")
            continue
        if v.get("verdict") not in ("ok", "partial", "wrong", "unsupported"):
            R.e(f"[核查] {it['id']} verdict 只能是 ok/partial/wrong/unsupported")
            continue
        if v["verdict"] != "ok":
            bad += 1
            c = claims.get(it["id"])
            if c is not None and claim_hash(c) == it["hash"]:
                R.e(f"[核查] {it['id']} 被判为 {v['verdict']}({v.get('reason', '')}),但命题和锚点都还没改")
    if sheet:
        R.i(f"事实核查:{len(sheet)} 条,其中 {bad} 条有问题(需要已修正)")
