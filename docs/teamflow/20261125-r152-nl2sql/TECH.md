# r152 nl2sql：只读数据问答

## 1. 需求与形态判定

用户问「本项目能不能做 nl2sql 功能」。结论是**能做，但只有一种形态成立**：不是给用户
一个 SQL 编辑器，而是**受控的只读指标查询层** —— 自然语言进，事实计数出，SQL 全程
用户不可见、不可写。

判定依据有两条硬约束，都来自代码而不是猜测。

### 1.1 约束一：全局写锁 + 单进程（决定性）

`core/db.py` 的 `connection()` 在取连接时持有进程级 `_WRITER_LOCK`（第 1098 行），
而 `docker-compose.yml` 写死 `--workers 1`。这意味着：

> nl2sql 生成的查询天然带 JOIN / GROUP BY。一条 3 秒的分析查询若走 `connection()`，
> 这 3 秒内**所有业务请求都在排队** —— 不是变慢，是整个应用卡死。

所以第一件要做的事不是写提示词，是**给数据层开一条不参与那把锁的只读连接**。

### 1.2 约束二：双库方言

PostgreSQL 是权威库，但 `DB_MODE=sqlite` 是受支持的单机形态（r113），内网 / 气隙部署会
走这条。若按 PG 方言生成 SQL，SQLite 形态直接不可用 —— 而内网恰恰最需要这个功能。

## 2. 设计

### 2.1 分层

| 层 | 文件 | 职责 |
| --- | --- | --- |
| 连接层 | `core/db.py::readonly_connection` / `readonly_query` | 只读执行，**不持 `_WRITER_LOCK`**，不进镜像链路 |
| 语义层 | `core/repository.py::NL2SQL_VIEWS` | 逻辑视图 → 物理 SQL 的唯一映射（说明与 SQL 同一对象，不漂移）；`nl2sql.py` 只取别名 |
| 校验层 | `services/nl2sql.py::check_sql` | 纯函数，零 IO，五道闸门 |
| 执行层 | `services/nl2sql.py::query` | 生成 → 校验 → 内联 → 包裹 LIMIT → 执行 → 审计 |
| 工具层 | `services/taifu/tools.py::query_my_data` / `tool_specs` | 只做形状搬运，不复制任何一条规则；按开关裁剪下发的 schema |
| 提示词 | `services/taifu/policy.py::TAIFU_AGENT_SYSTEM` | 工具清单是**硬编码**的，加工具必须同步这里，否则模型不知道有这能力 |
| 审计 | `db.NL2SQL_SCHEMA` / `repository.insert_nl2sql_query` | 一次问答一行，只写不改 |

> 视图定义为什么不在 `services/nl2sql.py`：工程门禁 `test_sql_only_through_repository`
> 扫 `app/` 下**所有** py 文件的字面量（连注释里的 `SELECT ` 都算），要求 SQL 只出现在
> `repository.py` / `db.py`。门禁注释写明「改动相关代码时请不要放宽」，所以把定义搬进
> repository，而不是给 `nl2sql.py` 开例外。

### 2.2 五道闸门（顺序固定）

1. **形状**：去尾分号后必须只剩单条语句、必须以 `SELECT` 开头、≤2000 字符；
2. **标识符**：禁注释（`--` / `/*`）、禁占位符 `?`、禁引号包裹标识符
   —— 后两条是为了让第 3 道的正则在结构上不会漏检；
3. **表名**：`FROM` / `JOIN` 后面的每个标识符必须在 `LOGICAL_VIEWS` 里。白名单是**穷举**的，
   没有「其余默认放行」。子查询会继续往内层找，藏在里面的裸表同样拦得住；
4. **函数与关键字**：函数只允许 `count/sum/avg/min/max/round/coalesce/abs/cast/nullif`；
   写操作 / DDL / `pg_*` 元数据函数另有一遍显式拒绝（冗余，但成本为零）；
5. **行级隔离**：每个逻辑视图内联成 `(SELECT ... WHERE user_id = ?)`，参数由服务端会话填
   （`core.context`），**绝不从模型参数取**。

### 2.3 为什么用「逻辑视图 + 代码内联」而不是数据库 VIEW

数据库 VIEW 要走 DDL，且 `current_setting('app.user_id')` 只存在于 PG，SQLite 需要
每连接注册自定义函数 —— 两套实现、两处漂移。代码内联的等价物只有一份：

- 两库通用（视图模板里只有 `WHERE user_id = ?` 这种最朴素的语法）；
- 越权在物理上不成立：模型看不到裸表，每个表引用都被替换成带过滤的子查询；
- 不新增 DDL，也就不需要 `init_db()` 之外的结构维护。

`user_id` 仍然只作为**参数**传，不做字符串拼接 —— 即使它来自服务端可信上下文。

### 2.4 只读是怎么保证的

| 后端 | 机制 | 作用域 |
| --- | --- | --- |
| PG | `SET TRANSACTION READ ONLY` + `SET LOCAL statement_timeout` | **事务级**，结束自动失效 |
| SQLite | `PRAGMA query_only = ON` + 临时连接（WAL 读读不互斥） | 连接级，用完即关 |

会话级 `SET` 被明确禁止：连接要归还连接池，会话级只读会让**下一个业务事务的写操作失败**。

### 2.5 行数上限

执行前一律包一层 `SELECT * FROM (<生成 SQL>) AS _nl2sql_sub LIMIT N`。模型自己写
`LIMIT 9999` 也只拿到 N 行。回灌模型的行数另由 `NL2SQL_FEED_LINES` 限制，超出的部分只
体现在摘要的「共 N 行」里（避免一次查询吃掉半个上下文窗）。

## 3. 配置项

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `NL2SQL_ENABLED` | `true` | 关掉后不下发工具 schema（`tools.tool_specs()` 裁剪），模型看不到这个能力 |
| `NL2SQL_TIMEOUT_S` | `3.0` | 语句超时；`readonly_connection` 另把上下界硬夹在 0.1–30s |
| `NL2SQL_MAX_ROWS` | `200` | 外层强制 LIMIT |
| `NL2SQL_FEED_LINES` | `12` | 回灌模型的最多行数 |

## 4. 产品口径

与 AGENTS.md 的 JD 闭环一致：**只返回可回溯的事实计数，不产出匹配分 / 百分比 / 掌握度**。
「9 题答对 6 题」是事实；「Redis 掌握度 67%」是编造 —— 后者在提示词的「口径」段
被显式禁止，且没有任何一个视图提供派生的评分类字段。

## 5. 明确不做

- 不给用户 SQL 输入框（用户永远看不到 SQL）；
- 不暴露 `users` / `sessions` / `ai_call_logs` / `documents`（简历正文）/ `rag_chunks`；
- 不允许跨账号聚合（没有 admin 视图）；
- 不做「生成报表存库」—— 那会变成第二个 `report.py`。

## 6. 取舍

| 选择 | 放弃的方案 | 代价 |
| --- | --- | --- |
| 独立只读连接 | 复用 `connection()` | 多一条连接获取路径，需单独测「不持锁」 |
| 逻辑视图白名单 | 给模型看全库 schema | 能力受限于 8 个视图，新需求要加视图 |
| 禁日期函数、时间走字符串比较 | 允许 `date_trunc` / `strftime` | 模型不能按周/月分组，只能按区间过滤 |
| 不建数据库 VIEW | PG 原生 RLS + VIEW | 过滤靠服务端内联，不在数据库层，需靠单测钉住 |
| 只注册进太傅 | 独立页面 + 独立端点 | 暂时没有独立入口（`/leap` 的「问一句」留作后续） |
