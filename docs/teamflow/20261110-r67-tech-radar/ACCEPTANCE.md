# r67 技术雷达 · 验收报告（ACCEPTANCE）

> 验收依据：本任务夹 `PRD.md`（AC-1..AC-9）与 `TECHNICAL.md`（§1–§13 方案、**§14 实施偏差与验证**）。
> 结论口径：**「通过」= 有可复跑的证据**（测试名 / 代码位置 / 实跑命令）；没证据的一律标「未验证」，不写成通过。

## 1. 交付范围

| 层 | 内容 |
|---|---|
| 页面 | 「先锋」`/pioneer`（技术清单 + 右侧「生成样例」按钮）、「国子监」`/guozijian`（样例进度 + 「扩充入库」/「废弃」两个出口） |
| 后端接口 | `GET /api/radar/techs`、`POST /api/radar/manual`、`POST /api/radar/run`、`GET /api/radar/runs/latest`、`POST /api/radar/generate`（`tech_slug` 走 body）、`GET /api/radar/jobs`、`GET /api/radar/jobs/{job_id}`、`POST /api/radar/jobs/{job_id}/adopt`、`POST /api/radar/jobs/{job_id}/discard` |
| 数据表 | `radar_techs` / `radar_snapshots` / `radar_assessments` / `radar_jobs` / `radar_runs`（`core/db.py::R67_SCHEMA` + `R67_INDEXES`） |
| 服务 | `services/radar/`：`sources`（六源采集：GitHub / Hacker News / arXiv / OpenAI Blog / Google AI Blog / 手动 + 离线样本）/ `normalize` / `rules` / `assess` / `generate` / `store` / `jobs` / `schedule` |
| 题池口径 | `question_bank.exam_pool()` 过滤 `source != 'radar'`；雷达生成题**只进练习池** |

## 2. 逐条验收

| AC | 结论 | 证据 |
|---|---|---|
| AC-1 无网络 + 无 Key 时 `RADAR_OFFLINE=1` 能跑通一轮，先锋页看到带四维的清单 | **通过** | `tests/test_r67_radar.py::test_offline_round_lands_techs`（跑轮后 `store.list_techs()` 非空、每行含 `verdict` 与四维）；离线样本 `backend/seed/radar_samples.json` 20 条；`sources.load_samples()` 不发起任何网络请求 |
| AC-2 单源失败不连坐，本轮记 `degraded` | **通过** | `test_r67_radar.py::test_round_marks_degraded_when_one_source_fails`（伪造 github `ok` + arxiv `failed`，断言 `degraded is True`、`notice` 含「部分信息源本轮不可用」、`sources` 逐源状态原样、条目仍全部落库）；实现 `services/radar/__init__.py::run_round` |
| AC-3 同一 tech 同时只 1 个未终态任务，重复点击返回同一 `job_id` | **通过** | `test_create_job_reuses_active_row`（同账号重复建任务返回同一 `job_id`、`reused=True`）；`test_create_job_blocks_other_user`（他账号占用时抛 `occupied` → 路由 409 中文「该技术正在为其他账号生成样例，请稍后再试」）；幂等靠 `idx_radar_jobs_active` 部分唯一索引 |
| AC-4 失败有中文原因，且不会永远「生成中」 | **通过** | ①失败原因：`test_r67_radar.py::test_generate_failure_is_visible`（响应 `failed` + 中文 `error_message`）；②卡死：`test_stale_running_job_is_swept_to_failed`（把 `running` 行 `created_at` 回拨 40 分钟后走读路径，惰性清扫为 `failed` 且原因含「生成中断」）；③重启兜底：`init_db()` 第 14 步 `_sweep_stale_radar_jobs()` |
| AC-5 扩充入库后进练习池、**不进**笔试卷 | **通过** | `test_r67_radar.py::test_manual_then_generate_then_adopt_only_practice`（入库后 `practice_pool()` 命中、`exam_pool()` 不命中）；实现 `question_bank.exam_pool()`（在 `load_questions()` 基础上去掉 `source == 'radar'` 的题），`services/assessment/exam.py` 取池改调 `exam_pool()`；`practice_pool()` 不筛选，雷达题自动进入 |
| AC-6 自检不一致的题不入库，并标注丢弃数 | **通过** | `test_manual_then_generate_then_adopt_only_practice` 断言 `discarded_count == 1` 且入库仅 2 题（夹具故意给一道答案键越界 `D` 的题）；实现 `services/radar/generate.py::clean_question`（确定性结构自检，见偏差 **D-10**） |
| AC-7 废弃不写 `questions`、不留章节档 | **通过** | `test_r67_radar.py::test_discard_writes_no_questions`（`succeeded` → `discard` → 状态 `discarded`，`question_bank.load_questions()` 中不存在 `radar-<job_id>` 前缀题）；`jobs.discard` 只改任务状态 |
| AC-8 `next_run_at` 跨日正确、固定 +08:00 | **通过** | `test_next_run_at_cross_day`（同日下一档 / 跨日首档）；`test_is_due_after_restart`（重启后按最近一轮 `started_at` 判是否到点）；`services/radar/schedule.py::next_run_at` 纯函数，档位按 +08:00 计算，不受进程时区影响 |
| AC-9 生成 / 入库 / 废弃按账号隔离，未登录 401 | **通过** | `test_radar_requires_login`（未登录 401）；`test_job_requires_owner`（他人 `job_id` 不可见，`store.get_job` / `list_jobs` / adopt / discard 均按 `user_id` 过滤）；`test_create_job_blocks_other_user` 覆盖跨账号占用 |

