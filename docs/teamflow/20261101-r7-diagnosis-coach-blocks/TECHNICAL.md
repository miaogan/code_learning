<!-- meta: summary="r7 技术方案：诊断报告旁挂三块可复算区块（薄弱地图/简历要点/竞争力对标），全部纯函数产出、AI 只补一句文案、.md 单源、契约双侧可选字段、样式 append-only + r6 门禁升格为增量断言。" -->

基线依赖：20261101-r7-diagnosis-coach-blocks/PRD.md、DESIGN.md（本任务夹）；20261101-r6-exam-proficiency-filter（题目标签、门禁基线）；20261031-r3-memory-resume-polish（润色引擎、.md 单源）；20261101-r5-interview-chat-config（`payload.settings` 投影）。

# r7 技术方案 · 诊断报告三块补强

## 0. 一句话架构判断

三块内容全部是**「既有能力的第二次投影」**：薄弱地图投影 `diagnosis._scored` 的已计分题、简历要点投影 `resume_polish.build_suggestions` 的建议、竞争力对标投影画像 vs 静态能力模型。因此本轮**不新增数据表、不新增路由、不新增依赖**，只在 `build_report` 里加三个纯函数投影 + 一次并发 AI 补文案，产物进 `Report` 的可选字段并由 `to_markdown` 单源渲染。

## 1. 现状事实与改动边界

| 事实（已核对代码） | 位置 | 本轮用法 |
|---|---|---|
| `_scored(run)` 返回 `[(index, question, score)]`，简答题（`kind=text`）无分不产出 | `services/diagnosis.py:167` | 薄弱地图**唯一**题源，不重写判分 |
| 聚类桶名 `_bucket_name(kind, question)`：面试按题型、笔试按方向 | `diagnosis.py:84` | 地图的「方向级」名称直接复用，口径与主轴一致 |
| `format_score` / `SEVERITY_MEDIUM_BELOW=7.0` | `markdown.py:12` / `rules.py` | 证据串与「错题」阈值单一出处 |
| 润色入口 `build_suggestions(resume_text, profile, target_role, *, client)` + `validate_suggestions`（逐字命中，未命中整条丢弃） | `resume_polish.py:141/251` | 简历要点**唯一**产出路径 |
| `POST /api/reports/generate` → `build_report()` → `repository.insert_report(report)`；`Report` 以 JSON 全文存 `reports.payload` | `diagnosis.py:322`、`repository.py:194` | 旧 payload 反序列化靠 pydantic 默认值兜住 |
| 报告 `.md` 只经 `to_markdown`；前端导出/复制取 `GET /api/reports/{id}/markdown` 文本 | `markdown.py`、`routers/report.py`、`ReportPage.tsx` | 三块必须进 `to_markdown`，前端零拼串 |
| `routers/report.py` 只有 3 条路由 | 同上 | **不改路由**（白名单外文件，零改动） |
| 画像 `Profile{skills[{name,source_quote,source_quotes[]}], tech_stack[], projects[], years_experience, target_role, resume_id}` | `schemas.py:110` | 差距计算与简历正文取用 |
| 简历正文：`repository.get_document_text(profile.resume_id)` | `repository.py:88` | 要点产出的正文来源 |
| `/polish` **不读** query，建议列表由「开始分析」后 `session` 才产生 | `PolishPage.tsx` | 定位需跨「无 session → 有 session」两态 |
| `test_style_baseline_untouched` 断言 `styles/{tokens,base}.css` 不出现在 git status | `tests/test_engineering_gates.py:405` | **与 AC-16 冲突，本轮必须升格**（见 §8.2） |

**改动面白名单（本轮最终版，含两处显式修订）**
1. 新增 `backend/app/seed/role_models.json`、`backend/app/services/{weakness,role_fit,resume_hints,coach_copy}.py`。
2. 修改 `backend/app/services/{diagnosis,markdown}.py`、`backend/app/schemas.py`、`frontend/src/api/types.ts`。
3. 新增 `frontend/src/components/report/{CoachBlocks,WeaknessMap,ResumePointers,RoleFitCard}.tsx`、`frontend/src/lib/{coach,polishFocus}.ts`。
4. 修改 `frontend/src/pages/{ReportPage,PolishPage}.tsx`、`frontend/src/components/polish/SuggestionCard.tsx`（**修订 AC-18**：仅追加可选 `focused`/`onFocused` 两个 props）。
5. 修改 `frontend/src/styles/{tokens,base}.css`（**修订 AC-18**：**纯 append，零改既有声明**，由 §8.2 新门禁强制）。
6. 修改 `backend/tests/test_engineering_gates.py`（**修订 AC-18**：门禁只增与升格）。
7. 测试：`backend/tests/test_{weakness,role_fit,resume_hints,report_markdown,report_coach}.py`、`frontend/src/test/{coach,polishFocus}.test.ts`。
8. 不动：`repository.py`、`db.py`、全部 routers、`rules.py`、`exam_selector.py`、`markdown` 之外的服务。

> 三处修订必须在 dev 开始前认领（PRD AC-18 白名单与 AC-16/AC-15 互斥），否则 dev 阶段才发现门禁与白名单对撞。

## 2. 数据模型与存储

### 2.1 存储：零 DDL、零新表

`Report` 仍整体序列化进 `reports.payload`（既有行为），三块作为 `Report` 的可选字段随之落库。**不需要** `db.py`/`repository.py` 任何改动：`insert_report`/`_report_of` 已经 `model_dump_json` / `model_validate_json`，新增带默认值的可选字段对旧行天然兼容（AC-13 的主路径）。

