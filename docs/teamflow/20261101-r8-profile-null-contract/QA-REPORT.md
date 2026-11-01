> r8（画像 null 契约 + 真实四步闭环）**D-4 修复复验**：12/12 AC 保持关闭，上轮唯一 P2（面试轮次上限）已关闭（原检测命令 exit 1→0，且反向自检证明门禁非空转），**可验收**；另留 2 条 P3 观察，不阻断。

# r8 QA 复验报告（第 2 轮 rework · 画像 null 契约 + 真实四步闭环）

## 1. 范围与环境

| 项 | 内容 |
|---|---|
| 任务夹 | `docs/teamflow/20261101-r8-profile-null-contract/` |
| 分支 | `feat/dev-skill-coach`（原地，未提交 / 未切分支） |
| 本轮被测改动 | 上一轮 D-4 修复：`backend/app/services/rules.py`（新增 `max_turns`/`follow_ups_left`、`is_follow_up_allowed` 改 4 参）、`backend/app/services/interview.py`（新增 `_planned_total`，`_round_input`/`_next_question` 走派生值）、`backend/tests/test_interview_chat.py`（+`test_turn_cap_derives_from_paper_size` 3 参数）、`backend/tests/test_engineering_gates.py`（`test_interview_prompt_paper_feasible` 追加门禁 48）；r8 其余 7 改 3 新增未变 |
| 后端 / 前端 | FastAPI + SQLite（`pytest -p no:cacheprovider`，零网络）/ React 18 + Vite 5 + TS strict |
| 真实模型 | `backend/.env` 的 `deepseek-chat`（本报告不含 Key/`.env` 内容；真实调用 3 次：AC-3 1 次、AC-9 2 次） |
| 环境限制 | ① 沙箱内无法启动真实浏览器（host token），前端改用 `react-dom/server` 真实渲染 + DOM 断言；② `ruff` 模块缺失（`No module named ruff`），按 AC-10 记「未执行」，不以缺工具冒充通过 |

## 2. 回归契约全量复跑（`logs/teamflow/tf-mvxkiihc-y5p1qf/scripts/`，逐条实跑）

| # | checker | 本轮实测（exit code） | 与上轮对比 |
|---|---|---|---|
| 1 | `check_qa_r8_functional.py`（契约/归一/下游/PATCH/存量/反幻觉） | **26 passed / 0 failed**，exit 0 | 持平 |
| 2 | `check_r8_t2_downstream_null.py`（润色白名单/开局投影/合并空值不覆盖） | **18/18 PASS**，exit 0 | 持平 |
| 3 | `check_r8_gate_sensitivity.py`（r8 镜像门禁内存变异） | **OK**（变异后断言必须 False 全部为 False），exit 0 | 持平 |
| 4 | `check_t3_profile_null_text.ts`（前端空值归一 + 真实组件渲染） | **40/40 asserts**，exit 0 | 持平 |
| 5 | `check_r8_contract_mutation.py`（AC-11 副本变异） | **PASS**：基线 exit 0 / 变异 A(role→str) exit 1 / 变异 B(types.ts) exit 1 / 原文 sha256 未变 | 持平 |
| 6 | `check_interview_prompt_gate_mutation.py`（D-1 反向自检） | **PASS**：9 题绿 → 改回 8 题 `1 failed` → 还原 `1 passed`、sha256 未变 | 持平 |
| 7 | `check_qa_r8_full_session.py`（**上轮 D-4 的检测命令**） | **20 passed / 0 failed**，**exit 1 → 0**；S2 实测「发言 12 = 正题 9 + 追问 3 ≤ 12」，归因断言「8 题老卷 = 12」同时 PASS | **上轮 exit 1 → 本轮 exit 0** |
| 8 | `check_r8_turn_cap_mutation.py`（D-4 修复的反向自检，dev 提供） | **PASS**：上限写死 → `1 failed`；去掉「剩余正题预留」→ `[9题][13题] 2 failed`；还原 exit 0、sha256 未变 | 新增（本轮实跑复核） |
| 9 | `check_r8_real_profile.py`（AC-3 真实 Key） | **PASS**：200 / 2.11s；skills 6 · projects 3 · tech_stack 6；溯源 **18/18**；`role/period=null` **3/3**；同 payload 喂旧 `str` 形状 → `string_type` 3/3（零额外调用） | 持平 |
| 10 | `check_r8_real_chain.py`（AC-9 真实四步闭环） | **PASS / exit 0**：开局 200 4.53s `total=9`（技术 5 / 项目 3 / 挑战 1）；作答 200 1.89s，score 3.0、点评 120 字；GET 200 answered=1；总 6.44s | 持平 |
| 11 | `check_qa_r8_quota_legacy.py`（**本轮新增**：逐轮额度 + 存量 v1 卷） | **31 passed / 0 failed**，exit 0；反向自检 `QA_QUOTA_MUTATE=old` → **exit 1 / 3 failed**（见 §3） | 新增表面 |

