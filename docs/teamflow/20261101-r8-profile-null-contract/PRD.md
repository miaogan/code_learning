<!-- meta: summary="修复真实模型产出 projects[].role/period 为 null 时画像生成必定 502 的缺陷：把「提示词允许 null」与「契约要求 str」的口径对齐（草稿模型 / ProfileProject / types.ts 三处可空），并连带修好空值在前端渲染编辑、简历润色数字白名单、面试开局画像输入、增量合并五处的崩溃与信息丢失。" -->

基线依赖：20261031-r1-dev-skill-coach、20261031-r3-memory-resume-polish、20261101-r5-interview-chat-config（画像五维契约与 `source_quote` 溯源闸门、增量合并与证据链、面试开局读取画像三项既有行为不得回归）

# r8 · 修复真实 AI 下「依据简历生成画像」必定 502 AI_SCHEMA_INVALID

## 1. 背景与目标

### 1.1 缺陷事实（已用真实 DeepSeek Key 实测复现，可原样重跑）

| 项 | 内容 |
|---|---|
| 环境 | `backend/.env`：`AI_BASE_URL=https://api.deepseek.com/v1`、`AI_MODEL=deepseek-chat`（Key 由 host 写入，已 gitignore） |
| 请求 | `POST /api/resumes/{resume_id}/profile` |
| 实际响应 | `502 {"error":{"code":"AI_SCHEMA_INVALID","message":"AI 返回的结构不符合预期，请重试一次","retryable":true}}` |
| 重试 | 无效 —— 模型每次返回同样形状，重试必然同样失败 |
| 影响 | 阻断级：四步闭环（画像 → 面试/笔试 → 诊断 → 课程）在第一步就断，真实 Key 下产品完全不可用。前几轮因无真实 Key 未覆盖到 |

### 1.2 根因（字段级，非模型行为异常）

模型返回的真实 JSON 中 `projects[0].role = null`、`projects[0].period = null`（简历里没写「承担角色」和「起止时间」），这与 `PROFILE_SYSTEM` 第 3 条「若某个维度无信息，给空数组（或 null）；宁缺毋滥」完全一致 —— **模型的输出是正确行为**。

而 `backend/app/schemas.py:84-87` 的 `ProfileProject` 把两个字段定为非可空 `str`，pydantic 校验失败：

```
2 validation errors for ProfileDraft
projects.0.role    Input should be a valid string [type=string_type, input_type=NoneType]
projects.0.period  Input should be a valid string [type=string_type, input_type=NoneType]
```

`AIClient.complete_model`（`app/services/ai.py:48-60`）在 `ValidationError` 后按 `ai_max_retries` 重试、仍失败即抛 `AI_SCHEMA_INVALID`（502，retryable=true）。

**一句话结论：提示词允许 null，响应模型不接受 null —— 两者口径不一致。** 本缺陷当前无既有 AC 保护（r1 AC-2 只要求五维与 `sourceQuote`，未规定 `role/period` 非空），因此本需求不取代任何历史 AC；`ProfileDraft` 复用 `ProfileProject`、`Profile` 继承 `ProfileDraft`，故一处字段改动同时覆盖「模型草稿」与「最终契约」。 缺陷不在模型，也不能靠「让提示词改口填空字符串」修复（空串会把「不存在的信息」伪装成已知信息，污染画像展示、面试提示词与合并语义）。

### 1.3 同类口径普查（本轮一并修，篇幅同源、不扩展成重构）