### 2.2 `backend/app/seed/role_models.json`（新增，人工维护）

与 `courses.json` 同级、同风格（纯 JSON、无注释、UTF-8）：

```json
{
  "models": [
    {
      "role": "前端工程师",
      "direction": "前端",
      "level": "中级",
      "years_min": 2,
      "years_max": 5,
      "must_have": ["JavaScript", "CSS", "React"],
      "skills": [
        {"name": "JavaScript", "required": 2},
        {"name": "TypeScript", "required": 3},
        {"name": "React", "required": 3},
        {"name": "CSS 布局", "required": 2},
        {"name": "浏览器与网络", "required": 2},
        {"name": "构建与工程化", "required": 2},
        {"name": "性能优化", "required": 3}
      ]
    }
  ]
}
```

硬约束（AC-7 与门禁同时校验）：
- `direction ∈ rules.DIRECTIONS`（4 个方向全覆盖），每方向 **4 级**：初级(0–2) / 中级(2–5) / 高级(5–10) / 专家(10+)，同方向 `level` 唯一、`years_min` 递增。
- 每级 `skills` **6–8 项**、`must_have` **≥3 项且必须∈该级 skills 的 name**、`required ∈ 1..4`（`ROLE_REQUIRED_LEVELS = (1,2,3,4)`）。
- `role` 唯一（`target_role` 精确匹配键；**不做模糊/同义词猜测**——猜错比没有更伤，AC-10 的降级就是为此）。

### 2.3 契约新增（`backend/app/schemas.py` ↔ `frontend/src/api/types.ts` 逐字镜像）

```python
DIFFICULTY_LABEL    # 在 services/coach_copy.py，不进契约
class WeaknessSample(BaseModel):   question_id: str; score: float; evidence: str
class WeaknessItem(BaseModel):
    key: str                      # "方向|difficulty,|essentiality," 分组键（前端 React key + AI 合并键）
    point: str                    # 展示名 = diagnosis._bucket_name 的结果
    direction: str                # 组内题目 payload 里的 direction，无则 ""
    wrong: int; total: int
    rate: float                   # round(wrong/total, 3)，服务端算好
    avg: float                    # 组内均分，round(...,1)
    difficulty: list[str]         # ⊆rules.DIFFICULTIES；无标签组为 []
    essentiality: list[str]       # ⊆rules.ESSENTIALITIES；无标签组为 []
    samples: list[WeaknessSample] # 1..3，score 升序取
    summary: str                  # 一句话薄弱描述（模板；AI 可替换，见 §6.4）
class ResumePointer(BaseModel):
    section: PolishSection; location: str; anchor_text: str; issue: str; focus_key: str
class RoleModelRef(BaseModel):    level: str; label: str            # {"level":"中级","label":"前端工程师 · 中级"}
class RoleFitItem(BaseModel):     name: str; required: int; user_level: int; gap: int; must: bool
class RoleFit(BaseModel):
    target_role: str | None = None
    role_source: Literal["interview", "profile"] | None = None
    role_source_label: str | None = None      # 「本次面试设定」/「简历画像」
    model: RoleModelRef | None = None         # None ⇒ 无匹配模型（AC-10）
    items: list[RoleFitItem] = Field(default_factory=list)
    missing_must: list[str] = Field(default_factory=list)
    first_fix: list[str] = Field(default_factory=list)   # 前 3 个 gap>0 的 name，按 items 顺序
    conclusion: str | None = None
    notice: str | None = None
```

`Report` 追加（全部可选、带默认值，旧 payload 直接过）：

```python
weakness_map: list[WeaknessItem] | None = None
resume_pointers: list[ResumePointer] | None = None
resume_pointers_notice: str | None = None     # 空数组时的中文原因（服务端定，前端只渲染）
role_fit: RoleFit | None = None
```

三种状态语义（**必须照此实现，否则 AC-13 与 AC-6 区分不了**）：

| 字段值 | 含义 | 页面/`.md` 呈现 |
|---|---|---|
| `None` | 旧报告，字段不存在 | 单行 `旧报告不含该区块，重新生成可补全` |
| `[]` | 新报告但本块无内容 | 中文空态（A：`本次测评还没有可统计的计分题`；B：`resume_pointers_notice` 文案） |
| 非空 | 正常 | 表格/列表/差距表 |

TS 侧同名字段、`snake_case`、`| null` 或 `| undefined` 与后端一一对应；`role_source` 用字面量联合 `'interview' | 'profile' | null`。

## 3. 后端模块设计

### 3.1 `services/coach_copy.py`（新增，只放常量，无逻辑）

```python
LEGACY_BLOCK_NOTICE  = "旧报告不含该区块，重新生成可补全"
WEAKNESS_EMPTY       = "本次测评还没有可统计的计分题"
RESUME_NO_TEXT       = "还没有可定位的简历正文，先上传简历再回来看改进要点"
RESUME_AI_FALLBACK   = "简历要点暂时没生成出来，可以先去润色页逐条查看"
ROLE_NO_MODEL        = "暂无该岗位的能力模型"
ROLE_NO_MODEL_HINT   = "可以先按上面的薄弱地图补，或在简历画像里填写更常见的岗位名"
ROLE_SOURCE_LABEL    = {"interview": "本次面试设定", "profile": "简历画像"}
DIFFICULTY_LABEL     = {"basic": "基础", "intermediate": "进阶", "challenge": "挑战"}
ESSENTIALITY_LABEL   = {"must_know": "必备", "advanced": "进阶", "nice_to_know": "了解"}
```

