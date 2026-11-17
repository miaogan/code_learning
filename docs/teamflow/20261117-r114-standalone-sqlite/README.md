# r114 单机模式：没有 PostgreSQL / Redis 也能跑

- 起始：2026-11-17
- 触发：用户在别的环境运行时报「一直警告 数据服务暂不可用，请稍后重试」，追问后确认那台环境**没有 PostgreSQL，也没有 Redis**。
- 结论：**不是兜底坏了，是兜底的设计前提不成立。**

## 1. 根因（先纠正一个误判）

r99 的兜底架构里，SQLite 是 **PG 的完整副本**，接管的硬门禁是库内 `_sync_state.complete='1'`：

```python
# backend/app/core/db.py::activate_sqlite()
if complete is None:
    _STATE["replica_ready"] = False
    raise RuntimeError("SQLite 副本尚未完整同步，拒绝写入")
```

这个标记只能由 PG 同步过程写入。一个从没连上过 PG 的环境永远不会有它，于是：

- `/health` 长期 `degraded`；
- 每个业务请求拿到 `DATABASE_UNAVAILABLE` / 503（文案「数据服务暂时不可用，请稍后重试」）；
- 恢复循环每 30s 打一条 `db.recovery.retry` —— 这就是「一直报警告」。

排查中确认过的事实：生产环境本身兜底正常（`db_replica=ready`，日志 0 次 503）；前端源码与 `dist` 里都**没有**这句文案，nginx 也没有 502/503 `error_page`。所以文案来自后端 503，来源唯一。

## 2. 为什么不是「把激活门禁放开」

放开等于允许「用一份不知道完整不完整的库顶替主库」。生产的 PG 抖动几秒就会触发，结果是：数据写进本地文件、PG 恢复后不切回、形成无法对账的分叉。所以答案是**换一个模式**，而不是松门禁。

## 3. 方案：启动时一次判定，服务与建号共用同一份代码

`db.bootstrap()` 是**唯一入口**，服务启动与 `admin_cli` 都调它 —— 判定必须逐条一致，否则会出现「服务起来了、建号却连不上库」的割裂（上一版的真实 bug）。

| 情况 | 结果 |
|---|---|
| PG 连得上 | **PostgreSQL**（优先，符合默认预期） |
| PG 连不上 + SQLite 有完整副本 | 副本接管，PG 恢复后由守护循环回切 |
| PG 连不上 + SQLite 是单机库 | 单机库（重启后仍认它是权威库） |
| PG 连不上 + SQLite 空库 / 不存在 | 等 `DB_STANDALONE_GRACE_S`（默认 15s）→ 仍不通才**新建**单机库 |
| PG 连不上 + 有数据但无权威标记 | 抛错拒绝，错误里给出「删库重来」或「`DB_MODE=sqlite` 显式声明」两条路 |

同时打印结论（用户明确要求「看得出用了谁」）：

```
[数据层] db.backend.selected backend=sqlite PostgreSQL 不可用且没有既有数据 → 已新建 SQLite 单机库：data/app-fallback.db
[缓存层] Redis 不可用 → 已降级为进程内缓存（恢复后自动切回）
```

`DB_MODE` 保留为**强制覆盖**：`auto`（默认，上表）／`sqlite`（不探测 PG）／`postgres`（连不上就报错，拒绝降级）。

**为什么不继续用「恢复循环里试错」**：那样用户只能看到 503 和每 30s 一条重试告警，看不到「为什么选了 SQLite」；而且每次重试都会重新走一遍探测与降级判定，决策点散在任何一次循环里，无法被断言。收敛到一个函数后，五种情况都能直接测。

## 4. 改动清单

| 文件 | 改动 |
| --- | --- |
| `backend/app/core/config.py` | 新增 `db_mode`（`auto`/`postgres`/`sqlite`）、`db_standalone_grace_s`；`is_sqlite_mode` 属性做唯一判据；生产档 `REDIS_URL` 空值在单机模式下不再拦启动，改为 WARNING |
| `backend/app/core/db.py` | **新增 `bootstrap()`**（服务与 CLI 共用的唯一判定入口，五种情况 + 打印结论）；`_standalone` 标记、`is_standalone()`、`has_sqlite_data()`、`sqlite_marker()`、`standalone_bootstrap_allowed()`、`mark_standalone_baseline()`、`activate_standalone_sqlite()`、`probe_postgresql_quiet()`；`activate_sqlite()` 识别 `standalone='1'` 持久标记；单机下关闭 `_offline_operations` 写入；`sync_sqlite_from_pg()` / `refresh_replica()` 单机下 no-op；`reset_runtime()` 复位标记 |
| `backend/app/main.py` | `_recover_database` 启动时先 `db.bootstrap()`（决策 + 建表 + 种子）再转守护；`_initialize_pg_database()` 只在恢复窗口内补 PG 结构；`_seed_business_data(rag_strict=...)` 区分 RAG 严格度；副本已接管时不再把 `initialized` 打回 False；新增 `_report_cache()` 打印缓存层结论；`/health` 补 `db_replica=na` |
| `backend/app/admin_cli.py` | `_prepare_database()` 改为直接调 `db.bootstrap()` —— 与服务同一套判定；`_sync_replica()` 在单机下直接返回，不再打印「已同步 0 张表」 |
| `backend/app/schemas.py` | `db_replica` 注释补齐 `na` 语义（r99 注释承诺过但未实现） |
| `backend/tests/test_db_standalone.py` | 新增 14 项专项测试（含 auto 自动降级、优先 PG、宽限期、显式覆盖、CLI 建号） |
| `docs/teamflow/20261117-r114-standalone-sqlite/smoke_standalone.py` | 进程级验收脚本（无 PG / 无 Redis / 空目录冷启动） |