## 3. 验证结果（本机实跑，2026-11-10）

| 命令 | 结果 |
|---|---|
| `python -m pytest tests/test_r67_radar.py` | **17 passed**（原 13 条 + 本轮新增 4 条：AC-2 `test_round_marks_degraded_when_one_source_fails`、AC-4 `test_generate_failure_is_visible` + `test_stale_running_job_is_swept_to_failed`、AC-7 `test_discard_writes_no_questions`） |
| `python -m pytest --deselect tests/test_r53_concurrency.py` | **737 passed / 1 skipped / 5 deselected**（全量收集 743 条，退出码 0，274.58s） |
| `python -m pytest`（全量，含并发用例） | 首跑**通过**；复跑出现 `test_r53_concurrency` 的 `database is locked`（环境性抖动，见 §4） |
| `python -m ruff check app tests` | 全过 |
| `python -m app.services.assessment.question_merge --check` | 逐字节 0 差异（题库种子未被本轮改动污染） |
| `npm run typecheck` / `npm run lint -- --max-warnings 0` / `npm test` / `npm run build` | 全绿（31 files / **415 passed**；build 仅有既有 549kB chunk 告警） |

前端 `frontend/src/test/radar.test.ts` 覆盖 `lib/radar.ts` 的纯函数派生（清单分组、四维展示、状态文案、按钮可用性），页面零计算。

## 4. 已知限制与未验证项

1. **并发用例环境抖动**：`test_r53_concurrency` 在本机高负载下偶发 `database is locked`（单次 INSERT ≈11ms × 400 ≈ 4.4s > `BUSY_TIMEOUT_MS=3000`）。**未放宽门禁、未改配置**，与 r64 记录的同类偶发一致，与本轮改动无关。
2. **视觉未实机核对**：「先锋」「国子监」两页需要登录账号，未做浏览器实机截图核对；样式只用 `tokens.css` 变量（门禁 `test_no_raw_colors_outside_tokens` 通过）。
3. **真实网络采集与真实模型评估未跑**：四源采集的实网行为、模型评估（`RADAR_MAX_ASSESS_PER_ROUND`）需账号与 Key，本轮只验证离线样本路径 + 伪造单源失败路径。
4. **自检为确定性结构校验**（非 PRD 描述的「模型重做一遍」），见 `TECHNICAL.md §14.1 D-10`；二次模型调用会使成本翻倍并与任务硬上限冲突。
5. **已采纳不可废弃**：`adopted` 任务再点废弃返回 409「样例已扩充入库，不能废弃」，撤回题目的设计本轮不做（见 `TECHNICAL.md §14.1 D-6`）。

## 5. 过程合规

- 本次交付**未执行任何 `git commit` / `git push`**。
- 三条工程门禁（SQL 唯一出口 / 熟练度阈值单源 / 契约无 `source` 字段）已修复并全过，偏差逐条记于 `TECHNICAL.md §14.1`。