| # | 位置 | 现象 | 处理 |
|---|---|---|---|
| C1 | `schemas.py` `ProfileProject.role/period` | 提示词允许 null，契约要求 `str` | 改为 `str \| None = None`（输入草稿模型 `ProfileDraft` 复用 `ProfileProject`，故一处生效） |
| C2 | `schemas.py` `skills`/`projects`/`tech_stack` | 提示词第 3 条允许该维度给 `null`，契约要求 `list` | 补 before-validator：`null`/缺省 → `[]`，输出类型不变 |
| C3 | `schemas.py` `projects[].bullets` | 同上经验（模型可能给 null 而非 `[]`） | `null` → `[]`，输出类型不变 |
| C4 | `frontend/src/pages/ProfilePage.tsx:143` | `[item.role, item.period].filter(part => part.trim() !== '')` —— null 上调 `.trim()` 抛 TypeError，画像页白屏 | 单点归一 `null → ''` 后再拼接，不显示 `null`/悬空 `·` |
| C5 | `ProfilePage.tsx:271-272, 311-312` | 编辑保存 `(values.role ?? target.role).trim()` 与编辑框 `value: target.role` 在 null 下崩溃/类型不符 | 编辑框取值 `?? ''`，保存写入时空白归一（不回写字面 `"null"`） |
| C6 | `app/services/resume_polish.py:188` | `_NUMBER_RE.findall(project.period)` —— `period=None` 直接 TypeError，润色端点 500 | 空值防护（`period or ""`），数字白名单口径不变 |
| C7 | `app/services/interview.py:300-301` | `_profile_brief` 把 `role/period` 原样放入开局输入，prompt 里出现 `"role": null` | None 时省略该键（不改提示词措辞、不改 `InterviewSettings`） |
| C8 | `app/services/profile_merge.py:163-170` | `payload.update({"role": getattr(source, "role", "")})` 会把 `None` 写成新值，覆盖旧简历已知的角色/时间 | 空值不覆盖已知值（对齐 `target_role` 既有规则：「新简历没写时沿用旧值」） |

**保持不动的字段（反幻觉闸门，不得借此放宽）**：`skills[].name`、`projects[].name`、`skills[].source_quote`、`projects[].source_quote` 仍为必填非空（`min_length=1`）；`years_experience`、`target_role` 已是 `float | None` / `str | None`，不动。

### 1.4 目标

- **G1** 契约与提示词口径一致：真实模型输出 `role/period: null` 时，`POST /api/resumes/{id}/profile` 返回 **200** 并落库。
- **G2** 空值全链路可承受：前端渲染/编辑、简历润色、面试开局输入、增量合并四处不因 null 崩溃或丢信息。
- **G3** 质量边界不放松：`source_quote` 逐字命中校验、反幻觉、证据链累积/去重、AI 失败降级（502/503 语义）全部保持；不得以「关掉校验」换绿。
- **G4** 真实模型下四步闭环可走通：画像 200 → 面试开局 → 提交一答 → 评分，全链在真实 Key 下验证并留证据。

### 1.5 非目标（明确不做）

- 不改 `PROFILE_SYSTEM` 的任何措辞（含把「无法判断填 null」改成别的说法）；不改其余 5 个 AI 入口（`InterviewDraft` / `RoundDraft` / `_SuggestDraft` / `_ReportCopyDraft` / `_CoachCopyDraft`）的提示词与模型。
- 不重构 AI 客户端、重试策略与超时预算，不改错误码闭集。
- 不新增 DDL / 迁移脚本（SQLite 无迁移，`ProfileProject` 变更只影响 pydantic 反序列化）。
- 不做画像页空态重设计、不加新交互；不重写增量合并算法。
- 不新增依赖（前端/后端零依赖变更）。

## 2. 用户故事与验收标准

> AC 编号仅在本任务夹内有效。每条 AC 必须可由命令或真实请求复验。

