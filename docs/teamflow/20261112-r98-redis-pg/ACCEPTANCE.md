# r98 验收记录

## 一、自动化验证

### 后端测试

```
cd backend && ./.venv/Scripts/python.exe -m pytest -q
```

| 项目 | 结果 |
|---|---|
| 全量用例 | **902 passed**，0 failed / 0 error（`--collect-only` 计数 902，进度条 100% 无 F/E） |
| 新增 `test_r98_redis.py` | 11 passed（真实 Redis，`redis:8-alpine` = v8.10.3） |
| 新增 `test_r97_production_guard.py` 用例 | +3（`redis_url` 缺失拒启 / `memory://` 放行但告警 / 示例口令告警） |
| `ruff check app tests` | All checks passed |

### 前端

本轮零改动，未跑。

### 最终结果

见本文件末尾「执行快照」。

## 二、逐条验收

| 编号 | 标准 | 结果 |
|---|---|---|
| AC-1 | 24 张表在 PG 全部建成 | ✅ `init_db()` 后 `pg_tables` 计数 24（27 个 `CREATE TABLE` 中 3 个是同名重定义，FTS5 虚表已移除） |
| AC-2 | `init_db()` 幂等 | ✅ `test_init_db_adds_columns_idempotently`（老库升级路径，结构快照逐字不变）+ r98 收尾实测空库连跑两次：**191 列 / 58 索引完全一致** |
| AC-3 | 占位符与 `%` 转义 | ✅ 含 `LIKE '%kw%'` 的检索用例全过（`test_r51_eval_harness`）；新增 `test_r98_pg_dialect.py` 8 项，锁住「`?` 与 `%s` 两条路都通」与「翻译幂等」 |
| AC-4 | 检索语义与旧 LIKE 分支一致 | ✅ `mode == "like"`、`notice == ""`、短查询（2 字）仍能命中 |
| AC-5 | 存量库补列且不重导 | ✅ `test_r11_data_layer` 14 passed（`sc_test_legacy` 库按 r6 DDL 造表） |
| AC-6 | 限流窗口跨进程共享 | ✅ `test_window_counts_across_processes`：limit=3 时第 4 次被拒，返回 1–60 秒重试 |
| AC-7 | 会话缓存命中 + 登出失效 | ✅ 删行后仍可读（证明命中），`delete_session` 后立即读不到 |
| AC-8 | 读缓存按前缀失效 | ✅ `_invalidate_reports()` 同时清掉 `latest` 与按 id 两个 key |
| AC-9 | 分布式锁互斥且异常释放 | ✅ 同锁二次获取返回 False；块内抛异常后仍可再获取 |
| AC-10 | Redis 故障全降级 | ✅ 不可达地址下：缓存当未命中、`window_hit` 返回 None、锁返回 True，均不抛错 |
| AC-11 | 生产档无 `REDIS_URL` 拒启 | ✅ `test_missing_redis_blocks_production_startup` |
| AC-12 | 迁移脚本幂等 + 行数校验 + 序列复位 | ✅ 六场景全部实跑，见下节 |
| AC-13 | 全量测试 + ruff | ✅ 见「执行快照」 |
| AC-14 | CI 能跑通换库后的测试与门禁 | ✅ backend job 自带 PG/Redis service；检索评测改为直连 PG，recall@5 与旧值一致（见第六节） |

## 三、迁移脚本实测

样本库 `backend/.tmp/migrate-src.db`（4 张表：`users` / `documents` / `reports` / `radar_runs`，
其中 `radar_runs` 用 `AUTOINCREMENT` 且已有 1 行，用于验证序列复位；
`users` 是老结构，只有 5 列，用于验证缺列兜底）。

六个场景全部实跑（目标库 `sc_migrate_check`，每轮先 `TRUNCATE ... RESTART IDENTITY CASCADE`）：

**1. 干跑**——只读不写：

```
源库 migrate-src.db：4 张表
  documents: 1 行
  radar_runs: 1 行
  reports: 1 行
  users: 1 行
```

**2. 首次迁移**：

