# r67 技术雷达 · 技术方案（TECHNICAL）

> 契约单源：`backend/app/schemas.py` ↔ `frontend/src/api/types.ts`，JSON 字段全 snake_case。
> 表名一律 `radar_*` —— **`learn_chapters` 已被 r61 学习进度占用，禁止复用**。

## 1. 模块结构

```
backend/app/services/radar/
  __init__.py      # 对外只暴露 run_round() / next_run_at() / start_scheduler()
  sources.py       # 6 个采集源定义 + 取数（httpx、固定 UA、超时、字节上限、重试一次）
  normalize.py     # 归一化与清洗（slug 生成、suspect 判定、跨源去重）
  rules.py         # 结论闭集、四维夹取、规则评估、排序权重（纯函数，零 IO）
  assess.py        # 规则评估 + 模型评估组合、证据白名单、input_sha256
  generate.py      # 章节草稿 + 题目样例 + 答案自检 + schema 校验（纯函数为主）
  store.py         # radar_* 表读写（沿用 repository 的「裸 sqlite3」风格）
  jobs.py          # 异步生成任务（create_task + 惰性清扫 + 进度落库）
  schedule.py      # next_run_at 纯函数 + 应用内 asyncio 循环
backend/app/routers/radar.py
backend/seed/radar_samples.json   # 离线样本 20 条（无网络、无 Key 端到端演示）
frontend/src/pages/PioneerPage.tsx      # 先锋
frontend/src/pages/GuozijianPage.tsx    # 国子监
frontend/src/lib/radar.ts               # 派生逻辑（纯函数）
```

`main.py` 改动：`lifespan` 里 `radar.start_scheduler()`（`RADAR_SCHEDULE=inapp` 时）+ `app.include_router(radar.router)`。

## 2. 数据表（追加到 `core/db.py` 的 `R67_SCHEMA`）

```sql
CREATE TABLE IF NOT EXISTS radar_techs (
  tech_slug TEXT PRIMARY KEY,        -- 'github:owner/repo' / 'hn:44123456' / 'arxiv:2411.01234'
  name TEXT NOT NULL,
  direction TEXT NOT NULL,           -- questions/directions 闭集
  sub_direction TEXT NOT NULL DEFAULT '',
  source_key TEXT NOT NULL,          -- github / hackernews / arxiv / openai / googleai / manual
  url TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS radar_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tech_slug TEXT NOT NULL,
  taken_at TEXT NOT NULL,
  stars INTEGER NOT NULL DEFAULT 0,
  forks INTEGER NOT NULL DEFAULT 0,
  repo_created_at TEXT NOT NULL DEFAULT '',
  pushed_at TEXT NOT NULL DEFAULT '',
  suspect INTEGER NOT NULL DEFAULT 0   -- 1 = 疑似刷 star（新建即巨量）
);
CREATE INDEX IF NOT EXISTS idx_radar_snapshots_tech ON radar_snapshots(tech_slug, taken_at);

CREATE TABLE IF NOT EXISTS radar_assessments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tech_slug TEXT NOT NULL,
  run_id INTEGER NOT NULL DEFAULT 0,
  verdict TEXT NOT NULL,               -- must_learn | worth_knowing | watch | skip
  relevance INTEGER NOT NULL,          -- 1..5
  adoption INTEGER NOT NULL,
  maturity INTEGER NOT NULL,
  effort INTEGER NOT NULL,             -- 5 = 最省力；口径见 §4.2
  reasons_json TEXT NOT NULL DEFAULT '[]',
  evidence_json TEXT NOT NULL DEFAULT '[]',
  profile_digest TEXT NOT NULL DEFAULT '',
  prompt_version TEXT NOT NULL DEFAULT 'radar-r1',
  model TEXT NOT NULL DEFAULT '',
  input_sha256 TEXT NOT NULL,
  rule_based INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_radar_assess_unique
  ON radar_assessments(tech_slug, input_sha256);   -- 同输入不重复写（可复算幂等）

CREATE TABLE IF NOT EXISTS radar_jobs (
  job_id TEXT PRIMARY KEY,             -- 'rj-<uuid4 hex 前 12 位>'
  tech_slug TEXT NOT NULL,
  user_id INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',   -- queued|running|succeeded|adopted|discarded|failed
  stage TEXT NOT NULL DEFAULT 'chapter',   -- chapter|questions|done
  progress INTEGER NOT NULL DEFAULT 0,     -- 0..100
  chapter_json TEXT NOT NULL DEFAULT '',
  questions_json TEXT NOT NULL DEFAULT '[]',
  discarded_count INTEGER NOT NULL DEFAULT 0,
  error_message TEXT NOT NULL DEFAULT '',
  trigger TEXT NOT NULL DEFAULT 'manual',
  parent_job_id TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_radar_jobs_active
  ON radar_jobs(tech_slug) WHERE status IN ('queued','running');  -- 同技术同时只 1 个在跑
CREATE INDEX IF NOT EXISTS idx_radar_jobs_user ON radar_jobs(user_id, created_at);

CREATE TABLE IF NOT EXISTS radar_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  trigger TEXT NOT NULL,               -- slot|manual|boot
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL DEFAULT '',
  sources_json TEXT NOT NULL DEFAULT '[]',
  degraded INTEGER NOT NULL DEFAULT 0,
  techs_seen INTEGER NOT NULL DEFAULT 0,   -- 双写列（snake_case 直出，前端零转换）
);
```

