<!-- meta: summary="r5 验收：18 条 AC 全部有已执行证据（独立复跑 pytest 140 / checkers 7 组 / typecheck / lint 28 / vitest 65 / build / 无 Key 泄漏 / /health 200 / 390px 与主路径走查），无 P0/P1/P2 开放项，4 条 P3 观察与 1 组环境受限人工补测（真实 Key 端到端、ruff、真机窄屏/读屏），判定 ✅ 通过。" -->

# 验收报告 · r5 模拟面试对话化与面试配置项

> 任务夹：`docs/teamflow/20261101-r5-interview-chat-config/`（PRD / DESIGN / TECHNICAL / QA-REPORT / ACCEPTANCE 自包含）
> 分支 `feat/dev-skill-coach`（原地继续，34 项未提交改动，由流水线验收后统一提交）｜runId `tf-mvx9f223-m8ms9l`｜验收角色：产品经理（验收负责人）｜2026-11-01
> 基线依赖 `20261101-r4-r3-acceptance-closure/`；本需求按 PRD 首部声明**取代** `20261031-r1-dev-skill-coach/#AC-3` 的作答形态，结构下限与 ≤15s 口径原样保留。

## 1. 结论

**✅ 通过**。PRD 18 条 AC（P0 15 / P1 3）**逐条有已执行证据**，无 P0/P1/P2 开放项；QA 第 1 轮 6 条缺陷（1×P1 / 3×P2 / 2×P3）的关闭结论由我按原判据复核成立。四条反面目标（换皮 8 题 / 答完看不到分·刷新清空 / 配置是摆设 / 临时岗位污染画像 / 结构失守）均未被触发。

- 本轮我**独立复跑**（不替代 QA 证据）：`pytest` 140 passed（exit 0）、7 个 QA 检查器全绿（functional 65/65、edges 35/35、replay OK、interface 309/0、parity 17/0、engine 15/0、projection 33/0）、`typecheck` 0 error、`lint` 0 error / 28 warning、`vitest` 65 passed、`build` 通过、`/health` 200 `ai_configured=false`、前端源码无 Key 泄漏、仓库根无 dump。
- 架构 M3：符合蓝图，无重复实现、无结构破坏（§4），**不构成返工**。
- 不阻断的 P3 观察 4 条（§5，含 2 条 QA 观察 + 2 条本轮新增）；环境受限的人工补测 1 组（§6）。

## 2. 逐条 AC 验收

