# TECH-PLAN · r42 任务化与断连恢复

> 配套 `PRD.md`。本文件回答：端点与表结构、幂等 / 超时语义、与 r30–r34 的兼容处理、前端状态机、HEIC 判定。

---

## 1. 端点

### 1.1 复用（零改动）

| 端点 | 说明 |
|---|---|
| `POST /api/resumes/{resume_id}/profile/async` | 画像任务受理（r30）。**r42 只加幂等**：已有 running 任务时返回同 `job_id` |
| `GET /api/profile-jobs/{job_id}` | 画像任务轮询（r30） |
| `GET /api/profile-jobs/latest` | 回上传页自动接上（r30/r32） |
| `POST /api/resumes/{resume_id}/profile` | **同步契约保留**，内部实现不变 |
| `POST /api/resumes/images` | **r41 同步图片入口保留**，内部改为共用校验/专用 HEIC 文案 |

> 复用端点不新增字段、不改状态取值；现有调用方与测试无需改动。

### 1.2 新增（图片识别异步）

| 端点 | 语义 |
|---|---|
| `POST /api/resumes/images/async` | 校验数量 / 体积 / 格式 → 视觉档就绪检查 → 幂等受理 → `{job_id, status:"running"}` |
| `GET /api/resume-jobs/{job_id}` | 任务状态：`running / completed / failed`，`completed` 带 `result: ResumeMeta` |
| `GET /api/resume-jobs/latest` | 最近一次图片识别任务（跨设备接上） |

错误码全部复用闭集：`VALIDATION_ERROR`（数量 / 字数不足）、`UNSUPPORTED_TYPE`（格式 / HEIC）、`FILE_TOO_LARGE`、`EMPTY_FILE`、`AI_UNAVAILABLE`（视觉未开通 / 超时）、`PARSE_FAILED`（图片打不开）、`INTERNAL_ERROR`（受理冲突兜底）、`NOT_FOUND`（任务不存在）。

---

## 2. 表结构

### 2.1 复用 `profile_jobs`（不删列、不改状态语义）

新增**部分唯一索引**：

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_profile_jobs_running_doc
    ON profile_jobs (user_id, document_id) WHERE status = 'running';