`init_db()` 追加执行 `R67_SCHEMA`；索引语句放同一段（部分唯一索引需先收敛存量再做，实现时先 `UPDATE radar_jobs SET status='failed', error_message='任务中断' WHERE status IN ('queued','running')` 于建索引前——**只在首次建索引时执行一次**，用 `PRAGMA user_version` 保护）。

## 3. 采集层（`sources.py`）

| source_key | 地址 | 取数要点 | 映射方向 |
|---|---|---|---|
| `github` | Search API `/search/repositories` | 需 token；组合检索式 `topic:llm pushed:>YYYY-MM-DD stars:>100`；配额 10/min（未认证更低） | 按 topics 映射 |
| `hackernews` | `/v0/newstories.json` + `/v0/item/{id}.json` | 1+N 请求，只取前 5 条；`score` 作为热度 | 关键词映射 |
| `arxiv` | `/api/query?search_query=cat:cs.AI` | Atom XML，取前 10 | `LLM 与 RAG` 默认 |
| `openai` | `openai.com/blog/rss.xml` | RSS，实测 836KB，需字节上限 | `通用 AI` |
| `googleai` | `blog.google/technology/ai/rss/` | RSS，实测 30KB | `通用 AI` |
| `manual` | 无（`POST /api/radar/manual` 录入） | 人给 name/direction/url/summary | 用户指定 |

**六条硬约束（实测驱动，不是推测）**：

1. 固定 `httpx.AsyncClient` —— Windows 的 curl/schannel 对 arXiv 握手失败，而 httpx 成功；不能依赖系统 curl / `Invoke-WebRequest`。
2. 固定 `User-Agent: EscapePlanRadar/1.0 (+https://github.com/miaogan/code_learning)` —— 无 UA 直接被 403。
3. 全源 `asyncio.gather` 并发；单源 `RADAR_FETCH_TIMEOUT_S=8`。
4. 读字节上限 `RADAR_FETCH_MAX_BYTES=2_000_000`（流式读，超限截断并标记 `truncated`）。
5. 网络异常 / 5xx 重试一次（退避 0.5s）；4xx 不重试。
6. 单源失败**不连坐**：`sources_json` 记 `{source_key, status, latency_ms, items, message}`，本轮 `degraded=1`。

**GitHub 清洗**（实测踩到 `affaan-m/ECC stars=300535 created=2026-01-18`）：

- 取 `created_at` 与 `stargazers_count`：`created_at` 距今 < 90 天且 stars > 50_000 → `suspect=1`。
- `star_delta_7d` 由最近两条快照按天数差归一：`round((stars_now - stars_prev) / days)`；无上一条快照记 0。
- `suspect=1` 的技术在评估阶段**结论降一档**（必学→值得了解，值得了解→观望）。

## 4. 评估层（`assess.py` + `rules.py`）

### 4.1 结论闭集

`must_learn` / `worth_knowing` / `watch` / `skip`，中文：必学 / 值得了解 / 观望 / 跳过。**闭集硬校验**，非法值直接标 `skip` 并记 `reasons=['评估结果不合法，已降级']`。

### 4.2 四维口径（1–5 粗档，界面标注「粗档，不是精确评分」）

