# 验收报告 · dev-skill-coach 0.1.0（round 1）

- 需求夹：`docs/teamflow/20261031-r1-dev-skill-coach/`
- 分支 / 基线：`feat/dev-skill-coach`，基线 `32487b4`（工作区未提交，验收未改动任何交付代码）
- 验收人：产品经理（验收负责人）· 验收日期 2026-10-31
- 验收依据：本夹 `PRD.md` §2（AC-1~AC-10，P0: AC-1~8；P1: AC-9/10）、`DESIGN.md` §0/§2.5、`TECHNICAL.md`、`QA-REPORT.md`（round 2）
- 输入状态：QA 判定「验收就绪」，round-1 的 D-1~D-4 全部 CLOSED，无 P0/P1/P2 未修复项

## 0. 结论摘要

10 条 AC 中 **9 条满足**、**1 条部分满足**：**AC-5 的「可一键复制为 Markdown 文本」未实现**——全前端零 `clipboard` 命中（`navigator.clipboard` / `writeText` 均 0），报告页只有「导出 .md」下载（这满足 AC-9，不等于 AC-5 的复制），且 DESIGN §2.5 要求的「复制 Markdown」次按钮、成功 Toast「已复制到剪贴板」与复制失败提示均缺失（`components/ui/` 无 `Toast`）。其余功能面、契约面与架构一致性全部通过（我独立复跑 7 个检查器 + pytest，全绿）。

因此本轮**不判「通过」**，判 **有条件通过**：仅需补 AC-5 的复制 Markdown 能力（复用现成 `GET /api/reports/{id}/markdown` 文本源 + Toast/失败提示），返工后重验该项即可，无需重走全量。

## 1. 验收方法与证据来源

- **独立复跑**（我本人执行，非照抄 QA）：`pytest` 全绿；`check_t14_delivery_e2e.py` 50/50；`check_qa_contract.py` 9/9；`check_profile_chain.py` 全 PASS；`check_interview_chain.py` 80/80；`check_exam_chain.py` 41 passed；`check_report_chain.py` 86 assertions；`check_history_chain.py` 3 组 OK；`check_seed_questions.py` 1130 次断言 0 失败。
- **结构级核对**（grep/AST）：裸 SQL 分布、`source_quote` 上限、`rules.py` 阈值、`target=_blank`/`rel`、`clipboard` 缺失、README 三步、`/health` 终态、routers/services 体量。
- **沿用 QA 未复跑项**：AC-1 在线边界探针 7/7、前端页逻辑/组件检查器（t7/t8/t9/t12、report-components-smoke、useasync）、`typecheck` / `lint`——这些的原始命令与计数已登记在 `QA-REPORT.md`，我按其结论采用。
- 未验证项全部属**环境限制**（浏览器不可启动、`vitest`/`vite build` spawn EPERM、`ruff` 未装、`pypdf`/`python-docx` 未装、无真实 AI Key），逐条见 §5。

## 2. 逐条 AC 核对

