"""各文件的字段规范(单一事实来源)。references/schema.md 由人工与此保持一致;tests 会核对枚举一致。"""
from __future__ import annotations

import re

KINDS = {
    "claim": "论断",        # 作者主张的判断/结论
    "mechanism": "机制",    # 解释“为什么/怎么起作用”
    "method": "方法",       # 可以照做的做法/步骤
    "evidence": "证据",     # 数据、研究、调研、统计
    "example": "案例",      # 用来说明/佐证的具体事例、故事
    "objection": "反对意见",  # 书中提到并回应的对立观点
    "caveat": "限定",       # 边界条件、局限、自我修正、承认的不足
    "aside": "题外话",      # 不构成论证的插话(标出来,免得被当成论据)
}
RELS = {
    "supports": "支持",      # 是 parent 的理由/证据
    "explains": "解释",      # 是 parent 的机制
    "illustrates": "举例",   # 是 parent 的例子
    "elaborates": "展开",    # 是 parent 的细化/组成部分
    "qualifies": "限定",     # 给 parent 加条件/边界
    "objects": "反对",       # 是针对 parent 的反对意见
    "rebuts": "回应",        # 是对 parent(一个反对意见)的回应
    "revises": "修正",       # 修改/收回 parent 的说法(可跨章)
}
VOICES = {"author": "作者主张", "other": "他人观点", "hedged": "作者存疑"}
LINK_TYPES = {
    "causes": "导致", "depends_on": "依赖", "tension": "张力/矛盾", "restates": "重述",
    "applies": "应用", "revises": "修正",
}
EV_TYPES = {"data": "数据/统计", "study": "研究/调研", "case": "案例", "anecdote": "亲身经历/轶事",
            "theory": "理论/模型", "analogy": "类比", "authority": "权威/引述"}
EV_STRENGTH = {"strong": "强", "moderate": "中", "weak": "弱", "illustrative": "仅作说明", "unclear": "书中未交代"}
CONCEPT_ORIGIN = {"coined": "作者自造", "redefined": "作者赋予特殊含义", "borrowed": "通用/他人概念"}
PRIORITY = {"must": "精读", "normal": "正常读", "skim": "可略读"}
CRIT_TYPES = {"evidence_weak": "证据偏弱", "gap": "论证缺口", "alt_explanation": "替代解释", "overreach": "结论过强",
              "scope": "适用边界", "inconsistency": "前后不一致", "counterexample": "反例", "strength": "站得住的部分"}
SEVERITY = {"high": "高", "med": "中", "low": "低"}
Q_KINDS = {"recall": "回忆", "explain": "解释", "apply": "应用", "compare": "辨析", "critique": "批判", "trap": "易错"}
GENRES = {"argument": "论证型", "howto": "方法/指南型", "narrative": "叙事/历史型", "science": "科普/研究型",
          "memoir": "回忆/传记型", "reference": "工具书型", "mixed": "混合"}
AUDIT_VERDICTS = {"ok": "忠实", "overstated": "说过头", "distorted": "走样", "unsupported": "原文找不到",
                  "misattributed": "归因错误", "too_vague": "太空泛"}
WAIVE = {"numbers", "overlap", "copy"}

RE_CARD_ID = re.compile(r"^(c\d{2})\.k(\d+)$")
RE_PARA_ID = re.compile(r"^(c\d{2}):(\d+)$")


def spec_card(extra_errors: list[str] | None = None):
    return {
        "id": ("str", True), "text": ("str", True, {"min": 8, "max": 260}), "label": ("str", True, {"max": 14}),
        "kind": ("enum", True, KINDS), "voice": ("enum", True, VOICES), "tier": ("int", True, {"in": (1, 2, 3)}),
        "parent": ("str?", False), "rel": ("enum?", False, RELS), "refs": ("list", True, {"min": 1, "max": 6}),
        "anchor": ("str", True), "ev": ("obj?", False), "waive": ("list?", False),
    }


NOTES_META = {
    "role": ("str", True, {"min": 8}), "summary": ("str", True, {"min": 20}), "takeaway": ("str", True, {"min": 6}),
    "priority": ("enum", True, PRIORITY), "reading_questions": ("list", True, {"min": 1, "max": 5}),
}
CONCEPT = {
    "term": ("str", True, {"max": 30}), "def": ("str", True, {"min": 8, "max": 300}), "origin": ("enum", True, CONCEPT_ORIGIN),
    "refs": ("list", True, {"min": 1, "max": 6}), "anchor": ("str", True), "not": ("str?", False),
}
LINK = {"from": ("str", True), "to": ("str", True), "type": ("enum", True, LINK_TYPES), "note": ("str", True, {"min": 6})}


def check_fields(obj: dict, spec: dict, where: str) -> list[str]:
    """返回错误文本列表。spec: field -> (type, required[, opts])。类型后缀 ? 表示允许 null。"""
    errs = []
    if not isinstance(obj, dict):
        return [f"{where}: 必须是对象"]
    for f, sp in spec.items():
        typ, req = sp[0], sp[1]
        opts = sp[2] if len(sp) > 2 else None
        nullable = typ.endswith("?")
        typ = typ.rstrip("?")
        v = obj.get(f)
        if v is None:
            if req and not nullable:
                errs.append(f"{where}: 缺少字段 {f}")
            elif req and f not in obj:
                errs.append(f"{where}: 缺少字段 {f}(没有就写 null)")
            continue
        if typ == "str":
            if not isinstance(v, str) or not v.strip():
                errs.append(f"{where}.{f}: 必须是非空字符串")
            elif opts:
                if "min" in opts and len(v) < opts["min"]:
                    errs.append(f"{where}.{f}: 太短(<{opts['min']} 字): {v!r}")
                if "max" in opts and len(v) > opts["max"]:
                    errs.append(f"{where}.{f}: 太长(>{opts['max']} 字,{len(v)}): {v[:20]!r}…")
        elif typ == "enum":
            if v not in opts:
                errs.append(f"{where}.{f}: {v!r} 不在 {sorted(opts)} 中")
        elif typ == "int":
            if not isinstance(v, int) or isinstance(v, bool) or (opts and "in" in opts and v not in opts["in"]):
                errs.append(f"{where}.{f}: 必须是 {opts['in'] if opts else '整数'} 之一")
        elif typ == "list":
            if not isinstance(v, list):
                errs.append(f"{where}.{f}: 必须是数组")
            elif opts:
                if "min" in opts and len(v) < opts["min"]:
                    errs.append(f"{where}.{f}: 至少 {opts['min']} 项")
                if "max" in opts and len(v) > opts["max"]:
                    errs.append(f"{where}.{f}: 最多 {opts['max']} 项(引用太散,拆成多张卡)")
        elif typ == "obj":
            if not isinstance(v, dict):
                errs.append(f"{where}.{f}: 必须是对象")
    return errs
