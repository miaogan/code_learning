# r98 数据层迁移：PostgreSQL + Redis

从「SQLite 单文件 + 进程内限流」换成「PostgreSQL 权威主库 + Redis 共享层」的完整操作手册。
面向已经跑着 r97 及更早版本、需要把线上数据搬过来的场景；全新部署只需 §2 之后的部分。

> **当前数据层不止 PostgreSQL**：r98 之后又加了 **SQLite 完整副本兜底**——PG 正常时逐笔镜像，
> PG 故障时副本接管读写并把离线操作记进 `_offline_operations`，PG 恢复后重放并回切。
> 副本不是缓存，卷 `skillcoach-sqlite` 不能随手删；运行期只允许**单进程单 worker**（见 §7）。

---

## 1. 为什么要换

| 维度 | SQLite（r97 及之前） | PostgreSQL（r98） |
|---|---|---|
| 并发写 | 单写锁，`busy_timeout` 重试 | 行级锁 + MVCC；但兜底副本仍要求单写进程 |
| 多副本 | 不可能（单文件被单进程独占） | PG 侧天然支持；**应用侧暂限单 worker**（副本与内存缓存是进程本地状态） |
| 备份 | `Connection.backup` 拷页面 | `pg_dump` 一致性逻辑备份，可单表恢复；副本卷另行备份 |
| 全文检索 | FTS5 虚表（编译期能力，缺则降级 LIKE） | `pg_trgm` + GIN，恒可用且更快 |
| 类型 | 动态类型（`'1'` 与 `1` 混用不报错） | 强类型，脏数据在写入时就暴露 |

Redis 承担四件事，共同点是「**多副本必须共享、丢了能重建**」：

1. **限流窗口**（`services/rate_limit.py`）——不共享时，N 个副本各放 N 倍流量，压测单副本永远看不出；
2. **会话缓存**（`repository.get_session`）——扛住一次页面加载的几十个并发请求；
3. **业务读缓存**（报告 / 画像）——写少读多的整份产物，写操作即刻按前缀失效；
4. **分布式锁**（`redis_cache.lock`）——后台任务防多副本重复执行。

---

## 2. 本地开发

```bash
# 起依赖（PG 映射到宿主 5433、Redis 6380）
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis

# 后端
cd backend
cp .env.example .env          # 若还没有
# 确认 .env 里：
#   DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5433/sc_app  ← 注意端口 5433
#   REDIS_URL=redis://127.0.0.1:6380/0                                ← 注意端口 6380
uvicorn app.main:app --reload --port 8000
```

> **必须带 `-f docker-compose.dev.yml`**：主 compose 按生产口径不发布任何 PG / Redis 端口，
> 少了这个覆盖文件，宿主的 `uvicorn` / `pytest` / 迁移脚本全都连不进去（报 `Connection refused`）。
> 覆盖文件只加 `ports`，其余定义与主 compose 完全一致。

> 开发时把 compose 的 PG 映射改到 5433、Redis 改到 6380 是刻意的：很多机器上 5432 已被
> 本机 PostgreSQL 占用，撞端口会连到**别的库**上——那种错误看起来像「迁移丢数据」。
> 若你的机器 5432 空闲，直接改回默认端口也可以，只要 `.env` 与 compose 一致。

跑测试（**必须有真实 PG 与 Redis**；依赖故障用例会自行构造不可达场景，并在临时目录建独立 SQLite 副本）：

```bash
cd backend
.venv/Scripts/python -m pytest -q      # Windows
.venv/bin/python -m pytest -q          # macOS / Linux
```

测试基座会自动建 `sc_test` / `sc_test_empty` / `sc_test_legacy` / `sc_test_seed` 四个库。
连不上会直接报错并给出启动命令，**不会静默跳过**。

---

## 3. 从 SQLite 迁移线上数据

### 3.0 先弄清两个卷

r98 起 **PG 用自己的卷 `skillcoach-pgdata`**，r97 的 SQLite 卷 `skillcoach-data` 原样保留、
不再被任何容器挂载。这不是洁癖，是必须——PG 的 `initdb` 只接受空目录，复用旧卷会直接报：

```
initdb: error: directory "/var/lib/postgresql/data" exists but is not empty
```