为什么单独立模块：`weakness` / `resume_hints` / `role_fit` / `markdown` 四个文件 + 前端都需要同一批文案，散落就会漂移；集中后 §9 的「文案双侧一致」门禁可以逐条断言。**不含任何提示词**（AC-4 的静态检查靠这一点）。

### 3.2 `services/weakness.py`（新增）

```python
def build_weakness_map(runs: list[dict[str, Any]]) -> list[WeaknessItem]
def build_summary(item: WeaknessItem) -> str        # 模板文案（AI 可替换）
def _labels_of(question: dict[str, Any], bank: dict[str, dict[str, Any]]) -> tuple[list[str], list[str], str]
```

要点：
1. 题源：`for run in runs: for index, question, score in diagnosis._scored(run)`。**不重算分**，不 import 判分/均分实现。
2. 标签：`question_bank.load_questions()` 建 `{id: row}` 索引（每份报告只调一次）→ 取 `difficulty`/`essentiality`/`direction`；payload 自带闭集值优先于库（旧题被删也能算），两者都没有则该组 `difficulty=[]`、`essentiality=[]`（**不猜、不填默认档**）。
3. 分组键 `key = f"{point}|{','.join(difficulty)}|{','.join(essentiality)}"`，`point = diagnosis._bucket_name(kind, question)`。
4. `wrong = sum(1 for score < rules.SEVERITY_MEDIUM_BELOW)`，`total = len(group)`，`rate = round(wrong/total, 3)`，`avg = round(mean, 1)`。
5. `samples`：组内按 `(score, index)` 升序取前 3，`evidence = f"Q{index} · {format_score(score)}/10"`（与主轴同一口径）。
6. 排序键（全序、可复算）：
   ```python
   (min(ESSENTIALITY_RANK[v] for v in essentiality, default=3),  # must_know 0 / advanced 1 / nice_to_know 2 / 无标签 3
    -rate, avg, -total, key)
   ```
   `ESSENTIALITY_RANK` 由 `rules.ESSENTIALITIES` 的**下标**推出（不复制闭集字面量）。
7. 无已计分题 → `[]`（前端出 AC-19 空态）；地图**不分页、不截断**，`>8` 的折叠是前端行为（AC-19），保证 `.md` 与 payload 条目数一致（AC-12）。

### 3.3 `services/role_fit.py`（新增）

```python
ROLE_LEVELS: tuple[int, ...] = (1, 2, 3, 4)
@dataclass(frozen=True) class TargetRole: role: str | None; source: str | None; label: str | None

@lru_cache(maxsize=1)
def load_role_models() -> dict[str, tuple[_RoleModelLevel, ...]]   # role → 按 years_min 升序的级别
def resolve_target_role(*, interview_settings: InterviewSettings | None, profile: Profile | None) -> TargetRole
def level_for_years(levels: tuple[_RoleModelLevel, ...], years: float | None) -> _RoleModelLevel | None
def user_level_of(skill: str, profile: Profile | None) -> int      # 0..4
def build_role_fit(profile: Profile | None, target_role: str | None) -> RoleFit
```

1. **加载与校验**（风格同 `courses.py`）：`json.loads` + `_RoleModelLevel.model_validate`；缺文件 / 坏 JSON / 缺字段 / 数量或闭集不达标 → `AppError(VALIDATION_ERROR, "岗位能力模型数据不完整，请检查内置模型文件", status=500→改用 400/500? 见下)`。
   - 具体：`errors.VALIDATION_ERROR`，`status=500` 不让（必须是 4xx/5xx 里的中文 envelope 且不是裸 500 traceback）；实现取 `raise AppError(VALIDATION_ERROR, "内置岗位能力模型数据有误，请检查后重启服务", status=500)`——**错误码是 VALIDATION_ERROR，HTTP 500 由 AppError 统一 envelope 输出**，无路径无堆栈（AC-7 断言的是 envelope 形态与中文 message）。测试断言 `exc.info.code == VALIDATION_ERROR` 且 message 不含 `seed`/`/`。
2. `user_level_of`（确定性规则，写进文档供复算）：
   - `0`：画像不含该技能名（技能 `name` / `tech_stack` 均不命中）；
   - `1`：仅 `tech_stack` 命中；
   - `2`：`skills[].name` 命中且证据 ≤1 条；
   - `3`：`skills[].name` 命中且 `len(source_quotes) ≥ 2`（`source_quote` 回填后算 1 条）；
   - `4`：在 3 的基础上，某个 `projects[].bullets` 文本里出现该技能名。
   命中判定：大小写不敏感，`skill.lower() in text.lower()` 双向（模型名/画像名任一包含即可）；`historical` 状态技能按 0 计（已消失能力不算当前水平）。
3. `build_role_fit`（AC-8 签名固定）：`items = [{name, required, user_level, gap=max(0, required-user_level), must=name in must_have}]`，排序 `(0 if must else 1, -gap, name)`；`missing_must = [s for s in must_have if user_level_of(s, profile) == 0 或 < 该 must 的 required]`——**定义取「gap>0」**（缺 ⇔ 未达标），与 `items` 完全同源，避免「必备技能明明缺却说已满足」（anti-goal 4）。
4. 级别选择：`level_for_years` 用 `profile.years_experience`（None → 最低级），落在 `[years_min, years_max)`；越界取最近一端。
5. 无匹配（`target_role` 为 None / 空 / 不在模型里）→ `RoleFit(model=None, items=[], missing_must=[], first_fix=[], notice=ROLE_NO_MODEL, target_role=原值, role_source=...)`，**不抛异常**（AC-10）。
6. 空画像 → 所有 `user_level=0`、`gap=required`、`missing_must=must_have`，不抛（AC-8 ④）。