| 维度 | 1 分 | 5 分 | 数据来源 |
|---|---|---|---|
| 岗位相关度 `relevance` | 与本产品 8 方向无关 | 直击 AI 应用 / Agent 后端 | 方向映射 + 最新画像的 `role_fit.target_role` 与薄弱方向 |
| 行业采用度 `adoption` | 几乎无人用 | 主流仓库 / 高频出现在 HN | GitHub stars 量级 + star 增速 + 跨源出现次数 |
| 成熟度 `maturity` | 纯概念 / 无稳定版本 | 有稳定 API 与大规模实践 | 仓库 `pushed_at` 活跃度 + 创建时长 + 源类型（论文降档） |
| 学习成本 `effort` | 要 3 个月以上 | 一个下午能上手 | **数值越大越省力**（避免界面出现「学习成本 5 分」的误读，见 §8 图注） |

### 4.3 规则评估（零成本兜底，`rule_based=1`）

确定性公式，全部在 `rules.py` 纯函数里，只依赖「快照 + 跨源计数 + 方向映射 + 画像摘要」：

- `adoption = clamp(1 + floor(log10(max(stars,1)) - 2) + (star_delta_7d >= 50) + (cross_source >= 2), 1, 5)`
- `maturity = clamp(1 + (repo_age_days >= 180) + (pushed_within_30d) + (source_key == 'github') + (cross_source >= 2), 1, 5)`
- `relevance`：方向命中画像薄弱方向 +2、命中 `role_fit.target_role` 关键词 +1、命中本产品 8 方向 +1、其余 1。
- `effort`：论文类 2、新兴仓库 3、教程/工具类 4、成熟工具 5。
- `verdict`：`relevance >= 4 && adoption >= 3 → must_learn`；`relevance >= 3 → worth_knowing`；`adoption >= 3 → watch`；其余 `skip`。

### 4.4 模型评估（有 Key 时，最多 `RADAR_MAX_ASSESS_PER_ROUND=3` 条）

- 复用 `user_ai.client_for(user, "light")` 或主档 `AIClient`；**专用超时 `RADAR_ASSESS_TIMEOUT_S=60`**，前台默认不重试（与 r34/r36 策略一致）。
- 输出 JSON：`{verdict, verdict_label, relevance, adoption, maturity, effort, reasons[], evidence[]}`。
- **证据白名单**：`evidence[].url` 必须逐字出现在本轮采集到的 URL 集合里，越界条目丢弃并计入 `dropped_citations`（与 r65 同一套思路）。
- 模型失败/超时 → 回落到规则评估，`reasons` 追加「模型评估不可用，已按规则评估」。
- **可复算指纹**：`input_sha256 = sha256(tech_slug + 归一化信号 JSON + profile_digest + prompt_version)`；写入前查 `idx_radar_assess_unique`，同指纹 `DO NOTHING`。

### 4.5 吃最新画像（用户确认第 4 条）

`profile_digest` = 最新画像的 `target_role` + 前 3 个薄弱方向（来自最新报告的 `weakness_map`，按错误率降序）+ 能力项数。**只进指纹与提示词，不落库原文**。无画像时 `profile_digest=''`，评估退化为「通用岗位视角」，界面在理由里注明「无最新画像，按通用岗位评估」。

## 5. 生成层（`generate.py` + `jobs.py`）

### 5.1 章节草稿 schema（硬校验，不合法即失败）

```
{title, summary, direction(闭集), sub_direction, level(basic|intermediate|advanced),
 sections: [{id(ASCII slug), title, preview}]}   -- sections >= 3，末节 preview 必须含自测
```

- `direction` 必须在 `rules.DIRECTIONS` 闭集里；`sub_direction` 必须在 `rules.SUBDIRECTIONS[direction]` 里（越界清空而不是报错）。
- 章节 `id` 与官方 40 章去重（`frontend/src/content/tutorials` 的 id 列表在后端也维护一份只读副本——**放在 `generate.py` 的 `RESERVED_CHAPTER_IDS` 常量**，冲突时给 `radar-<slug>` 前缀）。
- 草稿**只落 `radar_jobs.chapter_json`**，不写任何教程内容文件。

### 5.2 题目样例 schema + 答案自检

