# ACCEPTANCE — r2 · AC-5「报告页一键复制 Markdown」最终验收

> 任务夹 `docs/teamflow/20261031-r2-ac5-copy-markdown/` · runId `tf-mvwcb4xd-6150nu` · 分支 `feat/dev-skill-coach` · 验收人：产品经理（验收 Lead）
> 基线依赖：`docs/teamflow/20261031-r1-dev-skill-coach`（本轮只补 r1 唯一阻塞项 R-1，不取代任何既有 AC）

## 0. 结论速览

**验收通过**：PRD 的 AC-1~AC-6 全部由**本轮亲自复跑的**可执行证据驱动到终态（非存在性检查）；实现逐条符合注入的模块蓝图，未发现重复实现 / 适配漂移 / 既有结构破坏；4 条 P3 观察项与 6 项环境受限人工补测列入遗留，不构成返工。r1 的唯一阻塞项 **R-1 关闭**。

## 1. 逐条 AC 核对

| AC | PRD 判据 | 实测证据（本轮复跑） | 判定 |
|---|---|---|---|
| AC-1 复制按钮 | Hero 右侧次按钮、「导出 .md」左侧、40 高 secondary、复制中 loading 且禁用重复点击 | `ReportPage.tsx:250-252` 复制按钮（`secondary` `loading={copying}`）位于 `:253` 导出 .md 之前；`.sc-btn { height: var(--btn-h) }` = `tokens.css:108` 40px；行为门禁 `[AC-1.1] PASS`（copy@0 < export@1、variant=secondary、初始预取 0 次），忙态期间二次点击未产生第二次请求 | ✅ |
| AC-2 单源零变换 | 剪贴板文本 === `api.reportMarkdown(id)` === `GET /api/reports/{id}/markdown` 响应体，前端无 trim/replace/拼接/插值 | `ReportPage.tsx:150-162` 能力前置判断 → `const text = await api.reportMarkdown(report.id)` → `await navigator.clipboard.writeText(text)`（零变换）；行为门禁 `[AC-2/AC-3] PASS`：writeText 入参 **103B 与响应体字节相等**（含结尾 `\n`）、markdown 请求 1 次；后端唯一渲染 `backend/app/routers/report.py:38 → to_markdown(report)`；静态断言 `[AC-5.2] PASS`（10 项变换黑名单全未命中，函数体切片 885 字符） | ✅ |
| AC-3 成功 Toast | 文案原文、右下 24、`--elev-2`、2s 停留、180/120ms 淡入淡出、禁止 alert/console | 字面量 `ReportPage.tsx:22` 逐字「已复制到剪贴板，可直接粘进笔记」；`Toast.tsx` 自持计时（`durationMs=2000`、`EXIT_MS=120`、双 `clearTimeout`）+ `role="status" aria-live="polite"`；`base.css:599-640` `right/bottom: var(--sp-6)`=24px、`box-shadow: var(--elev-2)`、`sc-toast-in var(--base)`(180ms)/`sc-toast-out var(--fast)`(120ms)，14 个 `var(--)` 均在 `tokens.css` 有定义；行为门禁实测停留 **2034ms**、退场 **209ms**；`grep alert(/console. ReportPage.tsx` = 0 命中 | ✅ |
| AC-4 失败不破坏页面 | 页内 `InlineError`（中文+重试）、报告不清空不跳转、导出 .md 保留兜底、不用 Toast 承载失败、无未捕获 rejection | 行为门禁三条失败路径全 PASS：① `NotAllowedError` →「浏览器拒绝访问剪贴板，请改用「导出 .md」手动保存」+「重新复制」，无 Toast、2 张短板卡仍渲染、rejection 0、重试后请求 2 次；② `navigator.clipboard` 缺失 → 能力判断拦在 fetch 之前（**markdown 请求 0 次**）；③ markdown 503 → 后端中文 `message` 直出 `InlineError`、报告与导出兜底保留；`ReportPage.tsx:167` catch 只写 `copyError`，`finally` 用 `mountedRef` | ✅ |
| AC-5 静态门禁 | `check_copy_markdown.mjs` node 直跑、六条结构化断言、PASS/FAIL、退出码 0\|1 | `node logs/teamflow/tf-mvwcb4xd-6150nu/scripts/check_copy_markdown.mjs` → **7 PASS / 0 FAIL, exit 0**（6 条 PRD 断言 + AC-5.7 导出不回归）；repo 根与 `frontend/` cwd 各跑一次均 exit 0（cwd 无关）；**负向自检有效**：QA 在 HEAD 快照树得 `2 PASS / 5 FAIL, exit 1`，本轮 `COPY_BEHAVIOR_MUTATE=trim\|console-only` 均 `5 PASS / 1 FAIL, exit 1` | ✅ |
| AC-6 既有门禁不回归 | `npm run typecheck` + `npm run lint` 0 error；AC-9 导出（同一 Blob 文本源与文件名规则）不回归 | `npm run typecheck` exit 0（tsc + tsconfig.node 双通道）；`npm run lint` exit 0，**0 error / 18 warning**（全部为既有他文件 `react-refresh`，`npx eslint ReportPage.tsx Toast.tsx` 专项 exit 0 零告警）；行为门禁 `[AC-6] PASS`：`诊断报告-2026-10-31.md`、`text/markdown;charset=utf-8`、Blob 正文 === 同一 103B 响应体；`git diff -- frontend/package.json backend/` 为空；`pytest -q` 73 全绿（后端零改动防连带） | ✅ |

