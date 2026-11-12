# 第 2 步:全书综合

目的:把各章笔记**重新组织成全书的论证**。这一步修正第 0 步的假设,并产出读者最先看到的东西。

## 输入
`bk digest -w work`(所有章的作用/一句话/卡片/概念/链接,已压成紧凑清单)。书很大时分批:`bk digest --max-tier 2`,或 `--ch cXX` 查看某章细节。需要核对原文时用 `bk find "词" -w work`。
**读完 digest 再写。不要凭印象补书里没有的东西。**

## 写 `work/synthesis.json`

```json
{
  "one_liner": "一句话:这本书说了什么(给还没读的人)",
  "question": "这本书在回答的问题(修正后的版本)",
  "thesis": "全书的答案/主张,2~3 句,包含它的关键限定",
  "genre": "argument|howto|narrative|science|memoir|reference|mixed",
  "audience": "适合谁读、读它能得到什么",
  "parts": [{"title": "第一部分:诊断", "chapters": ["c02","c03"], "job": "这一部分在全书论证里承担什么"}],
  "pillars": [
    {"id": "P1", "label": "≤14字", "text": "支撑全书主张的第 1 根支柱(一句完整的话)", "chapters": ["c04","c05"]}
  ],
  "attach": {"c04.k1": "P1", "c05.k2": "P2"},
  "chains": [{"name": "自我强化回路", "steps": ["c04.k3","c05.k2","c05.k5"], "loop": true, "note": "可选说明"}],
  "concepts": [
    {"term": "…", "def": "…", "origin": "coined", "intro": "c03", "refs": ["c03:2"], "not": "…", "aliases": []}
  ],
  "misreadings": [{"wrong": "容易被读成……", "right": "书里实际是……", "refs": ["c02:1"]}],
  "reading_plan": {"must": ["c04"], "skim": ["c07"], "skip": [], "why": "按读者目标说明怎么读"}
}
```

### 怎么想
1. **thesis → pillars**:先写全书主张,再问“要让一个怀疑的读者接受它,需要哪 2~5 件事成立?”那就是支柱。支柱是**你对全书论证的重构**,不是章标题的复述;一根支柱往往跨好几章。
2. **attach**:把每章的顶层卡(parent 为 null 的卡)挂到它最支撑的那根支柱。每根支柱必须有卡片挂上来;每张顶层卡都要挂(与主线无关的也要挂到最近的一根——旁支同样是书的一部分)。有 parent 的卡不用挂,它们沿 parent 链自然归属。
3. **chains**:作者明确讲出的因果链/反馈回路(steps 是卡片 id 的先后顺序,loop=true 表示末尾回到开头)。没有就留空数组;不要自己造。
4. **concepts**:合并各章 concepts:同一个词只留一条,写清它第一次出现的章(intro)与最终含义;作者前后用法不同的,在 def 里点明。只收书里的原词。
5. **misreadings**:最重要的一项。列 2~5 条“没读透的人最可能读错的地方”:把被批评的流行观点当成作者观点、忽略后文的自我修正、把经验法则当成定律、混淆作者区分的概念……每条都要有 refs 指向书里的依据。
6. **reading_plan**:哪些章精读、哪些可略读、哪些可跳,各给一句话理由。

### 要回头检查的地方
- 第 0 步的假设有没有被推翻?以读完的结果为准。
- 后面章节对前面说法的修正,是否都在 parent(rel=revises) 或 links 里?没有就补一条 link(type=revises/tension),加进相应章的 notes(`links` 的 `from`/`to` 都可以跨章)。
- thesis 里有没有把书里带限定的话说成了绝对的话?

## 完成标准
`bk check --full -w work` 里 synthesis 相关的错误为 0;每根支柱都有人挂;所有卡片能沿 parent 链走到某个被挂的顶层卡。
