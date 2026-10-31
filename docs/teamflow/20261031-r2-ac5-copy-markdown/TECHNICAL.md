# TECHNICAL · AC-5 报告页「复制 Markdown」

基线依赖：`docs/teamflow/20261031-r2-ac5-copy-markdown/PRD.md`（其基线为 `docs/teamflow/20261031-r1-dev-skill-coach`）
本方案是**增量返工方案**：不为复制路径新增任何后端能力、不新增运行时依赖、不改契约。

## 0. 决策摘要（先说结论）

| # | 决策 | 理由 |
|---|---|---|
| D-1 | 复制按钮落在**报告概要卡（Hero Card）操作行** `.sc-btn-row` 内、「导出 .md」左侧，`variant="secondary"` | 现有代码的 Hero 操作组就在 `<Card>` 内这一行（`ReportPage.tsx` L199-208），PRD/DESIGN §2.5 描述的「Hero 右侧操作组」在本版代码里正是它；不为此改版式（needDesign=false） |
| D-2 | **导出按钮的 `primary` 变体、Blob 类型、文件名规则一行都不动**；只在其前插入复制按钮 | AC-6「AC-9 导出不回归」；DESIGN §2.5 原文写「次按钮下载 .md」与现码不一致，以**现码为准**并在 §6 记录该偏差（改变体会造成视觉回归，超出本轮范围） |
| D-3 | 文本源**只有一处** `api.reportMarkdown(report.id)`，剪贴板与导出两者各自调用、互不复用变量；不抽出共享 helper | 待澄清（fact，默认「允许最小抽取」）在本轮按**更小改动面**落地：复制分支自带一次调用，导出分支零改动（0 回归风险）。两条分支都用同一个 `requestText` 出口，单源由「后端 `services/markdown.py` 唯一渲染」保证，抽取反而要动已验证的导出代码 |
| D-4 | 新增 `Toast` 组件**自持计时**（停留 2s → 淡出 120ms → 回调关闭），页面只持有文案与自增序号 | 淡出 120ms 要求元素在退场期间仍在树上，需要组件内部 `closing` 态；页面侧保持极简，静态断言也更好定位 |
| D-5 | Toast 样式追加到既有 `styles/base.css`（`/* ---------- Toast ... ---------- */` 段），不新建 `.css` 文件 | 现有约定是两份全局 css（tokens + base）承载所有组件样式，`components/ui/*` 无同名 css；遵守既有风格 |
| D-6 | 剪贴板能力判断前置（`typeof navigator.clipboard?.writeText !== 'function'` → 失败分支），但 `writeText` 调用保持字面量 `navigator.clipboard.writeText(text)` | PRD §5「前置能力判断，不进 try 之外抛错」+ AC-5 断言 1 要求命中 `navigator.clipboard.writeText(`；不做 `execCommand` 兼容层 |
| D-7 | 失败**不自动下载**、成功**不加按钮态** | PRD §10 两条品味项默认值 |

## 1. 数据模型与存储

**本轮零变更**：不动 SQLite 4 表、不动 `backend/app/schemas.py`、不动 `frontend/src/api/types.ts`。

复制文本的「存储」语义：

| 项 | 事实 |
|---|---|
| 文本真源 | 服务端 `backend/app/services/markdown.py` 渲染，`GET /api/reports/{id}/markdown`（`text/markdown;charset=utf-8`）响应体 |
| 前端中间态 | `const text: string`（`await api.reportMarkdown(report.id)` 的返回值），**不落盘、不进 localStorage、不二次渲染** |
| 前端状态 | 3 个页面态 + 1 个 Toast 态（见 §5），均为组件内 `useState`，无全局 store |
| 持久化 | 无新增。报告本体仍由既有 `reports` 表持久化，复制动作不写库 |

新增/变更的类型定义（仅前端局部，不入 `api/types.ts`）：

```ts
// components/ui/Toast.tsx
export interface ToastProps {
  message: string
  seq?: number        // 同文案再次触发时自增，令 2s 计时重启
  durationMs?: number // 默认 2000（DESIGN §0.6）
  onClose: () => void // 淡出结束后由页面清空 toast 态
}

// ReportPage.tsx 局部
type ToastState = { message: string; seq: number } | null
```