| AC | 验收点（简） | 已执行证据（命令 / 位置） | 判定 |
|---|---|---|---|
| AC-1 | 4 项配置表单 + 画像预填 + 可跳过 + 服务端补默认 | `check_qa_r5_functional` AC-1 组；`check_interview_engine`（`experience_band_of` 逐档映射）；`vitest interviewSettings`；浏览器实测：预填 `Android 开发工程师` + 「按画像 2.5 年 → 1-3年」+ 5/4/3 档 chip + 一键跳过 | 通过 |
| AC-2 | settings 双侧契约、落 payload、每轮进提示词、映射逐档可测 | functional AC-2（payload 逐字段相等、每轮 prompt 含 4 项）；`check_contract_parity` 17 组；浏览器拦截 `POST /api/interviews` 实测 body 四项与点选逐字一致；⑤ 真实 Key 冒烟 → §6 | 通过（⑤人工） |
| AC-3 | 临时岗位不回写画像 | functional AC-3：开局后 `GET /api/profiles/latest` 与开场前等值、`payload.settings.target_role` 为新值；刷新/重进不变 | 通过 |
| AC-4 | 开局只 1 条发言、无 8 题列表 | functional + engine（开局响应仅 1 条 `question`，无 questions 数组）；`check_t5` 渲染气泡计数；`parity`（`InterviewRun` 无 `questions`）；浏览器开局面板面试官气泡 = 1 | 通过 |
| AC-5 | ≤15s 气泡内并置 0–10 分 + ≤120 字点评、点评逐字 | functional AC-5（timeout_s=14、comment 逐字）；`check_t5` 57/57（点评逐字含首尾空格、评分区在候选泡内、无 clamp）；浏览器「本题得分 7.5 / 10 · 良好」+ 整段点评 | 通过 |
| AC-6 | 每轮带 ≥3 轮上下文、追问 parent_id 继承 kind | functional AC-6（第 3 轮输入含第 1/2 轮 answer 原文）；`parity` `parent_id`/`kind`；`engine`；浏览器「↳ 追问自 Q1」 | 通过 |
| AC-7 | 开局与结束前配额闸门、不合格 502 不补题 | `check_interview_engine` 15/15（≥8 / 技术≥5 / 项目≥3 / 挑战≤20% 逐档拒绝 + 502 + 不落库）；functional AC-7；结束前 `validate_session` 不达标不置 completed | 通过 |
| AC-8 | `iq-N` 单调唯一、刷新不变、报告证据可反查 | functional AC-8；`check_t3_projection` 33/33（报告 `来源题目 iq-N` 反查命中 100%）；浏览器报告页 `来源题目 iq-3` 反查气泡 | 通过 |
| AC-9 | `GET /api/interviews/{run_id}` 恢复、不重出题、已完成只读 | functional AC-9；`check_qa_r5_edges` E3（终态再提交 400「这场面试已经结束」、payload 逐字不变、不多花一次 AI 调用）；`replay`；浏览器刷新后 6 泡 + 分数 7.5/3.9/8.2 全在、无 textarea | 通过 |
| AC-10 | 单轮超时/失败 503 中文零副作用、答案保留、不重复计分 | functional B21–B23（503 + retryable + payload 逐字未变 + 重试不重复计分）；`check_t5` 失败条在输入区上方且答案保留；`edges` E2 非法输入零副作用；timeline `(type,ref_id)` 幂等由 functional 断言 | 通过 |
| AC-11 | 历史 `interview_settings` + 旧记录「未记录设定」 | functional AC-11；`check_t3_projection` wire 形状；`check_t6` 44/44；浏览器 `/history` 新行 `岗位 · 经验 · 市场 · 规模`、旧行「未记录设定」、无 `undefined` | 通过 |
| AC-12 | 报告 `interview_settings`、null 不渲染 | functional AC-12（取最新合法面试 run）；`check_t3_projection`；`check_t6`；浏览器 `/report`「本场设定」区块；`edges` E4（缺键/全空 → `None`，不补默认值） | 通过 |
| AC-13 | 无 Key / AI 失败中文 InlineError 不白屏、中途失败不丢会话 | 后端：`ai.py:34-37` 未配置分支 → 503 中文「AI 服务尚未配置…」+ retryable；functional 503 envelope；前端：`InterviewSetupForm.tsx:195` 开局失败渲染 `InlineError`+重试（四项保留）、`InterviewPage` 恢复失败/轮次失败各有 `InlineError` 分支；`check_t5` 失败条断言；真机冒烟 → §6 | 通过（冒烟 §6） |
| AC-14 | 双侧同批 snake_case、零新表零迁移、旧库可读 | `check_contract_parity` 17/17；`check_qa_r5_interface` 309/0（AST 全量 import + 交付面成员 + 路由签名，含变异自检）；functional C17「表集合与基线一致」；`repository.py`/`db.py`/`ai.py` 零改动（git）；旧 payload 三处投影一致降级 | 通过 |
| AC-15 | 门禁不倒退 | 我复跑：`pytest` 140（≥118）、`typecheck` 0、`lint` 0 error/28 warning（脚本 `--max-warnings 28`，超 1 即 exit 1）、`vitest` 65（≥23）、`build` ok；无裸色值由 `tests/test_engineering_gates.py` 在 140 内通过 + r5 CSS 段 0 处 hex/rgba；r2 复制 Markdown：`ReportPage` 复制入口与 `COPY_TOAST_MESSAGE` 未改 + QA 6/6 | 通过 |
| AC-16 | 白名单、无新依赖、既得能力不回归、/health、无 Key 泄漏 | 改动面与 TECHNICAL §8 说明一致（tokens.css / 历史三组件为白名单外必需，附理由）；`package.json` 依赖零变化；四步闭环/报告/时间线/润色/复制由 pytest 140 + t6 + 浏览器复核；我实测 `GET /health` → 200 `{"status":"ok",…,"ai_configured":false}`；`grep -ricE "sk-|api_key" frontend/src` → 0 | 通过 |
| AC-17 | DESIGN.md 覆盖气泡布局/评分并置三档/配置表单/窄屏/滚动锚点/结束态且尺寸有推导 | DESIGN.md 377 行：§0.2 新增 7–8 个 `--iq-*` token、§0.3 评分三档（>7 / 4–7 / <4）、§0.5 几何逐条核算（156/84/172/720/640）、§2.2–2.4 配置/对话/结束态、§5 无障碍、§6 AC 速查 | 通过 |
| AC-18 | 390px 无横向滚动、输入区粘性可达、键盘焦点环、分数有文本 | 浏览器 390px iframe 实测 `scrollWidth 375 = clientWidth 375`（溢出 0）；`base.css:2708` `.sc-iq-composer{position:sticky}`；全局 `:focus-visible` 2px accent；`AnswerScore.tsx:61` 整句 `aria-label`（含档位词）文本呈现；真机/软键盘 → §6 | 通过（真机 §6） |