新增表面说明（6b）：上轮只验了「9 题满场发言数 ≤ 上限」这一条**结果**，仍缺两块：① 逐轮 `quota.turns_left`/`follow_ups_left`/`allow_follow_up` 与 `rules.*` 派生值是否**每轮**一致（D-4 的原始症状正是「第 12 轮 turns_left 已归 0 而会话仍继续 1 轮」，老 checker 只在开局验过一次）；② `_planned_total` 的**存量 v1 回落分支**（payload 无 `plan`）此前零覆盖——`create_run` 只造 v2 卷。两者已由 checker 11 补齐。

## 3. 上轮缺陷复验对照（表头非「严重级」，仅供追踪）

| 编号 | round-2 级 | 复验命令（原文照抄） | 本轮实测 | 状态 |
|---|---|---|---|---|
| D-1 | P0 | `cd backend && python -X utf8 ../logs/teamflow/tf-mvxkiihc-y5p1qf/scripts/check_r8_real_chain.py` | exit 0；开局 200、total=9（5/3/1）、评分 3.0、点评 120 字 | **已关闭（保持）** |
| D-2 | P3 | `check_t3_profile_null_text.ts`（40/40） | 空 `role/period` 输入框渲染占位、`value=""` | 已关闭（保持） |
| D-3 | P3 | `check_qa_r8_full_session.py` S5/S6 | 开局输入无 `"role": null` / `"target_role": null` | 已关闭（保持） |
| D-4 | P2 | `cd backend && AI_API_KEY= python -X utf8 ../logs/teamflow/tf-mvxkiihc-y5p1qf/scripts/check_qa_r8_full_session.py` | **exit 0，S2 PASS**（12 ≤ 12）；新 checker 逐轮额度 31/31；`turn_cap` 反向变异实测必红 | **已关闭** |
| 反幻觉闸门 | — | `pytest` 负向用例 + `git diff` | `name`/`source_quote` 仍必填、编造条目仍 `AI_SCHEMA_INVALID`、无 `extra="allow"`、`_check_structure`/`MIN_*`(8/5/3) 一行未改 | 未放松 |

复算缺陷类命中数（与 dev 修复摘要对比）：D-4 类（轮次上限越界）= 9 题卷 `13 > 12` 修复前 1 次命中 → 本轮 **0**；v1 13 题卷同样 `13 > 12` → 本轮 **0**（13 ≤ 13）；8 题卷 12/12 不变。dev 摘要「8→12、9→12、13→13」与本轮独立实测**逐项一致**，无口径分歧。反向自检把修复前三条口径在内存里复原后，本 checker 立即命中 3 条（2×「13 > 12」+ 1×「仍有 1 道正题待问却 turns_left=0」），证明其非空转。

## 4. 用例与结果（命令在 `backend/` / `frontend/` 下执行）

