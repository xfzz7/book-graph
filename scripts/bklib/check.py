"""校验:结构(必须修)+ 溯源(防编造/防照抄)+ 分布(提示)。

等级:E = 错误,必须修;W = 警告,要修或在卡片上显式 waive;I = 信息,仅供判断。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import schema as S
from .store import Work
from .text import CopyIndex, copy_threshold, detect_lang, norm, numbers, overlap, cjk_ratio, clip


@dataclass
class Issue:
    level: str   # E / W / I
    code: str
    where: str
    msg: str

    def __str__(self):
        return f"[{self.level}] {self.where}: {self.msg}  ({self.code})"


# 溯源阈值(在 canary 书上标定;见 REPORT)
OVERLAP_MIN = 0.30        # 命题与引用段落(±1 段)的 2-gram / 词干覆盖率
ANCHOR_ZH = (4, 30)       # 归一化后字符数范围
ANCHOR_EN = (12, 90)


def _window(w: Work, refs: list[str], pad: int = 1) -> str:
    """refs 指向的段落 + 前后各 pad 段的文本。"""
    out, seen = [], set()
    for r in refs:
        p = w.paras.get(r)
        if not p:
            continue
        for n in range(p["n"] - pad, p["n"] + pad + 1):
            pid = f"{p['ch']}:{n}"
            if pid in w.paras and pid not in seen:
                seen.add(pid)
                out.append(w.paras[pid]["text"])
    return "\n".join(out)


def _refs_ok(w: Work, refs, where: str, issues: list[Issue], only_ch: str | None = None) -> list[str]:
    ok = []
    if not isinstance(refs, list):
        return ok
    for r in refs:
        if not isinstance(r, str) or not S.RE_PARA_ID.match(r):
            issues.append(Issue("E", "ref_format", where, f"refs 里的 {r!r} 不是段落 id(形如 c03:12)"))
        elif r not in w.paras:
            issues.append(Issue("E", "ref_missing", where, f"段落 {r} 不存在"))
        elif only_ch and not r.startswith(only_ch + ":"):
            issues.append(Issue("E", "ref_wrong_chapter", where, f"卡片属于 {only_ch},但引用了 {r};跨章关系请用 parent/links 表达"))
        else:
            ok.append(r)
    return ok


class Checker:
    def __init__(self, w: Work):
        self.w = w
        self.issues: list[Issue] = []
        self.book_lang = w.meta.get("lang") or detect_lang(w.book_text())
        self._ci: CopyIndex | None = None
        self.stats: dict = {}

    # ---------- 工具
    def add(self, level, code, where, msg):
        self.issues.append(Issue(level, code, where, msg))

    @property
    def copy_index(self) -> CopyIndex:
        if self._ci is None:
            text = self.w.book_text()
            self._ci = CopyIndex(text, copy_threshold(text))
        return self._ci

    def _copy_check(self, text: str, where: str, waived: set, level="W"):
        if "copy" in waived:
            return
        n = self.copy_index.longest_shared(text)
        if n >= self.copy_index.k:
            self.add(level, "copy", where, f"与原文有连续 {n} 个字符相同,疑似照抄,请改成自己的话: “{clip(text, 40)}”")

    # ---------- 笔记
    def check_notes(self):
        w = self.w
        notes = w.load_notes()
        all_ids: dict[str, str] = {}
        cards_by_id: dict[str, dict] = {}
        for c in w.chapters():
            key = c["key"]
            n = notes.get(key)
            if not n:
                self.add("E", "chapter_missing", key, f"《{c['title']}》还没有笔记(notes/{key}.json)。确实不需要读,用 `bk skip {key}` 标记")
                continue
            if n["meta_count"] != 1:
                self.add("E", "meta_count", key, f"本章必须有且仅有一处 meta(现在 {n['meta_count']} 处)")
            if n["meta"]:
                for e in S.check_fields(n["meta"], S.NOTES_META, f"{key}.meta"):
                    self.add("E", "schema", key, e)
            if not n["cards"]:
                self.add("E", "no_cards", key, "本章没有任何卡片")
            for card in n["cards"]:
                cid = card.get("id", "?")
                where = f"{cid}"
                for e in S.check_fields(card, S.spec_card(), where):
                    self.add("E", "schema", where, e)
                m = S.RE_CARD_ID.match(str(cid))
                if not m or m.group(1) != key:
                    self.add("E", "id_format", where, f"卡片 id 必须形如 {key}.k1 且属于本章")
                if cid in all_ids:
                    self.add("E", "id_dup", where, f"id 重复(也在 {all_ids[cid]})")
                all_ids[cid] = card.get("_file", key)
                cards_by_id[cid] = card
            for con in n["concepts"]:
                where = f"{key}.概念[{con.get('term', '?')}]"
                for e in S.check_fields(con, S.CONCEPT, where):
                    self.add("E", "schema", where, e)
            for lk in n["links"]:
                for e in S.check_fields(lk, S.LINK, f"{key}.link"):
                    self.add("E", "schema", key, e)
        for key in notes:
            if key not in {c["key"] for c in w.chapters()}:
                self.add("W", "note_for_skipped", key, "这一章被标记为跳过,但有笔记文件")

        # 第二轮:引用/父子/溯源(需要全部 id)
        for cid, card in cards_by_id.items():
            key = cid.split(".")[0]
            self._check_card(card, key, cards_by_id)
        for key, n in notes.items():
            for lk in n["links"]:
                for end in ("from", "to"):
                    if lk.get(end) not in cards_by_id:
                        self.add("E", "link_end", key, f"link 的 {end}={lk.get(end)!r} 不是已有卡片")
                if lk.get("from") == lk.get("to"):
                    self.add("E", "link_self", key, "link 不能指向自己")
            for con in n["concepts"]:
                self._check_concept(con, key)
        self._check_cycles(cards_by_id)
        self._check_distribution(notes, cards_by_id)
        self._check_coverage(cards_by_id)
        return notes, cards_by_id

    def _check_card(self, card: dict, key: str, cards_by_id: dict):
        w = self.w
        cid = card["id"]
        where = cid
        waived = set(card.get("waive") or [])
        bad = waived - S.WAIVE
        if bad:
            self.add("E", "waive", where, f"waive 只能是 {sorted(S.WAIVE)},出现了 {sorted(bad)}")
        if waived:
            self.add("I", "waived", where, f"已豁免 {sorted(waived)}(审计会重点看这些卡)")
        # parent / rel
        p = card.get("parent")
        if p:
            if p not in cards_by_id:
                self.add("E", "parent_missing", where, f"parent {p!r} 不存在")
            elif p == cid:
                self.add("E", "parent_self", where, "parent 不能是自己")
            if not card.get("rel"):
                self.add("E", "rel_missing", where, "有 parent 就必须写 rel")
        elif card.get("rel"):
            self.add("E", "rel_orphan", where, "没有 parent 却写了 rel")
        if card.get("kind") == "objection" and card.get("voice") == "author":
            self.add("W", "voice", where, "反对意见一般是“他人观点”(voice=other);如果是作者自己提出的疑问,请在文本里说明")
        if card.get("kind") in ("evidence", "example") and card.get("tier") in (1, 2):
            ev = card.get("ev")
            if not isinstance(ev, dict):
                self.add("E", "ev_missing", where, "证据/案例卡需要 ev:{type, strength, limit}")
            else:
                if ev.get("type") not in S.EV_TYPES:
                    self.add("E", "ev_type", where, f"ev.type 必须是 {sorted(S.EV_TYPES)}")
                if ev.get("strength") not in S.EV_STRENGTH:
                    self.add("E", "ev_strength", where, f"ev.strength 必须是 {sorted(S.EV_STRENGTH)}")
                if not str(ev.get("limit", "")).strip():
                    self.add("E", "ev_limit", where, "ev.limit 必须写:这条证据能支持到哪一步、有什么局限(书里没说就写“书中未交代”)")
        refs = _refs_ok(w, card.get("refs"), where, self.issues, only_ch=key)
        text = card.get("text", "") or ""
        anchor = card.get("anchor", "") or ""
        # anchor:必须逐字出现在原文中
        if anchor:
            na = norm(anchor)
            lo, hi = ANCHOR_ZH if cjk_ratio(anchor) > 0.3 else ANCHOR_EN
            if len(na) > hi:
                self.add("E", "anchor_long", where, f"anchor 过长({len(na)}>{hi}):只留一个能 Ctrl+F 搜到的短语,不要抄整句")
            elif len(na) < lo:
                self.add("W", "anchor_short", where, f"anchor 太短({len(na)}<{lo}),搜不准")
            if refs:
                win = norm(_window(w, refs, 0))
                if na not in win:
                    # 去全章找,给出建议
                    hit = [p["id"] for p in w.ch_paras(key) if na in norm(p["text"])]
                    if hit:
                        self.add("E", "anchor_misplaced", where, f"anchor 不在 refs 里,但出现在 {hit[:3]};refs 写错了?")
                    elif na in norm(w.book_text()):
                        self.add("E", "anchor_other_chapter", where, "anchor 出现在别的章,不在本章")
                    else:
                        self.add("E", "anchor_not_found", where, f"anchor {anchor!r} 在原文里找不到(必须逐字摘自原文)")
        if not refs:
            return
        win = _window(w, refs, 1)
        # 数字
        if "numbers" not in waived:
            miss = [x for x in numbers(text + " " + str((card.get("ev") or {}).get("limit", ""))) if x not in numbers(win)
                    and not re.fullmatch(r"[0-9]", x)]
            if miss:
                self.add("W", "numbers", where, f"数字 {sorted(miss)} 没有出现在引用段落(±1 段)里;若是你推算的,请核对并 waive")
        # 语义重叠(仅同语种)
        if "overlap" not in waived and detect_lang(text) == self.book_lang:
            ov = overlap(text, win)
            if ov < OVERLAP_MIN:
                self.add("W", "overlap", where, f"命题与引用段落的用词重合率只有 {ov:.2f}(<{OVERLAP_MIN}),可能引错段落或说多了: “{clip(text, 40)}”")
        self._copy_check(text, where, waived)

    def _check_concept(self, con: dict, key: str):
        where = f"{key}.概念[{con.get('term', '?')}]"
        refs = _refs_ok(self.w, con.get("refs"), where, self.issues)
        term = con.get("term", "")
        if refs and term:
            blob = norm(_window(self.w, refs, 1))
            if norm(term) not in blob and not any(norm(a) in blob for a in con.get("aliases", [])):
                self.add("W", "term_not_in_refs", where, f"术语 {term!r} 没有出现在引用段落附近(术语必须是书里的原词)")
        a = con.get("anchor", "")
        if a and refs and norm(a) not in norm(_window(self.w, refs, 0)):
            self.add("E", "anchor_not_found", where, f"anchor {a!r} 不在 refs 里")
        self._copy_check(con.get("def", "") or "", where, set())

    def _check_cycles(self, cards: dict):
        for cid in cards:
            seen, cur = set(), cid
            while cur:
                if cur in seen:
                    self.add("E", "parent_cycle", cid, "parent 链成环")
                    break
                seen.add(cur)
                cur = (cards.get(cur) or {}).get("parent")

    def _check_distribution(self, notes: dict, cards: dict):
        total_w = 0
        for c in self.w.chapters():
            key = c["key"]
            n = notes.get(key)
            if not n:
                continue
            cs = n["cards"]
            total_w += c["weight"]
            if len(cs) >= 6:
                t1 = sum(1 for x in cs if x.get("tier") == 1)
                if t1 / len(cs) > 0.4:
                    self.add("W", "tier1_heavy", key, f"{t1}/{len(cs)} 张卡是 tier 1;tier 1 指“拿掉论证就垮”,请降级一些,否则总览没有重点")
                if t1 == 0:
                    self.add("W", "tier1_none", key, "本章没有 tier 1 的卡;是不是没找出本章的主论点?")
            dens = len(cs) / max(1, c["weight"] / 1000)
            if c["weight"] >= 1500 and dens < 0.3:
                self.add("W", "sparse", key, f"本章只有 {len(cs)} 张卡(每千字 {dens:.2f}),可能漏读了大段内容")
            if dens > 8:
                self.add("W", "dense", key, f"本章 {len(cs)} 张卡(每千字 {dens:.1f}),像是在逐句改写而不是抽取要点")
            tops = [x for x in cs if not x.get("parent")]
            cross = [x for x in cs if x.get("parent") in cards and cards[x["parent"]]["id"].split(".")[0] != key]
            if cs and not tops and not cross:
                self.add("W", "no_top", key, "本章所有卡都有本章内的 parent,没有顶层卡(通常是本章主论点)")
        self.stats["cards"] = len(cards)
        self.stats["weight"] = total_w

    def _check_coverage(self, cards: dict):
        """哪些大段正文没有任何卡片引用(±1 段内)?只报告,让你判断是不是漏读。"""
        w = self.w
        self.stats["uncovered"] = []
        cover = {}
        for card in cards.values():
            for r in card.get("refs", []) or []:
                cover[r] = cover.get(r, 0) + 1
        for c in w.chapters():
            ps = w.ch_paras(c["key"])
            if not ps:
                continue
            hit = [bool(cover.get(p["id"])) for p in ps]
            run, runs = 0, []
            for i, h in enumerate(hit + [True]):
                if not h:
                    run += len(ps[i]["text"])
                elif run:
                    j = i
                    runs.append((ps[j - 1]["id"], run, j))
                    run = 0
            lim = max(1500, c["chars"] * 0.35)
            for pid, ln, j in runs:
                if ln >= lim:
                    self.stats["uncovered"].append((c["key"], pid, ln))
                    self.add("I", "gap", c["key"], f"到 {pid} 为止有连续约 {ln} 字没有任何卡片引用,确认没有漏掉要点(或是题外话/重复内容)")
        # 位置偏倚:引用集中在章的前半?
        pos = []
        for card in cards.values():
            for r in card.get("refs", []) or []:
                p = w.paras.get(r)
                if p:
                    tot = w.chapter(p["ch"])["n_paras"]
                    pos.append(p["n"] / max(1, tot))
        if len(pos) >= 30:
            first_half = sum(1 for x in pos if x <= 0.5) / len(pos)
            self.stats["first_half_share"] = round(first_half, 2)
            if first_half > 0.75:
                self.add("W", "front_bias", "全书", f"{first_half:.0%} 的引用落在各章前半段,后半段可能读得太粗")

    # ---------- 综合
    def check_synthesis(self, cards: dict, notes: dict):
        w = self.w
        sy = w.read_json("synthesis.json")
        if sy is None:
            self.add("E", "synthesis_missing", "synthesis.json", "还没有全书综合(synthesis.json)")
            return None
        req = {"one_liner": ("str", True, {"min": 10}), "question": ("str", True, {"min": 6}),
               "thesis": ("str", True, {"min": 15}), "genre": ("enum", True, S.GENRES), "audience": ("str", True, {"min": 4}),
               "parts": ("list", True, {"min": 1}), "pillars": ("list", True, {"min": 2, "max": 8}),
               "attach": ("obj", True), "reading_plan": ("obj", True), "misreadings": ("list", True)}
        for e in S.check_fields(sy, req, "synthesis"):
            self.add("E", "schema", "synthesis", e)
        pillars = {}
        for p in sy.get("pillars", []) or []:
            pid = p.get("id", "?")
            if not re.fullmatch(r"P\d+", str(pid)):
                self.add("E", "pillar_id", "synthesis", f"支柱 id 必须形如 P1,得到 {pid!r}")
            for e in S.check_fields(p, {"id": ("str", True), "label": ("str", True, {"max": 14}),
                                        "text": ("str", True, {"min": 10, "max": 220}), "chapters": ("list", True, {"min": 1})}, f"synthesis.{pid}"):
                self.add("E", "schema", "synthesis", e)
            pillars[pid] = p
            self._copy_check(p.get("text", "") or "", f"synthesis.{pid}", set())
        for part in sy.get("parts", []) or []:
            for e in S.check_fields(part, {"title": ("str", True), "chapters": ("list", True, {"min": 1}), "job": ("str", True, {"min": 6})}, "synthesis.parts"):
                self.add("E", "schema", "synthesis", e)
        covered_ch = {c for part in sy.get("parts", []) or [] for c in part.get("chapters", [])}
        for c in w.chapters():
            if c["key"] not in covered_ch:
                self.add("W", "part_missing", "synthesis", f"parts 里没有包含 {c['key']}《{c['title']}》")
        # attach
        att = sy.get("attach") or {}
        for cid, pid in att.items():
            if cid not in cards:
                self.add("E", "attach_card", "synthesis", f"attach 里的卡片 {cid} 不存在")
            elif cards[cid].get("parent"):
                self.add("W", "attach_nonroot", "synthesis", f"{cid} 已有 parent,不需要 attach(会被忽略)")
            if pid not in pillars:
                self.add("E", "attach_pillar", "synthesis", f"{cid} 挂到不存在的支柱 {pid}")
        # 每张卡必须能沿 parent 链走到一个被挂到支柱的根
        def root(cid):
            seen = set()
            while cards.get(cid, {}).get("parent") and cid not in seen:
                seen.add(cid)
                cid = cards[cid]["parent"]
            return cid
        orphan_roots = {}
        for cid in cards:
            r = root(cid)
            if r not in att:
                orphan_roots.setdefault(r, []).append(cid)
        for r, members in orphan_roots.items():
            ch = r.split(".")[0]
            self.add("W" if len(members) < 3 else "E", "unattached", r,
                     f"以 {r} 为根的 {len(members)} 张卡没有挂到任何支柱(synthesis.attach);如果它们确实与主线无关,请说明并仍然挂到最近的支柱")
        # 支柱必须有人挂
        used = set(att.values())
        for pid in pillars:
            if pid not in used:
                self.add("E", "pillar_empty", "synthesis", f"支柱 {pid} 没有任何卡片挂上来")
        # chains
        for ch in sy.get("chains", []) or []:
            for e in S.check_fields(ch, {"name": ("str", True), "steps": ("list", True, {"min": 2}), "loop": ("bool?", False)}, "synthesis.chains"):
                self.add("E", "schema", "synthesis", e)
            for s in ch.get("steps", []) or []:
                if s not in cards:
                    self.add("E", "chain_step", "synthesis", f"chains 里的 {s} 不是卡片")
        # concepts
        seen_terms = set()
        for con in sy.get("concepts", []) or []:
            term = con.get("term", "?")
            where = f"synthesis.概念[{term}]"
            for e in S.check_fields(con, {"term": ("str", True), "def": ("str", True, {"min": 8, "max": 300}),
                                          "origin": ("enum", True, S.CONCEPT_ORIGIN), "intro": ("str", True),
                                          "refs": ("list", True, {"min": 1, "max": 6}), "not": ("str?", False)}, where):
                self.add("E", "schema", where, e)
            if term in seen_terms:
                self.add("E", "concept_dup", where, "概念重复")
            seen_terms.add(term)
            refs = _refs_ok(w, con.get("refs"), where, self.issues)
            if refs and norm(term) not in norm(w.book_text()):
                self.add("W", "term_not_in_book", where, f"术语 {term!r} 在原文里找不到(必须是书里的原词;别名请写 aliases)")
            self._copy_check(con.get("def", "") or "", where, set())
        # misreadings
        for m in sy.get("misreadings", []) or []:
            for e in S.check_fields(m, {"wrong": ("str", True, {"min": 6}), "right": ("str", True, {"min": 6}),
                                        "refs": ("list", True, {"min": 1, "max": 6})}, "synthesis.misreadings"):
                self.add("E", "schema", "synthesis", e)
            _refs_ok(w, m.get("refs"), "synthesis.misreadings", self.issues)
        rp = sy.get("reading_plan") or {}
        for fld in ("must", "skim", "skip"):
            for k in rp.get(fld, []) or []:
                if k not in {c["key"] for c in w.meta["chapters"]}:
                    self.add("E", "reading_plan", "synthesis", f"reading_plan.{fld} 里的 {k} 不是章")
        pri = {c["key"]: (notes.get(c["key"], {}).get("meta") or {}).get("priority") for c in w.chapters()}
        for k in rp.get("must", []) or []:
            if pri.get(k) == "skim":
                self.add("W", "plan_conflict", "synthesis", f"{k} 在 reading_plan.must 里,但章笔记 priority=skim;请统一")
        for k in rp.get("skim", []) or []:
            if pri.get(k) == "must":
                self.add("W", "plan_conflict", "synthesis", f"{k} 在 reading_plan.skim 里,但章笔记 priority=must;请统一")
        for fld in ("one_liner", "thesis", "question"):
            self._copy_check(sy.get(fld, "") or "", f"synthesis.{fld}", set())
        return sy

    # ---------- 审读
    def check_critique(self, cards: dict):
        w = self.w
        cr = w.read_json("critique.json")
        if cr is None:
            self.add("E", "critique_missing", "critique.json", "还没有审读(critique.json)")
            return None
        for e in S.check_fields(cr, {"verdict": ("str", True, {"min": 20}), "strengths": ("list", True, {"min": 1}), "items": ("list", True, {"min": 3})}, "critique"):
            self.add("E", "schema", "critique", e)
        ids = set()
        n_out = 0
        for it in cr.get("items", []) or []:
            iid = it.get("id", "?")
            where = f"critique.{iid}"
            for e in S.check_fields(it, {"id": ("str", True), "type": ("enum", True, S.CRIT_TYPES), "text": ("str", True, {"min": 15}),
                                         "target": ("list", True, {"min": 1}), "source": ("enum", True, {"book": "书中自己承认/可在书中查到", "outside": "我的外部判断"}),
                                         "severity": ("enum", True, S.SEVERITY), "refs": ("list", True)}, where):
                self.add("E", "schema", where, e)
            if iid in ids:
                self.add("E", "id_dup", where, "id 重复")
            ids.add(iid)
            for t in it.get("target", []) or []:
                if t not in cards:
                    self.add("E", "target_missing", where, f"target {t!r} 不是卡片 id")
            if it.get("source") == "book":
                if not it.get("refs"):
                    self.add("E", "book_needs_refs", where, "source=book 必须有 refs(指向书里自己承认/说到的那段)")
                else:
                    _refs_ok(w, it.get("refs"), where, self.issues)
            elif it.get("source") == "outside":
                n_out += 1
                if it.get("refs"):
                    _refs_ok(w, it.get("refs"), where, self.issues)
            self._copy_check(it.get("text", "") or "", where, set())
        self.stats["critique_outside"] = n_out
        return cr

    # ---------- 自测题
    def check_questions(self, cards: dict):
        w = self.w
        qs = w.read_json("questions.json")
        if qs is None:
            self.add("E", "questions_missing", "questions.json", "还没有自测题(questions.json)")
            return None
        if not isinstance(qs, list) or len(qs) < 8:
            self.add("E", "questions_few", "questions.json", "自测题至少 8 道(数组)")
            return qs if isinstance(qs, list) else None
        kinds = {}
        ids = set()
        for q in qs:
            qid = q.get("id", "?")
            where = f"questions.{qid}"
            for e in S.check_fields(q, {"id": ("str", True), "kind": ("enum", True, S.Q_KINDS), "q": ("str", True, {"min": 6}),
                                        "a": ("str", True, {"min": 8}), "cards": ("list", True, {"min": 1}), "refs": ("list", True, {"min": 1, "max": 8})}, where):
                self.add("E", "schema", where, e)
            if qid in ids:
                self.add("E", "id_dup", where, "id 重复")
            ids.add(qid)
            kinds[q.get("kind")] = kinds.get(q.get("kind"), 0) + 1
            for c in q.get("cards", []) or []:
                if c not in cards:
                    self.add("E", "q_card", where, f"cards 里的 {c!r} 不是卡片 id")
            refs = _refs_ok(w, q.get("refs"), where, self.issues)
            a = q.get("a", "") or ""
            if refs and detect_lang(a) == self.book_lang:
                ov = overlap(a, _window(w, refs, 1))
                if ov < OVERLAP_MIN and "overlap" not in (q.get("waive") or []):
                    self.add("W", "overlap", where, f"答案与引用段落重合率 {ov:.2f}(<{OVERLAP_MIN}):答案是否超出原文?")
            if refs and "numbers" not in (q.get("waive") or []):
                miss = [x for x in numbers(a) if x not in numbers(_window(w, refs, 1)) and not re.fullmatch(r"[0-9]", x)]
                if miss:
                    self.add("W", "numbers", where, f"答案里的数字 {sorted(miss)} 没有出现在引用段落里")
            self._copy_check(a, where, set(q.get("waive") or []))
        recall = kinds.get("recall", 0)
        if recall / len(qs) > 0.5:
            self.add("W", "q_mix", "questions", f"回忆题占 {recall}/{len(qs)};请多加 explain/apply/compare/critique/trap(检验理解而不是记忆)")
        if kinds.get("trap", 0) == 0:
            self.add("W", "q_trap", "questions", "没有 trap(易错)题:至少 1~3 道,针对容易读反/归因错的地方")
        return qs

    # ---------- 审计结果
    def check_audit(self, cards: dict):
        from .audit import items, h
        log = self.w.read_json("audit/log.json")
        if not log:
            self.add("W", "audit_missing", "audit", "还没做独立核对(bk audit-plan / audit-apply)")
            return
        cur = items(self.w)
        for k, v in log.items():
            if k not in cur:
                continue
            changed = v.get("hash") != h(cur[k]["text"])
            if v.get("verdict") != "ok":
                if changed:
                    self.add("W", "audit_reaudit", k, "核对不通过后已改动,需要 bk audit-plan --retry 重新核对")
                else:
                    self.add("E", "audit_unresolved", k, f"核对结论为 {v['verdict']}:{clip(v.get('note', ''), 70)}(修正后 bk audit-plan --retry 重审)")
            elif changed:
                self.add("W", "audit_stale", k, "核对通过之后又改动过,建议重审")

    def run(self, full: bool = True):
        w = self.w
        notes, cards = self.check_notes()
        if full:
            self.check_synthesis(cards, notes)
            self.check_critique(cards)
            self.check_questions(cards)
            self.check_audit(cards)
        for e in w.load_errors:
            self.add("E", "json", "文件", e)
        self.stats["errors"] = sum(1 for i in self.issues if i.level == "E")
        self.stats["warnings"] = sum(1 for i in self.issues if i.level == "W")
        return self.issues