（本机实测踩到过；同理，`docker volume rm` 旧卷之前先确认 §3.1 的备份已经拷出来。）

**改卷名 ≠ 换卷**——这是最隐蔽的一步。`docker compose up -d` 是幂等的，但它的「要不要重建容器」
只比较镜像 / 命令 / 环境变量 / 端口这类字段，**卷挂载的变化不在其列**：compose 文件里把
`skillcoach-data` 改成 `skillcoach-pgdata` 之后，已存在的容器**不会**被重建，仍然挂在旧卷上，
于是日志里无限刷同一句 `initdb: ... exists but is not empty`，`docker compose ps` 一直 `Restarting`。
改完卷名必须显式重建，并核验挂载：

```bash
docker compose up -d --force-recreate postgres
docker inspect $(docker compose ps -q postgres) \
  --format '{{range .Mounts}}{{.Name}} -> {{.Destination}}{{"\n"}}{{end}}'
# 期望：code_learning_skillcoach-pgdata -> /var/lib/postgresql/data
```

（同源坑还有 nginx 缓存的 `backend` IP：容器重建后 502，需 `--force-recreate frontend`，见 §6。）

### 3.1 迁移前：把 app.db 从旧卷里取出来

r98 的 backend 容器**不再挂旧的 `skillcoach-data` 卷**（现在挂的是独立的 `skillcoach-sqlite`），
所以不能再用 `docker cp` 从容器里捞，直接挂卷取：

```bash
# 卷名 = <compose 项目名>_skillcoach-data，本项目 = code_learning_skillcoach-data
docker volume ls | grep skillcoach

docker run --rm \
  -v code_learning_skillcoach-data:/data:ro \
  -v "$PWD/backups:/backups" \
  alpine cp /data/app.db /backups/app-pre-r98.db

# 记录基线行数，迁移后逐表比对
docker run --rm -v "$PWD/backups:/b" alpine sh -c \
  "apk add -q sqlite && sqlite3 /b/app-pre-r98.db \
   \"SELECT 'reports', COUNT(*) FROM reports UNION ALL SELECT 'profiles', COUNT(*) FROM profiles UNION ALL SELECT 'users', COUNT(*) FROM users;\""
```

### 3.2 建新库并迁移

```bash
# 起 PG（数据落在新卷 skillcoach-pgdata，旧卷不参与）
docker compose up -d postgres

# 先建表：让后端跑一次启动流程（或直接调 init_db）
docker compose run --rm backend python -c "from app.core.db import init_db; init_db()"

# 迁移脚本在**容器内**跑：compose 不发布 5432，宿主进程连不进去；
# 脚本与备份目录用只读挂载送进去，连接串用服务名 postgres:5432。
docker compose run --rm \
  -v "$PWD/scripts:/repo/scripts:ro" \
  -v "$PWD/backups:/backups:ro" \
  backend python /repo/scripts/migrate_sqlite_to_pg.py \
    --sqlite /backups/app-pre-r98.db \
    --pg "postgresql://postgres:${POSTGRES_PASSWORD}@postgres:5432/sc_app" \
    --dry-run

# 真迁（幂等，可重跑）——去掉 --dry-run 再来一次
```

脚本会做完这几件事，任何一步不满足都非 0 退出：

- 逐表 `INSERT … ON CONFLICT DO NOTHING`（中途失败重跑即可续上，不覆盖已有行）；
- 只搬两边都有的列（老库缺 `user_id` / `language` / `started_on` 也能迁，落 PG 默认值）；
- **非空列兜底**：老库缺的 `NOT NULL` 无默认列按类型补占位值（如 `display_name=''`），
  有列但值为 `NULL` 的套 `COALESCE` 补列自己的 DEFAULT（如 `role='member'`），并逐列打印；
- **逐行降级**：批次包 `SAVEPOINT`，某行违约只丢该行，末尾按主键点名「哪些行没进去」；
- **复位 `IDENTITY` 序列**（`radar_snapshots` / `radar_assessments` / `radar_runs`）——
  不复位的话，迁移后第一次技术雷达采集必然主键冲突；
- 逐表比对源/目标行数，缺行即失败。

### 3.3 迁移后验收

