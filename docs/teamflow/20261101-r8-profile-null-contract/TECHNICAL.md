# r8 技术方案 · 画像空值契约口径修正

> 基线依赖：`20261031-r1-dev-skill-coach`、`20261031-r3-memory-resume-polish`、`20261101-r5-interview-chat-config`
> 分支：`feat/dev-skill-coach` **原地继续**；**Agent 不提交**（由人工按 §9.4 清单提交）
> 零新增依赖、零 DDL、零新路由、零新 AC 之外的交互

## 0. 结论（一句话）

缺陷是**同一份数据的三处口径不一致**：`PROFILE_SYSTEM` 允许「无信息给 null」（提示词层）→ `ProfileProject.role/period` 要求 `str`（pydantic 契约层）→ `types.ts` 要求 `string`（前端镜像层），修法是**把三层统一到「可空」并由下游显式承载 null**，而不是让模型填空字符串。本方案只改 4 个后端文件、3 个前端文件、2 个测试文件（+1 门禁用例追加），全部落在既有模块边界内。

**null 的语义定死**（贯穿全案）：`null` = 简历里没有这条信息（未知）；`""` = 用户显式清空（编辑态才会出现，落库前归一为 `null`）；字段缺失 = 存量 payload（读回时同样归一为 `null`）。三者**都不得**在界面上呈现为 `null` / `undefined` / 悬空 `·`。

## 1. 变更面白名单（AC-18 口径，超出即打回）

| # | 文件 | 动作 | 关键点 |
|---|---|---|---|
| M1 | `backend/app/schemas.py` | 改 | `ProfileProject.role/period` 可空；`bullets` 与 `ProfileDraft` 三个数组 `null/缺失 → []` |
| M2 | `backend/app/services/resume_polish.py` | 改 | `_allowed_numbers` 对 `period=None` 空值防护（1 行） |
| M3 | `backend/app/services/interview.py` | 改 | `_profile_brief` 项目条目省略 None 键（不改提示词措辞） |
| M4 | `backend/app/services/profile_merge.py` | 改 | `_entry_payload` 空值不覆盖已知值 |
| M5 | `backend/tests/test_profile_null_contract.py` | 新增 | AC-1/2/4/6/7/8/11 的 18 条用例 + 真实模型形状 fixture |
| M6 | `backend/tests/test_engineering_gates.py` | 追加 1 条 | `test_r8_profile_nullable_mirror`（静态钉住三层口径 + 提示词互锁） |
| M7 | `frontend/src/api/types.ts` | 改 | `ProfileProject.role/period: string \| null` |
| M8 | `frontend/src/lib/profileText.ts` | 新增 | 纯函数 `textOrEmpty` / `joinMeta`（node 环境可测，沿用 r7 `lib/coach.ts` 先例） |
| M9 | `frontend/src/pages/ProfilePage.tsx` | 改 | 3 处空值点改调用 M8（行 143 / 271-272 / 311-312） |
| M10 | `frontend/src/test/profileText.test.ts` | 新增 | 8 条纯函数用例 |

**明确不改**：`components/profile/ProfileDimension.tsx`（`entry.meta ? … : null` 已能吞掉空串，无需改）、`styles/tokens.css`、`base.css`（AC-5 无新样式）、`PROFILE_SYSTEM` 任意字符、`ProfilePatch` 结构、`repository.py`、`db.py`、`ai.py`（重试/超时不变）、其余 5 个 AI 入口。

## 2. 数据模型与存储

### 2.1 契约 diff（M1）

```python
class ProfileProject(BaseModel):
    name: str                                       # 不变：仍必填（反幻觉锚点）
    role: str | None = None                         # ← 改：提示词允许 null
    period: str | None = None                       # ← 改：同上
    bullets: list[str] = Field(default_factory=list)  # ← 改：缺省 []
    source_quote: str = Field(min_length=1)          # 不变：仍必填非空（闸门）
    source_quotes: list[Evidence] = Field(default_factory=list)
    status: SkillStatus = "active"

    @field_validator("bullets", mode="before")
    @classmethod
    def _null_bullets(cls, value: Any) -> Any:
        """模型对「无要点」既可能给 []、也可能给 null；两者都归一为 []。"""
        return [] if value is None else value
```