### 3.4 `services/resume_hints.py`（新增）

```python
MIN_POINTERS = 3
MAX_POINTERS = 5
ANCHOR_MAX = 40          # focus_key 与 anchor_text 上限（仍逐字取自正文切片）
@dataclass(frozen=True) class ResumeHints: pointers: list[ResumePointer]; notice: str | None

def anchor_of(suggestion: PolishSuggestion, resume_text: str) -> str   # 纯函数，逐字切片
def to_pointers(suggestions: list[PolishSuggestion], resume_text: str) -> list[ResumePointer]
async def build_resume_pointers(resume_text: str | None, profile: Profile | None, target_role: str | None, *, client: AIClient | None = None) -> ResumeHints
```

1. 正文为空 / `None` → `ResumeHints([], RESUME_NO_TEXT)`，**不调模型**（AC-6）。
2. 否则 `suggestions = await resume_polish.build_suggestions(resume_text, profile, target_role, client=client)`，紧接 `kept, _ = resume_polish.validate_suggestions(suggestions, resume_text, profile, target_role=target_role)`——**复用反幻觉层**，未逐字命中的整条已被丢弃（AC-4 ③），本模块不再自写校验。
3. `anchor_of`：`original_text` 长度 ≤ 40 时原样；否则取 `resume_text[found:found+40]`（仍是正文逐字切片，不做 trim/归一化）。
4. `focus_key = anchor_text`（**逐字键**，AC-5 的匹配语义就是「逐字相等」，因此不需要任何新 id 或落库）。
5. `location = f"{SECTION_LABEL[section]} · 第 {line} 行"`，`line = resume_text[:start].count("\n") + 1`（由服务端算的 `start` 推出，零猜测）。
6. `issue` = `suggestion.reason` 的第一句（按 `。！？；` 切），截断 ≤60 字。
7. 排序：按 `start` 升序（与正文顺序一致），取前 `MAX_POINTERS`；`len < MIN_POINTERS` 时如实给（不编造补足）。
8. 任何异常（`AIClient` 未配置 / 超时 / 坏 JSON）→ `ResumeHints([], RESUME_AI_FALLBACK)`，**绝不向上抛**（AC-11）。

### 3.5 `services/markdown.py`（修改，单源）

`to_markdown` 在既有「短板总览表 + 每条短板块」**之后**按 `Report` 字段顺序追加三块（顺序固定，AC-12）：

```
## 知识薄弱地图
| # | 薄弱点 | 难度 | 必备级别 | 错/共 | 错误率 | 证据 |
## 简历改进要点           （逐条：1. 「项目经历 · 第 12 行」逐字原句 → issue → /polish?focus=...）
## 市场竞争力对标         （目标岗位 · 来源 · 模型级别；差距表 name/要求/当前/差距；缺失必备；先后补什么 1/2/3）
```
- `None` → 一行 `LEGACY_BLOCK_NOTICE`；`[]` → 对应中文空态；`notice`（无模型）→ 只出 `ROLE_NO_MODEL` + `ROLE_NO_MODEL_HINT`。
- 错误率用 `f"{round(rate*100)}%"`；分数一律 `format_score`；难度/必备级别用 `coach_copy.DIFFICULTY_LABEL/ESSENTIALITY_LABEL` join。
- **文件名/函数不新增渲染源**：不新增 `to_markdown_v2`，原函数扩展，AC-12 断言据此成立。

### 3.6 `services/diagnosis.py`（修改，仅编排）

```python
COACH_SYSTEM = "..."   # 只允许补 1 句文案，name 必须原样返回
class _CoachCopyDraft(BaseModel): weaknesses: list[_WeaknessCopy]; role_conclusion: str | None
async def _enrich_coach(weakness: list[WeaknessItem], role: RoleFit, *, client: AIClient) -> tuple[list[WeaknessItem], RoleFit]
def _resume_text_of(profile: Profile | None) -> str | None      # repository.get_document_text(profile.resume_id)
```

`build_report` 改成「先纯算、再并发补文案」：

```python
runs = _resolve_runs(run_ids)
shortfalls = attach_courses(build_shortfalls(runs))
if not shortfalls: raise AppError(NOT_FOUND, "所选测评里还没有可诊断的作答，请先完成一次模拟面试或笔试", status=404)
weakness = weakness.build_weakness_map(runs)
profile = repository.latest_profile()
role = role_fit.build_role_fit(profile, role_fit.resolve_target_role(
    interview_settings=interview_settings_of(runs), profile=profile).role)
ai = client or AIClient()

async def _copies() -> tuple[list[Shortfall], list[WeaknessItem], RoleFit]:
    """短板文案与教练文案串行两次调用（同一条 AIClient），但整体与简历要点并发。"""
    enriched = await _enrich_copy(shortfalls, client=ai)
    weak, role_out = await _enrich_coach(weakness, role, client=ai)
    return enriched, weak, role_out

copies, hints = await asyncio.gather(
    _copies(),
    resume_hints.build_resume_pointers(_resume_text_of(profile), profile, role.target_role, client=ai),
    return_exceptions=True,
)
shortfalls, weakness, role = _degrade_copies(copies, shortfalls, weakness, role)   # 异常→原纯函数结果
hints = hints if isinstance(hints, resume_hints.ResumeHints) else resume_hints.ResumeHints([], coach_copy.RESUME_AI_FALLBACK)
report = Report(..., weakness_map=weakness, resume_pointers=hints.pointers,
                resume_pointers_notice=hints.notice, role_fit=role)
```
**关键**：`build_shortfalls` 的调用位置、参数、返回与 r6 完全一致（AC-14 硬断言）；`_enrich_coach` 在两块都为空时不发请求（零额外延迟）。用户可见延迟 ≈ `max(短板文案, 简历要点)`，不是两者相加（anti-goal 5）。