| AC | 验证点 | 命令（摘要） | 结果 |
|---|---|---|---|
| AC-1 | 真实 payload（`role/period=null`）过 `ProfileDraft`/`Profile` 往返，`None` 不回退成 `""` | `pytest tests/test_profile_null_contract.py`（23 条） | PASS |
| AC-2 | `skills/tech_stack/projects` 的 null/缺键 → `[]`；`bullets:null → []`；`name`/`source_quote` 仍必填 | 同上 + `check_qa_r8_functional.py` | PASS |
| AC-3 | 真实 Key 上传→画像 200、计数、溯源逐字命中、null 3/3 | `check_r8_real_profile.py` | PASS（§2-9） |
| AC-4 | 润色 `_allowed_numbers(period=None)` 不崩、开局输入省略 null 键、落库读回 None、`polish` 路由 200 | `pytest` 定向用例 + `check_qa_r8_functional.py` | PASS |
| AC-5 | 渲染无 `null`/悬空 `·`、编辑留空可存 PATCH 200 且仍为 null、归一函数单测 | `check_t3_profile_null_text.ts` 40/40 + vitest 109 | PASS |
| AC-6 | 空值不覆盖已知 `role/period/bullets`；新值可补全；两侧 None → None；`profile_id` 不变；证据累积 | `pytest` merge 用例 + `check_r8_t2_downstream_null.py` 18/18 | PASS |
| AC-7 | 编造 `source_quote` 仍被拒；200 字截断/去重/无 Key 503 未放宽 | `pytest` 负向用例 + diff 静态核对（`profile.py`/`ai.py` 未触碰） | PASS |
| AC-8 | 存量画像（str 或字段缺失）读回、latest/PATCH 均 200 | `check_qa_r8_functional.py`（AC-8 6 条） | PASS |
| AC-9 | 真实四步闭环：画像→开局≥8题→作答→评分 0–10 且 ≤120 字；**满场 12 轮不越界** | `check_r8_real_chain.py` + `check_qa_r8_full_session.py` + `check_qa_r8_quota_legacy.py` | PASS |
| AC-10 | pytest≥305 / vitest≥104 / typecheck 0 / lint 0·≤28 / build / health / NO_KEY_LEAK | 见 §5 | PASS（ruff 未执行） |
| AC-11 | 真实形状 fixture 与 `PROFILE_SYSTEM` 互锁；改回 `str` 必红 | `check_r8_contract_mutation.py` + `check_r8_gate_sensitivity.py` | PASS |
| AC-12 | 报告如实、修复前后同请求证据、零 Key、零新依赖 | 本报告 §2/§9 | PASS |

## 5. 门禁汇总（逐条实跑）

| 门禁 | 要求 | 实测 |
|---|---|---|
| `AI_API_KEY= python -m pytest -p no:cacheprovider` | ≥305 | **325 收集 / 全绿**（exit 0；上轮 322 + `test_turn_cap_derives_from_paper_size` 3 参数） |
| `tests/test_engineering_gates.py` | 只增不减 | **26 条**（含 `test_r8_profile_nullable_mirror`、`test_interview_prompt_paper_feasible` 的门禁 48 断言） |
| `tests/test_profile_null_contract.py` | ≥8 | **23 条** |
| `vitest run` | ≥104 | **109 passed / 8 files** |
| `npm run typecheck` | 0 error | **0 error** |
| `npm run lint` | 0 error、≤28 warning | **0 error / 28 warning**（无新增文件） |
| `npm run build` | 通过 | 通过（92 modules，267.81 kB） |
| `GET /health`（uvicorn:8128，临时库 `tests/.tmp/qa-health-r8c.db`） | 200 | **200** `{"status":"ok","version":"0.1.0","db":"sqlite"}` |
| `grep -riE "sk-\|api_key\|AI_API_KEY" src/ dist/` | 无 | **NO_KEY_LEAK** |
| `python -m ruff check app tests` | — | **未执行**（`No module named ruff`，环境缺失，不伪造通过） |

## 6. 架构核查（蓝图一致性 · 0 条 P1 架构缺陷）

