# PRD · AC-5 报告页「复制 Markdown」

<!-- meta: summary="为诊断报告页补齐「复制 Markdown」次按钮（复用 api.reportMarkdown 单一文本源 + 成功 Toast + 失败页内提示），并配一个无需浏览器的静态断言检查器，闭合 r1 验收 R-1 阻塞项。" -->

基线依赖：docs/teamflow/20261031-r1-dev-skill-coach（其 AC-5 报告主体（≥3 条短板/证据/建议/严重度）、AC-9 `GET /api/reports/{id}/markdown` 同源导出、DESIGN.md §2.5 视觉与 Toast 规格已交付，本轮不得回归）

## 1. 背景与目标

上一轮验收（`docs/teamflow/20261031-r1-dev-skill-coach/ACCEPTANCE.md`）唯一阻塞项 R-1：AC-5 要求的「一键复制为 Markdown 文本」未实现——`frontend/src` 中 `clipboard|writeText` 零命中，`ReportPage.tsx` 只有「导出 .md」，`components/ui/` 无 Toast。

本轮**不是新功能**，是把 AC-5 的复制路径按 DESIGN §2.5 补全，并留下可复跑的断言，使 AC-5 可被复验为 PASS。目标：

- 用户一键把当前诊断报告文本放进剪贴板，粘进笔记/工单时格式完整。
- 复制文本与导出 `.md`、页面展示三者**同源**（仍只由 `backend/app/services/markdown.py` 渲染，前端零拼串）。
- 成功有轻量反馈、失败有明确中文提示且**不破坏报告页**，并保留手动导出兜底。
- 在无浏览器可用的沙箱里，用静态检查器把上述行为钉成可执行断言（typecheck/lint 之外的第二道门禁）。

## 2. 用户故事与验收标准（本文件夹内编号 AC-1~AC-6）

**US-1** 作为找工作的开发者，我要把诊断报告一键复制走，这样我能贴进简历修改笔记或私聊里给朋友看。
**US-2** 作为复验者，我要能证明「复制的文本 = 导出 .md = 页面」是同一份内容，这样我不必担心两份内容对不上。
**US-3** 作为复制失败的用户，我要看到中文原因并能改用手动导出，这样我不会以为报告丢了。

- **AC-1（P0）按钮存在与位置**：报告生成完成后，Hero 右侧操作组出现次按钮「复制 Markdown」，位于「导出 .md」左侧（DESIGN §2.5「次按钮「复制 Markdown」、次按钮「下载 .md」、幽灵「重新测评」」）；文案中文、与既有按钮同规格（40px 高、`secondary` 变体）；复制进行中按钮呈 loading 且禁用，连点不产生第二次相同的写剪贴板调用。
- **AC-2（P0）文本源单源且零变换**：点击复制写入剪贴板的字符串 === `await api.reportMarkdown(report.id)` 的返回值 === `GET /api/reports/{id}/markdown` 响应体；前端对该字符串**不做任何变换**（无 `trim()` / `replace()` / `slice()` / 前后拼标题 / 模板插值 / `JSON.stringify`）。契约不变：文本仍只由 `backend/app/services/markdown.py` 渲染。
- **AC-3（P0）成功反馈**：成功后出现 Toast，文案原文「已复制到剪贴板，可直接粘进笔记」，右下 24 定位、`--elev-2`、停留 2s、淡入 180ms / 淡出 120ms（DESIGN §0.7/§4）；以 `alert()` 或仅 `console.log` 表达成功一律不通过。Toast 组件放在 `frontend/src/components/ui/`，样式只用 `styles/tokens.css` 变量。
- **AC-4（P0）失败路径不破坏页面**：任一失败（`navigator.clipboard` 不存在/非安全上下文、权限被拒、`writeText` reject、接口 4xx/5xx）都表现为：① 页内 inline 错误条（中文原因、带「重试」），② 报告内容仍完整可见、不跳转、不清空、无整页白屏，③ 「导出 .md」仍可用作手动兜底，④ **不用 Toast 承载失败**（DESIGN §4「禁止只用 Toast 承载失败」），⑤ 无未捕获的 Promise rejection（不出现 `Uncaught (in promise)`）。
- **AC-5（P0）无浏览器等效断言门禁**：新增 `logs/teamflow/<runId>/scripts/check_copy_markdown.mjs`（`node` 直接跑，不依赖浏览器、不依赖 `vite`/`vitest`/构建产物），至少断言 6 条结构化事实并逐条打印 PASS/FAIL、总体退出码 0（全 PASS）/ 1（有 FAIL）：
  1. `ReportPage.tsx` 中存在 `navigator.clipboard.writeText(` 调用；
  2. 其入参来源链含 `api.reportMarkdown(`（或 `useAsync`/同一 `requestText` 出口），且该字符串在传入 `writeText` 前无变换调用；
  3. 成功分支设置 Toast 文案「已复制到剪贴板，可直接粘进笔记」原文；
  4. 失败分支写入页内错误状态，且不存在把报告置空的写法（如 `setReport(null)`）；
  5. Toast 组件样式中只有 `var(--…)`，无 `#`/`rgb(`/`hsl(` 裸色值；
  6. 未新增运行时依赖（`frontend/package.json` 的 `dependencies` 不变）。