## 4. HTTP API（零新增路由）

| 方法 | 路径 | 变化 |
|---|---|---|
| `POST /api/reports/generate` | 响应体 `Report` | 新增 `weakness_map / resume_pointers / resume_pointers_notice / role_fit` |
| `GET /api/reports/latest` | 同上 | 旧报告返回 `null`，**200 不报错** |
| `GET /api/reports/{id}/markdown` | 文本 | 追加三块（同一份 `Report` 渲染） |

错误形态不变：全部 `{error:{code,message,retryable}}`；本轮只新增一个错误来源（模型数据坏 → `VALIDATION_ERROR`）。

## 5. 前端设计

### 5.1 文件与组件树

```
pages/ReportPage.tsx                      # 短板卡片之后插入一行 <CoachBlocks report={report} />（DOM 顺序不可前置）
components/report/CoachBlocks.tsx         # 「提升路线」分区：标题 + 三块容器（顺序 薄弱→简历→竞争力）
components/report/WeaknessMap.tsx         # 表格 + 折叠（本地 useState expanded）
components/report/ResumePointers.tsx      # 列表 + <Link> 跳转 + 空态/降级
components/report/RoleFitCard.tsx         # 目标岗位行 + 差距表 + 缺失必备 + 先补 1/2/3
lib/coach.ts                              # 纯函数与常量（可被 vitest 直接测，无 DOM）
lib/polishFocus.ts                        # 定位纯函数（parseFocusParams / findFocusedSuggestion / focusNotice / SECTION_LABEL）
```

`lib/coach.ts` 公开面：
```ts
export const COACH_COPY: { legacy: string; weaknessEmpty: string; resumeEmpty: string; roleNoModel: string; roleNoModelHint: string }
export const WEAKNESS_FOLD_LIMIT = 8
export const DIFFICULTY_LABEL / ESSENTIALITY_LABEL       // 与后端 coach_copy 逐字一致
export type BlockState = 'legacy' | 'empty' | 'ready'
export function blockStateOf<T>(value: T[] | null | undefined): BlockState
export function foldWeakness<T>(items: T[], expanded: boolean): { visible: T[]; hiddenCount: number }
export function weaknessRateLabel(rate: number): string            // `${Math.round(rate*100)}%`
export function weaknessCountLabel(wrong: number, total: number): string   // `错 ${wrong} / 共 ${total} 题`
export function roleGapLabel(gap: number): string                  // gap===0 ? '达标' : String(gap)
export function polishHref(focusKey: string, section: PolishSection, anchorText: string): string
```

`lib/polishFocus.ts` 公开面：
```ts
export const SECTION_LABEL: Record<PolishSection, string>          // 从 SuggestionCard 内联常量上移（消除重复）
export interface FocusTarget { focus: string; section: PolishSection | null; anchor: string | null }
export function parseFocusParams(params: URLSearchParams): FocusTarget | null
export function findFocusedSuggestion(suggestions: PolishSuggestion[], target: FocusTarget): PolishSuggestion | null
export function focusNotice(section: PolishSection | null): string  // `未找到对应条目，已按「项目经历」筛选`
export const FOCUS_PENDING_NOTICE = '分析完成后会自动定位到报告里指出的那一条'
```

### 5.2 状态管理（不上全局 store）

| 状态 | 归属 | 说明 |
|---|---|---|
| `report` | `ReportPage`（既有 `useAsync`） | 三块只读 `report` 字段，**不合并默认值**（`null` 与 `[]` 语义不同，禁止 `?? []`） |
| `expanded` | `WeaknessMap` | 折叠开关，默认 `false`（首屏先给 8 条，AC-19） |
| `focusedId` | `PolishPage`（`useMemo` 派生） | `session` 变化后由 `findFocusedSuggestion` 重算 |
| `sectionFilter` | `PolishPage` | 未命中时的 section 预筛；与既有 all/pending 过滤**AND** 组合 |
| `focusDismissed` | `PolishPage` | 「显示全部」→ 清空 query + 清 sectionFilter |

### 5.3 `/polish` 定位时序（AC-5 的唯一易碎点）

进入 `/polish?focus=<anchor>&section=<section>&anchor=<encoded>` 时可能**还没有建议列表**（用户未曾点「开始分析」）。处理：
1. 挂载即 `parseFocusParams`，参数留存在组件 state（**不自动调 AI**：进页面就烧一次模型调用不可接受）。
2. `session === null && focusTarget !== null` → 在分析区下方显示 `FOCUS_PENDING_NOTICE`（灰字，不阻断）。
3. `session` 出现后（`useEffect([session, focusTarget])`）：`findFocusedSuggestion` 命中 → `document.getElementById(...).scrollIntoView({block:'center'})` + `.focus({preventScroll: true})`；`SuggestionCard` 收到 `focused` → `is-focused` 类 + `tabIndex={-1}`。
4. 未命中 → `sectionFilter = target.section`（`section` 缺失则不过滤）+ 列表顶部提示条 `focusNotice(section)` + 「显示全部」按钮清参数。
5. 匹配优先级：先按 `anchor`（逐字）比 `original_text`；只有 `focus` 时退化为与 `original_text` 全等比较；都不中才算未命中。