| 检查点 | 结论 |
|---|---|
| 轮次口径单点派生 | `max_turns`/`follow_ups_left`/`is_follow_up_allowed` 只在 `rules.py` 实现；`interview.py` 两处调用点（`_round_input` :428-432、`_next_question` :466）全部走派生值，**无第二份 `MAX_INTERVIEW_TURNS - len(entries)` 算术**（`grep MAX_INTERVIEW_TURNS backend/app/` 仅定义与注释） |
| 计划题量单点 | `_planned_total` 唯一实现（v2 取 `plan`、v1 回落非追问发言数）；与结构分母 `_total_of` 各司其职（后者 v1 优先 payload `total`），未合并以免改动结束闸门分母 |
| 冻结面未动 | `MIN_INTERVIEW_QUESTIONS=8` / `MIN_TECHNICAL=5` / `MIN_PROJECT=3` / `MAX_FOLLOW_UPS=4` / `MAX_INTERVIEW_TURNS` 数值与 `_check_structure`、`verify_quotes`、200 字截断、去重**一行未改**（`git diff -U0` 后 grep `_check_structure\|MIN_\|verify_quotes` → 空） |
| 契约单点归一（保持） | `ProfileDraft._normalize_null_lists`（before）+ `ProfileProject._null_bullets` 一次覆盖草稿/响应/存量；`ProfilePatch` 顶层 `None` 仍表「不改」 |
| 前端单点收敛（保持） | `lib/profileText.ts` 仅导出 `textOrEmpty`/`joinMeta`，`ProfilePage` 三处空值点全部改调用；`turns_left`/`follow_ups_left`/`allow_follow_up` **前端零消费**（`grep frontend/src/` → NONE），故本轮无需前端契约镜像 |
| 重复实现 / 未抽抽象 | 未发现：无第二份 null 归一、无第二份轮次算术、无新路由 / DDL / 依赖（`git status` 无 `package.json`/requirements 改动） |
| **蓝图偏离（已记录，可接受）** | ① 上轮 D-1：`INTERVIEW_SYSTEM` 规则 1（8→9 题），原规则 `5+3+1=9 > 8` 算术不可满足，是 502 根因，已由新门禁钉住；② 本轮 D-4：蓝图 api 清单未含 `rules.py` 新增派生函数——但它是 D-4 缺陷（上一轮修复引入的轮次越界）的最小修法，且不动任何闸门常量、附反向自检，属「偏离但正当」 |

## 7. 接口一致性（0a · 静态，无需运行）

| 调用 | 目标成员存在？ | 签名匹配？ | 依据 |
|---|---|---|---|
| `rules.is_follow_up_allowed(kind, follow_up_count, asked, planned_total)`（interview.py:431、:466） | 是（rules.py:154） | 4 参，两处均传 4 参 | `grep -rn "is_follow_up_allowed" --include=*.py backend/` → 仅定义 + 2 调用 + 文档字符串，**无残留 3 参调用**；测试无外部调用 |
| `rules.max_turns(planned_total)`（interview.py:429，gates 测试） | 是（rules.py:132） | 1 参 | 同上 grep |
| `rules.follow_ups_left(planned_total, asked, follow_up_count)`（interview.py:428，gates 测试） | 是（rules.py:142） | 3 参 | 同上 grep |
| `_planned_total(payload, entries, follow_up_count)`（interview.py:403、:461） | 是（interview.py:360） | 3 参 | 实跑 `pytest` 325 全绿 + 新 checker 31/31 |
| 前端 `joinMeta`/`textOrEmpty`（上轮已核） | 是（`export function` ×2） | 1 参 | 40/40 DOM 断言 |

## 8. 提交面卫生（0c）

- `git status --porcelain=v1 -uall`：9 改（`schemas.py`、`services/{interview,rules,profile_merge,resume_polish}.py`、`tests/{test_engineering_gates,test_interview_chat}.py`、`api/types.ts`、`pages/ProfilePage.tsx`）+ 3 新增代码（`tests/test_profile_null_contract.py`、`lib/profileText.ts`、`test/profileText.test.ts`）+ 任务夹 4 文档；**无** `node_modules/`、`dist/`、`.env`、`*.db`、`logs/teamflow/`，项目根无散落 `scripts/`/`probe/`。
- `.gitignore` 实测 6/6 命中：`.env`(:41)、`backend/tests/.tmp/`(:38)、`node_modules/`(:8)、`dist/`(:11)、`__pycache__/`(:18)、`logs/teamflow/`(:2)。
- 零新增依赖：`package.json` / requirements 均未出现在改动列表。

## 9. 缺陷（仅 OPEN）