```python
_LIST_FIELDS = ("skills", "tech_stack", "projects")

class ProfileDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")
    skills: list[ProfileSkill]
    tech_stack: list[str]
    years_experience: float | None = None
    projects: list[ProfileProject]
    target_role: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_null_lists(cls, data: Any) -> Any:
        """提示词第 3 条允许整个维度给 null；键缺失与显式 null 一视同仁 → []。

        只动「列表形状的缺省」，不碰元素校验：name / source_quote 仍必填非空，
        因此「AI 编造内容」仍会在元素级 ValidationError 处被拦（AC-7）。
        """
        if not isinstance(data, dict):
            return data
        patch = {name: [] for name in _LIST_FIELDS if data.get(name) is None}
        return {**data, **patch} if patch else data
```

要点：`ProfileDraft` 被 `Profile` 继承、且被 `Profile.model_validate_json` 读回路径复用 ⇒ 一个 before-validator 同时覆盖「模型草稿」「响应落地」「存量读回」三条路（AC-1/AC-8 一件达成）。**不得**用 `extra="allow"` 或 try/except 包 `verify_quotes` 达成绿（AC-7 anti-goal 2）。

### 2.2 存储

`profiles.payload` 存 `Profile.model_dump_json()`（`repository.py:102-126`）。pydantic 对 `str | None = None` 序列化为 `"role": null`，读回 `model_validate_json` 得 `None` ⇒ **None 往返等值，不被转成 `""`/`"None"`**（AC-4③）。**无 DDL、无迁移**：SQLite 里保存的是整份 JSON 文本，字段放宽对旧行零影响（旧行 `"role": "前端主力"` 照读，缺键行由 `default=None` 补齐）。

### 2.3 合并语义（M4，AC-6）

```python
def _prefer_text(new: object, old: object) -> str | None:
    """空值不覆盖已知值：新草稿有内容取新，否则沿用旧；两侧皆空 ⇒ None（不写 ""）。"""
    if isinstance(new, str) and new.strip():
        return new
    if old is None or (isinstance(old, str) and not old.strip()):
        return None
    return str(old)
```

`_entry_payload` 内改为：

```python
source = draft_entry or base
payload.update({
    "role":   _prefer_text(getattr(source, "role", None), getattr(base, "role", None)),
    "period": _prefer_text(getattr(source, "period", None), getattr(base, "period", None)),
    "bullets": list(getattr(source, "bullets", None) or getattr(base, "bullets", None) or []),
})
```

`bullets` 与 role/period 同一条语义（新简历没写要点 ⇒ 不抹掉旧要点），理由是同一项 anti-information-loss（r3 `target_role` 先例）。既有 fixture 均带 bullets，`tests/test_profile_merge.py` 12 条用例**保持不变且必须全绿**；若出现冲突，只对 role/period 生效并在 QA 报告中注明，不得改动既有断言。

`profile_id` 不变、`updated_at` 刷新、证据链旧→新累积：均由 `merge_profile` 既有逻辑保证，本需求**不触碰**。

## 3. API 设计（无新增/无删除，只放宽既有响应字段）

| 方法 | 路径 | r8 后的行为变化 | 响应模型 |
|---|---|---|---|
| POST | `/api/resumes` | 无变化 | `ResumeMeta` |
| POST | `/api/resumes/{resume_id}/profile` | **`role/period: null` 时由 502 变 200**（核心）；仍保留反幻觉校验与 502/503 语义 | `ProfileWithMerge` |
| GET | `/api/profiles/latest` | 存量画像（`str` 或字段缺失）照常 200 | `Profile` |
| PATCH | `/api/profiles/{profile_id}` | 条目 `role/period` 传 `null` 合法 → 存 `null`；空串 `""` 由前端归一为 `null` 后再发 | `Profile` |
| POST | `/api/resumes/{resume_id}/polish` | `period=None` 不再 500 | `PolishResponse` |
| POST | `/api/interviews` | 开局输入 JSON 不含 `"role": null` / `"period": null` | `InterviewRun` |
| POST | `/api/interviews/{run_id}/answers` | 无变化（评分链路不含 role/period） | `InterviewTurn` |
| GET | `/health` | 无变化 | — |

`PATCH` 语义不变：`router.update_profile` 已按 `exclude_unset` + 丢弃顶层 `None`（「不改这一维」）处理，**顶层** null 仍表示不变；**条目内** `role: null` 是合法值（`ProfileProject` 层）。两条语义不同不得混淆，这也是 M1 只放宽 `ProfileProject` 而不动 `ProfilePatch` 的原因。