| AC | 验收要点（PRD §2） | 证据（来源 · 命令/数字） | 判定 |
| --- | --- | --- | --- |
| AC-1 | PDF/DOCX/TXT ≤10MB；30s 内返回；前端显示正文长度与章节数；空文件/加密/超限中文错误且不生成画像 | `check_qa_ac1_upload_probe.py` 7/7（空/超限 413/类型 415/坏 PDF 500，均中文 envelope）；`UploadPage.tsx:175` 展示「抽取 {chars} · {sections} 章节」；`services/parser.py` 白名单 + 10MB + `FILE_TOO_LARGE`；E2E 上传得 `resume_id` 且未失败 | **满足**（真 PDF/DOCX 正常路径未跑：缺 `pypdf`/`python-docx`，环境） |
| AC-2 | 5 维度（技能/技术栈/年限/项目/目标岗位）+ 每条技能与项目带 `sourceQuote` ≤200 字 + 卡片可视化 + 逐条编辑 | E2E 终态画像 5 维度；`check_profile_chain.py` 全 PASS（模型给 250 字 → 存 199 字仍逐字可溯源）；`schemas.py:30` `source_quote` + `services/profile.py:24 MAX_QUOTE_CHARS=200`；`ProfileEditor.tsx` + `PATCH /api/profiles/{id}`（契约 23 对字段、6 方法对）；`ProfileDimension.tsx` 卡片+溯源展开 | **满足** |
| AC-3 | ≥8 题（≥5 技术 + ≥3 项目深挖）；逐题 0–10 分与 ≤120 字点评；单题 ≤15s；失败可重试且已答不丢 | E2E 10 题：technical 6 / project 3 / challenge 1，均分 6.5；`check_interview_chain.py` 80/80（含真实 `AIClient` 超时 → 503 `AI_UNAVAILABLE` 中文 envelope、不写半成品、`status=running`）；契约 `timeouts` PASS：`SCORING_TIMEOUT_S=14.0 ≤15s`；t9 页逻辑 168/168（失败保留作答） | **满足**（真实 AI 端到端计时未做：无 Key，环境） |
| AC-4 | ≥10 题、客观 ≥8 自动判分；10s 内出总分 0–100 与逐题对错并记录用时 | E2E：10 题 / 客观 8（单选 5 + 多选 3 + 文本 2）/ `total=100.0` / 含 `elapsed_s`；`check_exam_chain.py` 41 passed；本地静态答案判分、`answer` 不进响应模型（零网络、确定性） | **满足** |
| AC-5 | ≥3 条短板按优先级排序；每条含名称/证据（题目 id + 得分）/建议动作/严重度；页面可读；**可一键复制为 Markdown 文本** | 排序与证据：E2E 4 条短板 `severities=[medium,medium,medium,low]`，`question_refs` 命中真题（`iq-1 iq-7 iq-10 fe-q18`）；`check_report_chain.py` 86 assertions；`rules.py` `MIN/MAX_SHORTFALLS=3/5`、`SEVERITY_ORDER` | **部分满足** ⚠ 复制子项缺失（R-1） |
| AC-6 | 每条短板映射 ≥1 门课程；清单 ≥20 门且 ≥3 个零基础入门课；新标签打开外链 | E2E：`courses total=25`、`beginner=14`；`CourseCard.tsx:42-43` `target="_blank" rel="noopener noreferrer"`；报告链「无匹配兜底」断言通过 | **满足** |
| AC-7 | 单用户本地可用（无登录）；刷新后画像/记录/最新报告仍可读；全流程 5 分钟内 | E2E 三条「新会话」断言全 PASS：读回最新报告、历史含面试+笔试、报告即刚生成那份；无鉴权中间件（本地单库 SQLite） | **满足**（5 分钟计时未做，需真实 AI，环境） |
| AC-8 | 模型调用仅服务端；前端源码与产物无 Key；README 三步可起；`/health` 200 | 契约 `keyleak` PASS（`NO_KEY_LEAK`）；E2E `/health` = `{status:ok, ai_configured:false, db:sqlite}` 200；`README.md` §快速开始三步（pip install → copy .env.example → uvicorn，另 npm run dev） | **满足** |
| AC-9 | 报告可下载 `.md`，内容与页面一致 | E2E `markdown` 2414 字节 `text/markdown; charset=utf-8`；`ReportPage.tsx:49-118` 用 Blob 落盘且「页面不二次拼串」；`services/markdown.py` 唯一渲染源；报告链同源断言全过 | **满足** |
| AC-10 | 最近 ≥3 次成绩变化（笔试总分、面试均分、短板条数） | `check_history_chain.py`：rows=3、`interview_avg=6.0 exam_total=100.0 shortfall_count=3`、端点 200 + limit/422 envelope、running/未知 kind 被排除；`TrendTable.tsx` 三指标列 | **满足** |

## 3. 架构一致性核查（强制质量门）

**结论：实现符合蓝图，无重复实现、无该抽取未抽取、无适配器漂移 → 不构成架构返工。**

| 核查项 | 方法 | 结果 |
| --- | --- | --- |
| 蓝图模块是否按计划抽出 | ARCHITECTURE §3.1/§3.2 + TECHNICAL 新增模块清单 vs 实际文件 | 全部落盘：`app/repository.py`(199 行)、`services/rules.py`(57)、`services/markdown.py`(73)、`services/history.py`(120)、`frontend/src/lib/useAsync.ts`；模块职责与蓝图一致 |
| 分层是否真实成立 | 体量 + 依赖方向 | routers 13–55 行（仅参数与错误映射），业务在 services（`diagnosis.py` 455 / `exam.py` 372 / `interview.py` 270）；services → repository，路由不触库 |
| 唯一 SQL 出口 | grep `INSERT/UPDATE/DELETE/conn.execute` 全 `backend/app` | 命中 19 处，**全部在 `db.py`(1) + `repository.py`(18)**；路由与 services 零裸 SQL（D-1 未回退） |
| 契约对等（无适配器漂移） | `check_qa_contract.py` | routes 8 路径 / 6 方法对全命中；fields 23 对模型字段双向一致；`ai-contract` PASS（`complete_model(..., *, timeout_s)` keyword-only，旧反射兜底已删，AST 门禁防回归） |
| 无重复实现 | 设计对照 | 判分只在 `exam.py`（本地静态答案）；点评只在 `interview.py`；证据校验/排序/课程兜底只在 `diagnosis.py`；Markdown 只由 `markdown.py` 渲染，前端不二次拼串；前端出网只经 `api/client.ts` |
| 常驻防回归门禁 | `backend/tests/test_engineering_gates.py` | 6 例 AST 级断言（唯一 SQL 出口、`timeout_s` 签名与调用点、lockfile 完整性、`npm ci`、无裸色值）——改回旧写法即失败，D-1~D-4 不会静默复发 |