| AC | 用户故事 | 验收标准（可测） | 优先级 | 验证方式 |
|---|---|---|---|---|
| AC-1 | US-1 | **契约可空**：`backend/app/schemas.py` 的 `ProfileProject.role`、`period` 为 `str \| None = None`；`frontend/src/api/types.ts` 的 `ProfileProject.role/period` 为 `string \| null`（可选字段语义：字段缺失亦通过）。用 req 原文真实 payload 调 `ProfileDraft.model_validate` **不抛错**，且 `Profile.model_validate(draft_dump + id/resume_id/updated_at)` 通过 | P0 | pytest 单测 + 前后端字段集合静态断言 |
| AC-2 | US-1 | **同类口径闭集修复**：仅下列字段放宽——`skills`/`projects`/`tech_stack` 为 `null` 或缺失时归一为 `[]`，`projects[].bullets` 为 `null` 时归一为 `[]`；`name`、`source_quote` 仍必填非空；`years_experience`、`target_role` 不变。上述 5 个放宽点各 2 条参数化用例（null / 键缺失）全绿 | P0 | pytest 参数化 |
| AC-3 | US-1 | **真实链路 200（本需求核心）**：真实 Key 下上传一份简历 → `POST /api/resumes/{id}/profile` 返回 **200**；响应中 `skills` ≥1、`projects` ≥1、`target_role` 非空；每个 `skills[].source_quote` 与 `projects[].source_quote` 去空白后能在该简历 `documents.text` 中**逐字命中**；响应 `error` 字段不存在 | P0 | 真实 Key 端到端请求 + 命中率脚本（证据入 QA 报告） |
| AC-4 | US-1 | **下游空值不崩**：①`resume_polish._allowed_numbers` 传入 `period=None` 的画像不抛异常，且仍能从 `bullets` 收集数字；②`interview._profile_brief` 对 `role/period=None` 的项目省略该键，序列化后不含 `null` 值；③`repository` 落库后读回字段等值（None 仍是 None，不被转成 `""`/`"None"`）；④`POST /api/resumes/{id}/polish` 在该画像下 200 | P0 | pytest 单测 + 路由级断言 |
| AC-5 | US-2 | **前端渲染与编辑**：`/profile` 页面中 `role/period` 为 null 的项目卡 —— 不出现 `null`、`undefined`、悬空 `·`；有值侧正常拼接（如 `后端开发 · 2024-2026`，仅一侧有值则只显示一侧）；编辑弹层两字段为空串可输入，保存 `PATCH /api/profiles/{id}` 返回 200，刷新后仍可再次编辑；归一函数有单测（null→''，''→''，' x '→'x'） | P0 | vitest 组件/纯函数断言 + typecheck 0 |
| AC-6 | US-1 | **合并空值不丢信息**：旧画像 `role="前端主力"` + 新草稿 `role=None` → 合并结果仍为 `"前端主力"`（不覆盖）；旧 `role=None` + 新草稿有值 → 取新值（补全）；两侧均 None → 结果为 None 且不抛错；`role/period` 为空的合并**不改变** `profiles/latest` 的 `profile_id`，`updated_at` 刷新，证据链仍累积 | P0 | pytest（`test_profile_merge.py` 新增 3 条） |
| AC-7 | US-1 | **反幻觉与降级不放松**：①`source_quote` 为空/未在正文逐字命中时仍抛 `AI_SCHEMA_INVALID`（502、`retryable: true`、中文 message）；②`MAX_QUOTE_CHARS=200` 截断语义不变；③证据链「重复证据不重复追加、旧→新顺序」不变；④无 Key 仍 503、AI 超时仍 503；⑤本次 diff 中不得出现对 `verify_quotes` 判定的放宽、对 `ValidationError` 的整体吞掉、或 `extra="allow"` | P0 | pytest 负向用例 + diff 静态检查 |
| AC-8 | US-3 | **存量兼容**：含 `role/period` 为字符串的旧画像、以及**完全没有** `role/period` 键的旧 payload，`Profile.model_validate` 均通过；`GET /api/profiles/latest` 200 且前端旧数据渲染无差异；`PATCH` 旧格式 payload 200 | P0 | pytest 反序列化用例 + 前端渲染用例 |
| AC-9 | US-4 | **真实四步闭环**：真实 Key 下 画像 200 → 面试开局 200 且题量 ≥8（技术 ≥5、项目 ≥3，过 `rules.py` 配额）→ 提交一答 200 得 0–10 分与 ≤120 字点评 → 全程无 502/503；记录每步耗时。若某步超出既有预算（评分 15s），如实记录失败原因，**不得伪造通过** | P0 | 真实 Key 逐段请求 + 响应摘要证据 |
| AC-10 | US-all | **门禁只增不减**：`pytest` ≥297 passed 且新增 ≥8 条（合计 ≥305）；`vitest` ≥100 passed 且新增 ≥4 条（合计 ≥104）；`npm run typecheck` 0 error；`npm run lint` 0 error、≤28 warning；`npm run build` 通过；`GET /health` 200；`NO_KEY_LEAK`（前端源码与产物不含 Key）。`ruff` 若本机环境缺失，如实记录「未执行」而非假装通过 | P0 | 逐条命令输出（尾部摘要入 QA 报告） |
| AC-11 | US-1 | **回归用例钉住口径**：新增 fixture 保存「真实模型形状」（含 `"role": null, "period": null`）的完整 payload 与一份 `PROFILE_SYSTEM` 原文断言：若有人把 `role/period` 改回 `str`，或把提示词改成「填空字符串」，对应用例必须变红（两条断言互相牵制）。用例命名可检索（含 `role_null` / `prompt_shape`） | P1 | pytest + 反向自检（改回 `str` 跑一次应变红） |
| AC-12 | US-all | **报告如实可核查**：`QA-REPORT.md` 明确写出「修的是提示词与契约口径不一致」，并附**修复前后同一请求**的真实证据：修复前 502 + `error.code=AI_SCHEMA_INVALID` + pydantic 两条 `string_type` 错误摘要；修复后 200 + skills/projects 计数 + `source_quote` 命中数。报告中**不得**出现 Key 明文或 `.env` 内容；新增依赖数 0 | P1 | 文档人工核对 + grep Key 片段为 0 |

