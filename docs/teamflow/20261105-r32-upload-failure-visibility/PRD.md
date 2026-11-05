# r32：上传失败可见性 —— 后台任务的失败不能再「无声消失」

## 背景与问题

用户反馈「简历上传会失败，没有报错信息的提示」。

排查方式：不猜，直接搭真实环境复现 —— 真后端（8000）+ Vite dev + Playwright 登录后逐类上传坏文件，
并用 sqlite 直接改 `profile_jobs` 任务行模拟后台侧失败。

### 排查结论：同步路径本来就没问题

- 坏 PDF（后端 400/500）、空文件（本地校验）、超限等场景，错误条 + 重试**都正常显示**。
- 顺带发现：本机后端运行环境缺 `pypdf`/`python-docx`，任何真实 PDF 都会报
  「服务端缺少 PDF 解析依赖」——错误可见，但环境本身要修（已 pip install）。

### 真正的洞在 r30 异步化之后（2 处）

1. **回来看失败任务 → 全静默（主因）**。用户上传后离开（或刷新），后台任务失败；
   回上传页时 `shouldReattach` 只认 running，failed 的 latest 任务被直接忽略 ——
   页面呈现「已有画像」旧摘要或纯新用户态，对最近这次失败毫无痕迹。
2. **僵尸 running → 永远「生成中」**。后台任务活在进程内存里，uvicorn 重启 / 进程被杀后
   没有任何代码把任务行推进终态，行永远停在 running：轮询无限等，重接入也会接管一个
   永远跑不完的任务（还显示误导性的「已用 4s」）。

## 修复

### 后端（读路径惰性清扫）

- `repository.expire_stale_profile_jobs(stale_seconds)`：把 `updated_at` 超过阈值仍 running
  的任务行标记为 `failed`，error 落中文原因「后台任务长时间没有进展（可能因服务重启而中断），
  请重新生成画像」。ISO UTC 字符串比较，格式与 `_now()` 一致。
- `GET /api/profile-jobs/{id}` 与 `/latest` 读前先清扫（阈值 10 分钟，生成常态 30~90s）。
  惰性写的好处：终态持久化，轮询端点与重接入端点拿到的是同一个确定结论。

### 前端（failed 的 latest 任务明示）

- `lib/profileJob.ts` 新增 `shouldSurfaceFailure(job)`：最近一次任务为 failed 即返回 true
  （重试或重新上传后 latest 会变掉，错误自然消失，无需额外消亡逻辑）。
- `UploadPage` 重接入 effect：failed 时用 `jobToResumeMeta(job)`（document_id 即 resume_id）
  复用既有 `failure`/`error` 相位 —— 显示失败原因 + 「重试」（对 document_id 重新受理后台任务）
  + 「先去画像页」。StrictMode 双跑仍由 `reattachRef` 挡住。

## 验证

- 后端新增 2 例：僵尸行读即 failed（含 latest 路径）、新鲜 running 不受清扫影响；
  `test_profile_job.py` 共 7 例全过，全量 570 passed / 1 skipped，ruff 全绿。
- 前端新增 1 例（shouldSurfaceFailure），typecheck / lint 0 warning / 203 测试 / build 全绿。
- 真实浏览器复验（截图）：回来看 failed 任务 → 「AI 服务调用失败，请检查模型配置后重试」+ 重试；
  30 分钟前的僵尸 running → 「后台任务长时间没有进展…」+ 重试。两处布局均正常。

## 经验

- 异步任务的可观测性 = 「受理 + 轮询」之外还必须有「终态必然可见」：进程内存里的任务
  死于重启时，唯一知道它的地方就是任务行本身，读路径惰性清扫是最便宜的兜底。
- 「失败却无报错」类反馈优先怀疑状态机的历史分支（重接入/重放），而不是当下的 catch。