- **AC-6（P0）既有门禁全绿且不回归**：`npm run typecheck` 与 `npm run lint` 均 0 error（`npm run build` / `npm test` 在沙箱不可执行，见 §8）；AC-9 导出行为不变（仍以 Blob 落盘同一文本，文件名规则不动）；报告页其余区块（短板卡、课程映射、历史对比入口）渲染与交互不变。

## 3. 范围与非目标

**范围内**：`ReportPage.tsx` 的复制接线、`components/ui/Toast.tsx`（首次引入）、必要的状态（复制中/成功/失败）、一个 `node` 静态检查器、`backend/tests/.tmp/` 的 `.gitignore` 补齐。

**非目标（明确不做）**：不实现报告内容/排序/证据的任何变化；不改 `services/markdown.py` 与任何后端接口契约；不做「复制单条短板」「复制课程清单」等切片复制；不做剪贴板历史/剪贴板富文本（`text/html`）；不重做 UI 设计（DESIGN §2.5 已定稿，needDesign=false）；不重走全量 QA 套件；不引入剪贴板三方库。

## 4. anti-goals / 反面目标

即使 `typecheck`/`lint` 全绿、检查器全 PASS，下列任一情况发生，人仍然会判定这次返工失败：

1. **粘出来的文本和导出的 .md 不是同一份**：例如复制前顺手 `trim()` 或补了一个「# 诊断报告」页头，导致笔记里与文件里差几行——用户拿两份内容对账时发现不一致。
2. **点了按钮什么也看不见**：成功只写 `console.log`，用户不确定是否复制成功，于是连点 3 次。
3. **失败时报告页变空/变白**：一次剪贴板拒绝就让人以为报告丢失，或页面直接跳走。
4. **失败时自动往磁盘塞一个 .md**：用户没点导出却多出一个下载文件，或按钮在权限被拒后变成静默哑按钮（点多少下都无提示、也无手动替代路径）。
5. **为新反馈引入第二套视觉真源**：Toast 里出现裸 `#2ea043` 之类的直接色值，在深色主题下刺眼，且与 `tokens.css` 体系分叉。

## 5. 交互流程摘要

报告页生成完成 → Hero 右操作组 `[复制 Markdown]（次）[导出 .md]（次）[重新测评]（幽灵）` →

- 点「复制 Markdown」→ 置复制中（按钮 loading+禁用）→ `text = await api.reportMarkdown(report.id)` → `navigator.clipboard.writeText(text)` →
  - 成功：Toast「已复制到剪贴板，可直接粘进笔记」（2s 自动消失），按钮回到可用，无其他副作用；
  - 失败：inline 错误条（中文原因 + 重试），报告保持原样，「导出 .md」仍可点。
- `navigator.clipboard` 缺失/`writeText` 抛错时走同一条失败分支（前置能力判断，不进 try 之外抛错）。
- 复制与导出互不阻塞文案；两按钮在各自请求进行中各自 loading，均不隐藏。

## 6. 优先级

| AC | 说明 | 优先级 |
|---|---|---|
| AC-1 | 按钮存在与位置/忙态 | P0（阻塞项本体） |
| AC-2 | 文本源单源零变换 | P0 |
| AC-3 | 成功 Toast 规格 | P0 |
| AC-4 | 失败不破坏页面 + 手动兜底 | P0 |
| AC-5 | 无浏览器静态断言检查器 | P0（复验证据） |
| AC-6 | typecheck/lint 0 error 且不回归 | P0 |

本需求不含 P1/P2 项。

## 7. 工程约束（原样保留需求中的工程指令）