**US-1**：作为一名用真实 Key 部署的开发者，我上传简历后应看到生成的画像（技能/技术栈/项目/目标岗位），而不是一个让我「重试一次」的 502；项目里没写的角色与时间应显示为空，而不是让整条链路失败。
**US-2**：作为画像使用者，我编辑项目时角色/时间留空不应报错，页面不应因空值塌版或显示 `null`。
**US-3**：作为持续投递简历的用户，第二份简历没写角色/时间时，不应把我第一次写过的信息清空。
**US-4**：作为验收者，我需要确认四步闭环在**真实模型**下真的能跑通，而不是只在 fake client 下绿。

## 3. 范围与非目标

**范围**：`schemas.py` 两处可空性 + 三个顶层数组/`bullets` 的 null→`[]` 归一；前端 `types.ts` 与 `ProfilePage` 空值处理（单点归一）；`profile_merge` 空值不被 None 覆盖；`resume_polish._allowed_numbers` 与 `interview._profile_brief` 空值防护；新增/修订测试；真实 Key 端到端验证与报告。

**非目标**：见 §1.5。特别强调：**不以改动提示词、关闭校验、放宽 `source_quote` 为代价**达成 200。

## 4. anti-goals / 反面目标

即使门禁全绿、接口返回 200，出现下列任一情形即视为**产品失败**、应打回：

1. **用空字符串把「没有」伪装成「有」**：为消掉报错把 `role/period` 默认成 `""`，于是画像页出现一行没有标签的空字段、面试提示词里出现 `"role": ""`，用户以为系统从简历里读到了角色信息。可观察：导出/请求体内字段存在但为空串，而简历正文里根本没有对应文字。
2. **靠放宽校验换绿**：把 `source_quote` 改成可选、把 `verify_quotes` 包一层 try/except 或整体吞掉 `ValidationError`。可观察：注入一条编造的技能（原文不存在）后仍能落库，画像页多出一项点不到原句的能力。
3. **只修后端不修前端**：真实 Key 下画像生成 200 了，但打开 `/profile` 因 `null.trim()` 抛 TypeError 白屏 —— 用户看到的结果比修复前更糟（修复前至少是明确的错误提示）。
4. **修完仍是同一错误，只是换了文案**：真实模型连试 3 次仍是 502（或错误信息从「结构不符合预期」换成别的说法）。可观察：同一份简历连续 3 次 `POST /profile` 全部非 200。
5. **真实 Key 验证被 fake client 顶替**：报告声称「真实链路已通过」，但用真实 Key 复跑一次上传即失败。可观察：任何人用已配置的环境原样重放 req 里的请求即可证伪；报告里拿不出带时间戳的真实响应。

## 5. 交互流程摘要