## 4. 后端实现要点

### 4.1 空值防护（M2 / M3）

```python
# resume_polish.py:187-189
for token in _NUMBER_RE.findall(project.period or "") + _NUMBER_RE.findall(" ".join(project.bullets)):
```

```python
# interview.py:293-306
def _profile_brief(profile: Profile) -> dict[str, Any]:
    projects = []
    for project in profile.projects:
        item: dict[str, Any] = {"name": project.name, "bullets": project.bullets}
        if project.role:            # None / "" 都不进提示词（不出现 "role": null）
            item["role"] = project.role
        if project.period:
            item["period"] = project.period
        projects.append(item)
    return {"target_role": …, "years_experience": …, "tech_stack": …, "skills": […], "projects": projects}
```

`_plan_input` 的 `json.dumps(..., ensure_ascii=False)` 不变；测试断言 `'"role": null' not in _plan_input(...)`（AC-4②）。

### 4.2 反幻觉闸门（不得改动）

`verify_quotes`（`profile.py:79`）、`MAX_QUOTE_CHARS=200` 截断、`skills/tech_stack/projects` 全空 → 502、`:memory:` 去重、无 Key 503、`AIClient` 重试策略：**一行不改**。`_normalize_null_lists` 只改列表形状，元素级 `min_length=1` 校验照旧 ⇒ 编造的技能/未命中原文仍 502。

## 5. 前端组件与页面划分

```
frontend/src/
├─ api/types.ts                     (M7)  ProfileProject.role/period: string | null
├─ lib/profileText.ts               (M8, 新增)  纯函数：空值归一与 meta 拼接
├─ pages/ProfilePage.tsx            (M9)  dimensionEntries(:143) / buildEntryPatch(:271) / entryEditorFields(:311)
├─ components/profile/ProfileDimension.tsx  不改（entry.meta 空串已被 `? :` 吞掉）
└─ test/profileText.test.ts         (M10, 新增)
```

```ts
// frontend/src/lib/profileText.ts
/** null / undefined → ''；有值去首尾空白。编辑框的 value 与拼接都走它（AC-5 归一函数）。 */
export function textOrEmpty(value: string | null | undefined): string

/** 项目卡 meta：「角色 · 时间」；整侧为空则只显示另一侧，两侧皆空返回 ''（不渲染 meta 行）。 */
export function joinMeta(parts: ReadonlyArray<string | null | undefined>): string
```

调用点替换（3 处，逐行）：

| 位置 | 现在 | 改为 |
|---|---|---|
| `ProfilePage.tsx:143` | `[item.role, item.period].filter((part) => part.trim() !== '').join(' · ')` | `joinMeta([item.role, item.period])` |
| `ProfilePage.tsx:271-272` | `role: (values.role ?? target.role).trim()` | `role: trimToNull(textOrEmpty(values.role ?? target.role))` |
| `ProfilePage.tsx:311-312` | `value: target.role` | `value: textOrEmpty(target.role)` |

`trimToNull`（`ProfilePage.tsx:192`）保留在页面内：编辑态「用户显式清空」⇒ `null`，与 §2.3 的合并语义、`target_role` 既有写法（`buildDimensionPatch`）一致。渲染层单点归一，**全页不出现 `null`/`undefined`/悬空 `·`**（`joinMeta` 尾部不留分隔符）。

## 6. 状态管理

无新 store、无新 context：画像数据仍由 `ProfilePage` 的 `useAsync` + `PATCH` 回填驱动；编辑草稿仍是 `Record<string, string>`（`values.role` 恒为 `string`，空串即「未填写」），出站前经 `trimToNull` 归一为 `null`。服务端为唯一真值（PATCH 响应整体替换本地 profile），故「刷新后仍可再次编辑」由 M5/M8 的纯函数保证，不引入乐观更新。

## 7. 关键实现点与边界

