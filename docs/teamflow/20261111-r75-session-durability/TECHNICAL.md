# r75 · 技术方案：作答草稿与会话打断

> 依据 PRD `docs/teamflow/20261111-r75-session-durability/PRD.md`。纯前端，无后端、无契约、无新依赖、无新 token。

## 1. 现状证据（HEAD `82bd83b`）

| 事实 | 位置 | 影响 |
| --- | --- | --- |
| `answers` / `result` / `run` 全是组件 state | `ExamPage.tsx:69-71` | 卸载即归零 |
| 离开保护只挂 `beforeunload` + `a[href]` 捕获 | `ExamPage.tsx:179-203` | SPA 后退 / 侧滑不触发 |
| 弹框自称「无法恢复」 | `ExamPage.tsx:580-588` | 与产品目标冲突，本轮必须改文案 |
| 401 → `anonymous` → 整树换登录页 | `state/auth.ts:46-48`、`App.tsx:101-103` | 无解释、状态全丢 |
| 无兜底路由 | `App.tsx:165-183` | 未知地址空白 |
| 筛选条在 `total > 0` 内 | `HistoryPage.tsx:101`；空态条件 `:55` | 筛到 0 条即死路 |
| 面试 `answer` 纯 state | `InterviewPage.tsx:100` | 未提交回答丢失 |
| 既有本地会话范式可复用 | `lib/uploadSession.ts` | 版本号 + TTL + 安全读写 + 匿名不写 |

服务端 `elapsed_s` 按 `payload.started_at` 到提交的墙钟差计算（`backend/app/services/assessment/exam.py:252-256`），
所以前端恢复计时必须从**本卷开始时刻**算，不能把停留时长丢掉，也不能从 0 重计。

## 2. 设计原则

1. **不拦你，但丢不了**：不引入路由库改造（`BrowserRouter` 无 `useBlocker`），SPA 后退不拦截，靠草稿恢复。
2. **恢复是纯读**：`read*` 不删数据、不写数据，返回分类结果；清理由显式 `clear*` 完成。
   这样 StrictMode 双跑初始化函数也不会「第一次读成功、第二次读到空」。
3. **服务端仍是唯一真值**：草稿只存「本机未提交的输入 + 本卷快照」，提交仍以 `POST /submit` 响应为准。
4. **存储不可用要退化，不是静默丢**：写入失败返回 `false`，页面退回旧的离开保护。

## 3. 存储契约

| 键 | 介质 | 版本 | TTL | 说明 |
| --- | --- | --- | --- | --- |
| `sc.exam.<userId>` | localStorage | 1 | 24h | 每账号**仅一份**当前未提交笔试卷 |
| `sc.interview.draft.<userId>.<runId>` | localStorage | 1 | 24h | 每场面试一条当前草稿 |
| `sc.auth.notice` | sessionStorage | 1 | 10min | 一次性「登录已过期」提示 |

约定沿用 `lib/uploadSession.ts`：`userId` 为 `null` 时**不写**（不落 `anon` 共享键）；
读失败 / JSON 损坏 / 版本不符一律按无效处理；所有 `getItem/setItem/removeItem` 包 `try`。

`sc.exam.<userId>` 单账号单份是有意口径：产品是单人自用，同一时刻只做一套卷；
两个标签页同时做两套属于未支持场景（后写覆盖），在 PRD 非目标里已注明。

## 4. 新增模块

### 4.1 `lib/examDraft.ts`

```ts
export interface ExamDraft {
  version: 1
  run_id: string
  run: ExamRun                       // 卷面快照（不含答案，服务端本就只回题面）
  answers: Record<string, string[] | string>
  started_at: string                 // 本机进入作答的时刻（ISO）
  saved_at: string
}

export type ExamDraftRead =
  | { status: 'none' }
  | { status: 'ok'; draft: ExamDraft; elapsedS: number }
  | { status: 'expired' }            // 超过 24h
  | { status: 'invalid' }            // 结构坏 / 卷面 id 对不上 / 版本不符

export const EXAM_DRAFT_TTL_MS = 24 * 60 * 60 * 1000

export function readExamDraft(userId: string | null, nowMs?: number): ExamDraftRead
export function writeExamDraft(
  userId: string | null,
  input: { run: ExamRun; answers: Record<string, string[] | string>; startedAt: string },
): boolean
export function clearExamDraft(userId: string | null): void
```

