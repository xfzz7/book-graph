# 全书综合:`work/synthesis.json`

输入是 `bg digest` 的汇编(所有章节笔记)。你的任务是站在全书高度回答:**这本书到底在说什么、怎么一步步说成的、读者最需要抓住什么、最容易在哪里读错、哪里值得怀疑。**

## 格式

```json
{
  "title": "书名", "author": "作者", "lang": "zh",
  "one_liner": "一句话说清这本书(问题 + 回答,30–60 字)",
  "question": "全书的核心问题(一句问句)",
  "answer": "作者的回答(2–4 句)",
  "why_read": "为什么值得读:它挑战了什么常见看法,或提供了什么别处没有的东西",
  "key_ideas": [
    {"id": "K1", "title": "≤12 字短标题", "text": "一两句完整表述",
     "because": ["c3.2", "c4.1"], "evidence": ["c3.5"]}
  ],
  "storyline": [
    {"step": "论证的一步,一句话", "claims": ["c2.1", "c2.3"]}
  ],
  "cross_links": [
    {"from": "c7.2", "to": "c4.3", "rel": "answers", "note": "为什么有这条跨章关系"}
  ],
  "glossary": [
    {"term": "信任折旧", "aliases": ["信任的折旧"], "definition": "…", "distinct_from": "…",
     "chapters": ["c3", "c5"]}
  ],
  "misreadings": [
    {"wrong": "读者容易形成的错误理解", "right": "作者实际的意思", "anchors": ["c1.p3"]}
  ],
  "limits": {
    "author_admits": [{"text": "作者自己承认的局限", "anchors": ["c8.p2"]}],
    "critique": [{"text": "你的独立评估", "type": "evidence"}]
  },
  "reading_paths": [
    {"goal": "只有一小时", "chapters": ["c1", "c4", "c6"], "note": "为什么这样选"}
  ],
  "quiz": [
    {"q": "问题", "type": "why", "answer": "参考答案(一到三句)", "anchors": ["c4.p3"]}
  ]
}
```

## 各部分怎么写

**one_liner / question / answer**:先写 question——书在回答什么问题,往往在序言/第一章明说,有时要你从全书归纳。answer 必须回答这个 question。

**key_ideas(3–7 条)**:读者合上书应记住的东西。每条挂上 `because`(支撑它的主张/机制命题)和 `evidence`(证据/案例命题)。挑不出证据的关键思想,要么不是关键,要么是作者论证的薄弱处——后者写进 `critique`。

**storyline(4–12 步)**:把全书论证串成一条读者能复述的线:从问题出发,经过哪些概念和机制,到达什么结论,再到方案与局限。每步挂命题。好的主线读起来是一个因果/逻辑连续的故事,而不是章节目录的复写。

**cross_links**:章节笔记只有章内关系。现在补上跨章关系:后面的方案回答了前面哪个问题、后面的概念建立在前面哪个概念上、后记的局限限定了哪个结论。只写对理解有帮助的,每条写 `note`。

**glossary**:合并各章 `concepts`。同一概念不同叫法合并成一个词条,其余放 `aliases`(校验器会检查每个章节概念都进了词表)。`distinct_from` 写清和日常含义/相近概念的区别。

**misreadings(至少 2 条,通常 3–6 条)**——帮助"读懂"最有价值的部分。到这些地方找:
- `voice: reported` 的命题:作者转述然后反驳的观点,读者最容易把它当成作者立场;
- 有 `distinct_from` 的概念:按字面或日常含义理解就会错;
- 反直觉的结论:读者会按常识"脑补"成相反的意思;
- 作者有明确适用范围的结论:读者容易过度推广。
`wrong` 要写成一个读者真会产生的具体误解,不是稻草人。

**limits**:`author_admits` 只写作者自己说的(带锚点)。`critique` 是你的独立评估,页面上会醒目标为"导读者的评估";写 2–5 条,`type` 取 `evidence`(证据是否撑得起结论)、`logic`(推理跳步)、`scope`(能推广到哪)、`assumption`(隐含前提)、`alternative`(作者没排除的其他解释)。必须具体、公道,指向书中具体的论证;不要编造外部事实或数据,不确定就说"书中没有提供……"。

**reading_paths(2–3 条)**:按读者目标给章节组合,例如"一小时抓核心""想动手用""想评估它对不对"。

**quiz(8–15 题)**:检验的是理解,不是记忆。题型 `type`:
- `recall` 关键事实/数字(不超过总数 1/4)
- `concept` 用自己的话解释一个概念,或区分两个概念
- `why` 作者为什么认为 X(考机制)
- `connect` 把两章的内容联系起来(考主线)
- `apply` 给一个书里没有的新情境,按作者的理论推断/给建议(至少 2 题)
- `misread` 判断一个常见说法是否符合作者观点
每题的 `answer` 要能被 `anchors` 指向的段落支撑;`apply` 题的锚点指向它所依据的原理。

## 自查

- [ ] answer 回答了 question;key_ideas 与 storyline 覆盖了所有非附属章节(check 会提示漏掉的章)
- [ ] 每条 misreading 都对应书中一个真实的反驳、区分或限定
- [ ] critique 里没有任何未在书中出现、也无法从书中推出的"事实"
- [ ] quiz 至少两类高阶题(why/connect/apply/misread),apply 题情境是书里没有的
