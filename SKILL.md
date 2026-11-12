---
name: nonfiction-book-graph
description: 把一本非虚构书(epub/pdf/txt)拆成句子级命题与有向关系,产出「总览导图」和「关系网」两个自包含 HTML,并给出图论报告。当用户要做读书笔记导图、书籍知识图谱、概念关系图、论证链分析时使用。自带 EPUB 分章、JSON 校验与离线渲染脚本,不需要 API key。
---

# 非虚构书 → 总览导图 + 关系网

你(LLM)负责读书和标注,脚本负责校验、算图、出页面。两边只通过一个 `book.json` 交接,所以**不需要任何 API key,也不需要联网**。

- **总览导图**回答「这本书怎么讲」:篇 → 章 → 要点,按作者顺序,无交叉连线。
- **关系网**回答「书里的说法怎么互相作用」:命题为节点,有向、带类型、可查路径。

两者不重复:大纲不要复述关系,关系不要复述章节顺序。

## 0. 依赖与边界

| 项 | 说明 |
|---|---|
| Python | ≥ 3.10 |
| 校验 / 分章 | 只用标准库 |
| 出图 / 报告 | 需要 `networkx`(`pip install networkx`) |
| 不需要 | 任何模型 API、密钥、网络、前端构建 |
| 不做 | 虚构类(人物/时间线/防剧透);PDF 请先转成 txt/epub |

## 1. 文件地图

```
SKILL.md                     本文件(流程 + 硬性规则)
references/
  schema.md                  字段说明(与仓库文档同步)
  book.schema.json           JSON Schema 原文
  methodology.md             标注方法论
  example-book.json          最小可用样例,可直接复制改写
  prompts/01~04.md           四步提示词(抽命题 → 连关系 → 排大纲 → 自检)
scripts/
  extract_epub.py            EPUB → 按章 txt + chapters.json
  validate_book.py           独立校验器(规则与仓库一致)
  build_pages.py             校验 + 图论分析 + 生成两个 HTML
  export_formats.py          md / csv / graphml / obsidian 导出
assets/templates/
  overview.html              总览导图模板(/*DATA*/ 占位)
  network.html               关系网模板(/*DATA*/ 占位)
```

## 2. 工作流(按顺序执行,不要跳步)

### 第 1 步:文本预处理与分章

```bash
python scripts/extract_epub.py book.epub -o work/text
```

产出 `work/text/000_序_….txt`、`001_1_….txt`… 和 `chapters.json`(章键/标题/字数)。**先人工核对** `chapters.json` 的章数与标题,再往下走。

已知坑(务必检查):
- 很多 EPUB 没有 `<h1>`,整本被压成几个大 HTML 块;脚本会按「第X章 / 自序 / 后记」标题行切,切不出来会退回「一个文件一章」并打提示。
- 章标题可能单独一行("第三章")、正文只占下一页,脚本会把下一行短标题并入。
- 页码、页眉、版权页会混进正文,标注时忽略即可,不要为它们建命题。
- **版权**:原书文本只放临时目录,不要写进仓库或交付物;命题必须转述。

### 第 2 步:逐章抽命题

用 `references/prompts/01_extract_claims.md`,把 `{{书名}}`、`{{章}}`、`{{章键}}`、`{{章节文本}}` 替换成实际内容。一次一章,长书不要整本塞进去。

### 第 3 步:建立关系

用 `references/prompts/02_link_relations.md`。先章内、再跨章;跨章边必须写清理由。

### 第 4 步:写大纲

用 `references/prompts/03_outline.md`。结构是 篇 → 章 → 要点,每个要点挂命题 id。

### 第 5 步:自检(必须做)

```bash
python scripts/validate_book.py work/book.json --strict
```

零错误、零提示才算过。再用 `references/prompts/04_review.md` 做语义审查(照抄、方向写反、推断边是否站得住、缺的跨章关系)。

### 第 6 步:出图与报告

```bash
python scripts/build_pages.py work/book.json -o dist      # 两个 HTML
python scripts/build_pages.py work/book.json --report     # 图论报告
python scripts/build_pages.py work/book.json --report --json
```

### 第 7 步:交付

- `dist/{书名}_总览导图.html`
- `dist/{书名}_关系网.html`

两页数据已内联,断网可看、可直接发给别人。**每本书用独立的 `-o` 目录**,否则同名文件会互相覆盖。

需要给别的工具时再导出:

```bash
python scripts/export_formats.py work/book.json --format md       -o export/md
python scripts/export_formats.py work/book.json --format csv      -o export/csv
python scripts/export_formats.py work/book.json --format graphml  -o export/graphml
python scripts/export_formats.py work/book.json --format obsidian -o export/obsidian
```

| 格式 | 产物 | 用途 |
|---|---|---|
| `md` | `{书名}_大纲.md` | XMind / 幕布 / MarkMind |
| `csv` | `nodes.csv` + `edges.csv` | Gephi |
| `graphml` | `{书名}.graphml` | Gephi / yEd / Cytoscape |
| `obsidian` | 每个命题一页 md(frontmatter + `type:: [[链接]]`) | Obsidian + Dataview |

`csv` 是固定文件名、`obsidian` 直接平铺,所以**每本书必须给不同的 `-o`**,否则会互相覆盖或混在一起。