| 风险/边界 | 处理 |
|---|---|
| `null.trim()` TypeError 白屏（anti-goal 3） | 渲染与编辑取值全部经 `textOrEmpty`；`joinMeta` 内部对每侧做归一 |
| 空串伪装成已知（anti-goal 1） | 契约侧不设 `""` 默认值；仅「用户编辑清空」路径产生 `""`，且落库前 `trimToNull` 转 `null` |
| 模型给 `[]`、给 `null`、给缺键 | `_normalize_null_lists` / `_null_bullets` 三路归一为 `[]`，输出类型始终 `list` |
| 只修后端 | 前端 3 处同步修 + `types.ts` 镜像 + 单测，`typecheck` 强制约束（M7/M9 缺一即编译失败） |
| 存量 payload 缺键 | `default=None` + before-validator；`GET latest` / `PATCH` 均 200（AC-8） |
| `bullets=null` 落库后读回 | 存 JSON 里是 `[]`（校验后即归一），不是 `null` |
| 提示词被「顺手改口」 | `test_r8_profile_nullable_mirror` 断言 `PROFILE_SYSTEM` 仍含「无法判断填 null」 **且** 契约可空（两条互相牵制，AC-11） |
| 真实 Key 成本 | 最小必要 3 次调用（profile / interview / answer）+ 重试 ≤2；证据脚本逐次记录耗时与状态码 |
| 门禁基线（实测） | `pytest` **297 passed**（须以 `AI_API_KEY=` 运行：`backend/.env` 存在真实 Key 时 `tests/test_health.py::test_health_returns_ok` 会因 `ai_configured` 为 True 而失败，这是环境伪影、非回归）；`vitest` **100 passed** |

## 8. 测试策略

### 8.1 后端（M5，新增 18 条 ≥ +8 要求）

`backend/tests/test_profile_null_contract.py`，内含模块级 `REAL_MODEL_DRAFT`（真实模型形状 fixture：`"role": null, "period": null`）：

1. `test_role_null_draft_validates` —— `ProfileDraft.model_validate(REAL_MODEL_DRAFT)` 不抛（AC-1）
2. `test_role_null_profile_roundtrip` —— 加 `id/resume_id/updated_at` 后 `Profile` 通过，`projects[0].role is None`（AC-1）
3. `test_null_lists_normalized` —— 参数化 8 例：`skills` / `tech_stack` / `projects` × (`None`, 键缺失)，结果均为 `[]`（AC-2）
4. `test_null_bullets_normalized` —— `bullets: None` → `[]`（AC-2）
5. `test_gate_fields_stay_required` —— `name` / `source_quote` 置 None 仍 `ValidationError`（AC-7，闸门不放松）
6. `test_prompt_shape_matches_contract` —— `"若某个维度无信息，给空数组（或 null）"` 与 `"无法判断填 null"` 仍在 `PROFILE_SYSTEM`，且 `ProfileProject.model_fields["role"].annotation` 可接受 None（AC-11 互锁）
7. `test_legacy_payload_without_role_period` —— 无 `role/period` 键的旧 payload `Profile.model_validate` 通过（AC-8）
8. `test_legacy_payload_with_str_fields` —— `role` 为字符串的旧 payload 通过且值不变（AC-8）
9. `test_repository_none_roundtrip` —— 落库→读回 `None` 仍是 `None`，非 `""`（AC-4③，用 `tmp_db` fixture）
10. `test_allowed_numbers_tolerates_null_period` —— `_allowed_numbers` 不抛，且仍收 bullet 内数字（AC-4①）
11. `test_profile_brief_omits_none` —— `_plan_input` 序列化后不含 `'"role": null'` / `'"period": null'`（AC-4②）
12. `test_polish_route_with_null_period` —— 路由级 `POST /{id}/polish` 在 null 画像下 200（AC-4④，fake AI client）
13. `test_merge_keeps_known_role` —— 旧 `"前端主力"` + 新 `None` ⇒ 仍 `"前端主力"`（AC-6）
14. `test_merge_fills_from_new` —— 旧 `None` + 新有值 ⇒ 取新值（AC-6）
15. `test_merge_both_none` —— 两侧 None ⇒ `None`、不抛，`profile_id` 不变（AC-6）
16. `test_merge_bullets_not_lost` —— 新 `bullets=[]` 不抹掉旧要点（§2.3 语义钉住）
17. `test_verify_quotes_still_rejects_invented` —— 编造技能仍抛 `AI_SCHEMA_INVALID`（AC-7 回归位）
18. `test_no_schema_loosening_in_diff` —— `"extra=\"allow\""` 未出现在 `schemas.py`（AC-7 静态，落 M6 更合适 ⇒ 归入门禁测试）

`backend/tests/test_engineering_gates.py` 追加（M6）：

