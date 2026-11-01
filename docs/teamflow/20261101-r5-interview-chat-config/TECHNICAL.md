<!-- meta: summary="r5 技术方案：`runs.payload` v2（settings + plan + 递增 questions + current_id）承载对话流会话，零新表零迁移；3 条面试路由（开局只返回 1 条发言 / 每轮同轮产出「评分 + 下一条发言」/ `GET /api/interviews/{run_id}` 恢复）；每轮一次 AI 调用（timeout_s=14）先算后写，失败零副作用；四项配置由 rules.py 纯映射进每轮提示词且永不写回画像；前端 /interview 重写为 7 态 + 6 个新增气泡组件，评分与点评并置于候选人气泡内。" -->

# TECHNICAL · r5 · 模拟面试对话化与面试配置项

> **基线**：`docs/teamflow/20261101-r4-r3-acceptance-closure/`（四步闭环、报告「题号 + 得分」证据、成长时间线、简历润色、18 项门禁不得回归）。
> **取代**：`docs/teamflow/20261031-r1-dev-skill-coach/` 的「一次性出 8 题 + 逐题单屏卡片」作答形态；结构下限与「提交→出分 ≤15s」口径原样保留。
> **上游**：本夹 `PRD.md`（18 条 AC）、本夹 `DESIGN.md`（§0 观感规格 + 7 态 + 组件落点）。尺寸只在 DESIGN 里改，本文只做落地映射。
> **实测基线**：`cd backend && python -m pytest -q -p no:cacheprovider` 全绿（118 passed）；`frontend/node_modules` 已存在（`npm test` / `npm run build` 可跑）；`python -m ruff` **本环境不可用**（`No module named ruff`）→ 见 §10。

---

## 0. 架构判断（一句话）

**会话唯一真相仍是 `runs.payload`，但形状从「成品试卷」升级为「本场计划 + 增量对话」**：开局把一份经闸门校验的 8 题计划写进 `payload.plan`，只把第 1 题投放为 `payload.questions[0]`；此后每轮**一次 AI 调用**同时产出「本轮评分」与「下一条发言」（追问就地生成、正题从计划原文取），一次 `save_run` 原子落库。因此：无新表、无 SQL、无迁移（AC-14），刷新可恢复（AC-9），结构下限由「计划闸门 + 结束闸门」双保险（AC-7）。

---

## 1. 数据模型与存储

### 1.1 `runs.payload`（v2，唯一会话真相）

`repository` 的 `runs` 表已够用（`id/kind/profile_id/payload/status/created_at`），**零新增表、零 SQL 迁移**（AC-14）。payload 新增 `version` 字段便于读取分支，其余全部向后兼容。

```json
{
  "version": 2,
  "settings": {                       // 本场生效值（服务端补全后），AC-2②
    "target_role": "Android 开发工程师",
    "years_experience": "1-3年",
    "market": "北美",
    "company_size": "初创"
  },
  "calibration": {                    // 口径要点快照（纯函数产物，便于排障/断言；不进 HTTP 契约）
    "role": "…", "experience": "…", "market": "…", "company": "…"
  },
  "plan": [ { "kind": "technical", "prompt": "…", "hint": "…" }, … 共 ≥8 ],
  "plan_index": 0,                    // 已投放的计划下标（0 = 第 1 题已投放）
  "questions": [                      // 本场**已提出**的发言（图标即气泡，只增不改序）
    { "id": "iq-1", "kind": "technical", "prompt": "…", "hint": "…",
      "parent_id": null,              // AC-6：追问指向父题
      "answer": null, "score": null, "comment": null,
      "answered_at": null, "elapsed_s": null }
  ],
  "answered_count": 0,                // 有分数的条数（history.score_of 同口径）
  "total": 8,                         // = len(plan)，结构分母（AC-7）
  "follow_up_count": 0,               // 已用追问配额（≤4）
  "turn": 0,                          // 已推进轮次（前端「已推进 N 轮」）
  "current_id": "iq-1"                // 当前待答题 id；null = 会话已结束
  "status" 不进 payload —— 权威在 runs.status（running / completed）
}
```

字段级不变量：

| 不变量 | 作用 | AC |
| --- | --- | --- |
| `len(questions) ≤ turn + 1`（running 时恰 = turn + 1） | 气泡条数 = 已提出题数，不预先铺开 8 题 | AC-4 |
| `questions` 只追加、永不变序、`id = iq-{len+1}` 单调 | 题号刷新不变、报告证据可按下标反查 | AC-8 |
| `total` 恒 = `len(plan)`，不随追问增长 | 结构分母单一，追问不放大「本题数」 | AC-7 |
| `parent_id ≠ null` ⇒ `kind` 与父题逐字相同 | 追问不引入新分类 | AC-6 |
| `current_id` 指向唯一未答发言；结束置 `null` | 并发/重试的唯一推进依据 | AC-9/AC-10 |
| `settings` 只进 payload，**不写回 `profiles`** | 临时设定不污染长期资产 | AC-3 |

### 1.2 兼容与容错（旧 run 只读，不迁移）

`load_session` 对老 payload（r1–r4 的「成品试卷」：只有 `questions` + `answered_count` + `total`）按下列规则降级，**读取绝不抛错**：

- `settings` 缺失或 4 键不全/取值不在闭集 → `null`（前端显示「未记录设定」）。
- `parent_id` 缺失 → `null`；`plan` / `current_id` / `turn` / `follow_up_count` 缺失 → `[]` / 首个未答 `id` / `answered_count` / `0`。
- 老 run 若 `status=completed` → 只读；若 `status=running`（历史残留）→ `current_id` = 首个未答 id，可续答（走同一轮次引擎）。
- 历史/报告投影（`RunSummary` / `Report`）读不到 `settings` → `null`。

### 1.3 存储动作

- **写**：`create_run` 一次 `repository.insert_run`；每轮一次 `repository.save_run`（**成功路径唯一写点**）。
- **读**：`repository.get_run` / `list_runs`（唯一 SQL 出口，本次不改 `repository.py`）。
- **不**：不改 `init_db()`、不加索引、不 backfill。

---

## 2. API 设计

### 2.1 路由总表（前缀 `/api/interviews`）