```bash
docker compose up -d backend

# 1) 行数对得上
docker compose exec postgres psql -U postgres -d sc_app -c \
  "SELECT 'reports' AS t, count(*) FROM reports UNION ALL SELECT 'profiles', count(*) FROM profiles;"

# 2) 老账号能登录、能看到历史报告
curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"<老账号>","password":"<口令>"}' -c /tmp/c.txt
curl -s http://127.0.0.1:8080/api/reports/latest -b /tmp/c.txt | head -c 300

# 3) 题库检索有结果（trigram 索引生效）
curl -s -X POST http://127.0.0.1:8080/api/search/questions \
  -H 'Content-Type: application/json' -d '{"query":"闭包","limit":3}' -b /tmp/c.txt
```

**验收必须真登录一次**：会话 token 摘要存在 `sessions` 表里，只比对行数看不出
「token 能验签但查不到会话」这类问题。

---

## 4. Redis 的降级语义（务必知道）

| 情况 | 行为 |
|---|---|
| `REDIS_URL` 为空或 `memory://` | 限流回落进程内窗口；JSON 缓存走进程内 TTL+LRU 副本；锁按单进程语义放行 |
| 运行期连不上 | 记一次 WARNING；**新值/删除都落在进程内副本并标记待同步**，30 秒后再探活，不把 503 抛给用户 |
| 重连成功 | 先回放「前缀失效 → 精确删除 → 新值」，再公开 `up`；回放前健康检查不报 up |
| 生产档 `REDIS_URL` 为空 | **拒绝启动**（多个进程各自计数会让限流形同虚设） |
| 生产档 `REDIS_URL=memory://` | 能启动，但会打 WARNING（明确表示「我是单进程」） |

**Redis 挂了不会 503**，这是刻意的：它只是加速与跨进程一致层，数据真值在 PostgreSQL 或副本。
两个必须知道的边界：

- **删除屏障不能提前失效**：断线期间删除的会话 key 会一直记在屏障里（包括超过原 TTL），
  直到回放成功才清除；否则 Redis 故障超过一分钟，旧会话会在重连后复活。
- **首次故障请求会多花几秒**：Redis 客户端要等 DNS / socket 超时（实测 ~4s）才判定离线，
  之后 30 秒内直接走内存。这是故障瞬间的一次性成本，不是持续劣化。

如果你希望 Redis 故障时**限流收紧**（宁可错杀），把 `RATE_LIMIT_ENABLED` 与 Redis 健康检查
绑到 nginx 层做，而不是在应用层加 fail-closed —— 那会让一次 Redis 抖动变成全站 429。

### Redis 版本口径

compose 钉 `redis:8-alpine`（实测 **v8.10.3**）。本项目用到的命令只有 ZSET 滑窗、
Lua 脚本（`EVAL` / `redis.call`）、`SET NX EX`、`EXPIRE`、`SCAN`、`DEL`、`PING`，
这些在 7 与 8 上语义一致，**升 8 不需要改任何代码**；选 8 是因为它是当前主线，7 已进入维护期。

换大版本时的自检（不需要迁移数据）：

```bash
docker compose up -d redis                       # 容器 Recreate，内存数据全丢
docker exec code_learning-redis-1 redis-cli INFO server | grep redis_version
docker exec code_learning-redis-1 redis-cli ping
curl -s -o /dev/null -w '%{http_code}\n' -b cookie http://127.0.0.1:8080/api/me
docker exec code_learning-redis-1 redis-cli --scan --pattern 'sc:*'   # 应出现 sc:sess / sc:rl
```

后端**不需要重启**：重连成功后的下一个请求（或下一次健康探活）会先回放离线期间的失效与新值。
真正要留意的只有一处——如果两副本滚动升级，中间会短暂出现「一半连 7、一半连 8」，
共享 key 的结构（ZSET 成员、string 值）在两版之间是兼容的，但**别在此期间改 key 格式**。

### Redis 内存上限（让 allkeys-lru 真正有触发点）

`--maxmemory-policy allkeys-lru` 只在内存触到 `maxmemory` 时才淘汰；
**只写策略不设上限＝策略永不生效**，公网长期运行下缓存可无限涨，最后撞容器/宿主 OOM。
compose 默认 `--maxmemory 128mb`（2C4G 单机口径），按机器规格用 `REDIS_MAXMEMORY`
覆盖（`deploy.env` / 根 `.env` / 宿主 shell 均可）。

