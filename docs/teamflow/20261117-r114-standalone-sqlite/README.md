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

## 3. 方案：新增单机模式（SQLite 即权威主库）

`DB_MODE` 三档：

| 值 | 语义 |
| --- | --- |
| `auto`（默认） | PG 优先；PG 不可达时由**完整副本**接管。与 r99 行为一致 |
| `sqlite` | 单机模式：完全不碰 PG，SQLite 是权威主库，启动即建表 + 灌种子 |
| `postgres` | 强制 PG，连不上按故障处理并持续重试，不降级 |

`auto` 下**自动**新建单机库要同时满足三条闸门，缺一退回原有 503 语义：

1. `ever_ready == False` —— 本进程从启动到现在一次都没成功连上过 PG（排除运行中抖动）；
2. 已等过 `DB_STANDALONE_GRACE_S`（默认 15s）—— 排除「容器编排里 PG 比 backend 晚几秒就绪」；
3. `standalone_bootstrap_allowed()` —— `SQLITE_PATH` 里没有任何既有数据（排除半同步副本）。

## 4. 改动清单

| 文件 | 改动 |
| --- | --- |
| `backend/app/core/config.py` | 新增 `db_mode`（`auto`/`postgres`/`sqlite`）、`db_standalone_grace_s`；`is_sqlite_mode` 属性做唯一判据；生产档 `REDIS_URL` 空值在单机模式下不再拦启动，改为 WARNING |
| `backend/app/core/db.py` | 新增 `_standalone` 标记、`is_standalone()`、`has_sqlite_data()`、`standalone_bootstrap_allowed()`、`mark_standalone_baseline()`、`activate_standalone_sqlite()`；`activate_sqlite()` 识别 `standalone='1'` 持久标记；单机下关闭 `_offline_operations` 写入；`sync_sqlite_from_pg()` / `refresh_replica()` 单机下 no-op；`reset_runtime()` 复位标记 |
| `backend/app/main.py` | lifespan 分流到 `_bootstrap_standalone()`；`_recover_database` 加 `ever_ready` 与宽限期、单机后只做 5 分钟低频巡检；`_initialize_database` 拆分出 `_seed_business_data(rag_strict=...)`；`_activate_fallback(allow_bootstrap)`；`/health` 补 `db_replica=na` |
| `backend/app/schemas.py` | `db_replica` 注释补齐 `na` 语义（r99 注释承诺过但未实现） |
| `backend/tests/test_db_standalone.py` | 新增 9 项专项测试 |
| `docs/teamflow/20261117-r114-standalone-sqlite/smoke_standalone.py` | 进程级验收脚本（无 PG / 无 Redis / 空目录冷启动） |

**补丁（同批次）**：`app/admin_cli.py` 原来无条件调 `init_db()`（force_pg），单机环境下「建号」会直接失败 —— 而它恰是单机部署最需要的第一个命令。改为按模式分流：单机档接管单机库（空目录则 bootstrap 并打标记），其余档位不变；`_sync_replica()` 在单机下直接返回，不再打印「兜底副本已同步：0 张表、0 行」这种误导信息。

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

**单测**：`pytest tests/test_db_standalone.py` 9/9；`tests/test_dependency_recovery.py` + `tests/test_health.py` 33/33（含两个原本因自动降级而失败的用例，加上宽限期后恢复原有语义）。

## 7. 已知边界

- 单进程单副本：SQLite 是进程本地文件，不能多 worker / 多实例挂载。
- **不会自动切回 PG**：单机库数据只有一份。后来配好 PG 时保持单机 + 每 5 分钟 `db.standalone.postgres_reachable` 告警；迁移走 `scripts/migrate_sqlite_to_pg.py` 并换空数据目录。
- 没有外部备份，需自行备份 `SQLITE_PATH`（连 `-wal` / `-shm`）。
- 单机模式下 `_STANDBY` 巡检首次在进入单机 **300s 后**才发生（先睡再探），避免刚降级就在后台拉一轮注定超时的建连、打出 `psycopg error connecting in 'pool-1'` 噪声。
