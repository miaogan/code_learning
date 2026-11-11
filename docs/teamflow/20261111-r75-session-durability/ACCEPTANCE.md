# r75 · 验收报告：作答不丢与会话打断

> 结论：本轮 11 条验收标准全部满足。纯前端改动，未改 HTTP 契约、后端、数据表、视觉 token 或依赖。尚未提交 / 推送。

## 1. 交付内容

| 文件 | 改动 |
| --- | --- |
| `frontend/src/lib/examDraft.ts` | 新增按账号隔离的笔试草稿：卷面快照、答案、作答起点、24h TTL、结构与时间校验 |
| `frontend/src/lib/interviewDraft.ts` | 新增按账号 + 场次隔离的面试当前题草稿；800 字截断、空文本清除 |
| `frontend/src/state/authNotice.ts` | 新增 sessionStorage 一次性登录过期提示；兼容 StrictMode 重复初始化 |
| `frontend/src/pages/ExamPage.tsx` | 恢复卷面 / 答案 / 连续计时；每次作答落盘；提交与无效草稿清理；无存储时保留离开保护 |
| `frontend/src/pages/InterviewPage.tsx` | 防抖保存当前回答；刷新与 401 重登恢复；提交 / 切题 / 结束 / 重开 / 404 清理 |
| `frontend/src/pages/LoginPage.tsx` | 表单上方展示一次性「登录已过期，请重新登录」 |
| `frontend/src/state/auth.ts` | 非主动登出的 401 先标记过期提示，再回到匿名态；主动登出与启动失败不标记 |
| `frontend/src/pages/NotFoundPage.tsx` | 新增 404 文案与回首页出口 |
| `frontend/src/App.tsx` | 注册通配路由，未知地址保留壳层 |
| `frontend/src/pages/HistoryPage.tsx` | 筛选条常驻；0 条时给类型化空态与「看全部记录」 |
| `frontend/src/test/examDraft.test.ts` | 12 项草稿契约测试 |
| `frontend/src/test/interviewDraft.test.ts` | 8 项面试草稿测试 |
| `frontend/src/test/authNotice.test.ts` | 5 项登录提示测试 |

## 2. 验收标准

| AC | 结果 | 证据 |
| --- | --- | --- |
| AC-1 笔试可恢复 | 通过 | 真实浏览器：刷新恢复 10 题卷面与已答；站内「战绩 → 科考」恢复；401 重登后恢复同一卷 |
| AC-2 计时连续 | 通过 | 刷新前后计时环均为 `00:02`；草稿按 `started_at` 墙钟差恢复，单测另验 65s |
| AC-3 恢复有提示 | 通过 | 出现「已恢复你上次未提交的作答（… 保存）」，可关闭且不遮挡作答 |
| AC-4 过期与脏数据 | 通过 | 浏览器把 `saved_at` 改到 25 小时前，显示「已超过 24 小时」且不渲染题目；损坏 JSON / 版本 / 跨卷答案 / 非法答案值 / 未来时间由 12 项单测覆盖 |
| AC-5 生命周期 | 通过 | 真正提交成功后 `sc.exam.<userId>` 删除；「再出一套笔试」后键内 `run_id` 变为新卷、答案为空、起点更新 |
| AC-6 账号隔离 | 通过 | 同浏览器 A 登录可见自己恢复的答案；切到 B 无卷面、无 A 草稿副本；登出不删草稿，切回 A 仍恢复原答案 |
| AC-7 面试草稿 | 通过 | 刷新恢复；401 后重登恢复；300ms 内立刻切页仍补写；删空后切页清除；提交成功、提前结束、会话 404 均清除；800 字上限单测 |
| AC-8 登录过期解释 | 通过 | 由页面真实 `POST /submit` / `POST /answers` 返回 401 触发，登录页出现且只出现一次；sessionStorage 标记被消费。主动登出、首次启动 401、启动网络失败均不出现 |
| AC-9 未知地址 | 通过 | `/practise` 显示指定文案，「回首页」可用，壳层保留 |
| AC-10 战绩无死路 | 通过 | 只考过面试时点「笔试」：筛选条仍在、显示「「笔试」还没有已完成的记录」；「看全部记录」恢复全部并回第 1 页 |
| AC-11 不回归 | 通过 | typecheck / lint / 34 文件 448 测试 / build / `git diff --check` 全部通过 |

## 3. 验证命令与结果

```text
npm run typecheck  → passed
npm run lint       → passed，0 warning
npm test           → 34 test files / 448 tests passed
npm run build      → passed，172 modules
git diff --check   → passed（仅 LF/CRLF 提示）
```

构建产物 JS 569.57 kB，保留仓库既有的「chunk > 500 kB」提示；本轮未新增依赖，未引入新的构建告警类型。

真实浏览器为 Microsoft Edge 157（Chromium 157 headless），通过 CDP 9222 驱动；前端运行在 `http://127.0.0.1:5173`，所有 `/api/*` 响应由浏览器请求拦截注入合成数据，**未写真实开发库，也未发出真实 AI 请求**。验证脚本保存在 gitignored 的 `logs/teamflow/r75-session-durability/scripts/`：

- `check.cjs`：404、筛选空态、笔试刷新 / 站内恢复、计时、过期、提交清理、重新出卷覆盖、面试刷新 / 站内恢复与防抖补写。
- `check-auth.cjs`：应用内 401、一次性提示、重登恢复、换账号隔离、提交 / 结束 / 404 清理、主动登出与启动边界。

## 4. 验收中发现并修复的问题

1. **面试结束清草稿后又被旧 effect 写回**：结束流程先 `clearInterviewDraft`，随后上一个防抖 effect 的 cleanup 用旧 `answer` 补写，导致草稿复活。改为 cleanup 只按最新 ref 判断：仍处于当前题的 `chat` 且非提交中、user / run / question 全匹配时才补写；结束、重开、404 等失效上下文不再补写。
2. **防抖窗口内删空并离开会留下旧草稿**：同一 cleanup 现在允许空文本补写，从而清掉旧键。
3. **401 切换时机**：`emit(anonymous)` 改为下一个宏任务，确保触发 401 的请求先走完错误分支，不把失败误当提交成功。登录页提示的存储删除也延迟到宏任务，避免 StrictMode 重挂载时读不到。
4. **验证脚本自身问题**：直接 `fetch('/api/me')` 不经过 `api/client.ts`，无法触发应用 401；改为点击真实提交按钮。脚本同时补 `try/finally` 关闭 WebSocket 与标签页，失败不再悬挂进程。

以上 1–3 为产品代码修复，4 只改验收脚本，不影响产品。

## 5. 边界与未覆盖

- 本仓库无 jsdom / testing-library，未新增页面组件测试；交互全部用真实 Chromium 验证。
- localStorage 被禁用 / 配额满的真实浏览器行为未注入验证；单测覆盖 `writeExamDraft` 返回 `false`，页面保留旧的 `beforeunload` 与站内链接确认逻辑。
- 两标签页同时做两套笔试属于非目标：单账号只保留一份当前未提交卷，后写覆盖。
- 401 验证使用拦截响应，而非真实后端会话过期；实际请求路径已确认经过 `api/client.ts`。
- 未做笔试历史复核（后端无 `GET /api/exams/{run_id}`），未实施审计中的其余 P1/P2。
- 无截图证据；本报告只声明 DOM、计算值、存储键与脚本断言结果。
- 本轮未提交、未推送；工作区保留前端 6 个修改文件与 7 个新增文件，等待用户决定提交时机。