### 5.4 390px 与视觉

所有布局类名、尺寸 token、堆叠顺序严格按 DESIGN §0/§2 实现；三块容器复用 `.sc-card`，错题数与错误率**同屏**（同一行第二个单元格内的两段文本），禁止 `overflow-x`。

## 6. 关键实现点与边界

1. **口径唯一**：`weakness.py` 只 import `diagnosis._scored` / `diagnosis._bucket_name` / `format_score` / `rules.SEVERITY_MEDIUM_BELOW`；`tests/test_engineering_gates.py` 加静态门禁：`services/weakness.py|role_fit.py|resume_hints.py` 内不得出现 `sum(`+`/ len(` 形式的均分实现、不得重定义 `score_of`/`_grade`（按关键字扫描）。
2. **分母诚实**（anti-goal 2）：`sum(item.total for item in weakness_map)` 必须等于该报告内所有 run 的 `len(_scored(run))`——集成测试直接断言这条等式（简答题不进分子分母，因为 `_scored` 本身不产出 text 题）。
3. **逐字不可猜**（anti-goal 3）：`anchor_text` 一律由 `validate_suggestions` 之后的 `original_text`（或正文切片）产生，**不做任何归一化**；`focus_key === anchor_text`，因此跳转匹配失败只可能是「模型换了建议」，此时按 section 预筛给中文提示，绝不猜。
4. **AI 只补一句**（AC-11）：`_CoachCopyDraft` 只含 `weaknesses[{key,summary}]` 与 `role_conclusion`；合并时按 `key` **精确匹配**，不匹配即丢弃；条目数/顺序/数值/`gap` **零改动**；`role_conclusion` 只在 `model !== null` 且 `items` 非空时采纳。三个降级路径（未配置 Key / 抛异常 / 坏 JSON）都必须回模板文案。
5. **并发与超时**：`asyncio.gather(..., return_exceptions=True)`，任一分支异常→该块降级，不影响其它块与整体 200。`AIClient` 已有 `timeout_s`，不新增配置项。
6. **简历正文来源**：`profile.resume_id` → `repository.get_document_text()`；`profile is None` → notice=RESUME_NO_TEXT（无画像也没有可定位正文）。
7. **角色来源**（AC-9）：`resolve_target_role` 严格 `interview_settings.target_role`（经 `history._interviews_settings_of` → `rules.settings_or_none`，两处都为 `None` 时不补默认）> `profile.target_role`；两者都无 → `target_role=None, source=None` → 走 AC-10 降级。
8. **旧报告不白屏**（AC-13）：前端**禁止** `report.weakness_map ?? []`（会把 `null` 变成空态，错误地告诉用户「没有计分题」）；一律先判 `blockStateOf`。
9. **失败不静默**：`notice` 文案由服务端给（`resume_pointers_notice` / `role_fit.notice`），前端只渲染，避免两端各写一份。
10. **无新依赖**：前端不引入 RTL，前端断言全部落在 `lib/*.ts` 纯函数；渲染级验证用 `react-dom/server` 自检脚本（不进 vitest 门禁）。

## 7. 测试策略

### 7.1 后端新增（目标 ≥ +30 条，保持 204 基线不降）

`tests/test_weakness.py`（AC-1/2/3/19/AC-14 辅助）
1. 三键分组条数 == 预期；2. `difficulty/essentiality` 非空且 ⊆ 闭集；3. `samples` 长度 1–3 且 `question_id` 可在 `load_questions()` 反查；4. `wrong<=total`、`rate==round(wrong/total,3)`、`avg` 口径；5. `kind=text` 两题不进 `wrong`/`total`，`sum(total)==len(_scored(run))`；6. 排序全序（必备→rate↓→avg↑→total↓→key）；7. 同输入两次逐字相同；8. `AIClient.complete_model` 抛异常时顺序与 `summary` 不变；9. 无计分题 → `[]`；10. 面试 run（无标签）→ 组 `difficulty==[]`、`total` 仍计入。

`tests/test_role_fit.py`（AC-7/8/9/10/20）
11. seed 数量与结构（4 方向 / 每方向 4 级 / 每级 6–8 项 / `must_have≥3` 且 ⊆ skills）；12. 闭集与 `required∈1..4`、`level` 唯一；13. 坏文件三条异常路径（缺文件/坏 JSON/缺字段）→ `VALIDATION_ERROR` 中文无路径；14. `gap==max(0,required-user_level)` 与排序；15. 幂等两次相同；16. `missing_must` == 未达标的 must 集合；17. 空画像不抛且全 gap=required；18. `user_level` 四档规则；19. `resolve_target_role` 优先级与 label；20. 无匹配 → `model is None` + `notice`；21. `first_fix` 前 3 个 gap>0 且顺序 = items 顺序；22. `years=None` → 最低级。

`tests/test_resume_hints.py`（AC-4/5/6）
23. monkeypatch `build_suggestions` 记录调用次数 ≥1 且 `resume_text` 逐字相等；24. 未逐字命中的建议整条丢弃；25. 3–5 条上限与 `start` 升序；26. AI 异常/无 Key → `([], RESUME_AI_FALLBACK)`；27. 无正文 → `RESUME_NO_TEXT`；28. 静态：除 `POLISH_SYSTEM` 外无第二份含「润色」系统提示词；29. `focus_key == anchor_text`、`location` 含行号、`issue` 非空 ≤60。

