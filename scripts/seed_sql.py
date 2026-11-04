"""生成「SQL 与数据库」方向题库的 **staging 素材文件**（canonical 输入）。

本脚本只产出 `docs/question-bank-staging/07-sql.json`；`question_merge`
从该文件 + 存量重建 `app/seed/questions.json`（写完 staging 后跑
`python -m app.services.question_merge --write`）。

约束（与产品闭集一致）：
- 方向 direction = "SQL 与数据库"（rules.DIRECTIONS 已新增）
- 语言 language = ""（无语言方向；rules.LANGUAGES 含 ""）
- 来源 source = "sql"（question_merge.SOURCES 已新增；由 STAGING 文件名决定）
- kind ∈ {single, multiple, judge}（合并批不允许 text；practice / 笔试只认客观题）

选项长度纪律：单选/多选的正确项平均长度不得超过干扰项平均的 3 倍（与
`question_shuffle` 的 `_LENGTH_RATIO_LONG` 门禁一致），本脚本 `validate()` 会硬校验。

幂等：重跑会整体重写该 staging 文件。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGING_PATH = ROOT / "docs" / "question-bank-staging" / "07-sql.json"

JUDGE_OPTIONS = [
    {"key": "A", "text": "正确"},
    {"key": "B", "text": "错误"},
]


def q(
    qid: str,
    kind: str,
    difficulty: str,
    essentiality: str,
    prompt: str,
    options: list[dict],
    answer: list[str],
    explanation: str,
) -> dict:
    return {
        "id": qid,
        "kind": kind,
        "difficulty": difficulty,
        "essentiality": essentiality,
        "language": "",
        "direction": "SQL 与数据库",
        "prompt": prompt,
        "options": options,
        "answer": answer,
        "explanation": explanation,
    }


def opt(*pairs: tuple[str, str]) -> list[dict]:
    return [{"key": k, "text": t} for k, t in pairs]


QUESTIONS: list[dict] = []

# ---- 基础查询与过滤 ----
QUESTIONS += [
    q("sql-select-1", "single", "basic", "must_know",
      "SQL 中用于对查询结果去重的关键字是？",
      opt(("A", "DISTINCT"), ("B", "UNIQUE"), ("C", "GROUP BY"), ("D", "HAVING")),
      ["A"],
      "DISTINCT 对结果行去重；UNIQUE 是建约束用，不是查询去重关键字。"),
    q("sql-select-2", "single", "intermediate", "must_know",
      "SQL 中 UNION 与 UNION ALL 的主要区别是？",
      opt(("A", "UNION 合并后去重，UNION ALL 保留全部含重复"),
          ("B", "UNION 保留重复，UNION ALL 去重"),
          ("C", "两者完全等价、无任何差别"),
          ("D", "UNION 只能用于两张表")),
      ["A"],
      "UNION 会去重（常伴排序开销），UNION ALL 直接拼接保留重复、更快；能用 ALL 时优先 ALL。"),
    q("sql-select-3", "judge", "basic", "must_know",
      "在 SQL 中用 `WHERE col = NULL` 可以正确筛选出 col 为空的记录。",
      JUDGE_OPTIONS, ["B"],
      "NULL 与任何值（含 NULL）用 = 比较结果是 UNKNOWN，WHERE 只保留为真的行，故一行也查不出；判断空值必须用 IS NULL / IS NOT NULL。"),
    q("sql-select-4", "single", "basic", "must_know",
      "ORDER BY 对多个列排序时，排序优先级是？",
      opt(("A", "按列出现的先后顺序"), ("B", "按列名的字母顺序"),
          ("C", "按列的数据类型"), ("D", "随机，不固定")),
      ["A"],
      "先按第一个列排序，第一列相等时再看第二列，依此类推。"),
    q("sql-select-5", "single", "basic", "must_know",
      "LIMIT 10 OFFSET 20 表示？",
      opt(("A", "跳过 20 行，取 10 行"), ("B", "跳过 10 行，取 20 行"),
          ("C", "取第 10 到 20 行"), ("D", "取前 10 行再偏移")),
      ["A"],
      "OFFSET 先跳过指定行数，LIMIT 再取条数；这也是常规分页写法（第 3 页、每页 10）。"),
    q("sql-select-6", "single", "intermediate", "advanced",
      "SELECT 语句的逻辑执行顺序，正确的是？",
      opt(("A", "FROM→WHERE→GROUP BY→HAVING→SELECT→ORDER BY→LIMIT"),
          ("B", "SELECT→FROM→WHERE→GROUP BY→ORDER BY→LIMIT"),
          ("C", "FROM→GROUP BY→WHERE→SELECT→HAVING→LIMIT"),
          ("D", "WHERE→FROM→SELECT→GROUP BY→HAVING→ORDER BY")),
      ["A"],
      "逻辑上先 FROM/WHERE 取行、GROUP BY/HAVING 分组、SELECT 投影、ORDER BY 排序、最后 LIMIT。"),
    q("sql-select-7", "judge", "basic", "must_know",
      "BETWEEN a AND b 是左闭右开区间，不包含端点 b。",
      JUDGE_OPTIONS, ["B"],
      "BETWEEN 是闭区间（两端都含），等价于 >= a AND <= b；对数字和日期都如此。"),
    q("sql-select-8", "single", "basic", "must_know",
      "LIKE 中 `%` 与 `_` 的含义分别是？",
      opt(("A", "% 匹配任意长度，_ 匹配单个字符"),
          ("B", "% 匹配单个字符，_ 匹配任意长度"),
          ("C", "两者都匹配任意长度"),
          ("D", "两者都匹配单个字符")),
      ["A"],
      "% 匹配零或多个字符，_ 匹配恰好一个字符；注意前导通配（如 '%x'）会让索引失效。"),
]

# ---- JOIN 连接 ----
QUESTIONS += [
    q("sql-join-1", "single", "basic", "must_know",
      "INNER JOIN 返回的结果是？",
      opt(("A", "两表中连接条件匹配的行"),
          ("B", "左表全部行、右表不匹配补空"),
          ("C", "右表全部行、左表不匹配补空"),
          ("D", "两表的完整笛卡尔积组合")),
      ["A"],
      "INNER JOIN 只保留两表都能按 ON 条件匹配上的行，不匹配的一律丢弃。"),
    q("sql-join-2", "single", "basic", "must_know",
      "LEFT JOIN 的特点是什么？",
      opt(("A", "保留左表全部行，右表不匹配补 NULL"),
          ("B", "保留右表全部行，左表不匹配补 NULL"),
          ("C", "只保留两表都匹配的行"),
          ("D", "返回两表的笛卡尔积")),
      ["A"],
      "LEFT JOIN 以左表为主，匹配不到右表时右表列填 NULL；RIGHT JOIN 则相反。"),
    q("sql-join-3", "single", "intermediate", "advanced",
      "FULL OUTER JOIN 的语义是？",
      opt(("A", "保留两表全部行，缺失一侧补 NULL"),
          ("B", "只保留两表都有的行"),
          ("C", "只保留左表全部行"),
          ("D", "两表做笛卡尔积")),
      ["A"],
      "FULL OUTER JOIN 同时保留左右表所有行，任一侧缺失都用 NULL 补齐（部分数据库需变通实现）。"),
    q("sql-join-4", "single", "basic", "must_know",
      "CROSS JOIN 产生的结果是？",
      opt(("A", "两表的笛卡尔积（行数相乘）"),
          ("B", "只保留两表匹配的行"),
          ("C", "只保留左表全部行"),
          ("D", "两表按主键合并")),
      ["A"],
      "CROSS JOIN 无连接条件，结果行数 = 左表行数 × 右表行数；大表慎用。"),
    q("sql-join-5", "single", "challenge", "advanced",
      "LEFT JOIN 时把右表的过滤条件写在 WHERE 里，通常会？",
      opt(("A", "把左连接退化成内连接（只留匹配行）"),
          ("B", "结果与写在 ON 里完全一致"),
          ("C", "自动补全右表缺失的行"),
          ("D", "直接报语法错误")),
      ["A"],
      "WHERE 对右表列过滤会剔除 NULL 行，等价于内连接；想保留左表应把条件下推到 ON。"),
    q("sql-join-6", "single", "intermediate", "advanced",
      "自连接（表与自身 JOIN）典型用于？",
      opt(("A", "同一表内行与行的层级/比较（如员工与经理）"),
          ("B", "把两张结构不同的表合并在一起"),
          ("C", "只能用于删除历史数据"),
          ("D", "替代 GROUP BY 做分组")),
      ["A"],
      "给同一表起两个别名做自连接，可表达父子、前后、对比等行间关系。"),
    q("sql-join-7", "single", "intermediate", "advanced",
      "JOIN ... USING(col) 与 ON t1.col = t2.col 的主要区别是？",
      opt(("A", "USING 自动合并同名列且结果只出现一次"),
          ("B", "USING 不支持任何连接"),
          ("C", "二者完全相同、无差异"),
          ("D", "ON 只能用于全连接")),
      ["A"],
      "USING 指定同名列并合并为单列；ON 更灵活，可写任意条件且两列都会保留。"),
]

# ---- 聚合与分组 ----
QUESTIONS += [
    q("sql-agg-1", "single", "basic", "must_know",
      "GROUP BY 的作用是？",
      opt(("A", "把行按列值分组后做聚合"),
          ("B", "对结果整体排序"),
          ("C", "去重整行数据"),
          ("D", "过滤不满足条件的行")),
      ["A"],
      "GROUP BY 按指定列把行分组，再对每组做 COUNT/SUM/AVG 等聚合。"),
    q("sql-agg-2", "single", "intermediate", "must_know",
      "COUNT(*) 与 COUNT(列) 对 NULL 的差异是？",
      opt(("A", "COUNT(*) 计所有行，COUNT(列) 跳过 NULL"),
          ("B", "两者结果永远相同"),
          ("C", "COUNT(列) 会把 NULL 记为 0"),
          ("D", "COUNT(*) 会跳过 NULL 行")),
      ["A"],
      "COUNT(*) 统计行数；COUNT(col) 只统计 col 非 NULL 的行，有 NULL 时两者会不同。"),
    q("sql-agg-3", "single", "intermediate", "must_know",
      "HAVING 的作用是？",
      opt(("A", "对 GROUP BY 后的分组做过滤"),
          ("B", "对原始表逐行过滤每一行"),
          ("C", "对最终结果整体排序输出"),
          ("D", "对最终结果进行去重处理")),
      ["A"],
      "HAVING 作用于分组之后，可对聚合值（如 COUNT(*) > 1）做过滤。"),
    q("sql-agg-4", "judge", "intermediate", "must_know",
      "SUM、AVG 等聚合函数会把 NULL 当作 0 参与计算，所以 AVG 恒等于「总和 ÷ 总行数」。",
      JUDGE_OPTIONS, ["B"],
      "聚合函数直接忽略 NULL：AVG 的分母是非 NULL 行数，不是总行数；NULL 多时平均值会明显偏离「总和÷总行数」。"),
    q("sql-agg-5", "single", "intermediate", "advanced",
      "COUNT(DISTINCT col) 的含义是？",
      opt(("A", "统计 col 去重后的非 NULL 行数"),
          ("B", "统计 col 的总行数"),
          ("C", "统计 col 为 NULL 的行数"),
          ("D", "对 col 求和")),
      ["A"],
      "COUNT(DISTINCT col) 先去重再计数，且忽略 NULL；常用于算 UV/去重用户数。"),
    q("sql-agg-6", "judge", "intermediate", "advanced",
      "查询里有 GROUP BY 时，SELECT 中的非聚合列都应出现在 GROUP BY 中（或经聚合）。",
      JUDGE_OPTIONS, ["A"],
      "否则非聚合列取值不确定（标准 SQL 直接报错，部分数据库宽松但语义不可靠）。"),
]

# ---- 子查询与 CTE ----
QUESTIONS += [
    q("sql-subq-1", "single", "basic", "must_know",
      "WHERE col IN (子查询) 的语义是？",
      opt(("A", "col 等于子查询结果集中任一值"),
          ("B", "col 大于子查询所有值"),
          ("C", "col 必须等于全部值"),
          ("D", "col 与子查询无关系")),
      ["A"],
      "IN 是「属于集合」，col 命中子查询任一值即为真；NOT IN 遇到 NULL 需格外小心。"),
    q("sql-subq-2", "single", "challenge", "advanced",
      "EXISTS 与 IN 相比，通常的优势是？",
      opt(("A", "遇到匹配即可短路，且对 NULL 更安全"),
          ("B", "总是比 IN 更慢"),
          ("C", "只能用于 DELETE"),
          ("D", "结果一定不同")),
      ["A"],
      "EXISTS 只需判断存在即短路，且不像 NOT IN 那样被 NULL 干扰，相关子查询常更稳。"),
    q("sql-subq-3", "single", "intermediate", "advanced",
      "相关子查询（correlated subquery）的特点是？",
      opt(("A", "子查询引用外层查询的列、按外层行逐次执行"),
          ("B", "与外层查询完全独立"),
          ("C", "只能出现在 SELECT 列表"),
          ("D", "必须用 UNION 连接")),
      ["A"],
      "相关子查询依赖外层当前行，可能逐行执行；数据量大时要注意性能。"),
    q("sql-subq-4", "single", "intermediate", "advanced",
      "WITH ... AS (CTE) 的主要作用是？",
      opt(("A", "把复杂查询拆成可读、可复用的临时结果"),
          ("B", "创建一张永久存在的物理表"),
          ("C", "显式开启一个事务"),
          ("D", "为列创建索引")),
      ["A"],
      "CTE 是语句内的命名子查询，提升可读性与复用；部分库可被优化器内联。"),
    q("sql-subq-5", "single", "intermediate", "must_know",
      "标量子查询返回的是？",
      opt(("A", "单行单列的一个值"),
          ("B", "多行多列的结果集"),
          ("C", "一个布尔值"),
          ("D", "一张临时表")),
      ["A"],
      "标量子查询恰返回一行一列，可放在 SELECT/WHERE 中当作一个值使用，多行会报错。"),
    q("sql-subq-6", "single", "challenge", "advanced",
      "递归 CTE（WITH RECURSIVE）常用于？",
      opt(("A", "处理树形/层级结构（如组织架构、BOM）"),
          ("B", "只是简单地做多表连接查询"),
          ("C", "仅用于实现分页功能"),
          ("D", "替代索引来加速查询")),
      ["A"],
      "递归 CTE 先取锚点行，再反复迭代直到不再产生新行，适合层级/树结构遍历。"),
]

# ---- 窗口函数 ----
QUESTIONS += [
    q("sql-window-1", "single", "challenge", "advanced",
      "ROW_NUMBER、RANK、DENSE_RANK 三者的区别是？",
      opt(("A", "ROW_NUMBER 不并列，RANK 并列跳号，DENSE_RANK 并列不跳号"),
          ("B", "ROW_NUMBER 并列跳号，RANK 不并列，DENSE_RANK 并列不跳号"),
          ("C", "ROW_NUMBER 不并列，RANK 并列不跳号，DENSE_RANK 并列跳号"),
          ("D", "三者都并列跳号，仅数值不同")),
      ["A"],
      "举例（值相同）：ROW_NUMBER 给 1,2,3；RANK 给 1,1,3（跳号）；DENSE_RANK 给 1,1,2（不跳号）。"),
    q("sql-window-2", "single", "intermediate", "must_know",
      "OVER(PARTITION BY dept) 的作用是？",
      opt(("A", "按 dept 分组、在每组内做窗口计算"),
          ("B", "按 dept 对结果排序"),
          ("C", "只保留 dept 这一列"),
          ("D", "删除重复的 dept")),
      ["A"],
      "PARTITION BY 把行划成互不影响的窗口，聚合/排名在各自分区内独立计算。"),
    q("sql-window-3", "single", "intermediate", "advanced",
      "SUM(amount) OVER (ORDER BY dt) 会得到？",
      opt(("A", "按日期累计的滚动求和"),
          ("B", "每行都等于总和"),
          ("C", "只返回最后一行"),
          ("D", "对日期求和")),
      ["A"],
      "带 ORDER BY 的窗口聚合默认是累积帧（从首行到当前行），即滚动累计值。"),
    q("sql-window-4", "single", "intermediate", "advanced",
      "LAG/LEAD 窗口函数用于？",
      opt(("A", "取当前行前/后一行的值做对比"),
          ("B", "对行号重新编号"),
          ("C", "计算累计排名"),
          ("D", "对分组求和")),
      ["A"],
      "LAG 取前一行、LEAD 取后一行，常用于同比/环比、相邻差值等分析。"),
    q("sql-window-5", "judge", "challenge", "advanced",
      "窗口函数不能直接写在 WHERE 子句里做过滤，通常要包一层子查询或 CTE。",
      JUDGE_OPTIONS, ["A"],
      "WHERE 在窗口计算之前执行，故需用子查询/CTE 先算出窗口列，再在外层过滤。"),
    q("sql-window-6", "single", "challenge", "advanced",
      "RANK 遇到并列名次后，后续编号的特点是？",
      opt(("A", "并列占位、后续名次跳号（如 1,1,3）"),
          ("B", "并列不占位、后续不跳号（1,1,2）"),
          ("C", "并列后名次归零"),
          ("D", "并列时随机编号")),
      ["A"],
      "RANK 按位次编号并跳号（1,1,3）；不跳号的是 DENSE_RANK（1,1,2）。"),
]

# ---- 索引与执行计划 ----
QUESTIONS += [
    q("sql-index-1", "single", "basic", "must_know",
      "B-tree 索引最擅长的查询是？",
      opt(("A", "等值与范围查询（=、>、BETWEEN、排序）"),
          ("B", "模糊前导通配 LIKE '%x'"),
          ("C", "对列做函数后再比较"),
          ("D", "任意正则匹配")),
      ["A"],
      "B-tree 有序，天然适合等值/范围/排序；前导通配、列上函数会让它失效。"),
    q("sql-index-2", "single", "intermediate", "must_know",
      "联合索引 (a,b,c) 的「最左前缀」意味着？",
      opt(("A", "查询须从 a 开始连续使用才能真正命中索引"),
          ("B", "可跳过 a、直接用 b 和 c 命中"),
          ("C", "任意列顺序都能命中"),
          ("D", "只能查 a 一列")),
      ["A"],
      "联合索引按 a→b→c 有序，要用到索引需从最左列 a 起连续前缀（a、a+b、a+b+c）。"),
    q("sql-index-3", "single", "intermediate", "advanced",
      "覆盖索引（covering index）指的是？",
      opt(("A", "查询所需列全在索引里、无需回表"),
          ("B", "索引覆盖了所有表"),
          ("C", "把整表复制进索引"),
          ("D", "对主键外所有列建索引")),
      ["A"],
      "当 SELECT 的列都被索引包含时可只读索引、免回表，显著提速。"),
    q("sql-index-4", "multiple", "challenge", "advanced",
      "下列哪些写法容易导致索引失效？",
      opt(("A", "对索引列使用函数或计算"),
          ("B", "隐式类型转换（字符串列传数字）"),
          ("C", "前导通配 LIKE '%abc'"),
          ("D", "按索引最左列做等值查询")),
      ["A", "B", "C"],
      "函数/隐式转换/前导通配都会让 B-tree 无法定位；按最左列等值查询恰恰能用上索引。"),
    q("sql-index-5", "single", "challenge", "advanced",
      "聚簇索引与非聚簇索引的主要区别是？",
      opt(("A", "聚簇按索引键决定行物理顺序，非聚簇另存索引项"),
          ("B", "两者存储结构完全一致"),
          ("C", "非聚簇索引不能用于查询"),
          ("D", "聚簇索引只能建在主键之外")),
      ["A"],
      "聚簇索引叶子即数据行（如 InnoDB 主键），非聚簇索引叶子是主键/行指针，通常需回表。"),
    q("sql-index-6", "single", "intermediate", "must_know",
      "EXPLAIN 的主要用途是？",
      opt(("A", "查看查询的执行计划与是否走索引"),
          ("B", "直接执行并修改数据"),
          ("C", "给表加索引"),
          ("D", "统计表行数")),
      ["A"],
      "EXPLAIN 展示访问方式、是否命中索引与估算代价；EXPLAIN ANALYZE 还会真实执行并给耗时。"),
    q("sql-index-7", "judge", "intermediate", "advanced",
      "索引并非越多越好：过多索引会拖慢写入并占用更多存储。",
      JUDGE_OPTIONS, ["A"],
      "每次写入都要维护相关索引，索引越多写放大越重、空间越大；应按查询模式取舍。"),
]

# ---- 事务与锁 ----
QUESTIONS += [
    q("sql-tx-1", "multiple", "intermediate", "must_know",
      "事务 ACID 包含哪些特性？",
      opt(("A", "原子性（Atomicity）"),
          ("B", "一致性（Consistency）"),
          ("C", "隔离性（Isolation）"),
          ("D", "并发性（Concurrency）")),
      ["A", "B", "C"],
      "ACID = 原子性/一致性/隔离性/持久性；带 D 的应是持久性（Durability），并发性不是 ACID 成员。"),
    q("sql-tx-2", "single", "intermediate", "must_know",
      "READ COMMITTED 能防止哪种异常？",
      opt(("A", "脏读（读到未提交数据）"),
          ("B", "幻读（范围出现新行）"),
          ("C", "不可重复读"),
          ("D", "以上都不能防止")),
      ["A"],
      "READ COMMITTED 只读已提交数据，能防脏读；仍可能出现不可重复读与幻读，更强需可重复读/可串行化。"),
    q("sql-tx-3", "single", "intermediate", "advanced",
      "MySQL(InnoDB) 与 PostgreSQL 的默认事务隔离级别分别是？",
      opt(("A", "MySQL 可重复读、PostgreSQL 读已提交"),
          ("B", "两者都是可重复读"),
          ("C", "两者都是读已提交"),
          ("D", "MySQL 读已提交、PostgreSQL 可重复读")),
      ["A"],
      "InnoDB 默认 REPEATABLE READ（配合 MVCC 减少幻读），PostgreSQL 默认 READ COMMITTED。"),
    q("sql-tx-4", "single", "intermediate", "advanced",
      "行级锁相比表级锁的特点是？",
      opt(("A", "锁粒度更细、并发更高但管理开销更大"),
          ("B", "锁粒度更粗、并发更低"),
          ("C", "两者完全相同"),
          ("D", "行锁不需要事务")),
      ["A"],
      "行锁只锁涉及行、并发高，但锁数量多、管理开销大且更易死锁；表锁相反。"),
    q("sql-tx-5", "judge", "challenge", "advanced",
      "两事务以相反顺序加锁同一批资源，可能引发死锁；统一加锁顺序有助于避免。",
      JUDGE_OPTIONS, ["A"],
      "交叉等待会形成环导致死锁；统一加锁顺序、缩短事务可显著降低风险。"),
]

# ---- 范式与设计 ----
QUESTIONS += [
    q("sql-design-1", "single", "intermediate", "advanced",
      "第三范式（3NF）要求消除的是？",
      opt(("A", "非主属性对其它非主属性的传递依赖"),
          ("B", "消除表里所有冗余字段"),
          ("C", "主键的唯一性约束"),
          ("D", "表之间的外键关联")),
      ["A"],
      "1NF 原子列、2NF 消除部分依赖、3NF 消除传递依赖；目的是减少冗余与更新异常。"),
    q("sql-design-2", "single", "basic", "must_know",
      "主键（PRIMARY KEY）与唯一约束（UNIQUE）的区别是？",
      opt(("A", "主键非空且每表一个，唯一约束可多个且允许 NULL"),
          ("B", "主键可多个，唯一约束每表仅一个"),
          ("C", "两者完全等价、可互换使用"),
          ("D", "主键允许 NULL，唯一约束不允许")),
      ["A"],
      "主键唯一且非空、每表仅一个；UNIQUE 可建多个、且通常允许多个 NULL（依数据库而定）。"),
    q("sql-design-3", "judge", "intermediate", "advanced",
      "反范式（适度冗余）是为减少多表连接、提升读取性能的取舍。",
      JUDGE_OPTIONS, ["A"],
      "反范式用冗余换读取性能/简化查询，代价是写入维护与一致性成本，需权衡。"),
]

# ---- 性能优化 ----
QUESTIONS += [
    q("sql-perf-1", "single", "intermediate", "advanced",
      "N+1 查询问题指的是？",
      opt(("A", "先查 1 次列表，再对每行各查 1 次关联数据"),
          ("B", "一次查询返回 1 行"),
          ("C", "总是比 JOIN 更快"),
          ("D", "只发生在写操作中")),
      ["A"],
      "典型于 ORM 懒加载：1 次取列表 + N 次逐条取关联，应改为 JOIN/批量 IN 预取。"),
    q("sql-perf-2", "single", "challenge", "advanced",
      "深分页（LIMIT 100000, 20）性能差，常见的优化是？",
      opt(("A", "用基于游标/上次最大主键的 keyset 分页"),
          ("B", "把 LIMIT 调得更大"),
          ("C", "改用 SELECT *"),
          ("D", "加更多 ORDER BY 列")),
      ["A"],
      "深 OFFSET 需扫描并丢弃大量行；keyset（WHERE id > 上次最大 id LIMIT n）可稳定提速。"),
]


def _length_ratio(item: dict) -> float:
    if item["kind"] == "judge":
        return 1.0
    ans = set(item["answer"])
    right = [len(o["text"]) for o in item["options"] if o["key"] in ans]
    wrong = [len(o["text"]) for o in item["options"] if o["key"] not in ans]
    if not right or not wrong:
        return 1.0
    return (sum(right) / len(right)) / max(1, sum(wrong) / len(wrong))


def to_staging(questions: list[dict]) -> list[dict]:
    """canonical → staging 素材格式（额外带 id 供 export 分类；question_merge 会忽略 id）。"""
    records = []
    for index, item in enumerate(questions, start=1):
        kind = item["kind"]
        if kind == "judge":
            answer = "正确" if item["answer"] == ["A"] else "错误"
            options = JUDGE_OPTIONS
        elif kind == "single":
            answer = item["answer"][0]
            options = item["options"]
        else:  # multiple
            answer = ",".join(item["answer"])
            options = item["options"]
        records.append({
            "n": index,
            "id": item["id"],
            "language": item["language"],
            "direction": item["direction"],
            "kind": kind,
            "difficulty": item["difficulty"],
            "essentiality": item["essentiality"],
            "stem": item["prompt"],
            "options": options,
            "answer": answer,
            "explanation": item["explanation"],
        })
    return records


def validate(questions: list[dict]) -> None:
    seen_ids, seen_prompts = set(), set()
    for item in questions:
        assert item["id"] not in seen_ids, f"重复 id: {item['id']}"
        seen_ids.add(item["id"])
        assert item["prompt"] not in seen_prompts, f"重复 prompt: {item['prompt']}"
        seen_prompts.add(item["prompt"])
        opts, ans = item["options"], item["answer"]
        assert item["kind"] in ("single", "multiple", "judge")
        if item["kind"] == "judge":
            assert opts == JUDGE_OPTIONS, f"{item['id']} 判断题选项文案不符"
            assert ans in (["A"], ["B"]), f"{item['id']} 判断题答案应为 A 或 B"
        else:
            keys = {o["key"] for o in opts}
            assert 2 <= len(opts) <= 6, f"{item['id']} 选项数越界"
            assert set(ans).issubset(keys), f"{item['id']} answer 越出 options: {ans} vs {keys}"
            if item["kind"] == "single":
                assert len(ans) == 1, f"{item['id']} 单选答案应恰 1"
            else:
                assert len(ans) >= 2, f"{item['id']} 多选答案应 ≥2"
        assert item["explanation"].strip(), f"{item['id']} explanation 为空"
        assert item["difficulty"] in ("basic", "intermediate", "challenge")
        assert item["essentiality"] in ("must_know", "advanced", "nice_to_know")
        assert item["language"] == "", f"{item['id']} SQL 题语言必须为空串"
        ratio = _length_ratio(item)
        assert ratio <= 2.9, f"{item['id']} 正确项/干扰项长度比 {ratio:.2f} > 2.9（需平衡选项）"


def main() -> None:
    validate(QUESTIONS)
    records = to_staging(QUESTIONS)
    STAGING_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写出 staging 素材：{STAGING_PATH}")
    print(f"题目数：{len(records)}（下一步请运行 "
          f"`python -m app.services.question_merge --write` 重建 questions.json）")


if __name__ == "__main__":
    main()