| 方法 | 路径 | 入参 | 出参 | 语义 |
| --- | --- | --- | --- | --- |
| POST | `/api/interviews` | `InterviewCreateRequest` | `InterviewRun` | 开局：补全 settings → 生成计划 → 闸门校验 → 落库 → **只返回第 1 条发言** |
| POST | `/api/interviews/{run_id}/answers` | `AnswerRequest` | `InterviewTurn` | 一轮：评分 + 下一条发言（追问/下一正题/结束） |
| GET | `/api/interviews/{run_id}` | — | `InterviewSession` | **新增**：刷新 / 重进恢复全量会话（不重出题、不重计分） |

### 2.2 `POST /api/interviews` → `InterviewRun`

```json
// 请求（settings 四项全可选；整场跳过 = 不传）
{ "profile_id": "p-xxx",
  "settings": { "target_role": "Android 开发工程师", "years_experience": "1-3年",
                "market": "北美", "company_size": "初创" } }

// 响应（AC-4：只有 1 条发言，没有题目列表数组）
{ "run_id": "…",
  "settings": { "target_role": "…", "years_experience": "…", "market": "…", "company_size": "…" },
  "question": { "id": "iq-1", "kind": "technical", "prompt": "…", "hint": "…", "parent_id": null },
  "total": 8 }
```

### 2.3 `POST /api/interviews/{run_id}/answers` → `InterviewTurn`

```json
// 请求（形状不变，question_id = 当前气泡 id）
{ "question_id": "iq-1", "answer": "…" }

// 响应（ScoreResult 超集：score/comment 原样保留，便于 AC-5 逐字断言）
{ "score": 7.5,
  "comment": "…≤120 字中文点评…",
  "next_question": { "id": "iq-2", "kind": "technical", "prompt": "…", "hint": "…", "parent_id": null },
  "run_status": "running",       // "running" | "completed"
  "answered_count": 1, "total": 8, "interview_avg": 7.5 }
```

- `next_question = null` ⇔ 本场结束（`run_status=completed`）；前端据此切 `ended` 态。
- 追问轮：`next_question.parent_id = ` 父题 id、`kind` 继承父题。
- **重答已答旧题**（`question_id` 不是 `current_id`）：只覆盖分数/点评，**不追加发言、不推进 turn**（AC-10 不重复计分 / AC-9 不重出题）。

### 2.4 `GET /api/interviews/{run_id}` → `InterviewSession`

```json
{ "run_id": "…", "status": "running",
  "settings": { … } | null,
  "questions": [ { "id": "iq-1", "kind": "technical", "prompt": "…", "hint": "…",
                   "parent_id": null, "answer": "…", "score": 7.5, "comment": "…" }, … ],
  "answered_count": 1, "total": 8, "current_id": "iq-2", "interview_avg": 7.5 }
```

`status=completed` ⇒ `current_id=null`（前端只读：输入区禁用 + 中文文案）。

### 2.5 错误矩阵（沿用 `{error:{code,message,retryable}}`，message 中文、不含路径/端点/Key）

| 场景 | code | status | retryable | 副作用 |
| --- | --- | --- | --- | --- |
| 画像不存在（开局） | `NOT_FOUND` | 404 | false | 无 |
| run 不存在 / 不是面试 run | `NOT_FOUND` | 404 | false | 无 |
| `question_id` 不在本场 | `NOT_FOUND` | 404 | false | 无 |
| 回答为空 | `VALIDATION_ERROR` | 400 | false | 无 |
| run 已结束还提交 | `VALIDATION_ERROR` | 400 | false | 无 |
| 计划闸门不合格（开局 / 结束） | `AI_SCHEMA_INVALID` | 502 | true | 无（不落库） |
| 单轮 AI 超时 / 连接失败 / 服务端 5xx | `AI_UNAVAILABLE` | 503 | true | **零副作用** |
| 无 AI Key | `AI_UNAVAILABLE` | 503 | true | 无（`ai.py` 既有映射） |

### 2.6 契约双侧同步（AC-14，字段名 snake_case，Python 侧零转换）

| `backend/app/schemas.py` | `frontend/src/api/types.ts` | 变更 |
| --- | --- | --- |
| `ExperienceBand` / `InterviewMarket` / `CompanySize`（Literal） | 同名字符串联合 | 新增 |
| `InterviewSettings`（4 键全必填，默认值） | 同名 interface | 新增 |
| `InterviewSettingsPatch`（4 键全可选） | 同名 interface | 新增 |
| `InterviewQuestion`（+`parent_id: str\|None`） | 同名 interface | 增量 |
| `InterviewCreateRequest`（+`settings?`） | 同名 interface | 增量 |
| `InterviewRun`（`questions` **删除**；+`settings`/`question`/`total`） | 同名 interface | **破坏性重写（两侧同批）** |
| `ScoreResult`（保留，`InterviewTurn` 继承它） | `InterviewTurn extends ScoreResult` | 新增子类 |
| `InterviewSessionQuestion` / `InterviewSession` | 同名 interface | 新增 |
| `RunSummary`（+`interview_settings: …\|None = None`） | 同名 interface 增量 | 增量 |
| `Report`（+`interview_settings: …\|None = None`） | 同名 interface 增量 | 增量 |

保留 `ScoreResult` 的理由：`score/comment` 仍是「单轮评分」的语义载体，`InterviewTurn` 继承它 → 既有的分数越界校验用例（`ScoreResult.model_validate({"score":11})`）与 `lib/format` 展示无需另写一套，也不留死类型。

---

## 3. 后端实现

### 3.1 模块与函数签名（下游必须逐字调用）

**`backend/app/services/rules.py`**（阈值与口径的唯一出处；新增面试配置段）

```python
EXPERIENCE_BANDS: tuple[str, ...] = ("应届", "1-3年", "3-5年", "5-10年", "10年以上")
MARKETS: tuple[str, ...] = ("国内", "北美", "欧洲", "其他")
COMPANY_SIZES: tuple[str, ...] = ("大厂", "中型", "初创")
DEFAULT_TARGET_ROLE = "通用软件工程师"
DEFAULT_EXPERIENCE_BAND = "1-3年"
DEFAULT_MARKET = "国内"
DEFAULT_COMPANY_SIZE = "中型"
MAX_FOLLOW_UPS = 4                 # 每场追问上限
MAX_INTERVIEW_TURNS = 12           # = MIN_INTERVIEW_QUESTIONS + MAX_FOLLOW_UPS

def experience_band_of(years: float | None) -> str:      # <1 应届 / [1,3) / [3,5) / [5,10) / ≥10；None → DEFAULT
def is_follow_up_allowed(kind: str, follow_up_count: int, total_questions: int) -> bool:
    """追问守门：配额未满 ∧ 非 challenge 父题 ∧ answered+1 ≤ MAX_INTERVIEW_TURNS。

    非 challenge 的追问只会提高 technical/project 计数、拉低 challenge 占比，
    因此「开局闸门通过 ⇒ 结束闸门必通过」；challenge 一律不追问（避免挑战题 >20%）。
    """
```