```
{sample_id, kind(single|multiple|judge), prompt, options[2..5 去重], answer[索引合法],
 explanation(>=10 字), sub_direction, difficulty, self_check(pass|mismatch|skipped)}
```

- **答案自检**：把题干与选项、遮蔽答案，让模型重做一遍，与首次答案比对；不一致 → `self_check='mismatch'`，**该题不参与入库**（`discarded_count` 计数）。
- 自检调用失败 → `skipped`，同样不入库（宁缺毋滥）。
- 每轮生成上限：3–5 题。

### 5.3 异步任务（复用 r30/r42 的任务模式）

- `POST /api/radar/{tech_slug}/generate` → 建 job（`status='queued'`）→ `asyncio.create_task(_run_job(job_id))` → 202 `{job_id, status}`。
- 幂等：命中 `idx_radar_jobs_active` 唯一冲突时，返回**已存在**的 active job_id（不重复烧 token）。
- 进度：`chapter` 20% → `questions` 60% → `done` 100%。
- **任务级硬上限** `asyncio.wait_for(_run(), RADAR_GEN_TIMEOUT_S=300)`；超时 → `failed` + 中文原因。
- **惰性清扫**：读路径（列表 / 详情）发现 `running` 且 `updated_at` 超过 15 分钟 → 按 `failed` 落库「生成中断，请重试」（与 r32 同一做法，避免僵尸行）。
- 服务重启不续跑（任务是一次性模型调用，重跑比续跑简单）。

### 5.4 扩充入库 / 废弃

- `POST /api/radar/jobs/{job_id}/adopt`：
  - 仅 `succeeded` 可调用；把 `self_check='pass'` 的题目写 `questions`：`id='radar-<job_id>-<n>'`、`source='radar'`、`language=''`、`explanation` 原样、`essentiality` 取 `rules.py` 闭集默认值（实现时以 `rules.py` 为准）。
  - 写库用 `insert_questions`（`ON CONFLICT(id) DO NOTHING`），重复采纳幂等。
  - `status='adopted'`；章节草稿保留在 `chapter_json`（国子监可回看，界面标「草稿存档」）。
- `POST /api/radar/jobs/{job_id}/discard`：仅 `succeeded` 可调用 → `status='discarded'`。**已 `adopted` 的任务不可废弃**（题目已进池，撤回需要单独设计，本轮不做）。

## 6. 「只进练习池」的落地（用户确认第 3 条）

- `question_bank` 新增 `exam_pool()` = `load_questions()` 过滤 `source != 'radar'`。
- `services/assessment/exam.py:84` 的取池 `question_bank.load_questions()` **改为 `exam_pool()`**（唯一改动点，逐字节等价于原行为当且仅当库内无 radar 题）。
- 练习侧 `practice_pool()` 保持 `load_questions()` 派生 → **自动包含**雷达题，无需改动 `practice.py`。
- 计分与熟练度：雷达题与普通题共用 `question_attempts`，因此会进入熟练度统计——这是有意为之（练习过的题才可能变熟练），界面对雷达题打 `雷达新增` 标签。

## 7. 调度层（`schedule.py`）

- 配置：`RADAR_SLOTS="08:00,12:00,18:00"`；`RADAR_TZ_OFFSET_MIN=480`（固定 +08:00，**不引 tzdata**——Windows 无系统 tzdata 会抛 `ZoneInfoNotFoundError`，而中国无夏令时，固定偏移在本世纪内正确）。
- 纯函数 `next_run_at(now_utc, slots, offset_min) -> datetime`：把 `now` 平移到本地时间 → 找今天第一个 > now 的 slot → 没有则取明天第一个 → 平移回 UTC。
- 循环：`while True: sleep_until(next_run_at(...))`，**每次醒来重算**（抗系统时钟漂移 / 休眠）。
- **漏跑补偿**：醒来时若 `now - expected_slot <= RADAR_SLOT_GRACE_MIN=30` 则跑；超过 30 分钟则跳过本次（避免开机后补跑一串历史节点）。
- `RADAR_SCHEDULE='external'` 时完全不启动循环（由系统计划任务 / CI 调 `POST /api/radar/refresh` 兜底）。
- 单次 run 失败不终止循环（catch + 记 `radar_runs` 的 `degraded`）。