## 2. API 设计

**不新增、不修改任何路由/入参/返回。** 本轮只用一条既有接口：

| 方法 | 路径 | 入参 | 返回 | 错误 |
|---|---|---|---|---|
| GET | `/api/reports/{report_id}/markdown` | path `report_id`（前端 `encodeURIComponent`） | `200`，`text/markdown;charset=utf-8` 原始正文（**不是 JSON**） | 404 `REPORT_NOT_FOUND`（中文 message，`retryable:false`）；其他 4xx/5xx 走统一 envelope |

前端唯一出口：`frontend/src/api/client.ts`

```ts
reportMarkdown: (reportId: string): Promise<string> => requestText(`/api/reports/${encodeURIComponent(reportId)}/markdown`)
```

`requestText` 与 `request` 共用 `rawRequest`，因此错误已被归一成 `ApiError`（`code/message/status/retryable`），页面拿到的一定是 `ApiError`（`message` 中文、不含路径/堆栈）：

- 网络断开 → `NETWORK`（可重试）
- 404 → envelope 里的中文 message
- 非 JSON 错误页 → `HTTP_ERROR（HTTP xxx）`（可重试）

**契约不变约束**：本方案不允许在 `client.ts` 里新增 markdown 相关包装（如 `reportMarkdownRaw`），也不允许页面直接 `fetch`。

## 3. 前端组件与页面拆分

### 3.1 文件改动清单（本次全部改动）

| 文件 | 动作 | 所有者任务 |
|---|---|---|
| `frontend/src/components/ui/Toast.tsx` | **新增**（团队唯一 Toast 出口） | T1 |
| `frontend/src/styles/base.css` | **追加** `.sc-toast` 段（约 40 行，放「页内错误 / 空态」段之后） | T1 |
| `frontend/src/pages/ReportPage.tsx` | 改：新增导入、3 个状态、`copyMarkdown()`、`clipboardErrorMessage()`、错误条、按钮、Toast 渲染 | T2 |
| `logs/teamflow/tf-mvwcb4xd-6150nu/scripts/check_copy_markdown.mjs` | **新增**（不提交，`logs/teamflow/` 已被忽略，run 结束由 host 归档） | T3 |
| `.gitignore` | 追加一行 `backend/tests/.tmp/`（QA P3 项） | T4 |

不改：`backend/**`、`frontend/src/api/**`、`frontend/src/lib/**`、`tokens.css`、`DESIGN.md`（`--elev-2`/`--radius-8`/`--sp-6`/`--fast`/`--base` 均已存在，**无需新 token**）。

### 3.2 `components/ui/Toast.tsx`（新组件契约）

```tsx
export interface ToastProps { message: string; seq?: number; durationMs?: number; onClose: () => void }
export function Toast({ message, seq = 0, durationMs = 2000, onClose }: ToastProps): JSX.Element
```

- 内部状态：`closing: boolean`；`onCloseRef` 用 ref 保存回调用以**排除出 effect 依赖**（避免父级内联箭头函数导致计时反复重启）。
- 时序（effect deps = `[message, seq, durationMs]`）：
  1. `setClosing(false)`；
  2. `setTimeout(setClosing(true), durationMs)`（2s 停留）；
  3. `setTimeout(onCloseRef.current, durationMs + EXIT_MS)`，`EXIT_MS = 120`（与 `--fast` 同值，常量处注释说明）；
  4. cleanup 双向 `clearTimeout`，卸载后不再回调（防「组件已卸载仍 setState」）。
- 渲染：`<div className={closing ? 'sc-toast is-closing' : 'sc-toast'} role="status" aria-live="polite">{message}</div>`。
- 不接 `variant`/`tone`：PRD 明确**失败不用 Toast**，本轮只有 success 一种用途；多一种 tone 只会诱发误用（DESIGN §4「禁止只用 Toast 承载失败」）。未来需要 error tone 时再加，避免本轮造无用分支。

### 3.3 `styles/base.css` 追加段（规格逐项对齐 DESIGN §0.5/§0.6/§4）