（既有 `MIN_INTERVIEW_QUESTIONS` / `MIN_TECHNICAL_QUESTIONS` / `MIN_PROJECT_QUESTIONS` / `MAX_CHALLENGE_RATIO` / `max_challenge_count` / `is_challenge_kind` **一律不改**。）

**`backend/app/services/interview.py`**（会话引擎；`SCORING_TIMEOUT_S`、`MAX_COMMENT_CHARS`、`QUESTION_ID_PREFIX`、`INTERVIEW_KIND` 保留）

```python
HISTORY_WINDOW = 3                 # AC-6：最近 3 轮全文进提示词

def fill_settings(patch: InterviewSettingsPatch | None, profile: Profile | None) -> InterviewSettings
    # patch 优先 → 画像（target_role / experience_band_of(years_experience)）→ 兜底默认

def calibration_of(settings: InterviewSettings) -> dict[str, str]
    # 纯映射：{"role","experience","market","company"} 四段中文口径要点（每档 ≥1 条、档间互不相同）

def validate_questions(questions: list[InterviewQuestion]) -> None      # 保留签名（AC-7 开局闸门）
def validate_session(entries: list[dict[str, Any]]) -> None             # AC-7 结束闸门（同一口径，读 kind/prompt）

async def create_run(profile_id: str, settings: InterviewSettingsPatch | None = None,
                     *, client: AIClient | None = None) -> InterviewRun
async def score_answer(run_id: str, question_id: str, answer: str,
                       *, client: AIClient | None = None) -> InterviewTurn
def load_session(run_id: str) -> InterviewSession
```

内部（私有，不进 blueprint 公共面）：`_plan_input` / `_round_input` / `_next_question` / `_entry_of` / `_squash` / `_score_of` / `_comment_of`。

**`backend/app/routers/interview.py`**（只做参数与错误映射）

```python
POST ""                       -> InterviewRun     # create_interview_run(payload.profile_id, payload.settings)
POST "/{run_id}/answers"      -> InterviewTurn
GET  "/{run_id}"              -> InterviewSession  # load_session(run_id)，同步 def
```

**`backend/app/services/history.py`**：`list_history(limit)` 每行补 `interview_settings`（面试 run 取 `payload.settings` 合法值，否则 `None`；笔试恒 `None`）。
**`backend/app/services/diagnosis.py`**：新增 `interview_settings_of(runs: list[dict[str, Any]]) -> InterviewSettings | None`（取 `runs` 里**最新一条**合法面试设定）；`build_report(...)` 透传进 `Report.interview_settings`。

### 3.2 配置补全与口径映射（AC-1 / AC-2④ / AC-3）

`fill_settings` 的补全优先级与前端预填**逐条对称**（前端只是「显示层预填」，服务端结果才是权威）：

| 字段 | 来源 1 | 来源 2 | 兜底 |
| --- | --- | --- | --- |
| `target_role` | 用户填写 | 画像 `target_role` | `通用软件工程师`（≤40 字，超长截断） |
| `years_experience` | 用户选择 | 画像 `years_experience` → `experience_band_of` | `1-3年` |
| `market` | 用户选择 | — | `国内` |
| `company_size` | 用户选择 | — | `中型` |

`calibration_of`（纯函数，AC-2④ 单测逐档断言「非空 + 档间集合互不相同」）：

| 维度 | 档 → 口径要点（各档互不相同） |
| --- | --- |
| role | 「按 {target_role} 的职责与技术栈出题；与画像岗位冲突时以本项为准，项目素材尽量复用」 |
| experience | 应届 / 1-3年 → 基础概念、学习潜力，不考大规模架构取舍；3-5年 → 独立负责模块、有依据的技术取舍；5-10年 → 架构设计、跨团队协作与风险；10年以上 → 技术判断、选型与组织影响 |
| market | 国内 → 业务落地 + 基础原理深度（并发/内存/框架原理）；北美 → 系统设计与英文技术表达（规模/边界/trade-off）；欧洲 → 工程规范、可维护性与协作；其他 → 通用口径 |
| company | 大厂 → 大规模系统 + 流程协作 + 深度原理；中型 → 端到端负责 + 性能与成本；初创 → 全栈落地 + 资源受限取舍 + 快速交付 |

**AC-3 实现要点**：`create_run` 全程只读 `repository.get_profile`，**不调用任何 `save_profile`/`patch`**；契约里也没有「写回」入口。

### 3.3 提示词（结构化 JSON 投喂，不拼散文）

- `INTERVIEW_SYSTEM`（改）：要求「产出本场计划」——8 题、technical ≥5、project ≥3、challenge ≤2、题干互不相同、`ids` 由服务端重编号；说明「只输出 1 条发言供开场，其余按计划逐轮投放」；输出 JSON `{"questions":[{kind,prompt,hint}]}`（复用内部模型 `InterviewDraft`，`extra="ignore"`）。
  - `user` = `{"settings":{4键},"calibration":{4段},"profile":{target_role,years,tech_stack,skills,projects}}`（沿用既有 `_profile_brief` 的裁剪口径，不送整份简历）。
- `ROUND_SYSTEM`（新）：输入
  ```json
  {"settings": {…4 键…}, "calibration": {…},
   "history": [ {"id","kind","prompt","answer","score"} 最近 3 轮全文 ],
   "earlier": [ {"id","prompt"} 更早轮题面摘要 ],
   "current": {"id","kind","prompt","hint"},
   "answer": "…", "next_plan": {kind,prompt,hint} | null,
   "quota": {"follow_ups_left": 3, "turns_left": 9}, "allow_follow_up": true}
  ```
  输出 `{"score": 数字, "comment": "≤120 字中文点评", "next": {"mode": "follow_up|advance", "prompt": "…", "hint": "…"}}`。
  - 评分口径与既有 `SCORE_SYSTEM` 的 0–10 分档保持一致（<4 / 4–6 / 7–8 / 9–10），点评要求「先理由、再一条可改点」。
  - `follow_up`：必须接住上一答（追问/澄清/施压），题面 ≤120 字；`advance`：按计划下一题，`prompt` 可留空。
