# QA-REPORT · 20261031-r2-ac5-copy-markdown

R2 返工（仅补 AC-5「报告页一键复制 Markdown」）的功能级测试报告。QA 轮次：`tf-mvwcb4xd-6150nu`。

## 0. 结论速览

**验收就绪（acceptance-ready）**：未发现 P0/P1/P2 缺陷；P3 观察项 4 条（不阻塞）。AC-1 / AC-2 / AC-3 / AC-4 / AC-6 全部由**已执行**的门禁驱动到终态（不是存在性检查），AC-5 的静态门禁本身也做了负向自检（改动前树 5 FAIL / 注入违规必 FAIL）。唯一未验部分是环境限制项（见我司无法执行的真浏览器粘贴、`vite build` / `vitest`、`ruff`），已列入「人工补测清单」。

> AC-2 的「剪贴板文本 === 响应体 === 后端渲染」由三方支撑：① 前端字节相等（行为门禁实测 `writeText` 入参 === 响应体原文 103B，含结尾 `\n`）② 后端唯一渲染源 `backend/app/routers/report.py:33` → `to_markdown(report)`（本轮后端零改动）③ 静态断言 AC-5.2 钉死「writeText 前 10 项变换黑名单」。真机粘贴比对转人工（见 §6）。

## 1. 范围与环境

- 被测交付：`frontend/src/components/ui/Toast.tsx`（新增）、`frontend/src/styles/base.css`（+Toast 段）、`frontend/src/pages/ReportPage.tsx`（复制接线）、`.gitignore`、`logs/teamflow/tf-mvwcb4xd-6150nu/scripts/check_copy_markdown.mjs`（AC-5 门禁）。
- 不在本轮范围：后端与 HTTP 契约（`git diff backend/` 为空）、其余 AC-7/AC-8/AC-9/AC-10（r1 已验收）。
- 分支 `feat/dev-skill-coach`（按 PRD 约束不新开分支、未 commit）。
- 环境：Windows / node v22.22.2 / Python 3.13.9；沙箱限制：无浏览器（进程 token 限制，`--no-sandbox` 无效）、`vite build`/`vitest` spawn EPERM、`ruff` 未安装。**这些是环境限制，不是交付缺陷。**

## 2. 用例与结果

| 编号 | 用例 | 关联 AC | 执行命令 | 结果 |
|---|---|---|---|---|
| C1 | 类型门禁 | AC-6 | `cd frontend && npm run typecheck` | PASS（exit 0，0 error） |
| C2 | 风格门禁 | AC-6 | `cd frontend && npm run lint` | PASS（exit 0，0 error / 18 warning 全为既有他文件 `react-refresh`） |
| C3 | AC-5 静态断言门禁 | AC-5 | `node logs/teamflow/tf-mvwcb4xd-6150nu/scripts/check_copy_markdown.mjs`（repo 根 + `frontend/` cwd 各一次） | PASS（7 PASS / 0 FAIL，exit 0，cwd 无关） |
| C4 | C3 的负向自检（门禁有效性） | AC-5 | 同脚本副本跑 `HEAD` 快照树（`probe/head`，无 Toast.tsx、无复制接线） | PASS（`RESULT: 2 PASS / 5 FAIL`，exit 1 —— 证明不是橡皮章） |
| C5 | 行为门禁：真实源码 + 真实计时器 | AC-1/2/3/4/6 | `node logs/teamflow/tf-mvwcb4xd-6150nu/scripts/check_copy_behavior.cjs` | PASS（6 PASS / 0 FAIL，exit 0） |
| C6 | C5 的负向自检（3 组注入违规） | AC-2/3/4 | `COPY_BEHAVIOR_MUTATE=trim\|console-only\|toast-on-failure node <C5 脚本>` | PASS（三组均 exit 1，且分别命中 AC-2 字节相等、AC-3 Toast 缺失、AC-4 失败路径 3 条断言） |
| C7 | 后端回归（本轮零改动，防连带） | AC-6 | `cd backend && python -m pytest -q -p no:cacheprovider` | PASS（exit 0，73 tests 全绿） |
| C8 | 提交面卫生 | 0c | `git status --porcelain=v1 -uall` + `git check-ignore -v` | PASS（8 条均属预期交付面；依赖/构建/缓存/密钥全部命中忽略） |
| C9 | 依赖不漂移 | AC-5.6/AC-6 | `git diff -- frontend/package.json backend/` + 检查器断言 6 | PASS（空 diff；`dependencies` 3 项深等于基线） |
| C10 | 交付文档位置 | 边界 | `git status` 中 `docs/teamflow/**` | PASS（仅任务夹 3 文件 + `memory.md` 原位更新，无 changelog 段） |
| B1 | `npm test`（vitest） | - | `cd frontend && npm test` | **BLOCKED**（spawn EPERM，环境限制；已用 C5 行为门禁替代覆盖） |
| B2 | `npm run build`（vite） | - | `cd frontend && npm run build` | **BLOCKED**（spawn EPERM，环境限制） |
| B3 | `ruff` | - | `cd backend && python -m ruff check app tests` | **BLOCKED**（No module named ruff，环境限制） |