```css
/* ---------- Toast（复制成功等轻量反馈，DESIGN §0.5 / §0.6 / §4） ---------- */
.sc-toast {
  position: fixed;
  right: var(--sp-6);   /* 右下 24 */
  bottom: var(--sp-6);
  z-index: 20;          /* 高于 .sc-topbar 的 10；tokens.css 无 z 轴 token，沿用既有裸值约定 */
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-4);   /* 12 16 */
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-8);
  background: var(--bg-raised);
  color: var(--text-primary);
  font-size: var(--fs-body);
  line-height: var(--lh-body);        /* 14 / 22 */
  box-shadow: var(--elev-2);
  animation: sc-toast-in var(--base) var(--ease);   /* 淡入 180ms + translateY(8px) */
}
.sc-toast.is-closing { animation: sc-toast-out var(--fast) var(--ease) forwards; } /* 淡出 120ms */
@keyframes sc-toast-in  { from { opacity: 0; transform: translateY(var(--sp-2)); } to { opacity: 1; transform: translateY(0); } }
@keyframes sc-toast-out { from { opacity: 1; transform: translateY(0); } to { opacity: 0; transform: translateY(var(--sp-2)); } }
```

全部颜色/尺寸走 `var(--…)`，零裸色值；`prefers-reduced-motion: reduce` 由 base.css 末尾既有全局规则（`animation-duration: 0.01ms`）自动覆盖，不需要重复声明。

### 3.4 `pages/ReportPage.tsx` 改动点（精确到插入位置）

| 位置 | 改动 |
|---|---|
| import 区 | 增加 `import { Toast } from '../components/ui/Toast'` |
| 模块常量区（`GENERATE_PHASES` 之后） | `const COPY_TOAST_MESSAGE = '已复制到剪贴板，可直接粘进笔记'`（AC-3 原文，唯一字面量） |
| 模块函数区（`errorMessage` 之后） | 新增 `clipboardErrorMessage(error: unknown): string` |
| 组件状态区（`exportError` 之后） | `copying` / `copyError` / `toast` 三个 state |
| `generateReport` 的 `setGenerateError(null); setExportError(null)` 旁 | 追加 `setCopyError(null); setToast(null)`（重生成时清掉上一轮的复制残留） |
| `exportMarkdown` 之后 | 新增 `copyMarkdown()`（§6.1 全文） |
| 错误条区（`exportError` 的 `<InlineError>` 之后） | `{copyError ? <InlineError message={copyError} onRetry={copyMarkdown} retryLabel="重新复制" /> : null}` |
| `<Card>` 内 `.sc-btn-row`（L199-208） | 在「导出 .md」`<Button>` **之前**插入复制按钮 |
| 组件 `</section>` 之前 | `{toast ? <Toast message={toast.message} seq={toast.seq} onClose={() => setToast(null)} /> : null}` |

按钮 JSX（与既有 `Button` 契约一致，`loading` 同时置 `disabled`+`aria-busy`，天然满足「复制中禁用重复点击」）：

```tsx
<Button variant="secondary" onClick={copyMarkdown} loading={copying}>
  复制 Markdown
</Button>
```

操作行最终顺序：`[复制 Markdown secondary] [导出 .md primary] [重新生成 secondary]`。

## 4. 状态管理

无全局 store、不引入 context；全部是 `ReportPage` 局部 `useState`：

| 状态 | 类型 | 初值 | 迁移 |
|---|---|---|---|
| `copying` | `boolean` | `false` | 点击且守卫通过 → `true`；`finally` 且 `mountedRef.current` → `false` |
| `copyError` | `string \| null` | `null` | 进入复制 → `null`；失败 → 中文原因；重生成 → `null` |
| `toast` | `{ message, seq } \| null` | `null` | 成功 → `{ message: COPY_TOAST_MESSAGE, seq: 前值+1 }`；Toast 淡出结束 → `null`；重生成 → `null` |

规则（写死，QA 可直接对照）：

1. **成功才写 toast**；失败只写 `copyError` —— 断言里「`setToast` 在 `copyMarkdown` 内只出现 1 次且位于成功分支」。
2. **任何分支都不动 `report` 派生值**：`report = generated ?? reportAsync.data`，复制路径不调用 `setGenerated`/`setReport`/`navigate`。
3. `mountedRef` 守卫沿用现码模式（StrictMode 挂载→卸载→再挂载，effect 体里重置 `true`），所有 `setState` 前先判 `mountedRef.current`。
4. 复制与导出**各自 loading、互不禁用**（PRD §5「两按钮在各自请求进行中各自 loading，均不隐藏」）。

