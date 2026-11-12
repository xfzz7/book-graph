# 文件格式规范

所有文件都是 UTF-8 JSON。字段与枚举的唯一事实来源是 `scripts/bklib/schema.py`(`tests/test_schema_doc.py` 会核对本页枚举与它一致)。

## 段落 id 与卡片 id
- 章键 `c01`、`c02`……按书中顺序编号(与章标题里的“第几章”不一定一致,序言/附录也占一个键)。
- 段落 id `c03:12` = 第 3 个单元的第 12 段(由 `bk ingest` 生成,**生成后不要重切**,所有 refs 指向它)。
- 卡片 id `c03.k7`,必须属于所在章;同一章分多份笔记文件时接着编号。

## notes/cNN.json (章笔记;长章可拆成 cNN.2.json 等,meta 只写一次)

| 字段 | 说明 |
|---|---|
| `chapter` | 章键 |
| `meta.role` | 本章在全书论证里的任务(≥8 字) |
| `meta.summary` | 本章内容 3~5 句(≥20 字) |
| `meta.takeaway` | 一句话带走 |
| `meta.priority` | `must` 精读 / `normal` / `skim` 可略读 |
| `meta.reading_questions` | 读前问题 1~5 个 |
| `cards[]` | 见下 |
| `concepts[]` | `term`(书里的原词) `def` `origin`(coined/redefined/borrowed) `refs` `anchor` `not`(可选) |
| `links[]` | `from` `to` `type`(causes/depends_on/tension/restates/applies/revises) `note`;两端是卡片 id,可跨章 |

### cards[]
| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | ✓ | `cNN.kM` |
| `text` | ✓ | 自足的完整句子,转述,8~260 字;保留限定语 |
| `label` | ✓ | ≤14 字短标签 |
| `kind` | ✓ | claim 论断 / mechanism 机制 / method 方法 / evidence 证据 / example 案例 / objection 反对意见 / caveat 限定 / aside 题外话 |
| `voice` | ✓ | author 作者主张 / other 他人观点 / hedged 作者存疑 |
| `tier` | ✓ | 1 承重 / 2 重要 / 3 细节 |
| `parent` | ✓(可 null) | 挂在哪张卡下;null = 顶层卡 |
| `rel` | 有 parent 时必填 | supports / explains / illustrates / elaborates / qualifies / objects / rebuts / revises |
| `refs` | ✓ | 1~6 个本章段落 id |
| `anchor` | ✓ | 从 refs 段落逐字摘的短语(建议汉字 6~20 / 英文 3~8 词;校验去掉标点空格后只数字母数字:汉字 4~30 / 英文 12~90,过长报错) |
| `ev` | evidence/example 且 tier≤2 时必填 | `{type, strength, limit}`:type=data/study/case/anecdote/theory/analogy/authority;strength=strong/moderate/weak/illustrative/unclear |
| `waive` | 可选 | 显式豁免的警告:`numbers` `overlap` `copy`;会被独立核对重点审 |

## synthesis.json
`one_liner question thesis genre audience parts[] pillars[] attach{} chains[] concepts[] misreadings[] reading_plan{}`

- `parts[]`: `{title, chapters[], job}`
- `pillars[]`: `{id: "P1", label, text, chapters[]}`,2~8 个
- `attach`: `{顶层卡id: 支柱id}`;有 parent 的卡不用挂
- `chains[]`: `{name, steps[卡id], loop?, note?}`
- `concepts[]`: `{term, def, origin, intro(章键), refs, not?, aliases?}`
- `misreadings[]`: `{wrong, right, refs}`
- `reading_plan`: `{must[], skim[], skip[], why}`

## critique.json
`{verdict, strengths[], items[]}`;item = `{id, type, severity(high/med/low), source(book/outside), target[卡id], refs[], text}`。`source=book` 必须有 refs。

## questions.json
数组;`{id, kind(recall/explain/apply/compare/critique/trap), q, a, cards[], refs[]}`。

## audit/
`batch_NN.md`(`bk audit-plan` 生成)→ `verdicts_NN.json`(核对者写:`[{id, verdict, note, fix?}]`,verdict=ok/overstated/distorted/unsupported/misattributed/too_vague)→ `log.json`(`bk audit-apply` 汇总,带文本哈希:条目改动后会提示重审)。

## 校验规则速查
| 等级 | 规则 |
|---|---|
| E | 缺字段/枚举越界;id 重复或前缀不对;parent 不存在或成环;refs 不存在或不在本章;anchor 不在原文/不在 refs 段落/过长;证据卡缺 ev;章缺笔记或缺 meta;synthesis/critique/questions 缺失或不合规;核对未解决 |
| W | 数字不在引用段落(±1 段);命题与引用段落用词重合率 <0.30(仅同语种);疑似照抄(汉字 16 / 英文 45 字符);tier 1 占比 >40% 或本章无 tier 1;卡片过稀/过密;引用集中在章前半;未挂到支柱的卡 |
| I | 大段无人引用(可能漏读);已豁免的卡 |

## 最小完整例子(第四章的两张卡,出自 evals/canary)
```json
{
  "chapter": "c05",
  "meta": {
    "role": "从时间维度补充满载为何变慢:反馈延迟带来回声成本,并与排队机制合成一个自我强化回路",
    "summary": "……",
    "takeaway": "满载使复盘缺席、反馈变慢,回声成本推高紧急任务,形成越忙越慢的回路。",
    "priority": "must",
    "reading_questions": ["作者说的“回声成本”和一般的返工成本有什么不同?"]
  },
  "cards": [
    {"id": "c05.k1", "text": "决策的后果要隔一段时间才返回决策者,期间更多决策已建立在原判断之上,由此多出来的修复成本,作者称为回声成本。",
     "label": "回声成本", "kind": "claim", "voice": "author", "tier": 1, "parent": null, "rel": null,
     "refs": ["c05:1"], "anchor": "回声成本"},
    {"id": "c05.k3", "text": "作者的“六周法则”称反馈滞后超过六周纠错成本大致翻倍,但这只来自他约三十个咨询项目的经验,没做过严格统计检验。",
     "label": "六周法则", "kind": "evidence", "voice": "author", "tier": 2, "parent": "c05.k1", "rel": "supports",
     "refs": ["c05:3"], "anchor": "六周法则",
     "ev": {"type": "anecdote", "strength": "weak", "limit": "来自作者自己的约三十个项目经验,未做统计检验,作者自称是起点性估计"}}
  ]
}
```