1. **只做这一项，不改其他功能**；不要重走全量 QA，只需补该项与其断言后**重验 AC-5**。
2. UI 规范已就绪：DESIGN.md §2.5 与 `tokens.css` 已有定义，本轮**不需要重新做 UI 设计**（`needDesign=false`），按既有 token 与组件风格实现；如需新增 Toast 组件，放 `frontend/src/components/ui/` 并遵循 AGENTS §4（**只用 `tokens.css` 变量、无裸色值**）。
3. 前端可验证手段受限：本沙箱 `vite build` / `vitest` 因 **spawn EPERM 不可执行**，可用的门禁是 `npm run typecheck` 与 `npm run lint`（期望 0 error）；新增断言**优先写成无需浏览器的静态/逻辑检查器**（参照 `logs/teamflow/<runId>/scripts/` 现有 `.mjs` 检查器风格）。
4. 保持契约不变：Markdown 文本源仍只由 `backend/app/services/markdown.py` 渲染，前端**不二次拼串**。
5. 当前分支 `feat/dev-skill-coach`，工作树干净（仅未跟踪 `docs/teamflow/20261031-r2-ac5-copy-markdown/`），**保持在该分支上继续，不要新开分支**；提交时把本任务夹与新增检查脚本一并纳入（提交动作由 host 收口）。
6. **版本控制卫生**：`.gitignore` 已覆盖前端（`node_modules/`、`dist/`、`frontend/.vite/`、`*.tsbuildinfo`、`.pnpm-store/`、`node_modules-*/`）、后端（`__pycache__/`、`backend/.venv/`、`*.db`、`backend/.pytest_cache/`、`backend/.ruff_cache/`）、密钥（`.env*`，保留 `.env.example`）与 IDE；本轮按 QA P3 补齐 `backend/tests/.tmp/`，同时确保新增检查脚本只落 `logs/teamflow/`（该目录已被忽略），不把临时脚本或命令输出放进项目根。

## 8. 依赖与风险

- **依赖**：`api.reportMarkdown`（已存在，走 `requestText`）、`GET /api/reports/{id}/markdown`（已实现）、DESIGN §2.5/§0.7（已定稿）、`Button`/`InlineError` 既有组件。
- **R1（环境）**：剪贴板要求安全上下文。点击端 `http://127.0.0.1:5173` 属安全上下文，可用；若用户以局域网 IP 打开则 `navigator.clipboard` 为 `undefined`——按 AC-4 走失败分支（提示 + 导出兜底），**不做 `execCommand` 兼容层**。
- **R2（证据强度）**：沙箱无浏览器，AC-2 的「字节相等」在本轮只能由静态断言（单源、零变换）+ 后端单源渲染 + QA 阶段 `httpx` 取响应体比对三方共同支撑；真机剪贴板粘贴确认转入人工补测清单，不作为本项阻塞。
- **R3（视觉走查）**：Toast 位置/动效无法在沙箱肉眼验证，规格以 DESIGN §0.7 + `tokens.css` 变量落地，样式正确性由 AC-5 第 5 条断言兜住「无裸色值」。
- **R4（首次引入 Toast）**：新组件需避免与后续需求重复造轮子——本轮落成 `components/ui/Toast.tsx` 即团队唯一 Toast 出口（写入产品记忆）。

## 9. 里程碑建议

- **M1（前端接线）**：`components/ui/Toast.tsx` + `ReportPage` 复制按钮/状态/失败分支；本地 `npm run typecheck` 通过。
- **M2（断言门禁）**：`check_copy_markdown.mjs` 六条断言落地，首跑见 FAIL→修→全 PASS；`npm run lint` 0 error。
- **M3（复验闭环）**：只跑本项相关门禁（typecheck/lint + 新检查器 + AC-9 导出静态一致性），QA 报告标记 R-1 CLOSED；随后验收把 AC-5 从「未实现」改为 PASS。

## 10. 假设与待澄清

- **（事实）是否允许为复用文本获取做最小抽取**：AC-2 要求「复制文本 = 导出文本」。我假定允许把「取 markdown 文本」抽成一个小的共享 helper（`frontend/src/api/client.ts` 内已导出 `reportMarkdown`，页面侧可只保留一次调用），或在复制分支里再调一次 `api.reportMarkdown`（不改导出代码）。若用户要求「连导出分支一行都不许动」，则复制逻辑内联、`ReportPage` 内出现两处 `api.reportMarkdown` 调用——改动面更小但重复一次。
- **（品味）复制失败后要不要自动落盘 .md 兜底**：默认**否**——失败只在页内提示并对齐「导出 .md」手动路径；自动下载会在用户未同意时产生文件，且让失败语义变得含混。
- **（品味）成功反馈要不要再加按钮态**：默认**否**——只按 DESIGN §2.5 出 Toast（2s），不额外加按钮 300ms「已复制」切换，避免双反馈与动效噪音；若用户希望更强的确认感，可加按钮短暂 `已复制` 文案（改文案而非改设计 token）。

> 以上三条均已列入 `openQuestions`（1 条 fact + 2 条 taste）。