```python
def test_r8_profile_nullable_mirror() -> None:
    """门禁 46：role/period 三层口径（提示词 / schemas.py / types.ts）必须同向，改回 str 必红。"""
    schemas_py = (APP_DIR / "schemas.py").read_text(encoding="utf-8")
    types_ts = (FRONTEND / "src/api/types.ts").read_text(encoding="utf-8")
    profile_py = (SERVICES / "profile.py").read_text(encoding="utf-8")
    assert re.search(r"role:\s*str\s*\|\s*None\s*=\s*None", schemas_py)
    assert re.search(r"period:\s*str\s*\|\s*None\s*=\s*None", schemas_py)
    assert re.search(r"role:\s*string\s*\|\s*null", types_ts)
    assert re.search(r"period:\s*string\s*\|\s*null", types_ts)
    assert "_normalize_null_lists" in schemas_py
    assert 'extra="allow"' not in schemas_py
    assert "无法判断填 null" in profile_py   # 提示词仍允许 null，与契约互锁
```

### 8.2 前端（M10，新增 8 条 ≥ +4 要求）

`frontend/src/test/profileText.test.ts`（node 环境、只 import lib，沿用既有 7 个测试文件的写法）：

- `textOrEmpty(null) === ''`、`textOrEmpty(undefined) === ''`、`textOrEmpty('') === ''`、`textOrEmpty(' x ') === 'x'`
- `joinMeta([null, null]) === ''`、`joinMeta(['后端开发', null]) === '后端开发'`、`joinMeta([null, '2024-2026']) === '2024-2026'`、`joinMeta(['后端开发', '2024-2026']) === '后端开发 · 2024-2026'`、`joinMeta([' ', '']) === ''`（9 条）

### 8.3 门禁目标（AC-10）

| 项 | 基线（实测） | r8 目标 |
|---|---|---|
| `pytest` | 297 passed | ≥ 305（本方案新增 19） |
| `vitest` | 100 passed | ≥ 104（本方案新增 9） |
| `npm run typecheck` | 0 | 0 |
| `npm run lint` | 0 error | 0 error，≤ 28 warning |
| `npm run build` | 通过 | 通过 |
| `GET /health` | 200 | 200 |
| `NO_KEY_LEAK` | 无 | 无 |
| `ruff` | 环境缺（`No module named ruff`） | 如实记「未执行」，不假装通过 |

## 9. 任务拆分（文件所有权并行，3 波次）

### 波次 1（并行三路，文件互斥）

**T1 契约可空**（M1）`backend/app/schemas.py`
`ProfileProject.role/period` → `str | None = None`；`bullets` 缺省 `[]` + `_null_bullets`；`ProfileDraft._normalize_null_lists`。验收：`python -c "from app.schemas import ProfileDraft, Profile; ..."` 用真实形状 payload 通过；`python -m pytest -q tests/test_profile_service.py` 全绿。

**T2 下游空值防护**（M2/M3/M4）`resume_polish.py` + `interview.py` + `profile_merge.py`
三处按 §4.1 / §2.3 改（各 ≤8 行）。验收：`pytest -q tests/test_profile_merge.py tests/test_resume_polish.py tests/test_interview_service.py` 全绿。

**T3 前端契约与渲染**（M7/M8/M9）`types.ts` + `lib/profileText.ts` + `pages/ProfilePage.tsx`
按 §5 表替换 3 处。验收：`npm run typecheck` 0 error；`npm run lint` 不增。

### 波次 2（并行两路）

**T4 后端回归用例**（M5/M6）`tests/test_profile_null_contract.py`（新）+ `tests/test_engineering_gates.py`（追加）
按 §8.1 写 18 条 + 1 条门禁。验收：`AI_API_KEY= python -m pytest -q -p no:cacheprovider tests/test_profile_null_contract.py tests/test_engineering_gates.py -k "r8 or null"` 全绿；反向自检：临时把 `role` 改回 `str`，用例应变红后还原。

**T5 前端单测**（M10）`src/test/profileText.test.ts`
按 §8.2 写 9 条。验收：`npm test` ≥ 108 passed。

### 波次 3（串行）