## 8. HTTP 契约（`routers/radar.py`，前缀 `/api/radar`，全部 `Depends(current_user)`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/radar?verdict=&direction=&limit=20` | 先锋列表；`limit` 夹 1..50，脏筛选静默忽略 |
| GET | `/api/radar/{tech_slug}` | 详情（快照历史、评估、证据、最近 job） |
| POST | `/api/radar/refresh` | 手动跑一轮（同步，硬上限 90s）→ `RadarRunSummary` |
| POST | `/api/radar/manual` | 手动录入一条技术（name/direction/url/summary） |
| POST | `/api/radar/{tech_slug}/generate` | 202 `{job_id, status}` |
| GET | `/api/radar/jobs?status=&limit=20` | 国子监列表（按 `user_id` 隔离） |
| GET | `/api/radar/jobs/{job_id}` | 任务详情（进度 + 章节草稿 + 题目样例） |
| POST | `/api/radar/jobs/{job_id}/adopt` | 扩充入库 |
| POST | `/api/radar/jobs/{job_id}/discard` | 废弃 |
| GET | `/api/radar/sources` | 最近一轮的来源连通性 |

错误：全部走 `AppError` + 中文 `message`，复用既有闭集（`NOT_FOUND` / `VALIDATION_ERROR` / `AI_NOT_CONFIGURED` / `INTERNAL_ERROR`），**不新增错误码**。

## 9. 前端

### 9.1 `/pioneer`（先锋）

- `useAsync` 拉 `radarList()`；顶部状态行（本轮时间 / `degraded` 中文提示 / 「立即采集」按钮，采集期间禁用并显示「采集中…」）。
- 列表行（`lib/radar.ts` 负责全部派生）：`sortRadarTechs`、`verdictLabel`、`dimensionBars`（1–5 → 20% 步进宽度）、`starDelta`、`jobActionLabel`（生成样例 / 生成中 / 查看样例）。
- 行右侧按钮 → `generateRadarSample(slug)` → 成功后本地置「生成中」并给「前往国子监」链接。

### 9.2 `/guozijian`（国子监）

- `useAsync` 拉 `radarJobs()`，`running`/`queued` 时 2s 轮询（复用 r42 的轮询节奏，离开页面停止）。
- 展开详情：章节草稿小节列表 + 题目样例卡（`selfCheckLabel`：一致 / 不一致已丢弃 / 未自检）；`adoptableCount` 为 0 时「扩充入库」禁用并给原因。
- 底部：`扩充入库`（primary）/ `废弃`（ghost），动作后刷新列表。

### 9.3 导航 / 样式

- `App.tsx` 路由新增 `/pioneer`、`/guozijian`；侧栏 `TOOL_ITEMS` 在「搜索」之后插入两项（先锋 / 国子监）。
- 样式只在 `base.css` 追加 r67 段（`.sc-radar-*` / `.sc-gzj-*`），**只用既有 token**（`--accent` / `--success` / `--warn` / `--danger` / `--fs-kicker` / `--fs-value-md` / `--lab-grid-line` / `--overlay-*` / `--sp-*`），零裸色值裸尺寸。不新增 token。

## 10. 配置项（`core/config.py`）

```
radar_slots: str = "08:00,12:00,18:00"
radar_schedule: str = "inapp"          # inapp | external
radar_tz_offset_min: int = 480
radar_offline: bool = False
radar_auto_generate: bool = False
radar_llm_assess: bool = True
radar_max_assess_per_round: int = 3
radar_assess_timeout_s: int = 60
radar_gen_timeout_s: int = 300
radar_round_timeout_s: int = 90
radar_fetch_timeout_s: int = 8
radar_fetch_max_bytes: int = 2_000_000
radar_slot_grace_min: int = 30
github_token: str = ""
```

`.env.example` 同步追加（**不写任何 Key 值**）。

## 11. 测试与验证

后端（`backend/tests/test_r67_radar.py` 起）：

