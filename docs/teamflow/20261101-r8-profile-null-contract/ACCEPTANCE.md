# r8 验收报告 — 画像 null 契约（`ProfileProject.role/period` 可空 + 真实四步闭环）

| 项 | 内容 |
|---|---|
| 需求 | 真实 AI 下「依据简历生成画像」必定 502（`AI_SCHEMA_INVALID`）：提示词允许 `role/period=null`，契约要求 `str` |
| 任务夹 | `docs/teamflow/20261101-r8-profile-null-contract/`（PRD 12 条 AC，P0 10 / P1 2） |
| 分支 | `feat/dev-skill-coach`（原地、未提交、未切分支） |
| 验收方式 | 逐条 AC 复核 = **本轮独立复跑**（acceptance 自己执行）＋ QA 证据交叉核对；不复用 QA 的结论 |
| 验收人 | 产品经理（acceptance lead） · 2026-11-01 |

## 1. 结论

12/12 AC 全部达成，其中 **AC-3（真实 Key 画像 200）与 AC-9（真实四步闭环）由本轮亲自重跑复现**，非转述 QA；口径修正在契约层一次到位，下游四处显式承载 `null`，反幻觉闸门零放松（`services/profile.py` 未出现在 diff 中）。架构与蓝图一致，唯一偏离（`rules.py` 新增轮次派生函数）是 QA 轮 1 缺陷 D-4 的最小修法、附反向自检，属正当偏离。**判定：通过**，遗留 2 条 P3 观察（不阻断）。

## 2. 逐条 AC 核对

| AC | 判据 | 本轮证据 | 结论 |
|---|---|---|---|
| AC-1 | 契约可空、前端镜像 | `schemas.py:91-92` `str \| None = None`；`types.ts:56-58` `string \| null`；`test_profile_null_contract.py` 23 例全绿 | ✅ |
| AC-2 | 同类 `null→[]` 闭集 | `_normalize_null_lists`(:133) + `_null_bullets`(:104) 单点；`name`/`source_quote` 仍必填；无 `extra="allow"`、无 `min_length` 放宽 | ✅ |
| AC-3 | 真实 Key 画像 200 + 溯源 | **本轮重跑** `check_r8_real_profile.py`：上传 200 → profile **200** 2.06s（attempt 1/3）；skills 6 / projects 3 / tech_stack 6；溯源 **18/18** 逐字命中；`role/period=null` 3/3；同一真实 payload 喂旧 `str` 形状 → 拒绝 3/3 `string_type`（零额外模型调用） | ✅ |
| AC-4 | 下游空值不崩 | `_allowed_numbers` 用 `period or ""`（:189）；`_profile_brief`(:290-315) `None` 键整体省略（含 `target_role`）；repository 往返 None 仍 None；polish 路由 200 —— 本轮 `check_qa_r8_functional.py` 26/26 | ✅ |
| AC-5 | 渲染与编辑不塌版 | 空值点三处全改：`joinMeta`(:146 meta)、`trimToNull(textOrEmpty(...))`(:275-276 出站)、`textOrEmpty`(:322/329 编辑框)；本轮 `probe/t3.cjs` **40/40**（含 `react-dom/server` 真实渲染：无 `null`/`undefined`/悬空 `·`）；vitest 109（含 profileText 9 条） | ✅ |
| AC-6 | 合并空值不丢信息 | `_prefer_text`(:146) 单点，`role/period` 复用(:182-183)，`bullets` `source or base or []`；旧 `前端主力` 不被 None 覆盖、两侧 None 不抛、新值可补全、`profile_id` 不变 —— 本轮 functional checker AC-6 三例 PASS | ✅ |
| AC-7 | 反幻觉与降级不放松 | `services/profile.py` / `ai.py` **零改动**（不在 `git diff --stat`）；编造 `source_quote` 仍 `AI_SCHEMA_INVALID`；200 字截断、去重、无 Key 503 未触碰；无 `extra="allow"` | ✅ |
| AC-8 | 存量兼容 | 旧 `str` 与**缺键** payload 均 `model_validate` 通过、None/`str` 各自保真；latest 与 PATCH 200 —— functional checker AC-8 6 例 | ✅ |
| AC-9 | 真实四步闭环 | **本轮重跑** `check_r8_real_chain.py`：开局 **200** 4.21s `total=9`（技术 5 / 项目 3 / 挑战 1）→ 作答 **200** 2.15s `score=2.0`(0–10)、点评 111 字(≤120) → GET 200 `answered=1`；总 6.38s；满场 12 轮不越界（QA `check_qa_r8_quota_legacy.py` 31/31 + 本轮 `check_r8_turn_cap_mutation.py` 反向自检通过） | ✅ |
| AC-10 | 门禁只增不减 | 见 §4：pytest **325**、vitest **109**、typecheck 0、lint 0 error/28 warn、build 通过、`/health` 200、NO_KEY_LEAK | ✅ |
| AC-11 | 回归用例钉住口径 | `REAL_MODEL_DRAFT` fixture + `test_prompt_shape_matches_contract` 互锁；`test_r8_profile_nullable_mirror`(gates:529)；本轮重跑 `check_r8_gate_sensitivity.py`：把 `role` 改回 `str` / 改 `types.ts` 后断言必须 False **全部 False**（门禁非空转） | ✅ |
| AC-12 | 报告如实可核查 | QA-REPORT 附修复前 502 + 两条 `string_type` 摘要与修复后 200/18-18 计数；`grep "sk-…"` 于任务夹与前端源码/产物 = 0；`git diff --stat` 无 `package.json`/`requirements.txt`（零新依赖） | ✅ |

