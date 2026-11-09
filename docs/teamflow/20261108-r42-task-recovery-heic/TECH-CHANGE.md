# TECH-CHANGE · r42 实施清单

> 范围：后端任务化与幂等、前端断连恢复、HEIC 兜底。无样式 token 新增 / 无 CSS 改动。

---

## 1. 后端

| 文件 | 改动 | 关键点 |
|---|---|---|
| `backend/app/core/db.py` | 新增 `R42_SCHEMA`、`R42_INDEXES`、`_dedupe_running_profile_jobs()`，`init_db()` 扩到 9 步 | 新表 `resume_jobs` + 两条部分唯一索引；建索引前先收敛存量重复 running |
| `backend/app/core/repository.py` | `insert_profile_job` 返回 `bool`（撞唯一约束返回 False）；新增 `find_running_profile_job`；新增 `resume_jobs` 全套（insert / find_running / get / latest / expire / touch / finish / fail） | 幂等全在仓储层用 SQL 做；任务行 user_id 显式传入 |
| `backend/app/schemas.py` | 新增 `ResumeJobStarted`、`ResumeJobStatus` | 字段全 snake_case |
| `backend/app/services/resume/image_resume.py` | 新增 `is_heif()`、`sniff_or_raise()`、`HEIC_UNSUPPORTED_MESSAGE`；`extract_resume_text` 增 `on_page_done` 心跳回调；mime 校验改走 `sniff_or_raise` | 抽取逻辑与提示词不变 |
| `backend/app/routers/resume.py` | 抽出 `_read_images` / `_image_file_name` / `_image_meta`；同步端点保留；新增 `POST /api/resumes/images/async`、`jobs_router`（`GET /api/resume-jobs/{job_id}`、`/latest`）；新增 `_run_resume_job` 后台任务 | 受理前检查视觉档；`asyncio.wait_for` 硬上限；逐页心跳 |
| `backend/app/routers/profile.py` | 受理加幂等（先清扫再查 running，插入冲突兜并发）；`_PROFILE_JOB_STALE_SECONDS` 10 → 30 分钟；`_PROFILE_JOB_DEADLINE_S = 25 分钟` 与 `wait_for` | r30/r32/r33/r34 语义不变，只调阈值 + 加硬上限 |
| `backend/app/main.py` | 挂载 `resume.jobs_router` | 独立前缀 `/api/resume-jobs` |
| `backend/tests/test_profile_job.py` | 陈旧阈值断言 11 → 31 分钟（注释说明 r42 变更） | 语义未变，只改时长 |
| `backend/tests/test_r42_jobs.py`（新） | 8 例：画像 / 图片幂等、两类清扫、图片完成入库、失败可见、HEIC 两种入口 | 视觉调用用替身，零网络 |

### 1.1 契约差异

```diff
+ class ResumeJobStarted:  job_id: str; status: str = "running"
+ class ResumeJobStatus:   job_id/file_name/image_count/status/error/result: ResumeMeta|null/created_at
```

`ResumeMeta`、`ProfileJobStatus`、同步端点请求 / 响**均无字段变化**。

### 1.2 存量数据

- `profile_jobs`：启动时把同一 `(user_id, document_id)` 的多条 running 收敛为「最新一条保留、其余 failed」，随后建唯一索引；对干净库 0 行更新、可重复执行。
- `resume_jobs`：新表，无存量迁移。
- 旧 failed 行、旧 completed 行原样保留。

---

## 2. 前端

| 文件 | 改动 | 关键点 |
|---|---|---|
| `frontend/src/api/types.ts` | 新增 `ResumeJobStarted` / `ResumeJobStatus` | 与 `schemas.py` 逐字对齐 |
| `frontend/src/api/client.ts` | 新增 `uploadResumeImagesAsync` / `getResumeJob` / `latestResumeJob` | 旧 `uploadResumeImages` 不动 |
| `frontend/src/lib/uploadSession.ts`（新） | 本地上传会话读写 / 失效；`shouldReplayCompleted`（30 分钟）；`elapsedSince`；HEIC 字节嗅探 + 专用提示 | localStorage 异常全部吞掉；纯函数可单测 |
| `frontend/src/pages/UploadPage.tsx` | 新增 `recognizing` 阶段；图片入口改异步受理 + 轮询；重接入改为「本地会话优先 + 服务端 latest 兜底」；断网中文提示 + 重试接上；离开时清会话 | `uploading` 离开保护保留；后台阶段给出口不拦截 |
| `frontend/src/test/uploadSession.test.ts`（新） | 12 例：账号隔离、24h 失效、脏数据、回放窗口、真实 HEIC 头 | node 环境用 Map 模拟 localStorage（与 learnProgress 测试同口径） |

### 2.1 前端状态机

见 TECH-PLAN §7。渲染新增：

- `recognizing` 卡片（环形进度 + 「识别图片中的文字」+「离开不会中断」+ 练习 / 教程出口）。
- `netNotice` 中文提示（`InlineError`，任务仍活着时不给「重试接上」按钮，避免与轮询抢状态）。

### 2.2 未新增样式

没有新增 CSS 变量 / 类；`recognizing` 复用 `.sc-lab-panel`、`.sc-upload-progress`、`.sc-btn-row`、`.sc-meta-line`，窄屏规则沿用 r35/r40/r41。

---

## 3. 运行与验证命令

```powershell
# 后端
cd backend
python -m ruff check app tests
python -m pytest tests/test_r42_jobs.py tests/test_profile_job.py -q

# 前端
cd frontend
npm run typecheck
npm run lint
npm test -- --run
npm run build
```

结果见 `QA-REPORT.md`。
