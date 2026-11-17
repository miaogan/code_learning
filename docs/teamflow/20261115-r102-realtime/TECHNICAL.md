# r102 · 实时推送（SSE）：任务进度流 + 面试回合流

> 2026-11-15。B3 收尾件：把上传页「每 2 秒拉一次任务状态」升级为服务端推送，
> 面试提交从「一个 60s 的 POST 黑盒」变成「阶段可见的回合流」。

## 1. 交付物

| 层 | 文件 | 要点 |
|---|---|---|
| SSE 基建 | `backend/app/core/sse.py` | 帧格式化（`event:` + `data:` + 空行）、注释帧心跳、断连检测；统一响应头（`Cache-Control: no-transform` + `X-Accel-Buffering: no`） |
| 任务流 | `backend/app/routers/jobs.py` | `GET /api/jobs/{kind}/{job_id}/stream`（kind ∈ profile / resume）：**只送事实**（status / updated_at / error），终态推 `done` 关流；心跳 `jobs_stream_heartbeat_s`；客户端断开即退；超过 `jobs_stream_max_s` 发 `timeout` |
| 回合流 | `backend/app/routers/interview.py` | `POST /api/interviews/{run_id}/answers/stream`：`phase(scoring)` → `turn`（完整 `InterviewTurn`）→ `done`；业务失败走 `error` 帧（code / message / retryable），**不出现 turn** |
| 配置 | `backend/app/core/config.py` | `JOBS_STREAM_POLL_S=0.8` / `JOBS_STREAM_HEARTBEAT_S=15` / `JOBS_STREAM_MAX_S=3600` |
| 前端 SSE 客户端 | `frontend/src/lib/sse.ts` | fetch + ReadableStream 帧解析（支持任意分块 / 心跳 / 多行 data）；自带 `SseError`（**不反向 import api/client，避免循环依赖**） |
| 前端监听 | `frontend/src/lib/jobWatch.ts` | `watchJob(kind, jobId, { fetchOnce, intervalMs })`：SSE 驱动「有变化才查一次」，流打不开**自动回落 2s 轮询**；返回 stop |
| 上传页 | `frontend/src/pages/UploadPage.tsx` | 画像任务改 `watchJob` 驱动（`fetchOnce` 保留原失败计数 / 弱网提示 / 404 / 终态全部语义） |
| 面试页 | `frontend/src/pages/InterviewPage.tsx` + `api/client.ts` | 优先 `scoreAnswerStream`（阶段文案「评分并生成下一条发言」）；流不可用（`STREAM_UNAVAILABLE`）回落同步 `scoreAnswer`——两条路共用同一条 `score_answer` 业务链路 |
| 反代 | `frontend/nginx.conf` / `nginx.prod.conf` | 新增 `location ~ ^/api/(jobs|interviews)/.*/stream$`：`proxy_buffering off` + 1300s 读超时（nginx 默认攒包会把流变成「批量到达」）；prod 层重新 include 安全头（`add_header` 继承陷阱） |

## 2. 设计判断（为什么这样切）

1. **流只送事实，结果仍走单查**：任务完成态的大对象（画像 payload / 识别结果）不复制进
   流帧——否则序列化口径变成两处，迟早漂移；前端收到 `done` 用既有 GET 拿一次结果，
   整场只多一个请求，换来「一份契约」。
2. **面试评分不做「逐字文本流」**：评分 + 出题是一次结构化补全，契约是 JSON；
   为动画把一次调用拆成两跳只会让成本翻倍、两次结果还可能不一致。流的是**阶段事实**
   （评分中 → 就绪），把 60s 黑盒变成有反馈的过程。逐字流留在真正需要它的地方（太傅对话）。
3. **回落是产品需求不是兜底彩蛋**：旧后端 / 代理不支持流 / 弱网时，`watchJob` 自动回 2s
   轮询，功能不缺失；面试提交同理回落同步端点。可用性优先于「一定要用新协议」。
4. **断连检测放心跳节拍**：`request.is_disconnected()` 在 TestClient 下会误报（读完请求体
   即报断开），逐帧查会把流在第一条帧后掐断；生产真断开时 uvicorn 会取消任务，心跳处
   检查是保底而非唯一手段。
5. **nginx 必须显式关缓冲**：`proxy_buffering` 默认开，SSE 会被攒成一批；后端虽发了
   `X-Accel-Buffering: no`，反代层再写一遍是双保险。

## 3. 验证

| 项 | 结果 |
|---|---|
| `tests/test_sse_streams.py`（8 例） | ✅ 终态即推 status+done；running→completed 同流可见（推送而非轮询）；失败态带中文原因；404 / 未知 kind / 跨用户隔离；回合流 phase→turn→done；错误只出 error 帧 |
| 后端全量 pytest | ✅ 通过（含 r100/r101 全部用例） |
| 前端 `lib/sse.test.ts`（5 例）+ 全量 | ✅ 帧跨块归并 / 心跳不产帧 / 多行 data / 半帧不提前触发；41~43 文件全绿 |
| 前端 typecheck / lint / build | ✅ 全绿 |
| ruff | ✅ All checks passed |
