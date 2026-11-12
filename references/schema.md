# 数据结构(profile: nonfiction)

顶层字段

| 字段 | 说明 |
|---|---|
| `title / subtitle / author / thesis` | 书名、副题、作者、一句话全书主张 |
| `claimTypes` | 命题类型表,默认 V观点 M机制 F方法 E依据;可增删 |
| `relTypes` | 关系类型表,默认 cause/support/solve/require/oppose/refine;可增删 |
| `chapters` | 章键 → 章标题。**键的顺序就是书中顺序**(跨章距离据此计算) |
| `claims[]` | 命题 |
| `links[]` | 有向关系 |
| `outline[]` | 总览大纲 |

`claims[]` 元素:`id`(唯一)、`h`(≤10 字短标签)、`t`(完整句子,转述)、`ty`(命题类型键)、`ch`(章键)、`basis`(`e` 书中明确 / `x` 外部依据)。

`links[]` 元素:`s` 起点、`t` 终点、`ty` 关系类型键、`basis`(`e` 明确 / `i` 推断)、`note`(一句话说明为什么有这条边)。

`outline[]` 元素:`id/label/sub/color/thesis/chapters[]`;`chapters[]` 元素 `k/title/takeaway/points[]`;`points[]` 元素 `text` 与 `claims`(命题 id 数组)。

校验规则见 `src/bookgraph/schema.py`:错误(必须修)包括未知类型/章节、端点不存在、id 重复、自环、大纲引用不存在的命题;提示(建议修)包括命题未入大纲、孤立命题、重复边、标签过长、句子过短。

扩展:在 `claimTypes` / `relTypes` 里加键即可,页面会自动出现对应图例与筛选(颜色由模板按顺序分配)。