- **AC-2③ 可断言点**：`settings` 四键**出现在开局请求与每一轮的 `user` JSON 里**（fake client 断言首轮与第 2/3 轮均命中）。
- **AC-6 可断言点**：第 3 轮的 `history` 含第 1、2 轮 `answer` 原文（窗口 3 全文）+ 更早轮题面摘要。

### 3.4 轮次编排算法（`score_answer`）

```text
1  run = repository.get_run(run_id)；None 或 kind≠interview → 404「没有找到这次面试记录…」
2  status == completed → 400「这场面试已经结束，可重开一场」（前置于任何写入）
3  payload = dict(run.payload)；entries = payload.questions；target = entries[question_id] → 缺 404
4  text = answer.strip()；空 → 400
5  （不写库）draft = await ai.complete_model(ROUND_SYSTEM, _round_input(...), RoundDraft,
                                             timeout_s=SCORING_TIMEOUT_S)   ← 保留字面量，工程门禁断言
6  comment = draft.comment.strip()[:120] or "已记录本次作答，建议补充量化结果"
7  is_current = payload.current_id == question_id
8  若 is_current:
     next = _next_question(payload, target, draft.next)        # 见 3.5
     若 next is None:
         validate_session(entries_after_scoring)              # AC-7 结束闸门，失败 → 502（此时未写库）
         payload.current_id = None；status = COMPLETED
     否则: 追加 next（id = iq-{len+1}）、payload.plan_index 相应推进、current_id = next.id、
           follow_up_count += 1（仅追问）、turn += 1
   否则（重答旧题）: 只覆盖分数/点评，不追加、不推进 turn、不改 current_id
9  target.update(answer/score/comment/answered_at/elapsed_s)；answered_count 重算
10 repository.save_run(run_id, payload, status)               ← 唯一写点
11 status==COMPLETED 时 timeline.record_run_event({...})（既有旁路，幂等键 (type, ref_id)）
12 return InterviewTurn(score, comment, next_question, run_status, answered_count, total, interview_avg)
```

`interview_avg` 复用 `history.score_of("interview", payload)` —— 均分口径**唯一来源**（PRD §8 依赖），本层不另写一套。

### 3.5 下一条发言（`_next_question`，AC-4/AC-6/AC-7 共同落点）

```python
def _next_question(payload, target, d) -> InterviewQuestion | None:
# ① 追问：d.mode=="follow_up" ∧ rules.is_follow_up_allowed(target.kind, follow_up_count, len(entries))
#    ∧ 题面非空 ∧ _squash(prompt) 与既有题干不重复   → 新发言（kind=父题kind, parent_id=父题id）
# ② 正题：plan_index+1 存在 → 取 payload.plan[plan_index+1] 的 kind/prompt/hint **原文**
#    （不让模型改写正题：计划是结构闸门，改写会引入新的去重/配比风险）
# ③ 都没有 → None（会话结束）
# 追问被守门拦下时，第 ② 步照常执行（提问不受影响，不会 502）
```

追问降级规则（保证轮次永不因文案问题整轮失败）：`mode=follow_up` 但题面空/重复/未被允许 → 静默降级为第 ② 步（advance），并在 `calibration` 之外不留任何额外字段。

### 3.6 结构闸门（AC-7 双校验）

| 闸门 | 时机 | 判据（同一口径） | 失败 |
| --- | --- | --- | --- |
| 开局 | `create_run` 生成计划后、`insert_run` **之前** | `validate_questions(plan)`：总 ≥8、technical ≥5、project ≥3、challenge ≤ `max_challenge_count(total)`、题干去重 | 502 + retryable，**不落库**（不是 500、不静默补题） |
| 结束 | 最后一轮 `current_id→null` 之前 | `validate_session(entries)` 读同一批 kind/prompt | 502 + retryable，**不落库**（该轮分数也不写，用户可重试） |

由 §3.1 的 `is_follow_up_allowed`（非 challenge 父题 + 配额）保证「开局过 ⇒ 结束过」；结束闸门是**防御性断言**（可被构造 payload 单测命中）。允许整份计划重新生成（重试即重开），**禁止插入/替换单题凑配额**。

### 3.7 幂等与零副作用（AC-10）

- **零副作用**：AI 调用、闸门校验全部在 `save_run` 之前；任何 `AppError` 抛出时 payload 未变、`answered_count` 未变、无新发言。
- **不重复计分**：同一 `question_id` 重复提交 → 覆盖 `score/comment/answered_at`，`answered_count` 由「有分数的条数」重算，天然不累加。
- **不重复出题**：只有 `is_current` 才追加；重试旧题绝不追加。
- **时间线幂等**：`record_run_event` 的 `(type, ref_id)` UNIQUE 语义既有（`repository.insert_timeline_event` 返回 bool），重试不会写两条。

---

## 4. 前端实现

### 4.1 `/interview` 七态状态机（DESIGN §2.1）

```text
gate（画像加载中） ─┬─ 无画像 → empty（EmptyState + 上传入口）
                    ├─ 失败   → error（InlineError + 重试）
                    └─ 成功   → configure（配置卡，AC-1/AC-3）
configure ──开始/跳过──▶ creating（PhaseLoader 三段，可取消）
creating ──成功──▶ chat（摘要条 + 气泡流 + 粘性输入区，AC-4/AC-5/AC-6）
         └─失败──▶ configure（InlineError，四项原样保留，AC-13）
chat ──next_question=null──▶ ended（只读 + 汇总，AC-9）
?run_id= ──GET 会话──▶ status=running ? chat-续答 : ended(只读)
```

页面级状态（**单一 session state，不用全局 store**；`state/flow.ts` 本轮不改）：

```ts
const [session, setSession] = useState<InterviewSession | null>(null)   // 会话唯一真相（镜像后端）
const [draft, setDraft] = useState<SetupDraft>(...)                     // 配置表单
const [stage, setStage] = useState<'configure'|'creating'|'chat'|'ended'>('configure')
const [track, setTrack] = useState<RunTrack>({ submitting:false, elapsedS:0, error:null, turnError:null })
```

### 4.2 组件与文件（DESIGN §1.2；props / 纯函数为下游契约）