## 5. 关键实现要点与边界情况

### 5.1 `copyMarkdown()` 全文（实现即契约）

```tsx
/** 复制失败的中文原因：浏览器拒绝/不支持剪贴板时引导用户走「导出 .md」。 */
function clipboardErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message || '复制失败，请改用「导出 .md」手动保存'
  const name = typeof error === 'object' && error !== null ? (error as { name?: unknown }).name : null
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return '浏览器拒绝访问剪贴板，请改用「导出 .md」手动保存'
  }
  return '复制失败，请改用「导出 .md」手动保存'
}

const copyMarkdown = async () => {
  if (!report || copying) return
  setCopying(true)
  setCopyError(null)
  try {
    // 前置能力判断（非安全上下文 / 旧浏览器）：不进 try 之外抛错，直接走失败分支
    if (typeof navigator.clipboard?.writeText !== 'function') {
      throw new ApiError('CLIPBOARD_UNAVAILABLE', '当前浏览器不支持剪贴板复制，请改用「导出 .md」手动保存', 0, true)
    }
    // 文本只有一个来源：后端唯一渲染（services/markdown.py）；此处全程零变换（AC-2）
    const text = await api.reportMarkdown(report.id)
    await navigator.clipboard.writeText(text)
    if (!mountedRef.current) return
    setToast((prev) => ({ message: COPY_TOAST_MESSAGE, seq: (prev?.seq ?? 0) + 1 }))
  } catch (error) {
    if (!mountedRef.current) return
    setCopyError(clipboardErrorMessage(error))
  } finally {
    if (mountedRef.current) setCopying(false)
  }
}
```

### 5.2 边界情况（逐条给结论，不允许实现时临时改主意）

| # | 场景 | 行为 |
|---|---|---|
| E-1 | `navigator.clipboard` 为 `undefined`（局域网 IP / 非安全上下文） | 能力判断抛出 `CLIPBOARD_UNAVAILABLE` → `copyError` 中文提示 + 「重新复制」；不弹 Toast；不做 `execCommand` 兜底 |
| E-2 | `writeText` 被拒（`NotAllowedError`/`SecurityError`） | 同上，文案「浏览器拒绝访问剪贴板，请改用「导出 .md」手动保存」 |
| E-3 | 接口 404/500/断网 | `ApiError.message` 直出（已中文、无路径/堆栈/端点）；`retryable` 不复用（页面不据此禁用重试） |
| E-4 | 连点按钮 | `copying` 守卫 + `Button loading` 已 `disabled`，不产生第二次 `writeText` |
| E-5 | 2s 内再次复制成功 | `toast.seq` 自增 → Toast effect 依赖变化 → 计时重启（文案不变也不会提前消失）；不叠加第二个 Toast（同一实例） |
| E-6 | 组件在复制中途卸载 | `mountedRef` 守卫吞掉 `setState`；无 `Uncaught (in promise)`（全部 `await` 在 `try/catch/finally` 内） |
| E-7 | 报告未加载（`report === null`） | 按钮不可能出现（仅在 `report` 分支渲染），且 `copyMarkdown` 首行守卫 |
| E-8 | 复制进行中点「导出 .md」 | 允许（互不阻塞）；反之亦然 |
| E-9 | 重生成成功后 | `copyError`/`toast` 已清空，不残留上一轮提示 |
| E-10 | 失败后用户点「导出 .md」 | 完全独立路径，原样可用（手动兜底，AC-4 ③）；**不自动下载** |
| E-11 | 无障碍 | Toast `role="status"` + `aria-live="polite"`（不抢焦点、不打断朗读）；错误条既有 `role="alert"` |

### 5.3 明确不做（防跑偏）