`tests/test_report_markdown.py`（AC-12/16）
30. 三块存在且条目数/顺序与字段一致；31. 旧报告/空态/无模型三种文案；32. 错误率为整数百分比、分数走 `format_score`。

`tests/test_report_coach.py`（AC-11/13/14 集成）
33. `build_shortfalls` 序列与基线 fixture 逐字一致且 3≤len≤5；34. 三路 AI 全失败 → 200 且三块结构完整（模板文案非占位）；35. AI 返回条目数 ≠ 输入 → 输出条数/顺序不变；36. 旧 payload（无四字段）→ `repository.latest_report()` 与 `GET /api/reports/latest` 均 200、字段为 `None`；37. 无简历 → `resume_pointers==[]` 且 notice 为中文；38. 无匹配岗位 → `role_fit.model is None`、其余区块完整。

`tests/test_engineering_gates.py` 追加
39. 契约镜像：`schemas.py` 的四个新字段名逐字出现在 `types.ts`；40. 闭集单源：`weakness/role_fit` 不复制 `DIRECTIONS/DIFFICULTIES/ESSENTIALITIES` 字面量；41. 样式 **append-only**（替换 r6 的 `test_style_baseline_untouched`，见 §8.2）；42. 文案双侧一致：`coach_copy.py` 的 6 条中文逐字出现在 `lib/coach.ts`；43. `.md` 单源：`ReportPage.tsx`/`lib/*.ts` 不含 `.md` 拼串（无 `# 能力诊断报告` 等模板字面量）。

### 7.2 前端新增（≥ +12 条断言，基线 72 不降）

`src/test/coach.test.ts`：折叠 8/9 条边界、`blockStateOf(null/[]/非空)` 三态、`weaknessRateLabel`、`weaknessCountLabel`、`roleGapLabel(0)==='达标'`、`polishHref` 的 encodeURIComponent、`DIFFICULTY_LABEL` 覆盖三档。
`src/test/polishFocus.test.ts`：`parseFocusParams`（无 focus→null / 非法 section→null / 正常）；`findFocusedSuggestion` 命中与未命中；`focusNotice` 文案（含 section 名与 fallback 到通用文案）；`SECTION_LABEL` 四档齐全。

### 7.3 门禁与命令（verifyScripts）

```
cd backend && python -m pytest -q -p no:cacheprovider
cd backend && python -m ruff check app tests
cd backend && python -m pytest -q -p no:cacheprovider tests/test_engineering_gates.py
cd frontend && npm run typecheck
cd frontend && npm run lint
cd frontend && npm test
cd frontend && npm run build
cd backend && DB_PATH=tests/.tmp/qa-boot-r7.db AI_API_KEY= python -m uvicorn app.main:app --port 8125  →  curl -sS http://127.0.0.1:8125/health
cd frontend && grep -riE "sk-|api_key|AI_API_KEY" src/ dist/ || echo NO_KEY_LEAK
git status --porcelain=v1 -uall
```
阈值：pytest ≥ 204 + 新增、vitest ≥ 72 + 新增、typecheck 0 error、lint 0 error / ≤28 warning、build 通过、`/health` 200。

## 8. 两处必须认领的契约决定

### 8.1 AC-18 白名单修订（三处，已在上文 §1 列出）
`styles/{tokens,base}.css`、`components/polish/SuggestionCard.tsx`、`tests/test_engineering_gates.py` 都是 AC-16/AC-15/AC-5 的**必要条件**，不加进白名单则 dev 第一天就撞门禁。

### 8.2 r6 样式门禁升格（不是删除）
`test_style_baseline_untouched` 现在是「这两个文件不得出现在 git status」，与 AC-16 直接互斥。改为**同文件内的更强断言**：

```python
def test_style_baseline_append_only() -> None:
    """r7 AC-16：样式基座只允许 append（新增 token / 新增类），任何既有声明不得改动或删除。"""
    for style in ("styles/tokens.css", "styles/base.css"):
        diff = git("diff", "--unified=0", "--", f"frontend/src/{style}")
        removed = [ln for ln in diff.splitlines() if ln.startswith("-") and not ln.startswith("---")]
        assert not removed, f"{style} 出现删除/修改行：{removed[:5]}"
```
理由：r6 的意图是「样式基座零churn」，`append-only` 在语义上**更强**（新增整段仍通过，改动/删除立即失败），因此满足「门禁只增不减」，且新断言与 AC-16 的 token 约束叠加生效。

## 9. 工程约束与 git 动作（贯穿全部任务）

- 分支 `feat/dev-skill-coach` **原地继续**，不新开分支、不 rebase。
- Agent **不执行 git add/commit/amend/stash**；当前唯一未提交改动是本任务夹目录，保持原样。
- 只写 `docs/teamflow/`（本任务夹与技术文档）与产品代码；不写宿主 `docs/<role>/`，不在项目根留任何 `.log/.txt` dump。
- `.gitignore` 审计（dev 末轮自查）：后端 `__pycache__/`、`*.db*`、`.pytest_cache/`、`.ruff_cache/`、`backend/tests/.tmp/`；前端 `node_modules/`、`dist/`、`.vite/`、`*.tsbuildinfo`、`coverage/`；`.env`（`.env.example` 可提交）。
- 无新 pip / npm 依赖（AC-18）。

## 10. 任务拆分（4 波 / 10 任务，按文件所有权切分）