| 文件 | 变更 | 导出的公共面（逐字） |
| --- | --- | --- |
| `pages/InterviewPage.tsx` | 重写 | `export default function InterviewPage()`；内部 `startSession(patch?: InterviewSettingsPatch)`、`submitTurn()`、`restart()`、`answeredId` 派生 |
| `components/interview/InterviewSetupForm.tsx` | 新增 | `interface SetupDraft {target_role,years_experience,market,company_size}`；`bandOfYears(years: number \| null): ExperienceBand`；`prefillOf(profile: Profile \| null): {draft: SetupDraft; sources: Record<keyof SetupDraft,'profile'\|'default'>}`；`draftToPatch(draft: SetupDraft): InterviewSettingsPatch`；`previewLine(draft: SetupDraft): string`；`InterviewSetupForm(props:{draft; sources; submitting; error; onDraft(next: SetupDraft): void; onStart(): void; onSkip(): void})` |
| `components/interview/SettingsBar.tsx` | 新增 | `settingsLine(settings: InterviewSettings \| null): string`（null → `未记录设定`）；`SettingsBar(props:{settings; label?: string})`（48 高只读条，会话顶 / 报告顶共用） |
| `components/interview/ChatStream.tsx` | 新增 | `questionNoOf(id: string): number`（`iq-12`→12，非法→0）；`interface Bubble { role:'interviewer'\|'candidate'; id: string; question?: InterviewSessionQuestion; answer?: string \| null; score?: number \| null; comment?: string \| null }`；`bubblesOf(questions: InterviewSessionQuestion[]): Bubble[]`；`ChatStream(props:{questions; pending; notice?; onQuestionFocus?(id:string):void})` |
| `components/interview/ChatBubble.tsx` | 新增 | `ChatBubble(props:{bubble: Bubble; parentNo?: number})`（身份行 / 题号 chip / 「↳ 追问自 Q{n}」/ 提示行） |
| `components/interview/AnswerScore.tsx` | 新增 | `scoreTier(score: number): 'good' \| 'mid' \| 'low'`（>7 / ≥4 / 其余，复用 `scoreRingState` 映射，禁第二套阈值）；`AnswerScore(props:{score; comment})`（徽章 + 档位词 + **逐字**点评） |
| `components/interview/Composer.tsx` | 新增 | `Composer(props:{value; onChange(v:string): void; onSubmit(): void; submitting; disabled; readonly; elapsedS: number; error: string \| null})`（粘性 156，Ctrl/Cmd+Enter 提交） |
| `components/interview/SessionSummary.tsx` | 新增 | `averageOf(values: number[]): number`；`kindAverageOf(questions: InterviewSessionQuestion[], kind: QuestionKind): number`；`SessionSummary(props:{questions; settings; onRestart(): void})`（56 环均分 + 双 CTA） |
| `components/interview/ScoreBadge.tsx` | 保留 | `scoreRingState(score): RingState`（复用，不改阈值） |
| `components/interview/QuestionCard.tsx` | **删除** | 已被 `ChatBubble` 取代（已核实唯一引用为 `InterviewPage.tsx`） |
| `components/history/TrendTable.tsx` | 修订 | `settingsTextOf(row: RunSummary): string \| null`（面试行：`岗位 · 经验 · 市场 · 规模`；无设定→`未记录设定`；笔试卷→null 不渲染）；`TrendTable(props:{rows})` 行内追加 12/16 设定行 |
| `components/history/TimelineEvent.tsx` | 修订 | `TimelineEvent(props:{event; latest?: boolean; settingsText?: string \| null})`（面试卡第三行；`.is-interview` → `min-height: var(--tl-row-h-lg)`） |
| `components/history/TimelineSection.tsx` | 修订 | `TimelineSection(props:{runRows: RunSummary[] \| null})`：用 `event.ref_id` ↔ `runRows.id` 关联出 `settingsText`（**零新契约字段**） |
| `pages/ReportPage.tsx` | 修订 | 报告头下方 `SettingsBar`，`report.interview_settings` 为 `null` → 整行不渲染 |
| `styles/tokens.css` | 追加 | DESIGN §0.2 的 7 个 token（既有值一个不改） |
| `styles/base.css` | 追加 | `.sc-iq-*`、`.sc-settings-bar`、`.sc-tl-row.is-interview`、`.sc-td-settings`（**只用 token，注释里不写色值字面量**） |

### 4.3 数据流（一次轮次的原子更新）

```ts
// 提交：只用 session.current_id 对应的问题；失败保留输入
const turn = await api.scoreAnswer(session.run_id, { question_id: session.current_id, answer: text })
setSession(prev => ({
  ...prev, answered_count: turn.answered_count, interview_avg: turn.interview_avg,
  status: turn.run_status,
  questions: [
    ...prev.questions.map(q => q.id === answeredId
      ? { ...q, answer: text, score: turn.score, comment: turn.comment } : q),
    ...(turn.next_question ? [{ ...turn.next_question, answer: null, score: null, comment: null }] : []),
  ],
  current_id: turn.next_question ? turn.next_question.id : null,
}))
```

- `comment` 直接取服务端返回值 → **零 trim / 零截断 / 零重写**（AC-5）；`AnswerScore` 也不加 `-webkit-line-clamp` 与省略号。
- `creating` 的取消 = `AbortController.abort()`（沿用既有 `createAbortRef` 口径，`API` client 已把 `AbortError` 映射为 `ABORTED`）。

### 4.4 滚动锚点、粘性与窄屏（AC-18）

- 单一滚动层：页面滚动；输入区 `position: sticky; bottom: 0`（`--iq-composer-h` 156），页面底部留白 `--iq-scroll-pad` 172 保证最后一条气泡能完整滚出粘性区。
- 新气泡进入视口：追加后滚到该泡（`scroll-margin-top: var(--topbar-h)`），评分与被答气泡**同屏**；
- 窄屏（≤720）：配置卡与控制列全宽、四字段纵向不截断、5 档 chip 允许换行（DESIGN §0.5-9/10）；`390px` 无横向滚动（`document.scrollWidth ≤ 视口宽`）。
- 键盘：`Tab` 可达、`Ctrl/Cmd+Enter` 提交、全局 `:focus-visible` 焦点环沿用。

### 4.5 配置态（AC-1 / AC-3）

- 预填：`prefillOf(profile)` 产出的 `sources` 驱动「来自画像 / 默认」徽章；用户手改该字段 → 该字段徽章消失。
- 「跳过，用画像默认」= **不传 `settings`（`undefined`）**，由服务端补全（不是把表单清空）；按钮旁 `previewLine` 预览将采用的四项。
- 四项全空也可开始（主按钮永不因空值禁用）；无「保存到画像」类控件；底部 13/20 一句「本场设定只作用于这一次面试，不会写回你的画像」（AC-3 的可见承诺）。
- 开局失败：`InlineError` + 四项值与已选 chip 原样保留。

---