## 2. 架构一致性（M3 质量门）

| 蓝图条目 | 实现核对 | 判定 |
|---|---|---|
| `components/ui/Toast.tsx`，`ToastProps {message; seq?; durationMs?; onClose}`，自持 2s/120ms 计时，退场期仍挂载 | 实码逐字一致（`Toast.tsx:6-44`）：`closing` 由组件持有、退场期元素仍渲染、`onClose` 走 ref 避免父级内联箭头重启计时、`deps=[message,seq,durationMs]` | ✅ |
| 不提供 error tone（堵死误用） | 组件无 variant/tone 属性，注释声明「刻意不提供 error tone」 | ✅ |
| `base.css` 追加 `.sc-toast` / `.sc-toast.is-closing` / `@keyframes sc-toast-in\|out`，只走 token，不新建 css | `base.css:598-649` 位于「页内错误/空态」与「上传拖放区」之间；零裸色值、零新 token（`tokens.css` 无 diff）；`z-index: 20` 沿用 `.sc-topbar` 的 10 先例（tokens 无 z 轴 token） | ✅ |
| `ReportPage` 三态 + `copyMarkdown()` + `clipboardErrorMessage` + `COPY_TOAST_MESSAGE`，按钮插在导出左侧，Toast 渲染在 section 末 | 三态 `:75-77`、`copyMarkdown` `:150`、helper `:49`、常量 `:22`、按钮 `:250`、Toast `:329`；导出分支一行未改 | ✅ |
| 检查器 `check_copy_markdown.mjs`，`REPO_ROOT=scriptDir/../../../..`，末行 RESULT + 退出码，只读源文本、不提交 | 实测 cwd 无关、7/7 PASS；`logs/teamflow/` 被忽略未提交 | ✅ |
| `.gitignore` 追加 `backend/tests/.tmp/`（独立小节，不重排既有行） | `git diff .gitignore` = +2 行（注释 + 规则），`git check-ignore -v backend/tests/.tmp/` 命中 `.gitignore:30` | ✅ |

**重复实现 / 抽象核查**：全仓 `.sc-toast` 仅 1 段样式、Toast 仅 1 个组件实现、无第二套反馈组件；`InlineError` 仍是唯一失败出口（复制失败直接复用，`role="alert"` 保留）；无 `execCommand` 兼容层、无落盘兜底、无三方剪贴板库（依赖深等基线）。`api.reportMarkdown` 在页面内 2 处（复制 + 既有导出）是蓝图 §0 D-3 的**已记录取舍**（导出零回归），且被 AC-5.7 钉为不变量——判为取舍而非架构缺陷。