## 3. 架构一致性（M3 强制项）

| 检查点 | 结论 |
|---|---|
| 契约层单点归一 | `ProfileDraft._normalize_null_lists` + `ProfileProject._null_bullets` 各一处；`Profile` 继承 `ProfileDraft` ⇒ 草稿/响应/存量共用一条路；`ProfilePatch` 顶层 `None` 仍是「不改」，**无第二份 validator** |
| 前端空值单点 | `lib/profileText.ts` 仅导出 `textOrEmpty`/`joinMeta`；`ProfilePage` 三个取值点全部改调用，其余文件无 `role/period` 直读（`grep` 命中的 `target_role ?? ''` 属既有口径，非本次范围） |
| 合并空值单点 | `_prefer_text` 唯一实现，与 r3 `target_role` 先例同源；未逐字段写三元表达式 |
| 轮次派生单点 | `max_turns`/`follow_ups_left`/`is_follow_up_allowed` 只在 `rules.py`，`interview.py` 仅调用；`grep MAX_INTERVIEW_TURNS backend/app` 只剩定义与注释，无第二份算术 |
| 冻结面 | `MIN_INTERVIEW_QUESTIONS=8`/`MIN_TECHNICAL=5`/`MIN_PROJECT=3`/`_check_structure`/`verify_quotes`/200 字截断 一行未改 |
| 蓝图偏离（已裁定可接受） | ① `INTERVIEW_SYSTEM` 规则 1 由 8→9 题（原算术 `5+3+1=9 > 8` 不可满足，是另一 502 根因，已由门禁 48 钉住）；② `rules.py` 新增派生函数不在原蓝图模块清单 —— 属 QA 轮 1 缺陷 D-4（9 题卷 13 轮越界）的最小修法，不动闸门常量、附两种回退的变异自检（本轮实测必红、还原转绿），**判为正当偏离**，不构成需要返工的结构问题 |
| 重复实现 / 适配漂移 | 未发现：无第二份 null 归一、无第二份轮次算术、无新路由/DDL/依赖 |

## 4. 门禁复核（本轮实跑）

| 门禁 | 要求 | 实测 |
|---|---|---|
| `cd backend && AI_API_KEY= python -m pytest -q -p no:cacheprovider` | ≥305 | **325 收集 / 全绿**（exit 0）；`test_profile_null_contract.py` 23、`test_engineering_gates.py` 26 |
| `cd frontend && npx vitest run` | ≥104 | **109 passed / 8 files** |
| `npm run typecheck` | 0 error | **0 error**（两套 tsconfig） |
| `npm run lint` | 0 error、≤28 warning | **0 error / 28 warning**（全部既有 `react-refresh`） |
| `npm run build` | 通过 | **通过**（267.81 kB / gzip 87.86 kB） |
| `GET /health`（uvicorn:8137，本轮启动实测） | 200 | **200** `{"status":"ok","version":"0.1.0","db":"sqlite"}` |
| Key 泄露扫描（`frontend/src` + `dist`） | 无 | **NO_KEY_LEAK**（`sk-`/`AI_API_KEY=` 0 命中） |
| `python -m ruff check app tests` | — | **未执行**（`No module named ruff`，环境缺失，按 AC-10 如实记录，不以缺工具冒充通过） |

## 5. 遗留与意见（均不阻断交付）

1. **D-5（P3，产品观察）**：9 题卷的追问上限被压到 3 次（12 轮预算里 9 道正题占 9 轮），8 题卷仍 4 次。这是「追问不得挤占剩余正题」的必然结果，非缺陷；若产品要求「计划题量 + 4 次追问」全用满，需另立需求改预算并同步更新额度断言。
2. **D-6（P3，文档漂移）**：r5 `TECHNICAL.md:186,302` 仍记 `is_follow_up_allowed` 3 参旧签名（代码已 4 参）。按 ADR-0008 历史任务夹不可改，已在 memory 待办留痕，由后续需求在架构文档补记。
3. **存量 v1 长卷语义**：v1 payload 的 `turns_left` 从首轮即为 0 属修复前既有语义（前端零消费），本轮未改，仅记录。
4. **人工补测清单（沿旧）**：真实浏览器视觉/动效、390px 真机、真实 PDF/DOCX 解析、`ruff` 环境补齐 —— 沙箱内无真实浏览器与 ruff，不伪造通过。

## 6. 交付面与卫生

- 改动面：9 改（`schemas.py`、`services/{interview,rules,profile_merge,resume_polish}.py`、`tests/{test_engineering_gates,test_interview_chat}.py`、`api/types.ts`、`pages/ProfilePage.tsx`）+ 3 新增代码（`tests/test_profile_null_contract.py`、`lib/profileText.ts`、`test/profileText.test.ts`），全部在蓝图白名单内。
- 无 `node_modules/`、`dist/`、`.env`、`*.db`、`logs/teamflow/` 进入提交面；项目根无散落脚本目录；零新依赖、零 DDL、零新路由。
- 未提交、未切分支（`feat/dev-skill-coach` 原地），符合「Agent 不提交」约束。

验收结论：✅ 通过
