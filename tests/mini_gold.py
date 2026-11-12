"""为 canary 小册子手写一份“迷你金标准”笔记(约 12 张卡),用来做端到端测试与渲染调试。
真正的全量笔记由执行者(LLM)按 SKILL.md 产出,见 evals。"""
from __future__ import annotations

import json
from pathlib import Path


def build_gold(w) -> None:
    def P(needle):
        for p in w.paras.values():
            if needle in p["text"]:
                return p["id"]
        raise KeyError(needle)

    def ch(title_part):
        return next(c["key"] for c in w.meta["chapters"] if title_part in c["title"])

    c1, c2, c3, c4, c5 = ch("满载的错觉"), ch("三个常被混淆"), ch("排队的非线性"), ch("回声成本"), ch("修正与边界")
    cap = ch("调研方法说明")

    def meta(role, summary, takeaway, prio="normal", rq=None):
        return {"role": role, "summary": summary, "takeaway": takeaway, "priority": prio, "reading_questions": rq or ["本章的核心论断是什么?"]}

    def card(ch_, n, text, label, kind, voice, tier, parent, rel, needle, anchor, ev=None):
        d = {"id": f"{ch_}.k{n}", "text": text, "label": label, "kind": kind, "voice": voice, "tier": tier,
             "parent": parent, "rel": rel, "refs": [P(needle)], "anchor": anchor}
        if ev:
            d["ev"] = ev
        return d

    notes = {
        c1: {"chapter": c1, "meta": meta("提出核心问题:忙不等于快,并给出第一项实证", "作者批评“利用率越高越好”的流行信条,用一项针对14家物流公司的调研支持“满载悖论”,并预告了调研的局限。", "满载不等于快:容量全部分配出去,应对变化反而更慢。", "must", ["作者把谁的观点称为“满载崇拜”?他同意吗?"]),
             "cards": [
                 card(c1, 1, "流行的管理信条认为利用率越高越好、闲置资源都是成本;作者把它概括为“满载崇拜”,并明说这不是某位具体学者的原话,而是他对流行看法的概括。", "满载崇拜", "objection", "other", 2, None, None, "我把这套信念称为", "满载崇拜"),
                 card(c1, 2, "满载悖论:组织越是把容量全部分配出去,应对变化的速度就越慢,满并不等于快。", "满载悖论", "claim", "author", 1, f"{c1}.k1", "objects", "我提出“满载悖论”", "满载悖论"),
                 card(c1, 3, "调研14家区域物流公司发现,调度员平均利用率超过90%的公司,其配送延误的波动幅度是低于80%公司的2.6倍;差别体现在波动而非平均延误。", "调研:2.6倍", "evidence", "author", 1, f"{c1}.k2", "supports", "波动幅度，是利用率低于80%的公司的2.6倍", "2.6倍",
                      {"type": "study", "strength": "weak", "limit": "相关性研究,仅14家自愿参与的公司,作者自己承认不能代表行业"}),
             ]},
        c3: {"chapter": c3, "meta": meta("从排队角度解释满载为何变慢,并给出经验法则", "利用率接近100%时等待时间非线性上升;作者给出85%线经验法则,并用急诊科案例佐证,指出波动才是关键。", "接近满载时等待非线性上升,根源是波动。", "must"),
             "cards": [
                 card(c3, 1, "作者提出的“85%线”是经验法则:利用率超过85%后,需求小幅增加会让等待时间增加一倍以上,但它不是精确定律。", "85%线", "claim", "author", 1, f"{c1}.k2", "explains", "当利用率超过85%之后", "经验法则"),
                 card(c3, 2, "某二甲医院急诊床位使用率在一个冬季从78%升到91%,患者平均等待时间从42分钟增加到117分钟。", "急诊科数据", "evidence", "author", 2, f"{c3}.k1", "illustrates", "78%上升到91%", "42分钟增加到117分钟",
                      {"type": "case", "strength": "illustrative", "limit": "单一医院的跟踪案例,书中没有交代样本与方法"}),
             ]},
        c4: {"chapter": c4, "meta": meta("从时间维度补充:反馈延迟带来回声成本,与排队机制合成自我强化回路", "定义回声成本,用软件团队例子与六周法则说明,并描述满载→无暇复盘→反馈变慢→回声成本→更满载的回路。", "满载使复盘缺席,回声成本推高紧急任务,形成越忙越慢的回路。", "must"),
             "cards": [
                 card(c4, 1, "决策的后果要隔一段时间才返回决策者,期间更多决策已建立在原判断之上,由此多出来的修复成本,作者称为回声成本。", "回声成本", "claim", "author", 1, None, None, "称为“回声成本”", "回声成本"),
                 card(c4, 2, "作者的“六周法则”称反馈滞后超过六周,纠错成本大致翻倍;但这只来自他约三十个咨询项目的经验,没有做过严格统计检验。", "六周法则", "evidence", "author", 2, f"{c4}.k1", "supports", "总结出一条“六周法则”", "六周法则",
                      {"type": "anecdote", "strength": "weak", "limit": "来自作者自己约三十个项目的经验,未做统计检验,作者自称只是起点性估计"}),
                 card(c4, 3, "满载使人无暇复盘,于是反馈变慢、回声成本上升、紧急修复任务增多,又进一步挤占容量,形成越忙越慢、越慢越忙的自我强化回路。", "自我强化回路", "mechanism", "author", 1, f"{c1}.k2", "explains", "组织满载，就没有人有空做复盘", "没有人有空做复盘"),
             ]},
        c5: {"chapter": c5, "meta": meta("作者修正前文说法并交代调研局限", "第七章把85%线修正为随波动而变,列出调研的反向因果与混杂风险,并讨论缓冲的失败方式。", "85%不是普适的线,取决于波动;调研只能支持“值得认真对待”。", "must"),
             "cards": [
                 card(c5, 1, "作者修正了85%线:临界利用率取决于需求与处理时间的波动,变异系数低于0.3时约92%,高于1.2时约70%,85%只是中间地带的平均值。", "85%线的修正", "caveat", "author", 1, f"{c3}.k1", "revises", "说得太整齐了", "说得太整齐了"),
                 card(c5, 2, "作者承认调研可能存在反向因果(不稳定的公司更易被迫满载)和规模混杂,因此只能支持“值得认真对待”,不能说“已被证明”。", "调研的局限", "caveat", "author", 2, f"{c1}.k3", "qualifies", "反向因果", "反向因果"),
             ]},
        cap: {"chapter": cap, "meta": meta("披露调研的数据来源细节", "附录说明14家公司中11家有系统日志,3家利用率来自问卷自我报告且未核实,分析没有控制规模等因素。", "附录披露了正文没细说的数据质量问题。", "must"),
              "cards": [
                  card(cap, 1, "14家公司里11家提供系统日志、据此计算利用率,另外3家的利用率来自对调度主管的问卷、属于自我报告,且未做独立核实。", "3家自我报告", "caveat", "author", 2, f"{c1}.k3", "qualifies", "来自对调度主管的问卷", "属于自我报告"),
              ]},
    }
    for c in w.meta["chapters"]:
        if c["key"] not in notes and not c.get("skip"):
            notes[c["key"]] = {"chapter": c["key"], "meta": meta("(迷你金标准未覆盖)", "(此章未在迷你金标准中展开,仅占位以便端到端测试。)", "(占位:此章未展开)", "skim"),
                               "cards": [card(c["key"], 1, "(占位卡片)本章的主要论断留待完整笔记。", "占位", "claim", "author", 3, None, None,
                                              w.ch_paras(c["key"])[0]["text"][:6], w.ch_paras(c["key"])[0]["text"][:8])]}
    nd = w.root / "notes"
    nd.mkdir(parents=True, exist_ok=True)
    for k, n in notes.items():
        (nd / f"{k}.json").write_text(json.dumps(n, ensure_ascii=False, indent=1), encoding="utf8")

    tops = [f"{c3}.k1" if False else None]
    att = {}
    for k, n in notes.items():
        for cd in n["cards"]:
            if not cd["parent"]:
                att[cd["id"]] = "P1"
    att[f"{c1}.k1"] = "P1"
    for cd in notes[c4]["cards"]:
        if not cd["parent"]:
            att[cd["id"]] = "P2"
    syn = {
        "one_liner": "越忙的组织越慢:把容量全部分配出去会让组织失去应对意外的速度,需要主动留出“缓冲”。",
        "question": "为什么把资源用得越满的组织,反而交付越慢、越容易出事?",
        "thesis": "满载不等于快:容量被全部承诺后,波动无处吸收,等待非线性上升,复盘缺席又推高回声成本;因此应当主动留出已识别、可调用且未承诺的缓冲,比例随波动而定。",
        "genre": "argument", "audience": "管理者、运营与项目负责人,以及想理解“忙却慢”现象的个人。",
        "parts": [{"title": "诊断与概念", "chapters": [c1, c2], "job": "指出问题并澄清缓冲/冗余/闲置的区别"},
                  {"title": "机制与阻力", "chapters": [c3, c4], "job": "从排队与反馈两个角度解释为什么满载会变慢"}],
        "pillars": [{"id": "P1", "label": "满载使系统变慢", "text": "把容量全部承诺出去,会让等待非线性上升、反馈变慢,组织因此越忙越慢。", "chapters": [c1, c3]},
                    {"id": "P2", "label": "反馈延迟放大代价", "text": "反馈越慢,回声成本越高,并与满载互相强化。", "chapters": [c4]}],
        "attach": att,
        "chains": [{"name": "越忙越慢的回路", "steps": [f"{c4}.k3", f"{c4}.k1"], "loop": False, "note": "示例"}],
        "concepts": [{"term": "回声成本", "def": "决策后果延迟返回、期间更多决策已建立其上而多出来的修复成本。", "origin": "coined", "intro": c4, "refs": [P("称为“回声成本”")], "not": "一般的返工成本"}],
        "misreadings": [{"wrong": "作者主张利用率越高越好", "right": "这是作者批评的“满载崇拜”,他主张留出缓冲", "refs": [P("我把这套信念称为")]}],
        "reading_plan": {"must": [c1, c3, c4, c5], "skim": [], "skip": [], "why": "先读第一章建立问题,再读机制与修正章。"},
    }
    (w.root / "synthesis.json").write_text(json.dumps(syn, ensure_ascii=False, indent=1), encoding="utf8")
    crit = {"verdict": "核心直觉有道理,但实证证据偏弱:调研样本小、相关性、部分数据自我报告;经验法则被作者自己限定。", "strengths": ["作者主动修正85%线并披露调研局限,诚实度较高。"],
            "items": [
                {"id": "r1", "type": "evidence_weak", "severity": "high", "source": "book", "target": [f"{c1}.k3"], "refs": [P("来自对调度主管的问卷")], "text": "支撑满载悖论的调研只有14家自愿参与的公司,其中3家利用率为自我报告,且未控制规模等因素。"},
                {"id": "r2", "type": "overreach", "severity": "med", "source": "book", "target": [f"{c3}.k1"], "refs": [P("说得太整齐了")], "text": "85%线被作者自己承认过于整齐,实际取决于波动程度。"},
                {"id": "r3", "type": "alt_explanation", "severity": "med", "source": "outside", "target": [f"{c1}.k3"], "refs": [], "text": "可能存在第三变量(如业务类型、地形)同时影响利用率与延误波动,值得核实。"}]}
    (w.root / "critique.json").write_text(json.dumps(crit, ensure_ascii=False, indent=1), encoding="utf8")
    qs = []
    base = [("recall", "调研的主要发现是什么?", "利用率超过90%的公司延误波动幅度是低于80%公司的2.6倍。", f"{c1}.k3", "波动幅度，是利用率低于80%的公司的2.6倍"),
            ("trap", "“利用率越高越好”是作者的观点吗?", "不是,这是作者批评的“满载崇拜”。", f"{c1}.k1", "我把这套信念称为"),
            ("explain", "为什么85%线不能当定律?", "作者自称是经验法则,并在第七章修正为随波动而变。", f"{c3}.k1", "不是一个精确的定律"),
            ("recall", "急诊科案例的数字?", "使用率78%→91%,等待42→117分钟。", f"{c3}.k2", "78%上升到91%"),
            ("explain", "回声成本是什么?", "决策后果延迟返回,期间更多决策建立在原判断上而多出的修复成本。", f"{c4}.k1", "称为“回声成本”"),
            ("critique", "六周法则的证据基础如何?", "来自作者约三十个项目经验,未做统计检验。", f"{c4}.k2", "我没有对它做过严格的统计检验"),
            ("apply", "某团队日历94%排满且决策很慢,按书里的逻辑该先查什么?", "先测量真实利用率并看反馈周期,再考虑留出命名的缓冲。", f"{c4}.k3", "没有人有空做复盘"),
            ("compare", "调研的局限有哪些?", "反向因果、规模混杂,另有3家自我报告。", f"{c5}.k2", "反向因果")]
    for i, (k, q, a, cid, needle) in enumerate(base, 1):
        qs.append({"id": f"q{i}", "kind": k, "q": q, "a": a, "cards": [cid], "refs": [P(needle)]})
    (w.root / "questions.json").write_text(json.dumps(qs, ensure_ascii=False, indent=1), encoding="utf8")
    (w.root / "orient.json").write_text(json.dumps({"question": "为什么越忙越慢?", "thesis_guess": "满载不等于快", "genre": "argument", "audience": "管理者", "risks": ["流行观点≠作者观点"]}, ensure_ascii=False), encoding="utf8")