```bash
docker compose up -d --force-recreate redis       # 改完 command 必须重建容器
docker exec code_learning-redis-1 redis-cli CONFIG GET maxmemory
docker exec code_learning-redis-1 redis-cli INFO memory | grep -E 'used_memory_human|maxmemory_human|maxmemory_policy'
```

缓存里只有可重建的限流窗口 / 会话 / 读缓存，淘汰命中不会 503，最坏是回源一次数据库。
若 `used_memory` 长期贴着上限且 `evicted_keys` 猛涨，该调大 `REDIS_MAXMEMORY`
或缩短 `READ_CACHE_TTL_S`，**而不是关掉上限**。

---

## 5. 备份与恢复

```bash
# 备份（custom 格式，可单表恢复）
./scripts/backup_db.sh
KEEP=30 DEST=/mnt/backup ./scripts/backup_db.sh

# 恢复整库
docker compose stop backend
docker compose exec -T postgres \
  pg_restore -U postgres -d sc_app --clean --if-exists < backups/app-20261112-200000.dump
docker compose start backend

# 只恢复一张表（custom 格式才支持）
docker compose exec -T postgres \
  pg_restore -U postgres -d sc_app --table=reports --data-only < backups/app-xxx.dump
```

cron（每天 03:10，保留 14 份）：

```cron
10 3 * * * cd /opt/skillcoach && ./scripts/backup_db.sh >> /var/log/sc-backup.log 2>&1
```

**Redis 不需要备份**：里面只有可重建的计数、缓存与短时锁。

### SQLite 副本（`skillcoach-sqlite` 卷）要不要备份

| 时刻 | 是否必须 | 原因 |
|---|---|---|
| PG 正常、`pending=0` | 可选 | 副本可由 `sync_sqlite_from_pg()` 整库重建 |
| PG 故障 / 正在用副本服务 | **必须** | `_offline_operations` 里是尚未进入 PG 的唯一一份写入 |
| 恢复失败（日志反复 `db.recovery.retry`） | **必须** | 重放未完成，重建副本会丢掉离线写 |

```bash
# 0) 确认还有多少未回放的离线写；非 0 时不要重建副本
docker compose exec -T backend python -c "from app.core.db import pending_operations as p; print(len(p()))"

# 1) 停后端再拷：WAL 模式下热拷可能拿到半份数据
docker compose stop backend
docker run --rm -v skillcoach-sqlite:/data -v "$PWD/backups:/backup" alpine \
  sh -c 'cp /data/app-fallback.db /backup/app-fallback-$(date +%Y%m%d-%H%M%S).db'
docker compose start backend
```

恢复副本：停后端 → 把备份文件写回 `/data/app-fallback.db`（同时删掉同目录 `-wal` / `-shm`）→ 启后端。
启动日志出现 `db.recovery.ready` 且 `pending_operations()` 归零，才算重放完成。

---

## 6. 排障