**文档漂移（不影响架构判定，列入 R-2）**：`docs/teamflow/architecture/ARCHITECTURE.md` §3.2 与 §7.2「未落盘」仍把 profile/interview/exam/report/history 路由与四个 service 标记为「⛔ 501 待 M2–M4」，与已交付实现不符；`memory.md`「已知待办」同样仍列 M2–M5（本次验收已在 `memory.md` 修订待办清单，ARCHITECTURE.md 属架构师资产未改，避免验收阶段越界）。

## 4. 返工项与遗留

| 编号 | 严重级 | 项 | 复现 / 判据 | 返工要求 |
| --- | --- | --- | --- | --- |
| **R-1** | **P0 子项缺失（阻塞「无条件通过」）** | AC-5「一键复制为 Markdown 文本」未实现 | `grep -rn "clipboard\|writeText" frontend/src` → **0 命中**；`ReportPage.tsx` 仅「导出 .md」；`components/ui/` 无 `Toast`；DESIGN §2.5 要求 Hero 右侧「复制 Markdown」次按钮 + Toast「已复制到剪贴板，可直接粘进笔记」+ 复制失败 inline 提示 | 加「复制 Markdown」按钮：`navigator.clipboard.writeText(await api.reportMarkdown(id))`（复用现成 `requestText`，文本源与导出、页面三者同源）；成功 Toast、失败提示并可退回手动导出；随后补一条断言：点击复制得到的文本等于 `GET /api/reports/{id}/markdown` 响应体，失败路径不清空报告页 |
| R-2 | P3 | 产品级文档漂移 | 同 §3 末段（ARCHITECTURE §3.2/§7.2、memory 待办） | memory 待办已由本轮更新；ARCHITECTURE.md 建议下一轮由架构师同步「已实现/未落盘」清单 |
| R-3 | P3 | QA round-2 的三条观察 | `grep -c limit_bytes` 两处重复（`routers/resume.py` + `services/parser.py`）；框架级 405 返回英文 `Method Not Allowed`；`.gitignore` 无 `backend/tests/.tmp/` 规则 | 上限校验收敛到 `parser.py` 单源；405 文案中文化；`.gitignore` 补 `.tmp`（三项均不阻断验收） |

## 5. 环境限制与人工补测（非交付缺陷，沿用 QA §5）

1. 浏览器不可启动（sandbox 限制 Chromium crashpad 权限）→ 视觉/动效、刷新持久化的人工走查未做（静态断言 + E2E 新会话等价覆盖）。
2. `vitest` / `vite build` 不可 spawn（`EPERM`）→ 前端单测与构建产物未实跑；`typecheck`/`lint` 已绿（0 error / 18 warning）。
3. `ruff` 未安装 → 后端 lint 未跑。
4. `pypdf` / `python-docx` 未安装 → AC-1 的 PDF/DOCX **正常路径**未验证（降级路径与错误映射已验证）。
5. 无真实 `AI_API_KEY` → AC-1 ≤30s、AC-3 单题 ≤15s、AC-4 10s、AC-7 ≤5 分钟的**真实链路计时**未做（代码侧保障已验证：`AI_TIMEOUT_S=20`、`SCORING_TIMEOUT_S=14`、笔试本地判分零 AI）。
6. 屏幕阅读器 / 窄屏 safe-area / 真机多点触控未做。

## 6. 本轮复跑证据清单

- `cd backend && python -m pytest -q -p no:cacheprovider` → exit 0（全绿）
- `python -X utf8 check_t14_delivery_e2e.py` → `RESULT 50/50 passed, 0 failed`（终态：面试 10 题均分 6.5、笔试 10 题客观 8 总分 100.0、报告 4 条短板证据命中真题、markdown 2414 字节、新会话可读）
- `python -X utf8 check_qa_contract.py` → `9/9 passed`（routes/fields/sql-exit/keyleak/timeouts/ai-contract/repro/tokens）
- `python -X utf8 check_profile_chain.py` → 全部 PASS（250→199 字截断仍可溯源、终态维度保留、未知 id 404）
- `python -X utf8 check_interview_chain.py` → 80/80（含超时→503 中文 envelope、不写半成品）
- `python -X utf8 check_exam_chain.py` → 41 passed
- `python -X utf8 check_report_chain.py` → `ALL PASSED (86 assertions)`
- `python -X utf8 check_history_chain.py` → 3 组 OK（rows=3、端点 [real app]）
- `python -X utf8 check_seed_questions.py` → 1130 次断言、0 失败（各方向 12 题、挑战 8.3% ≤20%）
- 结构 grep：SQL 19 处全在 `db.py`/`repository.py`；`clipboard` 0；`target="_blank" rel="noopener noreferrer"` 命中；`MAX_QUOTE_CHARS=200`；README 三步就位

验收结论：⚠️ 有条件通过