- 不在复制链路里 `trim()`/补页头/补 BOM —— AC-2 的字节相等靠「零变换」成立（anti-goal 1）。
- 不用 `alert()`/`console.log()` 表达成功（`eslint no-console` 只是 warn，**不能靠 lint 兜**，靠断言 3 兜）。
- 不在失败分支 `setGenerated(null)`（anti-goal 3）。
- 不引入 `navigator.clipboard` polyfill、`clipboard` 三方库（断言 6 兜 `dependencies` 不变）。
- 不给 Toast 加裸色值/新视觉真源（anti-goal 5，断言 5 兜）。

## 6. 与 DESIGN/PRD 的两处显式对齐记录

1. **Hero 操作组位置**：DESIGN §2.5 描述为 Hero 右侧三按钮；现码是 `<Card>` 底部 `.sc-btn-row`（`sc-btn-row` 为 `flex-wrap` 左对齐）。本轮采用现码位置（复制插在导出左侧），不改为右对齐（`is-end`）——改版式会牵动报告页视觉，属 needDesign=false 禁区。验收以「复制按钮在导出按钮左侧、同一操作行」为判据。
2. **变体**：DESIGN 写「下载 .md」为次按钮，现码为 `primary`。本轮**不动**导出变体（AC-6 不回归），复制按钮用 `secondary`，与现码的「重新生成」同级。

## 7. 无浏览器静态断言门禁（`check_copy_markdown.mjs`）

路径：`logs/teamflow/tf-mvwcb4xd-6150nu/scripts/check_copy_markdown.mjs`（`node` 直跑，零依赖，只用 `node:fs`/`node:path`/`node:url`）。

- 仓库根解析：`path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..')`（`scripts → runId → teamflow → logs → 仓库根`）；若该处找不到 `frontend/package.json`，以中文信息退出 1（不猜 `process.cwd()`）。
- 输出格式：首行 `check_copy_markdown · runId=…`，随后每条 `PASS/FAIL  [AC-5.n] 断言说明`，FAIL 附 `detail`（命中片段/缺失锚点），末行 `RESULT: 7 PASS / 0 FAIL` → `exit 0`，否则 `exit 1`。
- 断言清单（前 6 条对应 PRD AC-5，第 7 条补 AC-6 的导出不回归；**只追加，不重造**）：

| # | 断言 | 判据（实现要点） |
|---|---|---|
| 1 | 存在 `navigator.clipboard.writeText(` 调用 | 在 `ReportPage.tsx` 源文本按字面量计数 `navigator.clipboard.writeText(` ≥ 1 |
| 2 | 入参来源单源且零变换 | 取 `copyMarkdown` 函数体（从 `const copyMarkdown` 到下一个顶层 `const ` 边界），断言同时含 `const text = await api.reportMarkdown(report.id)` 与 `navigator.clipboard.writeText(text)`，且该片段**不含** `.trim(`/`.replace(`/`.slice(`/`.substring(`/`.split(`/`JSON.stringify(`/`${text}`/`text + ` |
| 3 | 成功 Toast 文案原文 | `ReportPage.tsx` 含字面量 `已复制到剪贴板，可直接粘进笔记`；且 `setToast` 出现次数 == 1，位于 `writeText` 之后 |
| 4 | 失败不破坏页面 | `copyMarkdown` 内 `catch` 段含 `setCopyError(`；`ReportPage.tsx` 全文**不含** `setGenerated(null)`/`setReport(null)`/`navigate(`；无 `alert(`；无 `console.log` |
| 5 | Toast 样式只用 token | `base.css` 中 `.sc-toast` / `.sc-toast.is-closing` / `@keyframes sc-toast-in|out` 片段不含 `#`、`rgb(`、`hsl(`、`rgba(`；且含 `right: var(--sp-6)`、`bottom: var(--sp-6)`、`box-shadow: var(--elev-2)`、`var(--base)`（入）、`var(--fast)`（出）；`Toast.tsx` 无 `#`/`rgb(` |
| 6 | 无新增运行时依赖 | 解析 `frontend/package.json`，`dependencies` 深等于快照 `{react:^18.3.1, react-dom:^18.3.1, react-router-dom:^6.26.2}`；缺失/多出均 FAIL |
| 7 | 导出行为不回归（AC-6） | `ReportPage.tsx` 仍含 `text/markdown;charset=utf-8`、`anchor.download = markdownFileName(report)`、`function markdownFileName` 原实现（`诊断报告-` 前缀）；`tokens.css` 未被新增/删除 `--elev-2` 之外的改动（只校验 `--elev-2` 存在） |