| 现象 | 原因 | 处理 |
|---|---|---|
| 启动即 `PoolTimeout: couldn't get a connection` | PG 没起 / 连接串错 / 端口撞了本机 PG | `docker compose ps postgres`；`psql` 手连一次确认连的是哪个库 |
| `relation "xxx" does not exist` | 没跑 `init_db()` | `docker compose run --rm backend python -c "from app.core.db import init_db; init_db()"` |
| 迁移后第一次雷达采集主键冲突 | 序列没复位 | 重跑迁移脚本（会自动 `setval`），或手工 `setval` |
| 检索无结果但表里有数据 | 查询串含 `%` / `_`（被当通配符） | 属既有语义；需要字面匹配时转义后再传 |
| 多副本下限流仍然是 N 倍 | `REDIS_URL` 没配 / 配成了 `memory://` | 看启动日志 `production.config_warning` |
| 改密后旧设备还能用 | Redis 会话缓存未被清（TTL 60s 内） | 检查 `delete_other_sessions` 是否被调用；缓存 key 前缀为 `sc:sess:*` |
| PG 起不来：`directory "/var/lib/postgresql/data" exists but is not empty` | 复用了 r97 的 SQLite 卷（里面有 `app.db`） | 确认用的是 `skillcoach-pgdata` 卷；旧卷留作备份/回滚，不要删 |
| 明明已经改了 compose 的卷名，PG 还是报上一行的错、无限 `Restarting` | `up -d` 不因卷名变化重建已有容器，容器仍挂在旧卷上 | `docker compose up -d --force-recreate postgres`，再用 `docker inspect` 核 `.Mounts[].Name` |
| `docker compose build` 卡在 pip / npm 下载 | 直连 pypi.org / registry.npmjs.org 掉到几十 kB/s | `PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple NPM_REGISTRY=https://registry.npmmirror.com docker compose build`（两个构建参数默认官方源，不改代码） |
| 前后端都 healthy，但经 nginx 访问 `/health` 是 502 | nginx 启动时解析了一次 `backend` 的 IP，容器重建后 IP 变了，nginx 仍在用旧地址 | `docker compose up -d --force-recreate frontend`（或 `nginx -s reload`） |
| `/health` 里 `db` 字段 | 如实反映当前写库：`postgresql`（主库）或 `sqlite`（完整副本接管） | 长期停在 `sqlite` 说明 PG 没恢复；看 `db.recovery.retry` 与 `docker compose ps postgres` |
| `/health` 里 `db` 是 `postgresql`、`db_status=up`，但 `db_replica=stale` | 主库正常服务，**兜底副本已失效**（磁盘满 / 副本文件损坏 / 卷不可写） | 业务不受影响，但此刻 PG 再挂就没有兜底；查 `db.replica.rebuild_failed`，修好磁盘或删掉坏副本后等下一轮重建 |
| `/health` 返回 503 `DATABASE_UNAVAILABLE` | 既没有可用的 PG，也没有带 `complete` 标记的完整副本；或副本接管期间 SQLite 自身报错 | 先在 PG 可用时启动一次让副本建成；日志里会有 `db.sqlite_fallback.unavailable` 或 `db.sqlite.unavailable` |
| 副本接管时请求 503，日志 `db.sqlite.unavailable` | 副本文件损坏 / 磁盘写满 / 目录不可写（这类错误已统一转成可重试 503，不再是 500） | `df -h` 看卷；确认 `skillcoach-sqlite` 可写；坏文件修复后停后端替换并删掉 `-wal`/`-shm` |
| 停库后业务请求偶发 4s 才返回 | 故障瞬间的一次性 Redis 超时（DNS/socket），之后 30 秒内走内存 | 属预期；持续慢才是问题，检查 `redis.unavailable` 频率 |
| 恢复后 `db.recovery.retry` 反复出现、业务 503 | 回放冲突（唯一键/外键）或 PG 中途又断；只有**回放**失败才 fail-stop，副本重建失败只降级为 `db_replica=stale` | 查 `pending_operations()`、`_offline_operations` 里第一条失败的 SQL，处理冲突后等自动重试 |

---

## 7. 已知边界（本轮没做）

- **没有迁移框架**：仍是 `CREATE TABLE IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS`，
  删列 / 改类型需要手写 SQL 并写进 `memory.md`；
- **没有读写分离**：单实例 PG，读多时先加索引再考虑只读副本；
- **没有连接池指标**：`DB_POOL_MAX_SIZE` 用满时表现为请求变慢，暂无可观测面板；
- **`pg_trgm` 需要超级用户**：托管 PG 常不给，此时 `init_db()` 会记 WARNING 并跳过 GIN 索引，
  功能正常但检索退化为顺序扫描（数据量到十万级才会明显）；
- **Redis 单点**：没有 Sentinel / Cluster；挂了会降级，不会不可用，但限流精度下降。
- **应用侧只能单 worker**：SQLite 副本、离线日志、内存缓存与删除屏障都是进程本地状态。
  多 worker 会让同一次写分叉到两份副本；要横向扩容，得先把「副本 + 协调器」独立成单进程服务。
  当前 compose 已显式写死 `--workers 1`。
- **离线屏障的内存上限让位于正确性**：Redis 长时间不可用且删除量极大时，删除屏障会持续累积
  （这是安全状态，不是泄漏）；正常运行时回放成功即清除。