校验规则（任一不满足 → `invalid`，不返回半个卷子）：

- `version === 1`；`run_id` 非空且等于 `run.run_id`；
- `run.questions` 为非空数组，每项有非空 `id`；
- `answers` 的每个键都存在于卷面（防止旧卷答案串到新卷），值为 `string` 或 `string[]`；
- `started_at` / `saved_at` 可被 `Date.parse` 解析，且 `saved_at` 不是未来时间（容忍 5 分钟时钟漂移）。

`elapsedS = max(0, floor((now - started_at) / 1000))`，上限交给页面既有 `TIMER_DISPLAY_MAX_S` 截断。

### 4.2 `lib/interviewDraft.ts`

```ts
export interface InterviewDraft { version: 1; run_id: string; question_id: string; text: string; saved_at: string }
export function interviewDraftKey(userId: string | null, runId: string): string
export function readInterviewDraft(
  userId: string | null, runId: string, questionId: string, nowMs?: number,
): { status: 'none' | 'expired' | 'invalid' } | { status: 'ok'; text: string; savedAt: string }
export function writeInterviewDraft(userId: string | null, input: { runId: string; questionId: string; text: string }): boolean
export function clearInterviewDraft(userId: string | null, runId: string): void
```

- `runId` / `questionId` 与读入参数不一致 → `none`（不是错误，说明是别的题）；
- `text` 超过 `MAX_ANSWER_CHARS`（800，来自 `components/interview/Composer.tsx`）时截断后返回；
- 空串不写（顺手清掉旧键），避免每删一个字都落一次盘。

### 4.3 `state/authNotice.ts`

```ts
export function markSessionExpired(nowMs?: number): void   // sessionStorage 写 {version:1, at}
export function takeAuthNotice(nowMs?: number): string | null  // 纯读 → 宏任务后删 → 10min 内才返回
```

模块内缓存本次页面加载的首次结果（`let taken: string | null | undefined`），
保证 StrictMode 下 `useState(() => takeAuthNotice())` 两次调用拿到同一个值，不会「第一次取走、第二次为空」。

删除存储标记放在 `setTimeout(..., 0)` 中，不在读取时立刻消费：StrictMode 的挂载 / 卸载 / 重挂载
可能在同一页生命周期里短暂卸载登录页，立即删除会让第二次初始化读不到提示。模块缓存让同一页重复读取结果一致；
真正整页重进时会重新读标记，延迟删除保证它是「本次登录页一次性」，而不是污染下一次登录页。

接线：`state/auth.ts` 的 `setUnauthorizedHandler` 在 `emit` 前调用 `markSessionExpired()`；
仅 `current.status === 'authed'` 时触发（既有守卫不变），主动 `logout()` 不写。`anonymous` 切换同样
放到 `setTimeout(..., 0)`：先让触发 401 的请求完成自己的错误处理，再卸载页面，避免异步失败被误走成成功清理。

## 5. 页面接线

### 5.1 `ExamPage.tsx`

1. 取 `const userId = useAuth().me?.id ?? null`。
2. 初始化：
   ```ts
   const [restored] = useState(() => readExamDraft(userId))
   const [run, setRun] = useState(restored.status === 'ok' ? restored.draft.run : null)
   const [answers, setAnswers] = useState(restored.status === 'ok' ? restored.draft.answers : {})
   const [runElapsed, setRunElapsed] = useState(restored.status === 'ok' ? restored.elapsedS : 0)
   const [startedAt, setStartedAt] = useState(restored.status === 'ok' ? restored.draft.started_at : '')
   const [stage, setStage] = useState<Stage>(restored.status === 'ok' ? 'running' : 'idle')
   const [durable, setDurable] = useState(true)
   const [draftNotice, setDraftNotice] = useState(restored.status === 'ok'
     ? `已恢复你上次未提交的作答（${formatWhen(restored.draft.saved_at)} 保存）`
     : restored.status === 'expired' ? '上一份未提交的作答已超过 24 小时，已清除'
     : restored.status === 'invalid' ? '上一份未提交的作答无法恢复，已清除'
     : null)
   ```
   初始化函数只读不写，StrictMode 双跑安全（见 §2 原则 2）。
