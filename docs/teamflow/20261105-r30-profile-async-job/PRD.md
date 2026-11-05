# r30 — 画像生成异步化（后台任务 + 轮询）

## 背景

r29 给上传页补了离开保护，但根因还在：画像生成是**同步长请求**（AI 调用 20~60 秒），
页面必须一直等着，离开就只能靠拦截弹窗劝住用户。治本的思路是把「等待」从页面里拿掉：
生成放到服务端后台跑，前端只轮询，离开就变得无害。

## 方案

### 后端（同步 POST 契约保持不变，新增异步入口）

1. **新表 `profile_jobs`**（`db.py`，`CREATE TABLE IF NOT EXISTS` 幂等建表）：
   `id / user_id / document_id / file_name / chars / sections / status(running|completed|failed)
   / error / result / created_at / updated_at`。`result` 存 `ProfileWithMerge` 的 JSON
   —— **一次性 `merge_summary` 随任务落库**，后台完成也不丢「本次合并」摘要。
2. **`repository.py`**：`insert_profile_job / get_profile_job / latest_profile_job /
   finish_profile_job / fail_profile_job / get_document_stats`（任务行按 `user_id` 隔离；
   后台写状态显式传 `user_id`，不依赖 ContextVar 在任务里的隐式传播）。
3. **`routers/profile.py`** 三个新端点：
   - `POST /api/resumes/{id}/profile/async`：校验简历 → 受理任务行 →
     `asyncio.create_task(_run_profile_job(...))` → 立即返回 `{job_id, status: "running"}`；
   - `GET /api/profile-jobs/{job_id}`：轮询状态；`completed` 带 `result`，`failed` 带中文 `error`；
   - `GET /api/profile-jobs/latest`：最近一次任务（回上传页自动接上进度用），没有任务 404。
   - 后台任务体两种终态都必须落库可见（`AppError` 用中文 message，其余收敛为通用提示），
     不允许「无声消失」。
4. **`schemas.py`**：`ProfileJobStarted` / `ProfileJobStatus`。

### 前端（UploadPage 改轮询，画像阶段不再拦截导航）

1. `api/client.ts` + `types.ts`：`generateProfileAsync / getProfileJob / latestProfileJob`。
2. 上传解析（秒级）仍同步等待；解析成功后改调 `generateProfileAsync`，进入 profiling 阶段
   每 2 秒（`PROFILE_JOB_POLL_MS`）轮询，终态后停表。
3. **离开保护收窄到 `uploading` 窗口**：profiling 阶段任务在服务端，UI 直接给
   「先去练习 / 看站内教程」出口，不再弹确认框；`paused` 阶段随同步等待一起移除
   （后台任务没有「取消」，离开不丢进度）。
4. **重接入**：进上传页时查 `latestProfileJob`，还有 `running` 任务就把轮询接上
   （meta 全部来自任务行；StrictMode 双跑用 ref 守卫；completed/failed 历史任务不重放，
   走「已有画像」读路径）。
5. 轮询容错：网络抖动继续轮不判死；404（任务行没了）如实报错并允许重试。

## AC

- 画像生成中刷新/关闭/站内跳转 → **不弹任何拦截**，任务在服务端继续，回来自动接上进度。
- 生成完成后轮询端拿到完整画像 + `merge_summary`，done 卡片与同步版一致。
- 任务失败原因（中文）在页面可见，可重试（重新受理）。
- 他人任务 404；`GET /api/profile-jobs/latest` 无任务 404。
- 后端 `pytest` / `ruff`，前端 `typecheck / lint / test / build` 全绿。

## 改动清单

- `backend/app/db.py`：`profile_jobs` 表 + 索引。
- `backend/app/repository.py`：任务行 CRUD + `get_document_stats`。
- `backend/app/schemas.py`：`ProfileJobStarted` / `ProfileJobStatus`。
- `backend/app/routers/profile.py`：异步受理 + 轮询/最近任务端点 + 后台任务体。
- `backend/tests/test_profile_job.py`：完成/失败可见/404/最近任务/跨用户隔离（5 例）。
- `frontend/src/api/{client,types}.ts`、`frontend/src/lib/profileJob.ts`（+`src/test/profileJob.test.ts` 4 例）、
  `frontend/src/pages/UploadPage.tsx`（轮询 / 重接入 / 拦截收窄 / 移除 paused）。
- `docs/teamflow/20261105-r30-profile-async-job/`：本任务夹。
