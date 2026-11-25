# r152 nl2sql 验收记录

> 结论先说：**SQLite 单机形态与 PostgreSQL 形态都实测通过**（PG 分支由本次 `pytest` 覆盖）；
> 后端全量回归**零失败零错误**，但本机 pytest 进程在收尾阶段会以退出码 1 退出（见 §3.1，环境问题）。

## 1. 改动清单

| 文件 | 改动 |
| --- | --- |
| `backend/app/core/db.py` | 新增 `readonly_connection()` / `readonly_query()`；新增 `NL2SQL_SCHEMA`（审计表）并挂进 `init_db()` 与 `initialize_sqlite()` |
| `backend/app/core/config.py` | 新增 4 个 `nl2sql_*` 配置项 |
| `backend/app/core/repository.py` | 新增 `Nl2SqlView` + `NL2SQL_VIEWS`（8 个逻辑视图）、`NL2SQL_WRAP`、`NL2SQL_FEW_SHOT`、`insert_nl2sql_query()`；SQL 仍只有这一处出口 |
| `backend/app/services/nl2sql.py` | 新文件：五道闸门、生成 / 执行 / 审计（视图规格从 repository 取，本文件零 SQL 字面量） |
| `backend/app/services/taifu/tools.py` | 注册 `query_my_data`；新增 `tool_specs()`（按开关裁剪下发）；`ToolContext` 增加 `client` 注入 |
| `backend/app/services/taifu/graph.py` | `_prepare` 增加 `client` 参数，`build()` 用闭包节点传入；工具表改 `tools.tool_specs()` |
| `backend/app/services/taifu/policy.py` | 提示词的工具清单补 `query_my_data`（原清单是硬编码的，漏了等于模型不知道有这能力） |
| `backend/.env.example` | 补齐 4 个配置项说明 |
| `backend/tests/test_r152_nl2sql.py` | 新增 37 例（参数化后），其中 26 例不依赖数据库 |

## 2. 逐项验证（SQLite 单机模式 + PG，本机实跑）

启动方式：`DB_MODE=sqlite` + 临时 `SQLITE_PATH` + `activate_standalone_sqlite(bootstrap=True)`。

| 验证项 | 结果 |
| --- | --- |
| 按方向聚合（缓存 3 题对 2 / 数据库 2 题对 1） | 期望一致 |
| 另一账号的行是否混入 | 未混入（本账号 5 条，总数查到 5 而非 6） |
| `SELECT * FROM users` | 拒绝：「没有名为 users 的数据表」，审计 `status=rejected` |
| 只读连接执行 `INSERT` | 被拒（`OperationalError`，由 `PRAGMA query_only` 触发） |
| **只读连接是否持 `_WRITER_LOCK`** | `False` |
| 对照组：业务 `connection()` 是否持锁 | `True`（证明观测手法有效，排除了「没测到」） |
| 模型写 `LIMIT 9999` + `NL2SQL_MAX_ROWS=2` | 实际返回 2 行 |
| `NL2SQL_ENABLED=false` | 直接返回未开启，**模型调用 0 次** |
| 工具注册与统一形状 | `query_my_data` 在 `TOOL_NAMES` / `TOOL_SPECS`，返回 `ok/label/summary/href/content` |
| 审计落库 | `status` / `reject_reason` / `row_count` / `user_id` 均正确 |

`check_sql` 纯函数另跑了 15 组手工用例（写语句、多语句、未知表、嵌套子查询里的裸表、
`pg_read_file`、注释、占位符、引号标识符、CTE、UNION 越权），全部按预期拦截或放行。

## 3. 门禁结果

| 项 | 结果 |
| --- | --- |
| `python -m ruff check app tests` | 全绿 |
| `pytest tests/test_r152_nl2sql.py` | **37 passed**（含 PG 分支的只读事务、写拒绝、不持写锁 + 对照组） |
| `pytest tests/test_engineering_gates.py` | **41 passed**（含「SQL 只有 repository 一处出口」） |
| `pytest` 太傅三件套（r77 / r82 / r83） | **79 passed**（改动未破坏既有工具链） |
| `pytest` 全量（1349 例，分 5 批） | **零 FAILED、零 ERROR**；第 5 批 `269 passed` exit=0 |

### 3.1 已知环境现象：全量跑完 exit code 1（非用例失败）

本机（Windows + 宿主文件钩子）跑**全量**时，pytest 打印到 `[100%]` 后就退出，没有 summary 行，
退出码 1，但：

- 进度条里 **0 个 `F`、0 个 `E`**；
- `-rf` / `--durations` 强制输出失败摘要，仍是 **0 条 FAILED / ERROR**；
- 同一批文件单独跑（如第 5 批 16 个文件）→ `269 passed`、exit 0；
- 日志最后一行紧跟着宿主钩子的报错：
  `[safe-delete][SAFE_DELETE_BULK_GUARD_ERROR] EPERM: mkdir .../codebuddy-safe-delete-bulk/...`
- 把 `TEMP` / `TMP` 指到工作区内外都复现，排除「临时目录位置」这一个变量。

判定：**崩溃发生在 pytest 收尾阶段（临时目录清理 / `atexit` 关连接池），与用例结果无关。**
CI 跑在 Linux 上没有这个钩子，以 CI 的 `backend` 门禁为准。

## 4. 仍未验证

1. **真实模型生成的 SQL 质量**：本机全用 `FakeAI` 注入固定 SQL，没有跑真实模型。
   上线后按 `nl2sql_queries` 的 `status=rejected` 占比评估提示词是否需要调。

## 5. 生产验证（2026-11-25 16:34 部署后实测）

`74b46a3` 推送 `dev` → CI 双门禁 success（frontend 63s / backend 504s）→ 自动部署。

| 验证项 | 结果 |
| --- | --- |
| `logs/deploy-state` | `2026-11-25T16:34:12+08:00 74b46a3bd6f9df751aec68521210f466deb9b352`（与推送一致） |
| 容器 | `skillcoach-backend-1` Up healthy |
| `GET /health` | `status=ok` / `db=postgresql` `db_status=up` / `redis_status=up` / `db_replica=ready` |
| 审计表 | `SELECT count(*) FROM nl2sql_queries` → 0 行（表已建出） |
| **PG 只读事务** | `UPDATE questions SET updated_at = updated_at` → **`ReadOnlySqlTransaction`** |
| 只读连接正常查询 | `SELECT count(*) FROM questions` → 1634 |
| 工具注册 | `TOOL_NAMES` 含 `query_my_data` |

> 踩坑留痕：第一次用 `INSERT INTO taifu_memories (...)` 验证写拒绝，报的是
> `UndefinedColumn`（列名写错），那不是「只读生效」的证据 —— 换一条列名确定的
> `UPDATE` 才拿到 `ReadOnlySqlTransaction`。验证「某个约束生效」时，先确认语句本身是合法的。

## 6. 已知遗留

- **没有独立前端入口**：目前只能通过太傅对话触发。`/leap` 的「问一句」入口按
  TECH.md §6 的取舍留作后续。
- **不支持按周 / 月分组**：日期函数两库语义不同，被整体禁掉，只能按区间过滤。
  若确实需要，正确做法是在视图里预先算出 `answered_month` 这类文本列，而不是放开函数白名单。
- **`nl2sql_queries` 没有清理策略**：与其他审计表（`ai_call_logs`）同口径，暂不设 TTL。
- **输出侧 PII 脱敏未接入**：现有视图的列都来自题库 / 计数，不含用户 PII；
  若将来放开 `mirror_cards.question` 这类自由文本进结果，需接 `guardrails.guard_output`。