3. 挂载后一次性清理过期 / 损坏项：`useEffect(() => { if (restored.status === 'expired' || restored.status === 'invalid') clearExamDraft(userId) }, [])`。
4. `setAnswer` 里同步落盘（点击粒度，不防抖）：
   ```ts
   const next = { ...prev, [questionId]: value }
   if (!writeExamDraft(userId, { run, answers: next, startedAt })) setDurable(false)
   ```
5. 出卷成功（`startExam` 内 `setRun(created)` 之后）：`startedAt = new Date().toISOString()`，写入空答案草稿；写失败同样 `setDurable(false)`。
6. 提交成功（`submitExam` 内 `setStage('submitted')` 之前）：`clearExamDraft(userId)`。
7. 离开保护按 `durable` 分叉：
   - `durable === true`：不挂 `beforeunload`、不拦站内链接（草稿已可恢复）。离开确认框仅在 `!durable` 时出现。
   - `durable === false`（隐私模式 / 配额满）：保持 `:179-203` 原逻辑，弹框文案保持「无法恢复」。
8. 恢复提示条：`draftNotice !== null` 时在页头下渲染 `.sc-meta-line` + 关闭按钮，`role="status"`。

**计时口径**：`runElapsed` 恢复初值 + 既有每秒自增；`started_at` 用本机时刻，与服务端 `payload.started_at` 相差 ≤1s，
显示值与提交后返回的 `elapsed_s` 同量级（PRD AC-2 只要求连续与同量级，不要求逐秒相等）。

### 5.2 `InterviewPage.tsx`

1. 恢复成功（`getInterview` 的 `then`，`setAnswer('')` 处，`:149`）后：
   读取 `readInterviewDraft(userId, restored.run_id, restored.current_id)`；`ok` 则 `setAnswer(text)` 并给一行同款提示；
   `expired/invalid` 清键。
2. 编辑时防抖 300ms 写入（`useEffect` on `answer`，仅 `stage === 'chat' && session?.current_id`）；空串直接 `clear`。
   卸载时通过最新 ref 补写；effect cleanup 也必须以最新渲染状态判断当前题是否仍可编辑，不能用旧闭包补写。
   **实现修正**：提前结束 / 重开先清草稿后，旧 effect 的 cleanup 若无条件写旧 `answer`，会把已清回答复活；
   最终 cleanup 只在 `latest.stage === 'chat' && !latest.submitting` 且 user/run/question 全匹配时补写最新输入，
   空文本也补写以清掉防抖窗口内的旧草稿。其余卸载路径由页面卸载 effect 负责。
3. 清除点：`submitTurn` 成功、提前结束、主动重开、新开局、会话 `404`、过期 / 损坏；提交失败保留。

### 5.3 `App.tsx` + `pages/NotFoundPage.tsx`

- 新增 `NotFoundPage`：`EmptyState reason="这个地址不存在，可能是链接过期或拼写有误" actionLabel="回首页" actionTo="/"`。
- `Routes` 末尾加 `<Route path="*" element={<NotFoundPage />} />`；壳层不变（顶栏 / 侧栏仍可导航）。
- 未登录时仍由 `App.tsx:101` 先渲染登录页，不暴露 404 给未登录用户（既有行为保持）。

### 5.4 `LoginPage.tsx`

- `const [notice] = useState(() => takeAuthNotice())`；`notice !== null` 时在表单上方渲染 `InlineError`（无重试按钮）。
- 提示与登录失败错误分两个状态，互不覆盖。

### 5.5 `HistoryPage.tsx`

- 把「类型筛选」块从 `data !== null && total > 0` 分支里提出来，改为 `data !== null` 即渲染（首屏 loading 不渲染，避免闪）。
- 新增分支：`pickedKinds.length > 0 && total === 0` → `EmptyState`
  `reason={`「${pickedKinds.map(kindLabel).join('、')}」还没有已完成的记录`}`，
  `actionLabel="看全部记录"`，`onAction` 清空筛选并 `setPage(1)`。