```
  documents: 源 1 行 → 写入 1 行
  radar_runs: 源 1 行 → 写入 1 行
  reports: 源 1 行 → 写入 1 行
  users 缺列补默认值：display_name
  users: 源 1 行 → 写入 1 行
校验行数：
  documents: 源 1 / 目标 1 OK
  radar_runs: 源 1 / 目标 1 OK
  reports: 源 1 / 目标 1 OK
  users: 源 1 / 目标 1 OK
迁移完成，逐表行数均不少于源库。   ← EXIT=0
```

**3. 重跑（幂等）**——四张表全部写入 0 行，不报错，`EXIT=0`：

```
  documents: 源 1 行 → 写入 0 行
    （1 行已在目标库中，按幂等跳过）
```

**4. 序列复位**——迁移后在 PG 里插一条不带 `run_id` 的行：

```
INSERT INTO radar_runs (trigger, started_at) VALUES ('manual','...') RETURNING run_id;
 run_id
--------
      2      ← 不是 1，说明 setval 把序列推到了 MAX+1，不会撞旧 id
```

**5. 空值兜底**——另造一份样本，`users` 有 `display_name` / `role` 两列但值为 `NULL`：

```
  users.display_name：1 行为空，迁移时补默认值
  users.role：1 行为空，迁移时补默认值
→ 落库 display_name=''、role='member'（取列自己的 DEFAULT，不是空串）
```

**6. 单行脏数据**——把一条 `documents.chars` 改成 `'not-a-number'`（SQLite 无类型约束，PG 是 integer）：

```
    整批插入失败（invalid input syntax for type integer: "not-a-number"），降级为逐行重试
  documents: 源 1 行 → 写入 0 行
    1 行因约束失败被跳过
  ...
以下行未能迁移（需人工处理）：
  documents: id='doc-1' ← invalid input syntax for type integer: "not-a-number"
迁移不完整：documents   ← EXIT=1
```

即：脏数据只丢自己那一行、其余三张表照常迁完，末尾按主键点名并返回非 0，
不会留下「看起来成功了」的假象。

## 四、踩到并修掉的问题

| 问题 | 表现 | 修法 |
|---|---|---|
| psycopg3 的 `Connection` 没有 `executemany` | `AttributeError` | 改为 `conn.cursor().executemany(...)` |
| Python `#` 注释混进 SQL 字符串 | `SyntaxError: syntax error at or near "#"` | 改为 SQL 的 `--` 注释 |
| `$n <> ''` 无法推断类型 | `IndeterminateDatatype: could not determine data type of parameter $5` | 占位符标 `::text` |
| 毫秒时间戳溢出 int4 | `NumericValueOutOfRange: integer out of range` | `learn_chapters.updated_at` 改 `BIGINT` + `_ensure_bigint_columns()` 幂等加宽 |
| `rowid` / `max(ctid)` PG 不支持 | 去重语句无法执行 | 改窗口函数按 `(created_at, id)` 排序 |
| 测试并行跑同一测试库 | 大量 error + 极慢（4 分钟跑不到 50%） | 必须独占运行；已写进 DEPLOY.md |
| `tmp_db` 从 `Path` 变 `str` | 4 个用例 `AttributeError` | 改用 PG 语义断言（读 payload 列 / 独立 scratch 目录） |
| 迁移脚本「列取交集」遇 `NOT NULL` 无默认列 | `NotNullViolation: null value in column "display_name"` | 缺列按类型补占位值；有列但值为空的套 `COALESCE` 补列默认值 |
| `information_schema.is_identity` 是 `'YES'/'NO'` 字符串 | `not "NO"` 恒为假 → 兜底逻辑整段失效，报错照旧 | 改判 `!= "YES"` |
| 有 DEFAULT 的非空列被显式传 `NULL` | DEFAULT 只在「不列该列」时生效，显式 `NULL` 照样撞约束 | 非空列一律 `COALESCE`，与有无 DEFAULT 无关 |
| 批量 `executemany` 一行失败拖垮整表 | 整批 aborted，重跑也失败 | 批次包 `SAVEPOINT`，失败降级逐行重试，逐行记跳过 |
| 脚本 stdout 走管道时块缓冲 | 报错汇总先于过程输出，看着像「先报错后干活」 | `sys.stdout.reconfigure(line_buffering=True)` |
| PG 复用 r97 的 `skillcoach-data` 卷 | `initdb: directory exists but is not empty`（卷里躺着 `app.db`），PG 无限重启 | PG 换独立卷 `skillcoach-pgdata`，旧卷保留作迁移来源与回滚 |
| `/health` 里 `db` 仍硬编码 `"sqlite"` | 探活骗人：换库后运维看着还是 sqlite | 改 `db="postgresql"`，并同步 `test_health.py` 断言 |
| nginx 缓存旧 backend IP | 前后端都 healthy，经 8080 访问 `/health` 却 502 | 重建前端容器（`--force-recreate frontend`）；排障表已记 |
| 国内直连 pypi/npm 装依赖 | `docker compose build` 18 分钟没下载完（35 kB/s） | 加 `PIP_INDEX_URL` / `NPM_REGISTRY` 构建参数，换源后 60 秒完成 |

