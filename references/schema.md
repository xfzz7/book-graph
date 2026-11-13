# 数据格式

三种文件,都由你写、由 `bg check` 校验。完整样例:`examples/mini/work/`。

## notes/brief.json —— 检视阅读的假设

```json
{
  "question": "这本书在回答什么问题(暂定)",
  "thesis": "作者的回答(暂定)",
  "book_type": "论证型 / 方法型 / 综述型 / 叙事论证混合……一句话",
  "structure": [{"chapters": "c02-c04", "role": "这几章大概承担什么作用"}],
  "watch": ["精读时要留意的问题,例如:某个流行观点是作者赞同的还是要反驳的"]
}
```

不做严格校验;它只通过 `bg context` 回显给后面的精读。

## notes/cNN.json —— 一章的笔记

```json
{
  "chapter": "c03",
  "role": "这一章在全书论证里的作用(≤80 字)",
  "summary": "本章内容的转述概要(2–4 句,≤260 字)",
  "claims": [
    {
      "id": "c03-k1",            // 本章内唯一:<章id>-k<序号>
      "kind": "claim",           // claim | reason | evidence | method | caveat | counter
      "weight": "core",          // core | support | detail
      "text": "一个能独立读懂的完整句子,转述。",
      "refs": ["c03-p012"],      // 本章段落编号,1–3 个为宜
      "quote": "逐字摘自 refs 段落的 4–30 字定位片段",
      "ev": "study"              // 仅 kind=evidence 时必填:study | data | case | anecdote | authority | analogy | reasoning
    }
  ],
  "links": [
    {"from": "c03-k2", "to": "c03-k1", "type": "supports", "note": "可选"}
    // type: supports | causes | requires | refines | rebuts | limits | applies
    // 至少一端是本章命题;另一端可以是已读章节的命题 id
  ],
  "concepts": [
    {"term": "术语", "def": "作者的定义(转述)", "refs": ["c03-p005"],
     "aka": ["别称"], "note": "可选:与某概念的区别 / 本章修订了前文定义"}
  ],
  "skipped": [
    {"from": "c03-p040", "to": "c03-p055", "why": "为什么这一段不记笔记"}
  ]
}
```

(JSON 不支持注释,上面的 `//` 仅为说明。)`links`、`concepts`、`skipped`、`aka`、`note` 都是可选的,没有就省略或写空数组。

## book.json —— 全书综合

```json
{
  "title": "书名", "author": "作者",
  "book_type": "一句话说明书的类型",
  "question": "核心问题(≤80 字)",
  "thesis": "核心论点(≤120 字)",
  "abstract": "一段话摘要(≤400 字)",
  "pillars": [
    {"id": "P1", "title": "短名(≤12 字)", "statement": "这根支柱的完整判断",
     "how": "它如何支撑核心论点", "claims": ["c02-k1", "c05-k3"], "depends_on": []}
  ],
  "thesis_claims": ["c01-k1"],   // 可选:哪些章节命题就是作者对全书论点的直接表述(常在序言/结语)
  "aside": [{"claims": ["c09-k1"], "why": "作者自称的题外话,不承担论证"}],   // 可选:不属于任何支柱的 core 及原因
  "chapters": [
    {"id": "c02", "priority": "must", "why": "理由"}      // must | skim | skip;每个未跳过的章都要有
  ],
  "links": [
    {"from": "c08-k2", "to": "c02-k1", "type": "requires", "note": "跨章关系必须说明理由"}
  ],
  "concepts": [
    {"term": "术语", "aka": [], "def": "最终定义", "refs": ["c02-p008", "c06-p014"],
     "evolution": "可选:定义如何演变", "vs": [{"term": "易混概念", "diff": "区别"}]}
  ],
  "critique": [
    {"type": "gap", "text": "具体的审视", "targets": ["P2", "c05-k4"]}
    // type: gap | assumption | objection | scope | strength;targets: 支柱 id / 命题 id / "thesis"
  ],
  "questions": [
    {"level": "explain", "q": "题目", "a": "参考答案", "claims": ["P1", "c03-k2"]}
    // level: recall | explain | apply | evaluate
  ],
  "takeaways": ["读完可以带走的 2–5 件事"]
}
```

## 校验会查什么

**错误(必须修)**

- JSON 语法;必填字段;枚举值;id 格式与重复;引用的段落/命题/支柱是否存在
- `quote` 是否逐字出现在所引段落里(忽略空白和标点;若出现在本章别的段落会告诉你是哪一段)
- 除 `quote` 外的文字与原文连续 13 字(英文 8 词)相同 → 抄录(比较时忽略标点;已登记在 `concepts` 的术语及别称不计入,所以按原顺序罗列术语不会误报)
- 证据没有 `ev`;章内没有任何 core;支柱建立在 `counter` 上
- 独立核查判为不通过、且文本尚未修改的条目(`--final` 时还要求核查已完成)

**提示(逐条处理:改掉,或确认无碍)**

- 笔记里的数字没有出现在所引段落里
- 一大段连续原文(>30% 且较长)没有任何笔记引用、也没在 `skipped` 里说明
- 笔记过稀/过密(参考范围:每章 max(3, tokens/2400) 到 max(14, tokens/200) 条,中文约每 200–2000 字一条);core 太多
- 定位片段总量超过原书 5%(逐章也会预警)
- `counter` 没有被 `rebuts`;`caveat` 没有 `limits`;证据没连到主张;非主干笔记悬空
- core 没有连到任何支柱;很多章没有进入任何支柱;所有章都标成 must
- 审视只有赞扬;自测题层次单一

未处理的提示数量会如实显示在导读的"可靠性说明"里。不要为了消除提示而删掉正确的内容(例如为了躲数字提示而把数字删掉)——确认无误的提示可以留着。