## 5. 关键实现点与边界（逐条可测）

| # | 场景 | 期望行为 | AC |
| --- | --- | --- | --- |
| 1 | 开局响应 | 只有 1 条发言 + `total`；`questions` 数组**不存在**于响应 | AC-4 |
| 2 | 首屏气泡 | 1 条面试官泡（+ 可选占位泡），无 Q1–Q8 徽章条（r1 的进度条删除） | AC-4 |
| 3 | 4 项配置全空 | 服务端补全：画像岗位/映射经验/国内/中型，开局成功 | AC-1 |
| 4 | 临时岗位 ≠ 画像岗位 | `payload.settings.target_role` = 新值；`GET /api/profiles/latest` 逐字不变 | AC-3 |
| 5 | 每轮提示词 | 首轮与每轮 `user` JSON 都含 4 项 settings | AC-2③ |
| 6 | 纯映射逐档 | `calibration_of` 每档非空、档间集合互不相同（4 组单测逐档断言） | AC-2④ |
| 7 | 第 3 轮上下文 | `history` 含第 1、2 轮 `answer` 原文；更早轮只带题面摘要 | AC-6 |
| 8 | 追问 | 新 `iq-N` 单调、`parent_id`=父题、`kind`=父题 kind、独立评分 | AC-6/AC-8 |
| 9 | 计划不合格 | 502 中文 + `retryable=true`；`runs` 表无新增行 | AC-7 |
| 10 | 结束前结构校验 | 不达标不得 `completed`（502，无写入）；非 challenge 追问策略保证正常路径恒过 | AC-7 |
| 11 | 刷新 / 重进 | `GET /api/interviews/{run_id}` 还原气泡、答案、分数；不重出题、不重计分 | AC-9 |
| 12 | 已完成 run | `current_id=null`、输入区禁用 + 中文只读文案；再提交 → 400 中文 | AC-9 |
| 13 | 单轮超时 | 503 中文 + envelope；`answered_count` 不变、无新发言；输入框内容保留可重试 | AC-10 |
| 14 | 同一题重试成功 | `score/comment` 覆盖、`answered_count` 不 +2、发言不重复 | AC-10 |
| 15 | 重答非当前旧题 | 只覆盖分数，不追加发言、不推进 `turn` | AC-9/AC-10 |
| 16 | 无 AI Key | 开局 503 中文（提示配置 `backend/.env`）；页面 `InlineError` 不白屏 | AC-13 |
| 17 | 旧 run（无 settings） | `GET` 不报错、`settings=null`；历史行显示「未记录设定」，无 `undefined` | AC-14/AC-11 |
| 18 | 报告设定 | `Report.interview_settings` 取最新合法面试设定；无面试 run → `null` 且整行不渲染 | AC-12 |
| 19 | 追问降级 | `follow_up` 题面空/重复/未被允许 → 静默改投计划下一题（整轮仍成功） | AC-6/AC-7 |
| 20 | 报告证据反查 | `Shortfall.evidence = "Q{n} · {score}/10"`、`question_ref = iq-n`；气泡 `Q{n}` 由 `questionNoOf('iq-n')` 同源 → 命中率 100% | AC-8 |

---

## 6. 测试策略

### 6.1 后端（`pytest`，零网络：`FakeAI` / `patch_ai` / `tmp_db`）

**新增 `backend/tests/test_interview_chat.py`**（用例按 AC 命名）：

| 用例 | 断言要点 | AC |
| --- | --- | --- |
| `test_create_returns_single_question_and_settings` | 响应只有 `question` 一条 + `settings` 四键；payload `settings` 与响应逐字段相等；`len(questions)==1` | AC-2②/AC-4 |
| `test_create_fills_defaults_when_settings_omitted` | 全空 → 通用软件工程师/映射档/国内/中型 | AC-1 |
| `test_create_does_not_write_back_profile` | 开场后 `repository.latest_profile().target_role` 逐字不变 | AC-3 |
| `test_every_round_prompt_carries_settings` | 捕获 `fake.calls`：开局 user 与第 2/3 轮 user 均含 4 值 | AC-2③ |
| `test_calibration_bands_are_distinct` | 5 档经验 / 4 市场 / 3 规模：每档非空且集合互不相同 | AC-2④ |
| `test_round_prompt_contains_recent_answers` | 第 3 轮 user 含第 1、2 轮 `answer` 原文 | AC-6 |
| `test_follow_up_inherits_kind_and_parent` | `next_question.parent_id=="iq-1"`、kind 相同、id 单调 | AC-6/AC-8 |
| `test_follow_up_gated_by_quota_and_kind` | 配额用尽 / 父题 challenge → 走计划下一题 | AC-7 |
| `test_bad_plan_502_and_no_run_inserted` | 502 retryable + `repository.list_runs("interview")` 无新增 | AC-7 |
| `test_session_structure_guard_blocks_completion` | 构造 5 条 challenge 的 payload → 最后一轮 502 且 status 非 completed、payload 未被改写 | AC-7 |
| `test_load_session_restores_all` | 气泡数 / 答案 / 分数逐项相等；`current_id` 正确；无新 AI 调用 | AC-9 |
| `test_completed_session_is_readonly` | `current_id=null`；提交 → 400 中文 | AC-9 |
| `test_ai_timeout_leaves_no_trace` | `patch_ai` 抛 503 → payload/answered_count 不变 | AC-10 |
| `test_retry_same_question_is_idempotent` | 两次提交同 id：分数覆盖、`len(questions)` 不变 | AC-10 |
| `test_legacy_payload_reads_with_null_settings` | 手写 r1 形状 payload → `settings=null`、不抛错 | AC-14 |
| `test_report_carries_interview_settings` | `build_report(run_ids=[…])` → `interview_settings` 4 键；无面试 run → `None` | AC-12 |

**更新 `backend/tests/test_interview_service.py`**（契约破坏面）：
- `test_create_run_returns_questions_without_answers` → 改为断言 `run.question.id == "iq-1"` 且 `payload.questions` 只 1 条、`plan` ≥8；
- `test_score_answer_persists_then_completes_run` → 改为按轮推进：连续提交直到 `run_status=="completed"`，断言 `next_question` 链、`answered_count`、timeline 事件 1 条；
- `test_reanswer_same_question_is_idempotent` → 断言不追加发言；
- `test_score_out_of_range_rejected_by_schema`（`ScoreResult` 越界）**保持不变**（继承关系保住了它）。