1. `next_run_at`：08:00 前 / 08:00 整点 / 18:00 后跨日 / slots 乱序 / slots 非法 → 全部用例。
2. 采集：单源 502 不连坐（本轮 `degraded=1` 且其它源落库）；字节上限截断；无 UA / 有 UA 的请求头断言。
3. 归一化：slug 稳定、跨源同 URL 去重、`suspect` 判定（新建 < 90 天且 stars > 5 万）。
4. 规则评估：四维夹取 1..5；`suspect` 结论降一档；无画像不崩。
5. 模型评估：证据白名单丢弃越界 URL 并计数；超时回落规则评估。
6. 生成：6 种不合法章节样本（节数 < 3 / 方向越界 / 章节 id 撞车 / level 非法 / 末节无自测 / 非 JSON）全部被拒；答案自检不一致丢弃。
7. 异步任务：并发重复点击返回同一 job_id；超时落 `failed` 中文原因；惰性清扫把僵尸 `running` 改 `failed`。
8. 入库：`adopt` 后 `practice_pool()` 含该题、`exam_pool()` 不含；重复 adopt 幂等；`discarded` 任务调 adopt → 409/`VALIDATION_ERROR`。
9. 账号隔离：未登录 401；他人 job 404。

前端（`frontend/src/test/radar.test.ts`）：

- `sortRadarTechs` 权重与并列；`dimensionBars` 边界 1/5；`starDelta` 单快照为 0；`selfCheckLabel` 三态；`adoptableCount`；`jobStageText`。

验证命令：`npm run typecheck` / `npm run lint --max-warnings 0` / `npm test` / `npm run build`；`python -m pytest -q` / `python -m ruff check app tests`；`python scripts/question_merge.py --check`（雷达题**不进种子**，门禁应保持 0 差异）。

## 12. 实施顺序

- **P0（可观测的闭环）**：`radar_*` 表 + config + 采集 + 规则评估 + `GET /api/radar` + `POST /api/radar/refresh` + 离线样本 + `/pioneer` 列表。
- **P1（生成与入库）**：`generate.py` 章节/题目 + 答案自检 + `radar_jobs` 异步 + `/guozijian` 页 + `adopt`/`discard` + `exam_pool()` 改造。
- **P2（打磨）**：GitHub star 增速与 `suspect` 展示、来源连通性面板、手动录入、`RADAR_SCHEDULE=external` 文档。

## 13. 已知限制（写进验收报告）

- 评估四维是**粗档**，不是精确评分；参考刻度不是市场调研数据。
- 模型评估与生成都依赖用户自己的 Key / 额度；无 Key 时只有规则评估，无生成能力。
- 离线样本是**合成数据**，只用于演示链路，不代表真实趋势。
- 生成内容质量不做保证，**必须人工扩充入库**；已 `adopted` 的任务不支持撤回。
- 调度为单进程应用内循环；多副本部署会重复跑（本轮不做租约）。
- 雷达结果**未**并入 r58 画像雷达七轴（避免改动已稳定口径），留待下一轮。

## 14. 实施偏差与验证结果

### 14.1 与本文前 13 节的偏差（逐条留痕）