**T6 真实 Key 证据**（`logs/teamflow/tf-mvxkiihc-y5p1qf/scripts/`）
- `check_r8_real_profile.py`：TXT 简历上传 → `POST /profile`，打印状态码、`skills/projects` 计数、逐条 `source_quote` 在 `documents.text` 的命中数、耗时（AC-3）；修复前对照证据由「把 `role` 临时改回 `str` 复跑一次」的 502 摘要 + pydantic `string_type` 两条错误构成（**只记录摘要，不入库**）。
- `check_r8_real_chain.py`：profile 200 → `POST /api/interviews`（题量 ≥8、技术 ≥5/项目 ≥3）→ `POST /api/interviews/{run_id}/answers`（分数 0–10、点评 ≤120 字），逐段记录耗时与错误码（AC-9）。
- `check_r8_contract_mutation.py`：复制 `backend/` + `frontend/src/api/types.ts` 到 `backend/tests/.tmp/r8mut/`，把 `role: str | None = None` 改回 `role: str`，在该副本跑 `pytest tests/test_engineering_gates.py -k r8_profile_nullable`，断言**退出码非 0**（AC-11 反向自检）；清理副本。
- 预算：真实调用 3 次 + 重试 ≤2；任何一步失败只记录事实，不伪造通过。

**T7 门禁与交付自检**（无文件所有权）
按 §10 逐条跑；修掉发现的问题；确认 `git status` 只出现 §1 白名单文件（+ 任务夹未跟踪目录）；确认 `.env` / `*.db` / `logs/` 未被跟踪。**不写 QA-REPORT.md / ACCEPTANCE.md**（属 QA 与验收阶段）。

### 9.4 Git 约束（必须随任务走）

分支 `feat/dev-skill-coach` **原地继续**，不新建分支；**Agent 不执行 `git commit` / `git push`**，改动留工作区待人工提交；提交信息建议 `fix: 画像 role/period 允许 null，修复真实模型下 profile 必 502（runId=tf-mvxkiihc-y5p1qf，任务夹 docs/teamflow/20261101-r8-profile-null-contract）`；**不得**提交 `backend/.env`、`*.db(-wal/-shm)`、`logs/teamflow/`、`backend/tests/.tmp/`、诊断脚本。

## 10. 验证命令（逐条可复跑）

```bash
cd backend && AI_API_KEY= python -m pytest -q -p no:cacheprovider            # ≥305 passed
cd backend && AI_API_KEY= python -m pytest -q -p no:cacheprovider tests/test_profile_null_contract.py
cd backend && AI_API_KEY= python -m pytest -q -p no:cacheprovider tests/test_engineering_gates.py -k r8
cd backend && python -m ruff check app tests                                   # 环境缺 ruff ⇒ 如实记未执行
cd frontend && npm run typecheck && npm run lint && npm test && npm run build   # vitest ≥108、typecheck 0
curl -sS http://127.0.0.1:8000/health                                          # 200
cd frontend && grep -riE "sk-|api_key|AI_API_KEY" src/ dist/ || echo NO_KEY_LEAK
cd backend && python -X utf8 ../logs/teamflow/tf-mvxkiihc-y5p1qf/scripts/check_r8_real_profile.py
cd backend && python -X utf8 ../logs/teamflow/tf-mvxkiihc-y5p1qf/scripts/check_r8_real_chain.py
cd backend && python -X utf8 ../logs/teamflow/tf-mvxkiihc-y5p1qf/scripts/check_r8_contract_mutation.py
git status --porcelain=v1 -uall && git branch --show-current
```

## 11. 风险与回滚

| 风险 | 概率/影响 | 处置 |
|---|---|---|
| 真实 Key 预算内仍 502（模型给别的形状，如 `years_experience: ""`） | 低 / 高 | 记录模型原始返回摘要到 QA 报告，按「不伪造通过」处理；如属另一形状缺陷，新开需求而非本轮扩张白名单 |
| `_prefer_text` 改动影响既有合并用例 | 中 / 中 | 既有 12 条必须全绿；冲突时按 §2.3 收窄到 role/period 并记录 |
| `bullets` 默认值使「模型完全没提要点」伪装成空列表 | 低 / 低 | 空画像（三维全空）仍 502；单项目无要点本就允许 |
| 前端旧 payload（缺 `role` 键）在 TS 侧被当 `undefined` | 中 / 低 | `null` 与 `undefined` 由 `textOrEmpty` 一并兜住；`types.ts` 保持 `role: string \| null` 与后端 `= None` 对齐，不做可选化的连锁改动 |
| 回滚 | — | 全部改动集中在 §1 白名单 10 个文件，`git checkout -- <files>` 即可整体回退；无数据迁移需回滚 |