**既有结构完整性**：`tokens.css` 未触碰（无新 token，DESIGN §0.7 无需复算）；`base.css` 追加段括号平衡、未重排既有小节；契约与后端零改动（`git diff backend/` 为空）；构建/测试脚本未改。

## 3. 交付面与边界卫生

`git status --porcelain=v1 -uall` 共 6 条，全部属预期交付面：`M .gitignore`、`M docs/teamflow/memory.md`、`M frontend/src/pages/ReportPage.tsx`、`M frontend/src/styles/base.css`、`?? frontend/src/components/ui/Toast.tsx`、`?? docs/teamflow/20261031-r2-ac5-copy-markdown/`（PRD/TECHNICAL/QA-REPORT/meta.json）。无 `node_modules`/`dist`/`__pycache__`/`.env`/工具缓存入树；项目根无 `scripts/`、`probe/`、命令输出 dump；文档只落 `docs/teamflow/`，`AGENTS.md` 未动（无 changelog 段）；`logs/teamflow/` 未提交、由 host 归档。

## 4. 遗留与意见（不阻塞验收）

- **P3-1** 复制进行中仍可点「重新生成」（`ReportPage.tsx:253` 仅 `disabled={exporting}`）→ 存在「复制旧报告文本 + Toast 却提示已复制」的语义错位；建议下一轮把 `copying` 并入重新生成按钮的禁用条件。
- **P3-2** Toast 的 `role="status"` 与文案同时挂载，部分读屏可能不朗读；建议改为常驻空的 live 区、再变更其文本（需扩展 AC-3 断言）。
- **P3-3** Toast 未用 `env(safe-area-inset-*)` 规避移动端底部工具栏；项目全局样式均未使用，属既有约定，保持一致性即可。
- **P3-4** 检查器按 PRD/TECHNICAL 明确约束落在 `logs/teamflow/<runId>/scripts/`（gitignored），干净 clone 中无常驻 AC-5 门禁；建议后续把等价断言并入可常驻的前端测试（`vitest` 可执行后）。
- **取舍兑现**：复制与导出各自调用一次 `api.reportMarkdown`（导出零回归）；若未来抽共享 helper，必须同步改 AC-5.2 / AC-5.7 断言。
- **人工补测 H1–H6**（环境限制，非交付缺陷）：真机粘贴字节比对、非安全上下文（局域网 IP）行为、Toast 视觉/动效走查、读屏朗读、`npm test`+`npm run build`、`ruff`。本沙箱无浏览器且 `vite build`/`vitest` spawn EPERM、`ruff` 未安装。

## 5. 复跑指引（本需求的回归契约）

```bash
node logs/teamflow/tf-mvwcb4xd-6150nu/scripts/check_copy_markdown.mjs   # 静态门禁 7 条，exit 0/1
node logs/teamflow/tf-mvwcb4xd-6150nu/scripts/check_copy_behavior.cjs   # 行为门禁 6 条，exit 0/1
COPY_BEHAVIOR_MUTATE=trim node logs/teamflow/tf-mvwcb4xd-6150nu/scripts/check_copy_behavior.cjs  # 负向自检，应 exit 1
cd frontend && npm run typecheck && npm run lint
cd backend && python -m pytest -q -p no:cacheprovider
```

## 6. 验收决定

AC-1~AC-6 全绿、架构符合蓝图且无重复实现、交付面干净；4 条 P3 与 6 项人工补测均可平移至下一批次，**无需返工**。r1 遗留阻塞项 R-1 在本轮关闭，产品记忆 `docs/teamflow/memory.md` 已同步勾掉该待办行。

验收结论：✅ 通过