| 波次 | 任务 | 改动文件（所有权） | 只读依赖 | 验收要点 |
|---|---|---|---|---|
| W1 | **T1 契约与共享文案 + 岗位模型数据** | `backend/app/schemas.py`、`backend/app/services/coach_copy.py`、`backend/app/seed/role_models.json`、`frontend/src/api/types.ts` | `rules.py`、`courses.py`、DESIGN §2/§4 | 四字段双侧逐字镜像；seed 结构达标；`pytest`/`typecheck` 仍绿（旧用例零回归） |
| W2 | **T2 薄弱地图** | `services/weakness.py`、`tests/test_weakness.py` | `diagnosis.py`、`question_bank.py`、`rules.py`、`schemas.py`、`coach_copy.py` | AC-1/2/3/19 用例 1–10 全绿 |
| W2 | **T3 岗位差距与加载器** | `services/role_fit.py`、`tests/test_role_fit.py` | `schemas.py`、`rules.py`、`coach_copy.py`、`courses.py`（风格参照） | AC-7/8/9/10/20 用例 11–22 全绿 |
| W2 | **T4 简历要点** | `services/resume_hints.py`、`tests/test_resume_hints.py` | `resume_polish.py`、`repository.py`、`schemas.py` | AC-4/5/6 用例 23–29；无第二份提示词 |
| W2 | **T5 三块 .md 单源** | `services/markdown.py`、`tests/test_report_markdown.py` | `schemas.py`、`coach_copy.py`、`rules.py` | AC-12 用例 30–32；旧报告/空态/无模型三种渲染 |
| W2 | **T6 报告页三块 UI** | `lib/coach.ts`、`components/report/{CoachBlocks,WeaknessMap,ResumePointers,RoleFitCard}.tsx`、`pages/ReportPage.tsx`、`src/test/coach.test.ts` | `api/types.ts`、`components/ui/*`、`lib/format.ts`、DESIGN | DOM 顺序在短板之后；折叠 8 条；三态文案；vitest 新增通过 |
| W2 | **T7 润色页定位** | `lib/polishFocus.ts`、`pages/PolishPage.tsx`、`components/polish/SuggestionCard.tsx`、`src/test/polishFocus.test.ts` | `api/types.ts`、既有 `SuggestionCard` 内部常量 | AC-5：命中滚动+聚焦+`is-focused`；未命中 section 预筛+中文提示；无 session 待定提示 |
| W3 | **T8 编排与集成** | `services/diagnosis.py`、`tests/test_report_coach.py` | 全部 W1/W2 模块签名（见 §3） | AC-11/13/14 用例 33–38；两路 `gather` 并发；短板序列零变化 |
| W3 | **T9 样式 append + 门禁升格** | `styles/tokens.css`、`styles/base.css`、`tests/test_engineering_gates.py` | DESIGN §0.7/§3、W2 组件的类名 | 5 个尺寸 token + 6 组类 append-only；门禁 39–43 全绿；`test_style_baseline_append_only` 生效 |
| W4 | **T10 交付自检** | `.gitignore`、`logs/teamflow/tf-mvxhokwc-w1hxht/scripts/check_r7_selfcheck.cjs`（新增） | 全部 | 跑 §7.3 全部门禁 + `react-dom/server` 渲染自检（DOM 顺序/折叠/旧报告文案/is-focused）；修复发现的问题并记录结论；**不写 QA-REPORT/ACCEPTANCE，不做跨浏览器矩阵** |

并行性：W2 六个任务文件互不相交，`reads` 不计入冲突；W3 依赖 W2 的**签名**（blueprint 已固定），可在 W2 完成后顺序执行；W4 必须最后。

## 11. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 样式文件不在白名单（AC-18） | §8.1 显式修订 + §8.2 更强门禁 |
| 地图「错题数」与历史页口径漂移（anti-goal 2） | `sum(total)==len(_scored(run))` 集成断言 + `_scored` 单一题源 |
| 简历要点高亮不到（anti-goal 3） | `anchor_text` 只取正文逐字切片；`focus_key===anchor_text`；未命中只降级不猜 |
| AI 变慢导致报告难产（anti-goal 5） | 两路 `gather` 并发；两块皆空时不发 `_enrich_coach`；三路失败均降级 200 |
| 旧报告被新前端误判为「无数据」 | `null`（旧）与 `[]`（空）语义分离 + `blockStateOf` 纯函数测试 |
| 面试题无题库标签 | 归入 `difficulty=[]/essentiality=[]` 的组，不丢分不编造；文档明示地图是「题库维度」视角 |

## 12. 交付物清单

- 后端新增：`services/{coach_copy,weakness,role_fit,resume_hints}.py`、`seed/role_models.json`。
- 后端修改：`schemas.py`、`services/{diagnosis,markdown}.py`。
- 后端测试新增：`tests/test_{weakness,role_fit,resume_hints,report_markdown,report_coach}.py`；修改 `tests/test_engineering_gates.py`。
- 前端新增：`lib/{coach,polishFocus}.ts`、`components/report/{CoachBlocks,WeaknessMap,ResumePointers,RoleFitCard}.tsx`、`src/test/{coach,polishFocus}.test.ts`。
- 前端修改：`api/types.ts`、`pages/{ReportPage,PolishPage}.tsx`、`components/polish/SuggestionCard.tsx`、`styles/{tokens,base}.css`（append-only）。
- 零改动：`repository.py`、`db.py`、全部 `routers/`、`rules.py`、`question_bank.py`、`exam_selector.py`。