## 3. 独立复跑清单（本轮实测，命令原样）

| # | 命令 | 结果 |
|---|---|---|
| 1 | `cd backend && python -m pytest -p no:cacheprovider` | exit 0，`140 passed in 8.43s` |
| 2 | `python -X utf8 …/check_qa_r5_functional.py` | `65 passed, 0 failed` |
| 3 | `…/check_qa_r5_edges.py` | `35 passed, 0 failed` |
| 4 | `…/check_qa_r5_replay.py` | `REPLAY_IDEMPOTENCY_OK` |
| 5 | `…/check_qa_r5_interface.py` | `{"checked":309,"failed":0}` `INTERFACE_PARITY_OK` |
| 6 | `…/check_contract_parity.py` | 17 组 / 0 失败 |
| 7 | `…/check_interview_engine.py` | 15 PASS / 0 FAIL |
| 8 | `…/check_t3_projection.py` | PASSED=33 FAILED=0 |
| 9 | `cd frontend && npm run typecheck / lint / test / build` | 0 error / 0 error 28 warn / 65 passed / built ok（258.78 kB） |

## 4. 架构一致性（M3 质量门）

- 蓝图一致性：纯函数按方案抽到 `components/interview/chatModel.ts`（气泡/题号/汇总算术）与 `setupModel.ts`（`bandOfYears`/`prefillOf`/`draftToPatch`/`previewLine`），组件文件只导出组件（lint `react-refresh` 0 error 佐证），`InterviewPage` 仅 import 复用，无第二份实现。
- 重复实现：`rules.settings_or_none` 是唯一解析实现（`history._interviews_settings_of`、`interview._settings_or_none` 均为薄委托，`diagnosis` 复用 history），QA D-5 的读侧漂移已消除；`--iq-*` token 单点定义。
- 既有结构：`repository.py`/`db.py`/`services/ai.py` 零改动、零新表零迁移；`QuestionCard.tsx` 已删且无残留引用；接口一致性 309 项 0 失败（检查器做过变异自检，非空转）。
- 结论：**结构符合技术方案，无「应抽取未抽取 / 双份实现 / 破坏既有结构」** → 不产生返工项。

## 5. 观察项（P3，仅记录，不阻断验收）

| 编号 | 观察 | 建议 |
|---|---|---|
| O-1（QA） | 配置态无「本场尚未开始」一类会话状态行（`InterviewPage.tsx:288` 仅在 chat/ended 渲染） | 下轮补状态行，保持三态一致 |
| O-2（QA） | `Composer.tsx:73` 仅 `maxLength`，接近 800 字无计数、超出静默截断 | 补字数计数或上限提示 |
| O-3（本轮） | `ARCHITECTURE.md` §7.2 表格 r5 行与 §8 交接段仍写「待落地 / 进行中」（§3.3 路由表、§3.4.1、§7.1 已同步），§8 末尾还重复了一条「统一约束」 | 并入下次文档整理闭合（已登记 memory 待办） |
| O-4（本轮） | `frontend/package.json` 的 `lint` 脚本加 `--max-warnings 28`，而 TECHNICAL §8 把 `package.json` 列入「明确不动」；属**收紧**门禁（非放宽）、依赖零变化 | 下次技术方案把「脚本收紧」纳入改动面 |

## 6. 遗留（环境受限 / 不可自动判定，非交付缺陷）

1. **真实 AI Key 端到端**（AC-2⑤、AC-6③、AC-5 真实 15s、AC-13 无 Key 浏览器冒烟）：`backend/.env` 不存在，本轮只证到提示词层与降级分支；需配置 Key 后人工跑「上传简历 → 8 轮对话 → 报告」，重点看 ≥2 组配置的题面差异与追问措辞。
2. **后端 ruff**：本机 `No module named ruff`（环境限制，未重试），后端 lint 由 `test_engineering_gates.py` + 人工复审覆盖。
3. **真机窄屏 / 软键盘遮挡 / 滚动锚点观感 / `prefers-reduced-motion` / 屏幕阅读器**：沿用 QA §6 清单，人眼与真机复测。

## 7. 交付口径

- 分支 `feat/dev-skill-coach` 原地继续，**Agent 未提交**；改动面 = PRD §9.1 白名单 + TECHNICAL §8 已说明的 4 个白名单外必需文件（tokens.css、历史三组件） + 任务夹文档 + `logs/teamflow/<runId>/`（gitignored，由 host 归档）。仓库根无 dump、无新依赖、无新表。

验收结论：✅ 通过