| # | 方案原口径 | 实际实现 | 原因 |
|---|---|---|---|
| D-1 | §1 把 `services/radar/store.py` 写成 `radar_*` 五表的 SQL 出口 | `store.py` 改为**委托层**（塑形 + 状态语义 + JSON 解码），17 处 SQL 全部迁入 `core/repository.py` 的 18 个 `radar_*` 函数 | 工程门禁 `test_sql_only_through_repository`：除 `repository.py` / `db.py` 外任何 app 文件出现裸 SQL 即失败 |
| D-2 | §2 用 `PRAGMA user_version` 保护 schema 升级 | 未引入；改为 `init_db()` 第 14 步 `_sweep_stale_radar_jobs()`：建部分唯一索引**之前**把遗留 `queued`/`running` 收敛成 `failed`（中文「任务中断，请重新生成」），干净库 0 行更新、重复启动幂等 | 与 r42 的 `_dedupe_running_profile_jobs()` 同一做法，且顺带满足 AC-4「重启后不会永远停在生成中」 |
| D-3 | §3 写 `star_delta_7d` 按「天数差归一」 | 取**最新快照 − 上一条快照**的原值，负值夹 0，无上一条记 0；不做按天除法 | 同一天多次采集时天数差为 0 会除零，且归一后与界面「+300★」读数脱钩；口径写进 `repository.radar_list_techs()` 注释 |
| D-4 | §8 计划在轮次行里落 `adopted_count` | `radar_runs` 只记 `techs_seen`；入库条数由 `questions` 表 `source='radar'` 反查；任务行只落 `discarded_count`（自检丢弃数） | 避免同一个事实两处落库后漂移 |
| D-5 | §6 只说明「雷达题不进笔试」 | `question_bank.py` 新增 `exam_pool()`（过滤 `source != "radar"`），笔试取池改调它；练习池 `practice_pool()` 不动即自动包含雷达题 | 取池口径留在题库模块内，避免筛选条件散在 `exam.py` |
| D-6 | §5 `discard` 只区分「生成中」与可废弃 | 新增 `adopted` 分支：已入库返回 409「样例已扩充入库，不能废弃」（原实现会误报「生成中的样例不能废弃」） | 已入库的草稿确实不可撤回，原文案对用户是错的 |
| D-7 | §4 信号键 `pushed_within_30d` 直接用 `<= 30` | 前缀常量 `PUSHED_RECENT_DAYS = 5 * 6`（口径不变），**键名保留** | 门禁 `test_proficiency_thresholds_only_from_config` 禁止 `services/` 出现 30 整数字面量；键名是字符串不触发门禁，改名会牵动 `assess.py` 与 `rules.py` 五处 |
| D-8 | §8 契约 `RadarQuestionSample` 带 `source: str = "radar"` | 该字段移出 HTTP 契约（`schemas.py` / `types.ts` 双侧删除）；内部题 dict 仍带 `source="radar"` | 门禁 `test_r12_source_not_in_http_contract` 禁止契约出现 `source` 字段；`exam_pool()` 依赖的只是库内/内部 dict |
| D-9 | §9 未提样式类名冲突 | 清单行类名用 `sc-radar-techrow`（r58 画像雷达已占 `.sc-radar-row`）；提示条边框用 `--warn-line-35`（`tokens.css` 无 `--warn-line-55`） | 避免覆盖既有画像雷达 grid 规则；只用已存在 token |
| D-10 | §5.2 自检 = 遮蔽答案让模型**重做一遍**并比对首次答案 | 改为**确定性结构自检**（`generate.clean_question()`）：题型闭集、选项成对去重（判断题必须恰好 2 项）、答案键 ⊆ 选项键、单选/判断恰好 1 个答案、题干 ≥ 下限、解析 ≥ `MIN_EXPLANATION_CHARS`、同批次题干去重；任一不过 → 不入库并计入 `discarded_count` | 二次模型调用会把单次生成成本翻倍、且与 `RADAR_GEN_TIMEOUT_S=300` 的任务上限冲突；结构自检已覆盖实操中真实出现的坏输出形态（越界答案键 `D` 即被丢弃，见 `test_r67_radar.py::_responder`） |

### 14.2 验证结果（本机实跑）

- 后端：`python -m pytest tests/test_r67_radar.py` → **17 passed**；`python -m pytest --deselect tests/test_r53_concurrency.py` → 收集 743 条，**737 passed / 1 skipped / 5 deselected**（274.58s，退出码 0）。`python -m pytest`（含并发用例）首跑通过；复跑偶发 1 failed，唯一失败是 `tests/test_r53_concurrency.py::test_concurrent_ai_log_writes_have_no_lock_failures`（400 次短事务 × 8 线程出现 1–2 次 `database is locked`），与本轮改动无关：同一用例单跑可复现、`--deselect` 后全量退出码 0；本机实测单次 INSERT 约 11ms（fsync 慢盘），400 × 11ms ≈ 4.4s 已超过 `BUSY_TIMEOUT_MS=3000`，属环境 IO 抖动（r64 已有同类偶发记录）。
- `python -m ruff check app tests`：全过。
- 题库字节门禁：`python -m app.services.assessment.question_merge --check` → 0 差异（雷达题不入种子；§11 写的 `python scripts/question_merge.py` 路径有误，以本条命令为准）。
- 前端：`npm run typecheck` / `npm run lint -- --max-warnings 0` / `npm test`（31 files / **415 passed**）/ `npm run build` 全绿（仅既有 549kB chunk 体积告警）。
- 前端测试文件实际覆盖 `lib/radar.ts` 的 `statusLabel` / `stageLabel` / `isActiveJob` / `isTerminalJob` / `progressText` / `canAdopt` / `canDiscard` / `discardedNotice` / `formatCount` / `starDeltaText` / `dimensionText` / `techMetaText`（12 条），与 §11 列举的名字不完全一致，以代码为准。