| 编号 | 严重级 | 功能模块 | 复现步骤 | 期望行为 | 实际行为 | 关联验收项 | 检测命令 | 通过判据 |
|---|---|---|---|---|---|---|---|---|
| D-5 | P3 | 模拟面试 · 追问配额（D-4 修复的派生代价，产品观察） | 1) 以 9 题卷开局；2) 每轮请求追问；3) 打到结束 | 每场可用满 `MAX_FOLLOW_UPS=4` 次追问（r5 口径的直觉读法） | 9 题卷追问上限被压到 **3**（12 轮预算里 9 道正题占去 9 轮）；8 题卷仍是 4。属「追问不得挤占剩余正题」的必然结果，非功能缺陷 | AC-9 周边（r5 追问口径） | -（`check_qa_r8_quota_legacy.py` 打印「发言 12（追问 3）」，exit 0） | 若产品要求 9 题卷也用满 4 次追问，需把预算改为「计划题量 + MAX_FOLLOW_UPS」，届时该 checker 的 Q/L 断言需同步更新 |
| D-6 | P3 | 架构/文档（历史任务夹漂移） | `grep -rn "is_follow_up_allowed" docs/teamflow/` | 文档签名与代码一致 | `docs/teamflow/20261101-r5-interview-chat-config/TECHNICAL.md:186,302` 仍记 3 参旧签名（代码已 4 参）。按 ADR-0008 历史任务夹不可改，故以本报告记录 | AC-12（报告如实） | -（静态漂移，非运行缺陷） | 由后续需求在 memory.md/架构文档补记新签名；历史夹保持不改 |

存量 v1 长卷观察（不计缺陷）：v1 payload 的 `questions` 预载全卷，`turns_left = max_turns - len(entries)` 从首轮即为 0（13 题卷），与修复前逐字一致（旧代码同样 `12 - 13` 归 0），且 `allow_follow_up` 正确为 False、13 道正题一题不落、会话正常结束 —— **非回归**，仅提示 v1 卷的该字段语义本就与 v2 不同（前端零消费）。

## 10. 人工补测清单（环境限制，非交付缺陷）

| 项 | 方法 / 工具 | 说明 |
|---|---|---|
| 真实浏览器渲染 `/profile` 的 null 项目卡（390px 无横滚、meta 行视觉） | 开发机 Chrome + DevTools 设备模拟 | 本轮用 `react-dom/server` 真实渲染 + DOM 断言替代（40/40），像素级未经人眼确认 |
| 9 题卷 **真实 Key 满场 12 轮**（时长/节奏/追问降为 3 的体感） | 真机完整走一场（12 次真实调用，本轮预算外） | 本轮真实 Key 只到「开局 + 1 答」（AC-9 判据），满场用 fake AI 覆盖（A-9/Q 面） |
| 项目编辑弹层空值占位的焦点态/键盘走查 | 真实浏览器 Tab/Enter 走查 | 占位文本已 DOM 级验证；焦点环与真人手感未验 |
| `ruff` 静态检查 | 有 ruff 的环境执行 `python -m ruff check app tests` | 本机缺模块，未执行 |

## 11. 结论

- **可验收**：12/12 AC 保持关闭；上轮唯一 P2（D-4 面试轮次上限）**已关闭**——原检测命令 `check_qa_r8_full_session.py` exit 1→0（20/0，S2 PASS 12≤12，归因断言同绿），新增 `check_qa_r8_quota_legacy.py` 逐轮独立复算 31/31，且 `QA_QUOTA_MUTATE=old` 反向自检实测 3 failed / exit 1，证明该 checker 真能抓住修复前缺陷。
- 复算缺陷类命中数：D-4 类修复前 9 题卷 / v1 13 题卷各 1 次越界 → 本轮 **0**；8 题卷 12/12 不变；与 dev 修复摘要逐项一致。
- 门禁只增不减：pytest 322→**325**、vitest **109**、typecheck 0、lint 0 err/28 warn、build 通过、/health 200、NO_KEY_LEAK、零新依赖、零越界文件。
- 留 2 条 P3 观察（追问配额 4→3 的派生代价、r5 历史文档签名漂移），均不阻断。