## 五、执行快照

```
$ ./.venv/Scripts/python.exe -m pytest -q
......................................                                   [100%]
902 passed（`--collect-only` 计数；0 failed / 0 error）
（进程退出码 1 来自宿主 safe-delete 钩子在收尾时 EPERM，与用例无关，r93/r97 同样现象）

$ ./.venv/Scripts/python.exe -m ruff check app tests
All checks passed!
```

### 四容器实跑（`docker-compose.yml` + `docker-compose.dev.yml`）

```
$ docker compose ps
code_learning-backend-1   Up (healthy)   8000/tcp
code_learning-frontend-1  Up             0.0.0.0:8080->80/tcp
code_learning-postgres-1  Up (healthy)   0.0.0.0:5433->5432/tcp
code_learning-redis-1     Up (healthy)   0.0.0.0:6380->6379/tcp

$ curl -s http://127.0.0.1:8080/health
{"status":"ok","version":"0.1.0","ai_configured":true,"db":"postgresql",
 "ai_provider":"legacy","ai_model":"deepseek-chat","ai_json_mode":"json_object"}

$ docker exec code_learning-postgres-1 psql -U postgres -d sc_app -tAc \
    "SELECT count(*) FROM pg_tables WHERE schemaname='public';"
24

$ docker exec code_learning-redis-1 redis-cli ping
PONG

$ docker exec code_learning-redis-1 redis-server --version | tail -1
Redis server v=8.10.3 ...（镜像 redis:8-alpine，与 compose 钉的版本一致）
```

真实业务流（建号 → 登录 → 读接口），确认三个 Redis key 与实际流量对得上：

```
$ docker compose exec backend python -m app.admin_cli create-user --email qa@example.com --name QA --mode own
已创建用户：qa@example.com（QA，Key 模式 own）

$ curl -X POST /api/auth/login -d '{"email":"qa@example.com","password":"..."}'
{"id":"9211...","email":"qa@example.com","display_name":"QA","role":"member","key_mode":"own",...}

$ curl -b cookie /api/me
200（同上用户体）

$ docker exec code_learning-redis-1 redis-cli --scan --pattern '*' | head -3
sc:rl:api:172.28.0.1        ← 限流窗口（共享层）
sc:sess:8698e497...         ← 会话缓存
sc:rl:auth:172.28.0.1       ← 登录接口的独立窗口

$ psql -tAc "SELECT id,email,display_name,role FROM users;"
9211...|qa@example.com|QA|member     ← 落的是 PG，不是文件
```

对交付容器再跑一次针对性用例（用的就是这套 compose 起的 PG/Redis）：

```
$ pytest tests/test_r98_redis.py tests/test_health.py tests/test_r11_data_layer.py -q
29 passed
```

### 运维演练：Redis 容器重建

换 Redis 镜像版本必然经历一次容器重建（内存数据全丢），这是升级时最容易出事的一步，
实测这条路径：

```
$ docker compose up -d redis          # 镜像换成 redis:8-alpine，容器 Recreate
$ curl -b cookie /api/me              # → 200，立刻可用
$ redis-cli --scan --pattern '*'      # → sc:sess:8698e497... / sc:rl:api:172.28.0.1 已重建
```

即：**后端不需要重启**，重连成功后在下一个请求里就把会话缓存与限流窗口写回去了；
`test_r98_redis.py` 的 11 项也在同一个 v8.10.3 实例上全过。这正是「Redis 只存可重建状态」
这条设计的实际收益——换版本不需要迁移任何数据。

## 六、CI 环境对齐（r98 补）