```

- 只约束在途行：同一简历不会同时存在两条 running。
- 终态行可无限累积（历史任务照常可查）。
- 存量库可能有 r30 期间的并行 running（每次受理都新建行）：`init_db()` 先跑
  `_dedupe_running_profile_jobs()`，同一 `(user_id, document_id)` 只保留 `max(rowid)` 一条，
  其余按 `failed` + 中文原因收敛，再建索引 —— 不会因旧数据导致启动失败。

### 2.2 新表 `resume_jobs`

```sql
CREATE TABLE IF NOT EXISTS resume_jobs (
    id           TEXT PRIMARY KEY,          -- job_id（uuid hex）
    user_id      TEXT NOT NULL DEFAULT 'default',
    file_name    TEXT NOT NULL,
    image_count  INTEGER NOT NULL,
    content_hash TEXT NOT NULL DEFAULT '',   -- sha256(拼接后的图片字节)，幂等键
    status       TEXT NOT NULL,              -- running | completed | failed
    error        TEXT NOT NULL DEFAULT '',   -- failed 时可直接展示的中文原因
    result       TEXT NOT NULL DEFAULT '',   -- completed 时 ResumeMeta 的 JSON
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_resume_jobs_running_hash
    ON resume_jobs (user_id, content_hash) WHERE status = 'running';
```

- 图片字节不入库；`result` 里的 `resume_id` 指向 `documents`（正文已入库）。
- `content_hash` 只用于「同一批图片在途去重」，任务终态后不再拦新提交。

---

## 3. 幂等与并发（受理路径）

```
expire_stale(kind)                     # 先把僵尸 running 收敛成 failed
existing = find_running(key)           # 命中直接返回同 job_id
insert(...)                            # 部分唯一索引兜并发
  └ 撞唯一约束 → 再查 running → 命中返回；否则换新 id 重试一次
```

- 画像键：`(user_id, document_id)`；图片键：`(user_id, content_hash)`。
- 受理时读 `user_id`：同步请求走 `_uid()`；后台任务写状态时**显式传 user_id**（不依赖 ContextVar 的隐式传播）。
- 视觉未就绪在**受理阶段**直接 503 `AI_UNAVAILABLE`（不会产生一个注定失败的任务行）。

---

## 4. 超时与清扫

| 任务 | 心跳 | 无进展判死 | 任务体硬上限 |
|---|---|---|---|
| 画像 | 无（单次 AI 调用） | 30 分钟（r32 语义，阈值上调） | `asyncio.wait_for` 25 分钟 |
| 图片识别 | **每页识别完写 `updated_at`** | 10 分钟无心跳 | `3 × 600s + 300s` |

- 阈值上调依据：统一 AI 超时 600s 且允许重试一次 → 合法上限约 20 分钟；r30 的 10 分钟会误杀。
- 清扫在读路径（`get` / `latest` / 受理前）惰性执行，不依赖后台定时器；
  服务重启留下的 running 行会在下一次读取时变成 `failed` + 中文原因。
- 超时落 `failed` 的文案：画像「画像生成超时，请重新生成（稍后重试通常即可）」；图片「图片识别超时，请稍后重试」。

---

## 5. 与 r30–r34 的兼容处理

| 既有能力 | r42 处理 | 旧数据 / 旧状态 |
|---|---|---|
| r30 `profile_jobs` + async/latest | **复用**，只在受理加幂等、加硬 deadline | 旧 running 行：保留最新一条，其余由启动 dedupe 收敛为 failed |
| r30 同步 profile 端点 | **原样保留** | 无 |
| r32 读路径惰性清扫 | **复用**，阈值 10 → 30 分钟 | 旧 failed 行不变，仍可查 |
| r33 24h 失败提示窗口 | **复用**（`shouldSurfaceFailure` 不改） | 旧失败超窗不打扰 |
| r34 重试与超时 | **不推翻**：`generate_profile` 的超时 / `retry_unavailable` 不动 | — |
| r41 同步图片端点 | **保留**；内部改用共享校验（HEIC 文案更具体） | 旧客户端不受影响 |
| r41 图片任务无 | 新增 `resume_jobs`，与 `profile_jobs` 并列（不合并、不改名） | 新表，空库无迁移数据 |

> 结论：**没有替换任何 r30–r34 的语义**；新增的是「图片识别任务 + 幂等 + 前端本地恢复锚点 + 文案」。

---

## 6. 契约（两侧同步）

`backend/app/schemas.py`：

```python
class ResumeJobStarted(BaseModel):
    job_id: str
    status: str = "running"

class ResumeJobStatus(BaseModel):
    job_id: str
    file_name: str
    image_count: int
    status: str
    error: str
    result: ResumeMeta | None = None
    created_at: str
```

`frontend/src/api/types.ts`：`ResumeJobStarted` / `ResumeJobStatus` 逐字对齐；`ProfileJobStatus` 不变。

JSON 全 snake_case；错误 envelope `{error:{code,message,retryable}}` 不变。

---

## 7. 前端状态机与恢复语义

### 7.1 阶段

```
idle
 ├─(文档) uploading（同步解析，仍拦截离开）
 └─(图片) recognizing（后台识别，不拦截离开）
        ↓ 识别完成（拿到 ResumeMeta）
      profiling（画像后台任务，不拦截离开）
        ↓
      done / error（记住失败发生在 upload｜profile）
```

- `uploading`：原离开保护不变（浏览器原生提示 + 站内链接先确认）。
- `recognizing` / `profiling`：给「先去练习 / 看教程」出口，离开不丢任务。
- 计时：`uploading` / `recognizing` 用 `uploadSec`，`profiling` 用 `profileSec`。

### 7.2 本地上传会话（`sc.upload.<userId>`）

```ts
interface UploadSession {
  version: 1
  source: 'file' | 'image'
  resume_job_id?: string
  profile_job_id?: string
  meta?: ResumeMeta
  saved_at: string          // 24h 后失效
}
```

写入时机：图片任务受理后、画像任务受理后；清除时机：主动重新上传、进画像页、进润色页、会话 404 / 过期。存储异常（隐私模式 / 配额）静默降级，不影响上传主流程。

### 7.3 重入页面顺序

1. 本地会话有 `profile_job_id`：running → 接上；completed 且 30 分钟内 → 回放结果（含 merge 摘要）；failed 且在 r33 24h 窗口内 → 明示原因 + 重试；否则清会话回落。
2. 本地会话有 `resume_job_id`：running → `recognizing`；completed → 拿 `ResumeMeta` 继续 `profiling`；failed → error 可重试。
3. 无本地会话 / 404：服务端 `latestResumeJob`（running）→ `latestProfileJob`（r30/r32 原逻辑）。
4. 网络异常：中文提示 +「重试接上」（`recoverTick` 重新跑一次恢复流程），不白屏。

### 7.4 断网提示

- 轮询连续 2 次失败：`navigator.onLine === false` → 「网络已断开：任务仍在服务端继续，恢复网络后会自动接上。」；否则「网络连接不稳定，正在自动重试；任务在服务端继续，不会丢失。」
- `offline` / `online` 事件直报与清除，不等下一轮轮询。
- 轮询**不因失败停止**，任务在服务端照跑；只有 404 才判「任务不存在」。

---

## 8. HEIC 判定

### 8.1 前端

- 选图后只读前 32 字节：`ftyp` 的 major brand（偏移 8）与兼容品牌（偏移 16 起）命中
  `heic / heix / hevc / hevx / heim / heis / mif1 / msf1` 即判 HEIC。
- 命中直接给 `HEIC_UNSUPPORTED_HINT`：
  「这是 iPhone 的 HEIC 照片，当前浏览器无法直接处理。请在「设置 → 相机 → 格式」里选择「兼容性最佳」后重新拍摄，或在相册里导出为 JPG / PNG 再上传。」
- 在 `img.decode()` **之前**拦下，不依赖浏览器是否支持 HEIC。

### 8.2 后端

- `services/resume/image_resume.py` 新增 `is_heif()` / `sniff_or_raise()`。
- HEIC → `UNSUPPORTED_TYPE` + 专用中文文案（不新增错误码）；其它未知格式保持「仅支持 JPG / PNG / WebP」。
- 同步与异步图片端点共用同一校验出口。

### 8.3 iOS Safari 实际行为

- **实测不了**：本环境无 iOS 真机 / 模拟器。
- 按公开行为推断：iOS 通过 `<input type="file" accept="image/*">` 走系统照片选择器时通常转码为 JPEG；
  走「文件」App 选择 `.heic` 原文件，或部分 Android / 桌面浏览器，会原样送出 HEIC。
- 因此实现不假设「前端一定转成 JPEG」：前后端都按真实字节兜底。