首跑允许见 FAIL→修→全 PASS（PRD M2「首跑见 FAIL→修→全 PASS」是流程要求，不是产物）。

> 该脚本落在 `logs/teamflow/`（`.gitignore` 已整体忽略），**不进提交**；run 结束由 host 归档为留存物。检查器只读源文本，不写任何文件。

## 8. 测试策略

| 层 | 手段 | 本轮状态 |
|---|---|---|
| 类型 | `cd frontend && npm run typecheck`（tsconfig + tsconfig.node 双跑） | **必须 0 error** |
| 规范 | `cd frontend && npm run lint` | **必须 0 error**（`no-console` 为 warn，成功路径本就不写 console） |
| 行为 | `node logs/teamflow/tf-mvwcb4xd-6150nu/scripts/check_copy_markdown.mjs` | **必须 7 PASS / exit 0** |
| 单测 | `frontend/src/**/*.test.ts`（vitest） | **沙箱 spawn EPERM 不可执行**；不新增 `*.test.ts`（新测也跑不起来，只会留下「无法验证」的假证据） |
| 构建 | `npm run build` | 沙箱阻塞，同上；typecheck 已覆盖编译期 |
| 后端 | `pytest`/`ruff` | 本轮零后端改动，不重走；如跑得通则顺带跑 `python -m pytest -q` 作不回归旁证（不阻塞） |
| 人工补测（移交 QA/验收清单） | ① 真机粘贴比对「剪贴板 === 下载的 .md === 页面」；② 局域网 IP 下确认走失败分支；③ 视觉走查 Toast 右下 24 / `--elev-2` / 2s / 180-120ms | 沙箱无浏览器，属 R2/R3 |

**回归边界**：不跑全量 QA（PRD §7.1）；只需 AC-6 的 typecheck/lint + 断言 7（导出静态一致）。

## 9. 任务拆分（按文件所有权，可并行度已标注）

> 本需求未被 pipeline 预派任务，以下是平行化任务表；每项都带「只读依赖」与验收判据。

| 任务 | 文件（MODIFY，所有权） | 只读依赖（reads） | 依赖 | 验收判据 |
|---|---|---|---|---|
| **T1 · Toast 组件 + 样式段** | `frontend/src/components/ui/Toast.tsx`、`frontend/src/styles/base.css` | `styles/tokens.css`、`components/ui/InlineError.tsx`（风格参照） | 无（**与 T3 并行**） | Toast.tsx 导出 `Toast`/`ToastProps` 与 §3.2 逐字一致；base.css 追加 `.sc-toast` 段且零裸色值；`npm run typecheck`/`lint` 通过（此刻 ReportPage 尚未引用，独立可绿） |
| **T2 · ReportPage 复制接线** | `frontend/src/pages/ReportPage.tsx` | `components/ui/Toast.tsx`（T1 产物契约）、`api/client.ts`（`reportMarkdown`/`ApiError`）、`components/ui/Button.tsx`、`components/ui/InlineError.tsx` | **after T1**（要 import 真实文件才能 typecheck） | 按 §3.4 表格逐处落地；`copyMarkdown` 与 §5.1 一致；断言 1-4、7 可过 |
| **T3 · 静态断言检查器** | `logs/teamflow/tf-mvwcb4xd-6150nu/scripts/check_copy_markdown.mjs` | `frontend/src/pages/ReportPage.tsx`、`frontend/src/components/ui/Toast.tsx`、`frontend/src/styles/base.css`、`frontend/package.json`（只读） | 文件独立，**可与 T1 并行**；执行需 after T1+T2 | `node` 直跑输出 7 行 PASS；对 T2 的预期锚点全部命中；无外部依赖；退出码 0 |
| **T4 · 卫生收口 + 交付自检** | `.gitignore` | 上述全部产物、`git status` | **after T1–T3** | `.gitignore` 追加 `backend/tests/.tmp/`；typecheck+lint 0 error；检查器 7 PASS；`git status -uall` 只见 4 处预期改动（见 §10.3）；发现问题**当场修**，只记录结论（不写 QA/ACCEPTANCE 报告） |