r98 把数据层换成 PG 后，`.github/workflows/ci.yml` 的 backend job 仍在裸
`ubuntu-latest` 上跑测试——没有 PG 实例，902 个用例**全部报错**
（每个用例一条 `RuntimeError: 测试需要 PostgreSQL，但连不上 …`，来自
`conftest._ensure_database_exists` 的显式失败，不是静默跳过）。

| 改动 | 说明 |
|---|---|
| backend job 加 `services` | `postgres:16-alpine`（映射 5433）+ `redis:8-alpine`（映射 6380），都带 healthcheck，Actions 自动等待就绪 |
| 显式 DSN | `TEST_DATABASE_URL` / `EVAL_DATABASE_URL` / `REDIS_TEST_URL` 写进 job `env`，不依赖「端口恰好相同」的巧合 |
| 检索评测改直连 PG | `scripts/eval_question_retrieval.py` 原先在**内存 SQLite** 上重建 FTS5 虚表来评测，而 r98 已删除该虚表——门禁评的是一条死代码。改为直连 PG、直接调 `repository.search_questions()` |
| `eval_live.py` 去掉 `DB_PATH` | r98 已删该配置，原代码设置它无效，真跑会连 `backend/.env` 里的开发库（有污染真实数据的风险）。改为同实例独立库 `sc_eval_live_<pid>`，跑完即删 |
| `eval_harness.py --check` 改真只读 | 原实现 `--check` 仍会重写 `docs/eval/REPORT.md`，「本地处理耗时」的微秒抖动会污染 git diff（本次实测 4 微秒 → 3 微秒） |

失败现场（GitHub API 查到的 #112，即 r98 Redis 那次提交）：

```
JOB backend   failure
    FAIL  8 Test
    skipped 9~12  Offline eval / Question retrieval / Reliability / Live eval
JOB frontend  success
```

frontend 绿、backend 只红在 `Test`，且后续四个评测门禁被 skip——与「pytest 连不上库、
每个用例一条 RuntimeError」完全吻合。同一次里 `Dependency audit`（`pip-audit`）**是过的**，
说明失败不是新依赖引入漏洞，纯粹是环境缺服务。

修复后 #113 全绿（4 分 16 秒）：

```
JOB frontend  success   10 步全过（audit / typecheck / lint / test / build / retrieval gate）
JOB backend   success   13 步全过，含
                        step 2  Initialize containers      ← service 生效
                        step 9  Test                       ← 902 项在有 PG 的环境里真跑
                        step 10~13  四个评测门禁（上一轮被 skip 的全部补跑）
                        step 26 Stop containers
```

检索评测从 FTS5 内存库换到真实 PG 后的结果：

```
评测库    : postgresql://postgres@127.0.0.1:5433/sc_eval（题库 1284 道）
样本量 n  : 20（覆盖 8 个方向）
recall@5  : 100.0%（20/20）
检索路径  : like 20/20
```

recall@5 与旧 FTS5 内存库完全一致——**切库没有带来召回回归**，这也顺便证明了
`ILIKE` 单路径与旧双路径在标注集上的等价性。

## 七、未覆盖 / 已知边界

- Let's Encrypt 的证书脚本、nginx 配置都是 r97 的产物，本轮未改，也未重新验证；
- `pg_trgm` 在无超级用户权限的托管 PG 上会被跳过（只记 WARNING），检索退化为顺序扫描；
- 迁移脚本没有「增量同步」能力：切换窗口内 SQLite 侧的新写入不会被带走，**必须停服迁移**；
- 多副本下的真实限流行为没有做压测（本机单实例只能验证「共享同一计数器」这一层）。

## 八、幂等性核对（r98 收尾专项）

用户要求「检查代码和文档的幂等性」。逐层实跑，结论分三类。

### 8.1 确认幂等（实测通过）