### C5 行为门禁的逐条结果（真实组件 + 真实 `setTimeout`，fetch/clipboard 为唯一外部替身）

| 断言 | 内容 | 实测证据 |
|---|---|---|
| AC-1.1 | 复制按钮在「导出 .md」左侧、`secondary`、初始非 loading | `copy@0 < export@1`；`variant=secondary`；挂载阶段 markdown 预取 0 次 |
| AC-2 | 成功复制 `writeText` 入参 === 响应体原文（单源一次） | writeText 调用 1 次、入参 103B **字节相等**（含结尾 `\n`，无 trim/拼接）；markdown 请求 1 次 |
| AC-1.2 | 复制中 loading 且禁用重复点击 | 真实 `Button` 渲染 `<button disabled=true aria-busy=true class` 含 `is-loading`）`；忙态期间二次调用未产生第 2 次请求 |
| AC-3 | Toast 文案原文 + 2s 停留 + 120ms 淡出 + role/aria | 文案「已复制到剪贴板，可直接粘进笔记」原文；`role="status"` `aria-live="polite"`；停留实测 **2042ms**、`is-closing` 后退场实测 **211ms**（含 flush 延迟，均在容差内）；超时后 vnode 卸载 |
| AC-4.1 | 剪贴板拒绝 → 页内 InlineError 中文 + 重试 | `NotAllowedError` → 「浏览器拒绝访问剪贴板，请改用「导出 .md」手动保存」+「重新复制」；无 Toast；2 张短板卡仍在、`面试均分` 仍在；无未捕获 rejection；重试后 markdown 请求 2 次 |
| AC-4.2 | 非安全上下文 `navigator.clipboard` 缺失 | 「当前浏览器不支持剪贴板复制…」+「重新复制」；**markdown 请求 0 次**（能力前置判断拦在 fetch 之前）；页面不清空 |
| AC-4.3 | markdown 接口 503 中文错误信封 | 后端中文 `message` 直出 InlineError；无 Toast、无剪贴板写入、报告保留 |
| AC-6 | 导出 .md 不回归 | `诊断报告-2026-10-31.md`；Blob `text/markdown;charset=utf-8`；Blob 正文 === 同一响应体 103B；导出走唯一 markdown 端点 1 次；导出成功无错误条 |

### 静态核对（被 C3 覆盖并由 C5 动态佐证）

- `ReportPage` 复制分支持有 `copying/copyError/toast` 三态；`copyMarkdown` 能力前置判断 → `api.reportMarkdown(report.id)` → `writeText(text)`（零变换）→ `setToast(seq+1)`。
- 失败一律 `setCopyError` → `InlineError`；全文件无 `alert(` / `console.`（`grep -n "alert(\|console\." ReportPage.tsx` → NONE）。
- Toast 段 14 个 `var(--)` 全部在 `tokens.css` 有定义；`--sp-6: 24px`（右下 24）、`--base: 180ms`（淡入）、`--fast: 120ms`（淡出）、`--elev-2`、`--btn-h: 40px`（40 高按钮）实测匹配 AC-3/AC-1 的数值要求；`prefers-reduced-motion` 由既有全局规则（`base.css:1230`）覆盖。
- `z-index: 20` 为裸值：`tokens.css` 无 z 轴 token，沿用 `.sc-topbar` 的 10 先例，符合蓝图取舍。

## 3. 架构核对（M3 质量门）

**蓝图符合性**（逐条对照注入的模块蓝图，全部符合、无重建）：

| 蓝图条目 | 实现 | 判定 |
|---|---|---|
| `components/ui/Toast.tsx`，`ToastProps {message; seq?; durationMs?; onClose}`，自持 2s/120ms 计时，退场期仍挂载 | 实码一致：`closing` 态由组件持有、双 `clearTimeout`、`onClose` 走 ref；`seq` 在 deps 中 | ✅ |
| 不提供 error tone（堵死误用） | 组件无 variant/tone，注释亦声明 | ✅ |
| `base.css` 追加 `.sc-toast` / `.sc-toast.is-closing` / `@keyframes sc-toast-in\|out`，只走 token，不新建 css 文件 | 追加在「页内错误/空态」段后、「上传拖放区」前，零裸色值、零新 token（`git status` 无 `tokens.css` 改动） | ✅ |
| `ReportPage` 三态 + `copyMarkdown()` + `clipboardErrorMessage` + `COPY_TOAST_MESSAGE`，按钮插在导出左侧，Toast 渲染在 section 末 | 逐处命中；导出分支一行未改 | ✅ |
| 检查器 `check_copy_markdown.mjs`，`REPO_ROOT = scriptDir/../../../..`，末行 `RESULT` + 退出码，只读源文本、不提交 | 实测 repo 根与 `frontend/` cwd 均 7 PASS、exit 0；`git check-ignore` 命中 `logs/teamflow/` | ✅ |
| `.gitignore` 追加 `backend/tests/.tmp/`（独立小节，不重排既有行） | `git diff` +2 行；`git check-ignore -v backend/tests/.tmp/` 命中 `.gitignore:30` | ✅ |

**重复实现 / 抽象核查**：

- 全仓 `Toast`/`.sc-toast` 只有**一份**组件实现 + **一段**样式（`grep -rn "sc-toast\|Toast"` 除 Toast.tsx 外仅 ReportPage 的接线与 base.css 的样式段）——没有第二套反馈组件、没有手搓 `alert`/自定义 div。
- `InlineError` 仍是**唯一**失败出口（本次新增的复制失败直接复用它，`role="alert"` 保留）；失败路径无 Toast（C5 AC-4.1/4.2/4.3 实测）。
- 无 `execCommand` 兼容层、无落地盘兜底、无三方剪贴板库（`dependencies` 深等基线）。
- **本次刻意保留的重复（非漂移）**：`api.reportMarkdown` 在页面内出现 2 处（复制 + 既有导出）。与蓝图 §0 D-3 的取舍一致（导出零回归），并由 AC-5.7 断言把「2 处」钉成不变量；若未来抽共享 helper 必须同步改断言 2。判为**已记录的取舍，非架构缺陷**。
- 抽象未抽取判定：复制逻辑留在页面内、未新建 helper/store 层，符合「只做这一项」的约束；未出现过度抽象，也无跨模块重复。

**接口一致性（0a，静态可证）**：

- `tsc --noEmit`（C1）exit 0 覆盖全部导入的事实存在与签名匹配；另人工核对：
  - `api.reportMarkdown: (reportId: string) => Promise<string>`（`api/client.ts:133`）← 调用 `api.reportMarkdown(report.id: string)` ✅
  - `ApiError` 构造 4 参 `(code, message, status, retryable)`（`client.ts:29`）← `CLIPBOARD_UNAVAILABLE` 处 4 参 ✅
  - `ButtonProps {variant?, size?, loading?}`（`Button.tsx:6`）← `<Button variant="secondary" loading={copying}>` ✅
  - `InlineErrorProps {message, onRetry?, retryLabel?}`（`InlineError.tsx:3`）← 复制错误条 ✅
  - `Toast` 导出/导入路径一致；`requestText` 返回 `response.text()` 原样（无二次处理）✅
- 运行时佐证：C5 通过内存 CJS 加载器**真实 import 并执行**了 `ReportPage.tsx → Toast.tsx / Button.tsx / InlineError.tsx / api/client.ts` 全链（类型转译 + 实际运行），模块图可在运行时解析，不存在「存在但死掉」的导入。

**既有结构完整性**：`tokens.css` 未被触碰；`base.css` 追加段位于既有小节之间；失败/成功反馈职责边界（Toast=成功、InlineError=失败）代码形状上即被强制，未与既有导出错误模式冲突。

## 4. 提交面卫生（0c）

`git status --porcelain=v1 -uall` 共 8 条，全部属预期交付面：`M .gitignore`、`M docs/teamflow/memory.md`、`M frontend/src/pages/ReportPage.tsx`、`M frontend/src/styles/base.css`、`?? frontend/src/components/ui/Toast.tsx`、任务夹 3 文件（PRD/TECHNICAL/meta.json）。无 `node_modules/`、`dist/`、`__pycache__/`、`.env`、工具缓存或 IDE 文件进入工作树；`git check-ignore -v` 实测命中 `node_modules/`、`dist/`、`__pycache__/`、`backend/tests/.tmp/`、`logs/teamflow/`。项目根无 `scripts/`、`probe/`、命令输出 dump。

## 5. 缺陷表

未发现 P0/P1/P2 缺陷。以下 4 条为 **P3 观察项**（不阻塞验收，按工艺维度记录）。

| 编号 | 严重级(P0/P1/P2/P3) | 功能模块 | 复现步骤 | 期望行为 | 实际行为 | 关联验收项 | 检测命令 | 通过判据 |
|---|---|---|---|---|---|---|---|---|
| P3-1 | P3 | 报告页·交互 | 点「复制 Markdown」后在请求未返回（约 80ms 内）立即点「重新生成」 | 复制中的动作应与重新生成互斥，避免「复制旧报告 + Toast 说已复制」的语义错位 | 「重新生成」仅 `disabled={exporting}`，复制中可点；点击会 `setToast(null)`/`setCopyError(null)`，在途复制仍以旧报告文本成功并再弹 Toast（`ReportPage.tsx:253`） | AC-1 | - | -（观察项） |
| P3-2 | P3 | 无障碍·Toast | 开启屏幕阅读器后触发一次复制 | 成功提示被朗读 | Toast 以 `role="status"` 与内容**同时挂载**（aria-live 区域应先空存在、再变更内容），部分读屏可能不朗读 | AC-3 | - | -（观察项） |
| P3-3 | P3 | 视觉·Toast | 半屏/移动端浏览器（底部工具栏可变高）下触发复制 | Toast 不被底部工具栏遮挡 | `bottom: var(--sp-6)` 未使用 `env(safe-area-inset-*)`（项目全局样式均未使用，属既有约定） | AC-3 | - | -（观察项） |
| P3-4 | P3 | 交付形态·门禁 | 在干净 clone 上执行 AC-5 门禁 | 检查器可长期复跑 | 检查器按 PRD/TECHNICAL 约束落在 `logs/teamflow/`（gitignored），随 run 归档保活、不常驻产品仓库，故干净 clone 中不存在 AC-5 门禁 | AC-5 | - | -（观察项） |

## 6. 人工补测清单（环境限制，非交付缺陷）

| # | 项 | 验收判据 | 方法 / 工具 |
|---|---|---|---|
| H1 | 真机剪贴板粘贴一致性（AC-2 第四方证据） | 粘贴文本与「导出 .md」下载的 `.md` **字节相同**（含结尾换行、无页头增补） | 浏览器（Chrome/Firefox）打开 `http://127.0.0.1:8000/report`（安全上下文）→ 点「复制 Markdown」→ 粘贴进编辑器，与导出的 `.md` diff |
| H2 | 非安全上下文真机行为（AC-4 风险项） | 局域网 IP 访问下 `navigator.clipboard` 为 undefined 时出页内中文提示、不白屏不静默 | 以 `http://<局域网IP>:8000/report` 访问后点复制，观察 InlineError |
| H3 | Toast 视觉/动效走查（AC-3 观感） | 右下 24、`--elev-2` 阴影、180ms 淡入、120ms 淡出、不遮挡顶栏与正文 | 浏览器 DevTools 慢放（0.25x）动画；截图比对 DESIGN |
| H4 | Toast 朗读（a11y，对应 P3-2） | 读屏能播报成功文案 | VoiceOver / NVDA 触发一次复制 |
| H5 | 前端既有测试与构建（`npm test` / `npm run build`） | 全绿 | 宿主环境（非 agent 沙箱）执行 `cd frontend && npm test && npm run build` |
| H6 | 后端静态检查（`ruff`） | 0 error | 宿主环境 `cd backend && python -m ruff check app tests` |

## 7. 复跑指引（本需求的回归契约）

```bash
# AC-5 静态门禁（7 条断言，exit 0/1）
node logs/teamflow/tf-mvwcb4xd-6150nu/scripts/check_copy_markdown.mjs
# 行为门禁（6 条，真实源码 + 真实计时器，无需浏览器，exit 0/1）
node logs/teamflow/tf-mvwcb4xd-6150nu/scripts/check_copy_behavior.cjs
# 负向自检（证明门禁有效，均应 exit 1）
COPY_BEHAVIOR_MUTATE=trim node logs/teamflow/tf-mvwcb4xd-6150nu/scripts/check_copy_behavior.cjs
cd frontend && npm run typecheck && npm run lint
cd backend && python -m pytest -q -p no:cacheprovider
```

> 说明：`check_copy_behavior.cjs` 读真实 `frontend/src` 源码，经 `typescript.transpileModule` 内存转译后由一个 hook harness 执行真实组件函数；计时器是真实 `setTimeout`（刻意不用假时钟，避免「计时器从不触发」被掩盖）；`fetch`/`navigator.clipboard` 是唯一外部替身。`COPY_BEHAVIOR_MUTATE` 仅用于负向自检，正常门禁不受影响。