**`backend/tests/test_engineering_gates.py` 不改**：其中 `test_interview_passes_timeout_without_reflection` 断言源码含字面量 `timeout_s=SCORING_TIMEOUT_S`、且不得出现 `inspect.signature` → §3.4 第 5 步已按该形态写。

### 6.2 前端（`vitest`，`environment: 'node'`、`include: ['src/**/*.test.ts']` → **只能纯函数测试，no new deps**）

- **`frontend/src/test/interviewSettings.test.ts`**：`bandOfYears` 五档边界（`null`、`0.5`、`1`、`2.9`、`3`、`4.9`、`5`、`9.9`、`10`、`12`）；`prefillOf` 画像有值 / 画像空 / 无画像三态的 `draft` 与 `sources`；`draftToPatch` 空白串 → 缺省键；`previewLine` 逐字中文；**闭集字面量与后端一致**（三组枚举逐字比对，防漂移）。
- **`frontend/src/test/interviewChat.test.ts`**：`questionNoOf`（`iq-1`→1、`iq-12`→12、`abc`→0）；`bubblesOf` 顺序与条数（n 题 → 2n−1/2n 条，面试官泡数 = 已提出题数）；`scoreTier` 边界（`3.9`→low、`4`→mid、`7`→mid、`7.1`→good）；`averageOf` / `kindAverageOf` 空集与四舍五入；`settingsTextOf` 三态（有设定 / 面试无设定 → `未记录设定` / 笔试 → `null`）；**点评逐字**（含首尾空格与换行的输入 → 输出字符串完全相等，证明零 trim/截断）。
- 既有 `exportName.test.ts` / `format.test.ts` 不动（`npm test` 只增不减，≥23）。

### 6.3 门禁与证据（AC-15 / AC-16）

| 门禁 | 基线 | 本轮要求 |
| --- | --- | --- |
| `python -m pytest -q -p no:cacheprovider` | 118 passed | ≥118 且全绿（实际因新增用例上升） |
| `npm run typecheck` | 0 error | 0 error |
| `npm run lint` | 0 error / 28 warning | 0 error，warning 不新增（≤28） |
| `npm test` | 23 passed | ≥23 且全绿 |
| `npm run build` | 通过 | 通过 |
| 无裸色值（`test_no_raw_colors_outside_tokens`） | 绿 | 新增 CSS 与其**注释**里零 `rgba`/`#hex` 字面量 |
| 无 Key 泄漏 | `grep -riE "sk-\|api_key\|AI_API_KEY"` → `NO_KEY_LEAK` | 同上 |
| r2 复制 Markdown 检查器 | 按其既有断言集 | 全 PASS（`AnswerScore` 不引入复制路径，`lib` 未改） |
| `/health` | 200 | 200 |

---

## 7. 任务拆分（并行边界 = 文件互斥；未派发任务表，本表为权威）

> **全局工程约束（逐字带入每个任务）**：分支 `feat/dev-skill-coach` **原地继续、不新开分支**；**Agent 不提交**（由流水线验收后统一提交）；当前未提交改动仅本任务夹（不清理、不 stash、不移动）；不得顺手改动白名单外文件；新增 CSS 注释里不写色值字面量；契约字段变更必须两侧同批。

| 任务 | 文件（ownership） | 读 | 依赖 | 交付与验收 |
| --- | --- | --- | --- | --- |
| **T1 契约底座（串行，最先）** | `backend/app/schemas.py`、`frontend/src/api/types.ts`、`frontend/src/api/client.ts` | `backend/app/repository.py`、`PRD.md §2` | — | §2.6 对照表逐行落地；`InterviewRun` 破坏性重写两侧同批；`client.ts` 增 `getInterview`、`scoreAnswer` 返回 `InterviewTurn`；`python -c "import app.schemas"` 与 `npm run typecheck` 通过（页面此时可暂时报错，由 T4 修） |
| **T2 后端会话引擎** | `backend/app/services/interview.py`、`backend/app/services/rules.py`、`backend/app/routers/interview.py` | `schemas.py`、`services/ai.py`、`services/timeline.py`、`repository.py` | T1 | §3.1–§3.6 全部实现（`fill_settings`/`calibration_of`/`validate_session`/`create_run`/`score_answer`/`load_session` + 三条路由）；保留 `timeout_s=SCORING_TIMEOUT_S` 字面量；`pytest backend/tests/test_interview_service.py` 单点跑通（该文件由 T7 全量更新，T2 只需保证服务层自洽） |
| **T3 回溯投影** | `backend/app/services/history.py`、`backend/app/services/diagnosis.py` | `schemas.py`、`repository.py` | T1 | `RunSummary.interview_settings` / `Report.interview_settings` 投影 + 旧 run → `None`；`interview_settings_of(runs)` 纯函数；跑 `tests/test_report_service.py`、`tests/test_timeline.py` 不回归 |
| **T4 前端配置态与页面骨架** | `frontend/src/pages/InterviewPage.tsx`、`components/interview/InterviewSetupForm.tsx`、`components/interview/SettingsBar.tsx` | `api/types.ts`、`api/client.ts`、`lib/useAsync.ts`、`lib/format.ts`、`DESIGN.md §2.1–2.3` | T1 | 7 态状态机 + `?run_id=` 恢复 + 轮次提交编排 + 配置卡（预填/来源徽章/跳过/预览/字数计数）；**严格按 §4.2 导出签名**（T5 组件未落地前允许 typecheck 暂红） |
| **T5 前端对话流组件** | `components/interview/ChatStream.tsx`、`ChatBubble.tsx`、`AnswerScore.tsx`、`Composer.tsx`、`SessionSummary.tsx`、**删除** `components/interview/QuestionCard.tsx` | `api/types.ts`、`components/interview/ScoreBadge.tsx`（`scoreRingState`）、`ui/RingProgress.tsx`、`DESIGN.md §2.3–2.4/§0.3` | T1 | §4.2 导出的纯函数与组件；点评逐字渲染（无 clamp/trim）；粘性输入区与只读态；Ctrl/Cmd+Enter 提交 |
| **T6 样式与回溯展示** | `frontend/src/styles/tokens.css`、`frontend/src/styles/base.css`、`frontend/src/pages/ReportPage.tsx`、`components/history/TrendTable.tsx`、`TimelineSection.tsx`、`TimelineEvent.tsx` | `DESIGN.md §0.2/§0.3/§0.5/§2.5–2.6`、`tokens.css` 既有变量、`api/types.ts` | T1（`SettingsBar` 由 T4 提供，T6 只读其签名） | 7 个 token 追加（既有值不动）；`.sc-iq-*` / `.sc-tl-row.is-interview` 只引用 token；历史行设定文本（`未记录设定` 兜底）+ 时间线第三行（`ref_id ↔ runRows.id` 关联，零新契约）；报告顶 `SettingsBar`，`null` 不渲染 |
| **T7 测试与门禁用例** | `backend/tests/test_interview_chat.py`（新）、`backend/tests/test_interview_service.py`（改）、`frontend/src/test/interviewSettings.test.ts`（新）、`frontend/src/test/interviewChat.test.ts`（新） | 全部上部产物 | T2、T3、T5 | §6.1/§6.2 用例清单逐条落地；`pytest` ≥118 全绿；`npm test` ≥23 全绿 |
| **T8 收尾自检（不写 QA 报告）** | `docs/teamflow/architecture/ARCHITECTURE.md`（§3.2 路由表 + §1.2 payload 说明） | 所有改动 diff | T1–T7 | 全量门禁复跑并记录结论：`pytest` / `typecheck` / `lint` / `npm test` / `build` / `/health` / 无 Key 泄漏 / `git status --porcelain=v1 -uall` 改动面核查；`grep` 死代码（`QuestionCard` / 旧 `questions` 字段）已清；**只修不自检报告**：发现即改，不外写 `QA-REPORT.md` / `ACCEPTANCE.md` |