| 层 | 验法 | 结果 |
|---|---|---|
| `init_db()` 结构 | 空库连跑两次，比对 `information_schema.columns` 与 `pg_indexes` | 191 列 / 58 索引**逐字一致** |
| 题库种子 | `ensure_seeded()` 连跑两次 + `refresh_from_seed()` 单独跑 | 1284 行不变；`refresh` 改写 **0 行**（库内已与种子逐字段一致时不写 `updated_at`） |
| 迁移脚本 | 首迁 → 重跑 → 插入验证序列 | 重跑四表各写 0 行、`EXIT=0`；新插入拿到 `run_id=2`（序列已复位） |
| 并发入队 | `radar_jobs` 的 active 部分唯一索引 + `IntegrityError` 兜底 | 同技术第二个未终态任务被索引拒绝，`create_job()` 转「返回已有 job_id」而非 500 |
| 读缓存写入 | `SET key value EX ttl` | 覆盖语义天然幂等；`ttl<=0` 时直接不写 |
| 备份脚本 | 按 `YYYYmmdd-HHMMSS` 命名 + 滚动保留 | 重复执行只产生新文件，不覆盖历史备份 |

### 8.2 查出并修掉的问题

| # | 问题 | 影响 | 处理 |
|---|---|---|---|
| 1 | **`to_pg_sql()` 判据过宽**：原为「含 `?` **或** `%` 就翻译」，于是直写 `%s` 的新 SQL 被二次转义成 `%%s`，psycopg 报 `0 placeholders but N parameters` | `db.py` 顶部与 `memory.md` 都写着「新写的 SQL 直接用 `%s`」——**文档教人写必崩的代码** | 判据收紧为「只看有没有 `?`」。两条路都通；额外收益是翻译**变成幂等**（旧判据下翻译两次会得到 `%%%%`，重试/重放路径会踩） |
| 2 | **改卷名不换卷**：`docker compose up -d` 不因 volumes 卷名变化重建容器 | compose 已写对 `skillcoach-pgdata`，容器仍挂旧卷，PG 无限 `Restarting`（本机实际踩到，日志刷 `initdb: ... is not empty`） | 文档补「必须 `--force-recreate` + `docker inspect` 核挂载」；§6 排障表加一行 |
| 3 | **`ARCHITECTURE.md` 完全没跟上 r98**：381 行里 0 处提及 PostgreSQL / Redis，仍写「SQLite（`backend/app.db`）、7 张表」 | 架构文档是新人理解系统的第一入口，比代码注释更该准 | 更新持久化选型、取舍 #3、`config.py` 契约、§3.4 标题与目录树；补「r98 换库的三处语义差异」 |
| 4 | `scripts/backup_db.sh:15` 引用不存在的路径 `20261113-r98-redis-pg` | 按图索骥找不到手册 | 改为 `20261112-r98-redis-pg` |

### 8.3 已知前提（不是 bug，但没写在代码里就会变 bug）

`init_db()` 里有两条**破坏性收敛**，都建立在「单副本 / 单 worker」的前提上：

- `_sweep_stale_radar_jobs()`：把**所有** queued/running 的雷达任务判为 failed（实测：插入 2 条后跑一次 `init_db()`，两条都变 `failed` + 「任务中断，请重新生成」）；
- `_dedupe_running_profile_jobs()`：同 `(user_id, document_id)` 只留最新一条 running，其余判死。

单副本重启时这是正确的兜底（旧进程的 `asyncio` 任务确实死了）。但**多副本滚动升级**时，新副本一启动就会误伤旧副本正在跑的任务；`uvicorn --reload` 下改一行代码也会废掉正在跑的长任务。

当前部署是单进程（`backend/Dockerfile` 的 `CMD` 无 `--workers`），所以成立。已在两处 docstring 写明前提与改法（多副本时关掉启动清扫、只留读路径的 `radar_sweep_stale_jobs` 按 `radar_job_stale_minutes` 超时清扫，或给 `radar_jobs` 加属主列）。

> 补一句口径：r98 引入 Redis 分布式锁是为了「多副本时共享状态」，但**上图这两处尚未多副本安全**。上多副本前必须先处理这里，否则滚动发布会随机失败正在进行的雷达生成与简历画像任务。

### 8.4 本轮验证记录

```
$ pytest -q -p no:randomly
910 passed / 0 failed / 0 error          （含新增 test_r98_pg_dialect.py 8 项）

$ ruff check backend/app backend/tests scripts/
All checks passed!

$ CI #117（提交 da6bd25）
backend  success  13 步全过（Test / 四个评测门禁 / 依赖审计）
frontend success
```

宿主实跑（vcenv 起 uvicorn 连交付容器的 PG + Redis）：`/health` → `db=postgresql`；
登录 → `/api/me` → 题库检索（`闭包` 命中 12 条、`100%` 作为字面量正常命中）全通。