并行图：`T1 ⇄ T3` → `T2` → `T4`（T2 与 T4 是硬序；T1 与 T3 文件不相交）。

## 10. 工程约束与 git 动作（PRD §7 原样承接，不得丢失）

### 10.1 分支

- 留在 `feat/dev-skill-coach`，**不新开分支**（PRD §7.5）。
- 自检记录：`git branch --show-current` 必须输出 `feat/dev-skill-coach`。

### 10.2 提交（由 host 收口，T4 只需准备好工作树）

- 提交内容：`frontend/src/components/ui/Toast.tsx`、`frontend/src/styles/base.css`、`frontend/src/pages/ReportPage.tsx`、`.gitignore`、`docs/teamflow/20261031-r2-ac5-copy-markdown/`（PRD/TECHNICAL，PRD 已存在）。
- 建议信息：`feat(report): 报告页一键复制 Markdown（AC-5 返工）`。
- **不提交**：`logs/teamflow/**`（`.gitignore` 已整体忽略；检查器由 host 归档到 `$DSH_HOME/teamflow/<workspace>/logs/<runId>/`）、`node_modules/`、`dist/`、临时脚本与命令输出。
- 不写项目根日志、不写宿主 `docs/<role>/`；本阶段只写 `docs/teamflow/20261031-r2-ac5-copy-markdown/TECHNICAL.md`。

### 10.3 预期工作树（T4 自检判据）

```
M  .gitignore
M  frontend/src/pages/ReportPage.tsx
M  frontend/src/styles/base.css
?? frontend/src/components/ui/Toast.tsx
?? docs/teamflow/20261031-r2-ac5-copy-markdown/       （PRD + TECHNICAL）
```

除以上 5 处外出现任何改动（尤其 `backend/**`、`api/**`、`lib/**`、`tokens.css`、`package.json`）即为越界，必须回退。

### 10.4 gitignore

追加独立小节：

```
# 后端测试临时目录（QA P3）
backend/tests/.tmp/
```

置于后端缓存小节之后，不重排既有行。

## 11. 风险与应对

| 风险 | 应对 |
|---|---|
| R1 剪贴板需安全上下文（`127.0.0.1` 可用、局域网 IP 下 `navigator.clipboard === undefined`） | E-1 失败分支 + 中文提示 + 导出兜底；不引入 `execCommand` |
| R2 「字节相等」无法在沙箱真机验证 | 三方支撑：断言 2（单源零变换）+ 后端 `services/markdown.py` 唯一渲染 + QA 阶段 `httpx` 取响应体比对；真机粘贴转人工补测 |
| R3 Toast 视觉/动效无法肉眼走查 | 规格写死于 base.css token 变量（`--sp-6`/`--elev-2`/`--radius-8`/`--base`/`--fast`），断言 5 兜「无裸色值 + 关键属性齐全」 |
| R4 首次引入 Toast 造成后续重复造轮子 | 本轮即团队唯一出口 `components/ui/Toast.tsx`，写入产品记忆（memory.md 已由 prd 阶段落「Toast 唯一出口」约定） |
| R5 `npm test`/`npm run build` 沙箱 EPERM | **不重试、不绕过**；门禁以 typecheck+lint+检查器为准，环境阻塞在 QA/验收一并记录 |

## 12. 验收自查清单（dev 交回时逐条对）

- [ ] AC-1 复制按钮在导出左侧、`secondary`、`loading` 时禁用
- [ ] AC-2 `writeText` 入参即 `api.reportMarkdown(report.id)` 返回值，零变换；后端未知改动
- [ ] AC-3 文案原文 + Toast 右下 24/`--elev-2`/2s/180-120ms；无 `alert`、无 `console`
- [ ] AC-4 失败 → 页内 `InlineError`（中文 + 「重新复制」）；报告不空不跳；导出可用；无 Toast 承载失败；无未捕获 rejection
- [ ] AC-5 检查器 7 条 PASS、退出码 0、`node` 直跑无依赖
- [ ] AC-6 `npm run typecheck`、`npm run lint` 0 error；导出分支与文件名规则未改
- [ ] 工作树只含 §10.3 五处；分支仍在 `feat/dev-skill-coach`
- [ ] `logs/teamflow/` 下的检查器未被提交