**主流程（真实模型）**：上传简历（PDF/DOCX/TXT）→ 解析得到 `documents.text` → 前端调 `POST /api/resumes/{id}/profile` → 服务端 `AIClient.complete_model(PROFILE_SYSTEM, context, ProfileDraft)` → **契约接受 `role/period: null`** → `verify_quotes` 逐字命中 → `merge_profile` 合入当前画像（空值不覆盖已知值）→ 落库 + resume 时间线事件 → 200 `ProfileWithMerge` → 画像页 5 维卡片渲染（空 `role/period` 不显示该片段、无占位乱码）。

**编辑流程**：项目卡「编辑」→ 弹层中角色/时间输入框为空串 → 用户可留空可填写 → `PATCH /api/profiles/{id}`（空值不写入 `"null"` 文本）→ 卡片刷新。

**降级路径（不变）**：无 Key → 503 中文提示；AI 超时 → 503；模型未返回 JSON / 结构仍不符 → 502 `AI_SCHEMA_INVALID` 且 `retryable: true`；`skills/tech_stack/projects` 全空 → 502 中文「AI 没能从简历里抽出任何内容」。所有错误一律 `{error:{code,message,retryable}}`，message 中文、不含路径/堆栈/Key。

**空值可观察形态**：`role=None, period="2024-2026"` → 卡片 meta 仅显示 `2024-2026`；两者皆 None → 不渲染 meta 行（不留空行、不留 `·`）。

## 6. 优先级

- **P0（10 条）**：AC-1、AC-2、AC-3、AC-4、AC-5、AC-6、AC-7、AC-8、AC-9、AC-10 —— 不做则缺陷未修或质量边界被破坏。
- **P1（2 条）**：AC-11（防回归的用例牵制）、AC-12（报告可核查）—— 不影响「今天能跑通」，但决定这个缺陷会不会被写回去。
- 实施顺序建议：AC-1/AC-2（契约）→ AC-4/AC-6（后端下游）→ AC-5/AC-8（前端）→ AC-3/AC-9（真实 Key）→ AC-7/AC-10/AC-11/AC-12（闸门与证据）。

## 7. 依赖与风险

| 风险 | 说明 | 应对 |
|---|---|---|
| R1 真实 Key 可用性 | Key 由 host 写入 `backend/.env`；QA/验收窗口内可能因额度/网络不可用 | 真实调用集中在一次执行；若确实不可用，**明确标注「真实 Key 未复验」**并给出 fake client 等价证据 + 手动重放命令，不得判「已通过」 |
| R2 模型输出比 req 更飘 | 例如整份 `{}` 或字段改名 | 本次只做口径对齐，不扩到 AI 客户端；全空仍走既有 502 中文提示（属另一缺陷，另立需求） |
| R3 放宽 `null` 掩盖模型退化 | 模型开始大量省略 `source_quote` 却不再报错 | AC-7 守住：`source_quote` 仍必填非空；`verify_quotes` 强度不变 |
| R4 空值合并语义分歧 | 「保留旧值」vs「以新为准」 | 已在 AC-6 定为「空值不覆盖」，与 `target_role` 既有规则一致；该取舍列入 §10 供用户否决 |
| R5 前端只改一处 | 其他渲染路径若再读 `role/period` 仍会崩 | AC-5 要求单点归一函数；静态检查确认 `role/period` 的读取点仅在归一后使用 |
| R6 ruff 环境缺失 | 历史轮次已出现 | AC-10 允许如实记录「未执行」，不用缺工具替代通过 |

## 8. 工程约束

**工程动作（原位保留，不得改写）**：
- 分支 `feat/dev-skill-coach` **原地继续**（不新建分支、不切分支、不 rebase）。
- **Agent 不提交**，由流水线验收后统一提交；本需求的改动不自行 commit / tag / push。
- 当前工作区未提交改动仅 `?? docs/teamflow/20261101-r8-profile-null-contract/`（本任务夹），**保留原样**，不 stash、不清理。
- **不提交** `backend/.env`（含真实 Key，已 gitignore）、任何诊断脚本、数据库文件（`*.db` / `*.db-wal` / `*.db-shm`）。
- **不动**其余 5 个 AI 入口（面试开局 `InterviewDraft`、评分 `RoundDraft`、润色 `_SuggestDraft`、报告文案 `_ReportCopyDraft`、教练文案 `_CoachCopyDraft`）的提示词与模型；已实测真实模型下均 PASS。
- **不得打印 Key、不得把 `.env` 内容贴进任何交付文档**；报告中的真实响应证据只保留状态码、错误码与结构性摘要。
- 真实 Key 冒烟用的临时脚本只落在 `logs/teamflow/tf-mvxkiihc-y5p1qf/scripts/`（已 gitignore，run 结束由 host 归档并从项目删除），不落在仓库根。