**并行波次**：`T1` →（`T2` ∥ `T3` ∥ `T4` ∥ `T5` ∥ `T6`）→ `T7` → `T8`。T2/T3 与 T4/T5/T6 文件全互斥；T4 与 T5 依赖 T1 的类型而非对方的实现（签名已在本文 §4.2 冻结）。

---

## 8. 改动面与白名单说明（AC-16）

**落在 PRD §9.1 白名单内**：`schemas.py`、`routers/interview.py`、`services/interview.py`、`services/rules.py`、`services/history.py`、`services/diagnosis.py`、`types.ts`、`client.ts`、`InterviewPage.tsx`、`components/interview/*`、`styles/base.css`、`backend/tests/*`、`frontend/src/test/*`。

**白名单外但必需（附理由）**：

1. `frontend/src/styles/tokens.css` —— DESIGN §0.2 明确「追加 7 个 token」，且 `base.css` 禁止裸尺寸；不追加 token 只能写裸值，反而违反 AGENTS §4。
2. `frontend/src/components/history/TrendTable.tsx` / `TimelineSection.tsx` / `TimelineEvent.tsx` —— AC-11 要「历史页每条面试记录显示本场设定」，而 `/history` 的记录列表就是 `TrendTable`（`RunSummary`）与 `TimelineSection`（DESIGN §2.5 指定时间线卡第三行）。**零新契约字段**：`TimelineSection` 用既有 `event.ref_id` ↔ `runRows.id` 关联出文本。
3. `frontend/src/pages/ReportPage.tsx` —— AC-12 要求报告页顶部显示设定（白名单已含，仅重申）。

**明确不动**：`repository.py`（唯一 SQL 出口，零改动）、`db.py`/`init_db()`、`services/ai.py`、`services/timeline.py`、`services/markdown.py`、`services/exam.py`、`services/courses.py`、`ExamPage.tsx`、`PolishPage.tsx`、`ProfilePage.tsx`、`UploadPage.tsx`、`state/flow.ts`、`main.py`、依赖清单（`package.json` / `pyproject`）。

**与 DESIGN 的一处落地取舍（记录，不改 DESIGN 文件）**：DESIGN §1.2 把「历史页设定行」挂 `TimelineEvent.tsx`；AC-11 的字段落在 `RunSummary`，而时间线事件不带设定。落地时**两个面都呈现**：`TrendTable` 行内设定文本（直接来自 `RunSummary.interview_settings`）+ 时间线卡第三行（前端 join，零新字段）。`--tl-row-h-lg` 88→112 按 DESIGN §0.5-8 使用。

---

## 9. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 单轮 15s 预算 vs「评分 + 下一条发言」同轮产出 | 一次调用、`timeout_s=14`；正题取计划原文（模型只写评分 + 追问题面）；历史窗口 3 条全文 + 更早只给题面摘要（控制 token）；超时按 AC-10 整轮失败可重试 |
| 计划质量不稳（配比不合规） | 502 + 可重试，允许整份重新生成；**禁止插入/替换单题** |
| 追问推高 challenge 占比 | `is_follow_up_allowed` 一律不给 challenge 父题追问；结束闸门防御性二次校验 |
| `InterviewRun` 破坏性重写 | 两侧同批（T1 单任务完成），旧前端不存在（同仓同发布）；旧 **payload** 只读兼容已在 §1.2 定义 |
| 无真实 AI Key | 自动化证据 = fake client 捕获提示词 + `calibration_of` 纯函数单测；真实差异由 QA 人工冒烟（PRD §10 F1） |
| 无新依赖 / 纯手写 CSS | 几何与状态全部落到 DESIGN §0，T6 只引用 token；`vitest` 环境为 `node` → 测试只写纯函数，不引 `@testing-library` |
| `ruff` 在本环境不可用 | 见 §10：不阻塞，lint 面以 `pytest` 的 `test_engineering_gates` + 人工 review 覆盖；在交付说明里登记为环境限制，不算实现缺口 |

---

## 10. 验证命令（交付即跑）

```bash
# 后端
cd backend && python -m pytest -q -p no:cacheprovider
cd backend && python -m pytest -q -p no:cacheprovider tests/test_interview_chat.py tests/test_interview_service.py
cd backend && python -m uvicorn app.main:app --port 8000   # 另开：curl -sS http://127.0.0.1:8000/health
# 前端
cd frontend && npm run typecheck
cd frontend && npm run lint
cd frontend && npm test
cd frontend && npm run build
# 无 Key 泄漏 / 无裸色值 / 改动面
cd frontend && grep -riE "sk-|api_key|AI_API_KEY" dist/ src/ || echo NO_KEY_LEAK
git status --porcelain=v1 -uall
```

**环境限制（如实登记，不重试）**：`cd backend && python -m ruff check app tests` → 本机 `python -m ruff` 报 `No module named ruff`（Python 3.13 环境未装 ruff）。因此 lint 面以「`pytest` 内的 `test_engineering_gates.py`（裸 SQL / 裸色值 / 超时字面量）+ `tsc` + `eslint`（前端） + 人工 review」代替；**不在沙箱里反复重试该命令**。