- 既有「全库为空」分支（`:80-99`）保持不变。

## 6. 失败模式与处理

| 场景 | 行为 |
| --- | --- |
| localStorage 被禁 / 配额满 | `write*` 返回 `false` → 笔试退回原生离开提示；面试只影响草稿，不报错 |
| JSON 损坏 / 旧版本 | `invalid` → 清键 + 一次性提示，不阻塞开始新卷 |
| 卷面 id 对不上 | `invalid`（防止旧答案串卷） |
| 系统时间被改早 | `saved_at` 在未来 → 按 `invalid`；`elapsedS` 恒 `≥0` |
| 换账号 | 键不同，读不到；登出不清（重新登录可续） |
| 提交后同一 run 再恢复 | 提交成功即清键，不会出现「已提交还能改」的假象 |

## 7. 测试计划

新增 `src/test/examDraft.test.ts`（12 例）：写入-读取往返、`elapsedS` 计算、24h 边界、损坏 JSON、
版本不符、答案键不在卷面、未来时间、`userId === null` 不写、`clear` 后 `none`、读 / 写 / 清失败退化。

新增 `src/test/interviewDraft.test.ts`（8 例）：run/question 不匹配返回 `none`、空串清键、超长截断、TTL、损坏、未来时间、清理失败不抛出。

新增 `src/test/authNotice.test.ts`（5 例）：StrictMode 重复读同值并延迟消费、10min 过期、未来时间、损坏 JSON、存储不可用。

页面不做组件测试（仓库无 jsdom / testing-library），按 AC 在真实 Chromium 走查：

| AC | 手工步骤 | 期望 |
| --- | --- | --- |
| 1 / 2 / 3 | 答 8/12 题 → F5 | 同卷、8 题保留、计时接着走、出现恢复提示 |
| 1 | 答 5 题 → 点侧栏「战绩」→ 回「科考」 | 恢复（无拦截弹框） |
| 6 | 换账号登录 → `/exam` | 看不到上一位的卷与答案 |
| 4 | DevTools 把 `saved_at` 改成 25h 前 → 刷新 | 不恢复 + 一次性过期提示 |
| 5 | 提交 → 查 localStorage | `sc.exam.<id>` 已删 |
| 7 | 面试写 300 字 → 刷新 | 文字仍在；提交后清空 |
| 8 | DevTools 删 `sc_session` → 触发请求 → 重新登录 | 登录页有「登录已过期」 |
| 9 | 访问 `/practise` | 404 文案 + 回首页可用 |
| 10 | 只考过面试 → 战绩点「笔试」 | 筛选条常驻、空态说明、能回全部 |

## 8. 验证命令

```bash
cd frontend
npm run typecheck && npm run lint && npm test && npm run build
```

预期：0 error / 0 warning；新增 3 个测试文件全绿；构建产物无新增 chunk 警告（本需求不新增依赖）。

## 9. 实施顺序与回滚

1. 三个 lib + 单测（可独立合入，不改页面行为）。
2. `NotFoundPage` + 路由 + `HistoryPage`（互不依赖）。
3. `authNotice` + `LoginPage`。
4. `InterviewPage` 草稿。
5. `ExamPage` 恢复（最后做，改动最大，需手工矩阵全跑）。

回滚：删除三个 lib 与测试、删除 `NotFoundPage`，`git checkout --` 五个页面文件即可；无数据迁移、无后端回滚。

## 10. 风险

- **单账号单份草稿**：两个标签页做不同卷会互相覆盖。已列为非目标；如未来需要，改为 `sc.exam.<userId>.<runId>` + 索引键。
- **本机草稿含题面与作答**：只在本机、按账号、24h、提交即清；不随账号同步，换设备不可续（与上传会话同边界）。
- **计时轻微漂移**：本机 `started_at` 与服务端 `started_at` 可能差 1s 内，AC 只要求同量级。
- **`formatWhen` 展示到分钟**：恢复提示不写「几分钟前」，避免页面停留后数字失真。