**`.gitignore` 审计（dev 阶段动作）**：本仓库为 Python + Node 双栈，需确认已覆盖 `__pycache__/`、`*.py[cod]`、`backend/.venv/`、`backend/.pytest_cache/`（通配 `.pytest_cache/`）、`backend/tests/.tmp/`、`node_modules/`、`.pnpm-store/`、`dist/`、`*.tsbuildinfo`、`*.db` / `*.db-wal` / `*.db-shm`、`.env` / `.env.*`（保留 `!.env.example`）、`logs/teamflow/`。**当前实测已 9/9 覆盖，本轮不新增条目**；若实测发现缺项，只补对应两栈的真实工具产物，不得泛化加噪。

**改动面白名单（超出即需在 TECHNICAL 中显式说明）**：
`backend/app/schemas.py`、`backend/app/services/{profile_merge,resume_polish,interview}.py`（仅空值防护/合并语义）、`backend/app/services/profile.py`（预期零改动，仅在必须补 validator 时允许）、`frontend/src/api/types.ts`、`frontend/src/pages/ProfilePage.tsx`、`frontend/src/components/profile/*`（仅空值展示）、`frontend/src/lib/profile.ts`（可选，归一函数单点）、对应测试文件（`backend/tests/*.py`、`frontend/src/**/*.test.ts`）、本任务夹文档。
**禁止改动**：`backend/app/db.py`（零 DDL）、依赖清单（`requirements*.txt` / `package.json` 依赖段）、`styles/tokens.css`、其余 5 入口提示词常量、`AIClient` 重试策略。

## 9. 里程碑建议

- **M1 契约对齐（约 0.3 天）**：AC-1、AC-2、AC-11（用例先行）——先把「真实形状」钉成 fixture，再改模型。
- **M2 后端下游（约 0.3 天）**：AC-4、AC-6、AC-8 —— 润色/面试/合并/存量兼容，全部可本机验。
- **M3 前端空值（约 0.3 天）**：AC-5 —— 归一 + 渲染 + 编辑，typecheck 0。
- **M4 真实 Key 与证据（约 0.3 天）**：AC-3、AC-9、AC-7、AC-10、AC-12 —— 真实链路 + 门禁全量 + 报告。
- 总估 **≈1 人天**；M1/M2/M3 可并行（文件所有权互不重叠），M4 依赖三者完成。

## 10. 假设与待澄清

- **假设 A1（展示形态，taste）**：`role/period` 为空时不显示占位文案，只是不渲染该片段（卡片 meta 只拼接有值项，不留 `·`、不留空行）。若用户希望显示「角色未填写」之类占位，则改为固定占位串并同步 DESIGN；影响 AC-5 的断言。
- **假设 A2（合并语义，taste）**：空值**不覆盖**已知值，维持 r3 对 `target_role` 的既有先例（「新简历没写时沿用旧值」）。若用户要求「以最新简历为准、空值即清空」，则 AC-6 反向断言，且可能出现「用户看到角色凭空消失」的观感。
- **假设 A3（提示词不动，taste）**：`PROFILE_SYSTEM` 逐字不改 —— 第 3 条已声明允许 `null`，只需把契约补齐；改提示词会波及已 PASS 的其它入口的共用措辞习惯。若用户坚持在 `projects` 行显式标注「无信息给 null」，属可选澄清，不影响契约。
- **假设 A4（真实调用预算，taste）**：真实 Key 调用按最小必要执行 —— 1 次画像 + 1 次面试开局 + 1 次提交评分，失败重试 ≤2 次；超出需用户另行同意。若用户希望更大样本（多份简历）以更强的证据支撑「非偶发」，则需追加调用与耗时。