> 如果本机装了 book-graph 仓库的 CLI(`bookgraph`),上述命令都有同义版本:`bookgraph validate|analyze|build|export`。

## 3. 数据契约(一个字都不能猜)

顶层必须有这 7 个键,少一个校验就失败:
`title`、`claimTypes`、`relTypes`、`chapters`、`claims`、`links`、`outline`。

```json
{
  "profile": "nonfiction",
  "title": "书名",
  "subtitle": "",
  "author": "",
  "thesis": "一句话全书主张",
  "claimTypes": {"V": "观点", "M": "机制", "F": "方法", "E": "依据"},
  "relTypes": {"cause": "导致", "support": "支持", "solve": "化解",
               "require": "需要", "oppose": "对立", "refine": "细化"},
  "chapters": {"1": "第一章 ……", "2": "第二章 ……"},
  "claims": [
    {"id": "a1", "h": "短标签", "t": "用自己的话写成的完整句子。", "ty": "V", "ch": "1", "basis": "e"}
  ],
  "links": [
    {"s": "a1", "t": "a2", "ty": "cause", "basis": "e", "note": "为什么有这条边"}
  ],
  "outline": [
    {"id": "P1", "label": "第一篇", "sub": "", "color": "#8a7f6d", "thesis": "",
     "chapters": [
       {"k": "1", "title": "第一章 ……", "takeaway": "",
        "points": [{"text": "要点一句话", "claims": ["a1"]}]}
     ]}
  ]
}
```

| 字段 | 规则 |
|---|---|
| `chapters` | 键 → 章标题;**键的顺序就是书中顺序**,跨章距离据此计算 |
| `claims[].id` | 全书唯一,建议「章前缀 + 序号」(a1、b2) |
| `claims[].h` | ≤ 10 字,图上显示;超了会提示 |
| `claims[].t` | 完整句子,≥ 10 字,转述不抄原文 |
| `claims[].ty` | 必须在 `claimTypes` 里:V 观点 / M 机制 / F 方法 / E 依据 |
| `claims[].ch` | 必须在 `chapters` 里 |
| `claims[].basis` | `e` 书中明确写出 / `x` 作者经历、外部案例 |
| `links[].s/t` | 必须都存在于 claims;不能自环 |
| `links[].ty` | 必须在 `relTypes` 里 |
| `links[].basis` | `e` 书中明确 / `i` 你的推断(页面画虚线,**如实标**) |
| `links[].note` | 一句话说明依据,必写 |
| `outline` | 每条命题至少出现在一个要点里;`k` 必须在 `chapters` 里;`color` 给篇用 |

## 4. 标注硬规则

1. 一个命题 = 一个能独立读懂的完整句子,不是名词短语,一条只说一件事。
2. **一律转述**;与原书连续 15 字以上相同即视为抄录,必须改写。
3. 类型语义:V 主张/判断;M 解释“为什么”的因果或原理;F 可照做的做法;E 案例/数据/亲身经历。
4. 边方向:**从书中先说的指向后说的**,读作「s 作用于 t」。
5. 推断边宁缺毋滥;只有书中只写了单向、但构成反馈回路时,才用 `i` 补反向。
6. 不要为了图连通而硬连;孤立命题比乱连好,但要在大纲里解释它为何存在。

## 5. 质量闸门

交付前逐条确认:

- [ ] `validate_book.py --strict` 零错误、零提示
- [ ] 每章 6–14 条命题;整本量级参考:16 万字 ≈ 100 条(经验值,按信息密度调整)
- [ ] 每条命题都进了某个大纲要点,且没有被大纲引用不存在的 id
- [ ] 推断边占比 < 30%;超过就回去核对原文
- [ ] 没有自环、没有重复边
- [ ] 观点类(V)有支撑:不被 support/refine 指向的 V 要能解释原因
- [ ] 随机抽 5 条命题对照原文,确认是转述而非摘抄

## 6. 常见失败与修复

| 现象 | 原因 | 处理 |
|---|---|---|
| `缺少顶层字段: claimTypes` | 只写了 title/claims/links/outline | 按第 3 节补全 7 个键 |
| `未知章节 '3'` | claims 的 `ch` 不在 `chapters` | 统一章键,别混用“第三章”和“3” |
| `大纲引用了不存在的命题` | 改了 id 没同步 outline | 全局替换 id 后重跑校验 |
| 只切出 1 章 | EPUB 整本在一个文件 / 无标题行 | 手动按章拆 txt,或改用仓库 CLI 前先修文本 |
| 页面打开是空白 | `/*DATA*/` 占位被破坏 | 用本包 `assets/templates` 原模板重出,不要手改 HTML |
| `ModuleNotFoundError: networkx` | 没装依赖 | `pip install networkx` |
| 终端中文乱码 | Windows 控制台编码 | `chcp 65001` 或设 `PYTHONIOENCODING=utf-8` |

## 7. 边界与同步

- 本包模板与规则对齐 **book-graph v0.1.0**。改动 `assets/templates` 或校验规则后,需与仓库 `src/bookgraph/` 同步,否则两边产物会不一致。
- 迭代永远只改 `book.json`,**不要手改生成的 HTML**;改完重跑 `build_pages.py`。
- 导出脚本是仓库 `src/bookgraph/export.py` 的副本,产物与 CLI 一致;需要更多分析维度时再用仓库 CLI。