## 5. 四个必须一并处理的坑

1. **`_offline_operations` 无限增长**：单机模式没有 PG 可回放，每笔业务写都会附一条永远无法消费的记录。已在 `connection()` 的 SQLite 分支整体关闭。
2. **种子里的 RAG 教程索引会连 embedding 供应商**：无 AI Key 的环境必然失败，会把整个启动拖成不可用。`_seed_business_data(rag_strict=False)` 降级为跳过 + WARNING；PG 档保持原严格语义不变。
3. **`reset_runtime()` 把后端硬编码成 `postgresql`**：单机标记是进程本地状态，不复位会漏到下一轮（测试里表现为副本模式静默停止记日志）。
4. **`production_blockers` 要求 `REDIS_URL` 非空**：单机模式天然单副本，空值等于进程内缓存，不应拦启动。

## 6. 验证

**进程级**（`smoke_standalone.py`，`DB_MODE=auto` + 不可达 DSN + 空目录 + 空 `REDIS_URL`）：

```
[PASS] 进程可服务
[PASS] 业务库为 sqlite
[PASS] db_status=up
[PASS] db_replica=na（没有副本这个概念）
[PASS] redis_status=memory（无 Redis 自动进程内）
[PASS] 整体 status=ok
[PASS] 运行时标记为单机
[PASS] 活动后端为 sqlite
[PASS] 能写入用户
[PASS] 能登录
[PASS] 能读当前用户
[PASS] 能读业务统计 → {"total":1322,...}
[PASS] 题库种子已写入 → 1334 题
[PASS] 离线重放日志不增长 → 0 条
RESULT: ALL PASS
```

**单测**：`pytest tests/test_db_standalone.py` 14/14；`tests/test_dependency_recovery.py` + `tests/test_health.py` 33/33（含两个原本因自动降级而失败的用例，加上宽限期后恢复原有语义）；后端全量 `pytest` 0 failed / 1 skipped。

## 7. 已知边界

- 单进程单副本：SQLite 是进程本地文件，不能多 worker / 多实例挂载。
- **不会自动切回 PG**：单机库数据只有一份。后来配好 PG 时保持单机 + 每 5 分钟 `db.standalone.postgres_reachable` 告警；迁移走 `scripts/migrate_sqlite_to_pg.py` 并换空数据目录。
- 没有外部备份，需自行备份 `SQLITE_PATH`（连 `-wal` / `-shm`）。
- 单机模式下 `_STANDBY` 巡检首次在进入单机 **300s 后**才发生（先睡再探），避免刚降级就在后台拉一轮注定超时的建连、打出 `psycopg error connecting in 'pool-1'` 噪声。

## 8. 收尾修复：主库维护语句不再进镜像日志

把选库收敛到 `db.bootstrap()` 之后，`test_health.py` 的两条用例变红（`status` 由 `ok` 变 `degraded`）。日志只留 `db.replica_stale error=OperationalError`（按约定只记类型不记内容），继续往下挖才发现是两件事叠在一起：

**根因一（真 bug）**：`init_db()` 里的维护语句被当成业务 DML 记进了副本镜像日志。`Connection.execute()` 只要当前后端是 PG 就会 `_record_write()`，于是这三类语句全被塞进 `_pending_sqlite`：

| 语句 | SQLite 的反应 |
|---|---|
| `UPDATE radar_jobs SET updated_at = to_char(now() …)` | 纯 PG 方言 |
| `INSERT INTO _id_allocations … SELECT … ON CONFLICT(kind) DO NOTHING` | **语法不接受**（upsert 不能挂在 `INSERT … SELECT` 上）：`near "DO": syntax error` |

镜像一失败就把 `replica_ready` 打回 False（设计如此：副本已经不可信），于是同一次启动里 `/health` 从 `ok` 掉到 `degraded`，守护循环接着做了一整轮**无谓的副本重建**（实测 1s，期间 `db.recovery.ready` 才补上）。

修法是给维护语句开一个窗口：`db.suppress_mirror()`（新增的 ContextVar `_mirror_suppressed`），`_record_write()` 首行判它。`init_db()` 整段包进去 —— 副本与主库的对齐本来就靠 `sync_sqlite_from_pg()` 整体重建，这些 DDL / 存量收敛 / 游标播种语句逐条重放既没有意义，也不该有。

**根因二（误报口径）**：守护循环把「副本需要重建」和「主库不可达」当成同一件事，都先把 `initialized=False`（修一之后这个误报在正常启动时不再触发，但架构上仍然错）。现在改成**先探活再决定**：

- 探活拿到 PG 应答 → 缺的只是兜底副本 → 不动 `initialized`，让 `/health` 报 `status=ok` + `db_replica=stale`（这正是 §7 契约里 stale 的语义：主库在服务、副本要重建）；
- 探活失败 → 才把状态打到 `recovering` 并交给统一的 `except` 分支按副本接管。

**验证**：`tests/test_health.py` 4/4、`test_db_standalone.py` 14/14、`test_dependency_recovery.py` 29/29；后端全量 `pytest` **0 failed / 1 skipped**；单机冒烟 `smoke_standalone.py` 仍 `RESULT: ALL PASS`（14/14）。

**留给下一个人的教训**：`Connection` 无法区分「业务 DML」与「主库维护」，两者混在同一个出口 —— 凡是写 `init_db()` / 一次性运维脚本里的语句，要么保证 SQLite 也能执行，要么显式 `suppress_mirror()`。判断标准不是「看起来像不像 DDL」，而是「副本重建时会不会自己算对」。

