基线依赖：docs/teamflow/20261031-r2-ac5-copy-markdown
取代：docs/teamflow/20261031-r1-dev-skill-coach#AC-2（上传→画像从「每次新建一份画像」改为「与当前画像增量合并」）

# TECHNICAL · r3 · 长期记忆（成长时间线 + 增量画像）与简历 AI 润色

> 上游：本任务夹 `PRD.md`（15 条 AC）、`DESIGN.md`（§0 观感规格、§7 对技术的契约输入）。
> 本文只写「怎么实现」。可视化规范、尺寸推导一律回 DESIGN 取值，不在此重复。

## 1. 架构判断与落点

现有代码形态（已核对真实文件）：`backend/app/{main,db,repository,schemas,errors,config}.py` + `routers/`（resume/profile/interview/exam/report/courses/history）+ `services/`（ai/parser/profile/interview/exam/diagnosis/courses/history/markdown/rules）；前端 `pages/`（6 页）+ `components/{ui,profile,interview,exam,report,history}` + `api/{client,types}.ts` + `lib/{useAsync,format}.ts`。

本轮**不引入新框架、不引入新依赖、不新建分包**，按既有约定加三块纵向切片：

| 切片 | 新增后端 | 新增前端 | 复用 |
| --- | --- | --- | --- |
| 成长时间线 | 1 张表 + `services/timeline.py` + `routers/timeline.py` + 3 处写入钩子 | 历史页时间线区（2 组件） | `history.score_of`、`diagnosis.build_shortfalls`、`useAsync`/`PhaseLoader`/`InlineError`/`EmptyState` |
| 画像记忆 | `services/profile_merge.py` + payload 扩展 + 1 个响应模型 | 合并摘要条 + 证据折叠 + 历史分组 | `verify_quotes`、`repository` upsert、`ProfileDimension` |
| 简历润色 | `services/resume_polish.py` + 2 个端点 | `/polish` 页（4 组件）+ 两个入口 | `AIClient.complete_model`、`InlineError`、`ReportPage` 的导出 Blob 写法 |

**三条硬边界（评审要点）**
1. **指标单一来源**：时间线里的 `interview_avg` / `exam_total` 只调 `services/history.py:score_of(kind, payload)`（本轮把既有私有 `_score_of` 提为公开 `score_of`，函数体零改动）；`shortfall_count` 只调 `services/diagnosis.py:build_shortfalls([run])` 取 `len()`。时间线服务内**不写任何分数算式**。
2. **润色单入口**：提示词、模型名、反幻觉校验、成稿拼装只在 `backend/app/services/resume_polish.py`；`routers/` 与 `pages/`、`components/` 零提示词（AC-13 由检查器 grep 断言）。
3. **成稿单源**：`.md` 导出/复制的文本只能来自 `POST .../polish/full` 响应的 `markdown`（服务端 `compose_full` 一次拼装），前端不做 trim/replace/拼接（沿用 r2 的口径）。

## 2. 数据模型与存储

### 2.1 新表 `timeline_events`（`backend/app/db.py:SCHEMA` 追加，只用 `CREATE TABLE IF NOT EXISTS`）

```sql
CREATE TABLE IF NOT EXISTS timeline_events (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,            -- interview | exam | resume
    ref_id TEXT NOT NULL,          -- run_id 或 resume_id
    occurred_at TEXT NOT NULL,     -- ISO(UTC)，排序与对比的唯一口径
    payload TEXT NOT NULL,         -- TimelineEvent JSON 快照
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_timeline_type_ref ON timeline_events (type, ref_id);
CREATE INDEX IF NOT EXISTS idx_timeline_occurred ON timeline_events (occurred_at);
```

- **快照语义**：事件里的分数在写入时定格 → AC-2「事件写入后即使重算报告，分数不得漂移」自然成立（重算报告只写 `reports`，不回写事件）。
- **幂等语义**：`UNIQUE(type, ref_id)` + `INSERT ... ON CONFLICT(type, ref_id) DO NOTHING`，`rowcount==0` 即「已存在」（AC-3）。
- 不写迁移框架：既有 `backend/app.db` 反复执行 `init_db()` 即得新表（与 r1 约定一致）。

### 2.2 画像 payload 扩展（`profiles.payload`，兼容读取，不迁移存量行）

```python
SkillStatus = Literal["active", "historical"]

class Evidence(BaseModel):            # 一条可溯源证据
    quote: str = Field(min_length=1)  # 旧→新累积，逐字来自其来源简历正文
    resume_id: str = ""               # 来源 documents.id（存量行留空）
    file_name: str = ""               # DESIGN §2.2「来源 · xxx.pdf」
    captured_at: str = ""             # 来源简历抓取时间

class ProfileSkill(BaseModel):
    name: str
    source_quote: str                 # 【兼容字段】恒等于 source_quotes[0].quote
    source_quotes: list[Evidence] = [] # 【新增】旧→新累积
    status: SkillStatus = "active"    # 【新增】消失项标 historical

class ProfileProject(ProfileProject→同名扩展，字段同上)
```

- **兼容读取**（`schemas.py` 的 `model_validator(mode="after")`）：`source_quotes` 为空时用 `[Evidence(quote=source_quote)]` 回填、`status` 缺省 `active` → 存量 payload、既有 PATCH、既有测试全部零破坏（PRD R1 的缓解落地）。
- `source_quote` 不废弃：`ProfileDimension` 现有单条溯源展示、`ProfileEditor` 的编辑字段、r1 用例都继续用它，显示口径 = 首条证据。
- 存量数据一次性说明写进 `docs/teamflow/memory.md`（不做迁移脚本）。

### 2.3 润色缓存（进程内，不落库）

`services/resume_polish.py` 内模块级 `_POLISH_CACHE: dict[str, _CachedPolish]`（上限 8 条、TTL 1800s、插入序淘汰）。用途：`/polish` 生成一次，`/full` 复用同一次结果（受 R4「成稿不重复调模型」约束），且**任何采纳状态、目标岗位、成稿都不入库**（AC-10 / AC-12 / 非目标 5）。单进程 uvicorn 下有效；多进程部署不承诺（记入 §11 风险）。

## 3. API 设计

前缀一律 `/api`，`snake_case`，错误走既有 `AppError` → `{error:{code,message,retryable}}`（`message` 中文、不含路径/端点/Key）。**不新增错误码**：只复用既有闭集 `NOT_FOUND` / `VALIDATION_ERROR` / `AI_UNAVAILABLE`（`ai.py` 已把超时/连接/5xx/不可解析统一映射到它，503） / `AI_SCHEMA_INVALID`（502）。

| 方法 | 路径 | 请求 | 响应 | AC |
| --- | --- | --- | --- | --- |
| GET | `/api/timeline` | `?limit=20`（`ge=1,le=50`） | `TimelineEvent[]`（`occurred_at` 倒序） | AC-1/2/5 |
| POST | `/api/resumes/{resume_id}/profile` | —（行为变更：改为合并） | `ProfileWithMerge`（`Profile` + `merge_summary`） | AC-6/7 |
| POST | `/api/resumes/{resume_id}/polish` | `PolishRequest{target_role?}` | `PolishResponse` | AC-8/9/12 |
| POST | `/api/resumes/{resume_id}/polish/full` | `PolishFullRequest{polish_id?, target_role?, suggestion_ids?}` | `PolishFullResponse` | AC-11 |

**契约模型（`backend/app/schemas.py` ↔ `frontend/src/api/types.ts` 逐字段同步）**

```python
TimelineType = Literal["interview", "exam", "resume"]

class TimelineMetrics(BaseModel):
    interview_avg: float | None = None      # 与 history.score_of 同源
    exam_total: float | None = None         # 与 ExamResult.total 同源
    shortfall_count: int | None = None      # len(build_shortfalls([run]))
    skill_added: int = 0                    # resume 事件：新增能力项数
    skill_removed: int = 0                  # resume 事件：转历史的能力项数

class TimelineComparison(BaseModel):        # 服务端算好，前端零减法（AC-5）
    prev_event_id: str
    prev_occurred_at: str
    metric: str                             # "interview_avg" | "exam_total"
    prev_value: float
    current_value: float
    delta: float                            # round(current-prev, 1)
    repeated_shortfalls: list[str]          # 两次都在 = 复现/持续
    disappeared_shortfalls: list[str]       # 上次有、本次无

class TimelineEvent(BaseModel):
    id: str
    type: TimelineType
    ref_id: str
    occurred_at: str
    key_metrics: TimelineMetrics
    shortfall_names: list[str] = []
    added_shortfalls: list[str] = []        # 本次有、上次无（无上次则 = 全部）
    removed_shortfalls: list[str] = []      # 上次有、本次无
    summary: str                            # 中文一句话，服务端组装
    duplicate: bool = False                 # Q4：同一份简历仍记事件
    comparison: TimelineComparison | None = None

class ProfileMergeSummary(BaseModel):
    added: int          # 新增能力项（技能）
    historical: int     # 转为历史的能力项
    evidence_added: int # 证据净增条数
    duplicate: bool

class ProfileWithMerge(Profile):
    merge_summary: ProfileMergeSummary | None = None

PolishSection = Literal["project", "experience", "education", "summary"]

class PolishSuggestion(BaseModel):
    id: str
    section: PolishSection
    original_text: str         # 与 resume 正文逐字相等（字节）
    suggested_text: str        # 已通过反幻觉校验；缺数值处含「〈待补充〉」
    reason: str
    target_role: str | None = None
    flags: list[str] = []      # "numeric_added" 等
    start: int                 # 原句在正文中的起止偏移（服务端算，供前端切片预览）
    end: int

class PolishRequest(BaseModel):
    target_role: str | None = None

class PolishResponse(BaseModel):
    polish_id: str
    resume_id: str
    target_role: str | None = None
    suggestions: list[PolishSuggestion]
    dropped_count: int = 0
    insufficient_reason: str | None = None   # 条目不足时的中文说明（AC-8）

class PolishFullRequest(BaseModel):
    polish_id: str | None = None
    target_role: str | None = None
    suggestion_ids: list[str] | None = None  # None = 全部采纳

class PolishFullResponse(BaseModel):
    id: str
    markdown: str
    dropped_count: int = 0
    regenerated: bool = False                # True = 缓存失效后重跑建议
```

**错误映射（路由层，不写 SQL）**

| 场景 | code | status | message（中文，示例） |
| --- | --- | --- | --- |
| resume_id 不存在 | `NOT_FOUND` | 404 | 没有找到这份简历，请重新上传 |
| 正文为空 / `target_role` 非法 | `VALIDATION_ERROR` | 400/422 | 这份简历没有可润色的正文 / 请求参数不合法，请检查后重试 |
| 模型不可达 / 超时 / 5xx | `AI_UNAVAILABLE` | 503 | AI 服务暂时不可用/响应超时，请稍后重试（沿用既有 `ai.py` 文案） |
| 模型输出不可用（JSON/字段不合规） | `AI_SCHEMA_INVALID` | 502 | AI 返回的建议不合规，请重试一次 |
| 时间线读取 | —（不抛） | 200 空数组 | 时间线不是错误源：空即空态 |

## 4. 后端实现（模块契约，下游必须逐字调用这些名字）

### 4.1 `backend/app/repository.py`（唯一 SQL 出口，新增 4 个函数）

```python
insert_timeline_event(event: TimelineEvent) -> bool     # ON CONFLICT DO NOTHING；插入成功 True，已存在 False
get_timeline_event(event_type: str, ref_id: str) -> TimelineEvent | None
list_timeline_events(limit: int = 20, event_type: str | None = None) -> list[TimelineEvent]
previous_timeline_event(event_type: str, before: str, exclude_id: str = "") -> TimelineEvent | None
get_document(document_id: str) -> dict[str, Any] | None # {text, file_name, created_at}；get_document_text 保留并复用它
```

`list_timeline_events` 的 `ORDER BY occurred_at DESC, created_at DESC` 是**唯一排序点**，服务层与前端不得二次排序。

### 4.2 `backend/app/services/history.py`（1 处提权，不改算法）

```python
score_of(kind: str, payload: dict[str, Any]) -> float | None   # 原 _score_of：私有 → 公开，函数体零改动
```

理由：时间线与历史页对同一 run 的分数必须同源（AC-2 差 ≤0.05）；复制一份算式就是两套口径。

### 4.3 `backend/app/services/timeline.py`（新，写入与读取的唯一入口）

```python
record_run_event(run: dict[str, Any], *, occurred_at: str | None = None) -> TimelineEvent | None
record_resume_event(*, resume_id: str, skill_added: list[str], skill_removed: list[str],
                    duplicate: bool, occurred_at: str | None = None) -> TimelineEvent | None
list_timeline(limit: int = 20) -> list[TimelineEvent]
build_comparison(current: TimelineEvent, previous: TimelineEvent | None) -> TimelineComparison | None
```

`record_run_event` 算法（`interview` / `exam` 共用）：
1. `kind` 必须是 `interview|exam`，否则 `None`；
2. `score = history.score_of(kind, run["payload"])`；`shortfalls = diagnosis.build_shortfalls([run])`；
3. `previous = repository.previous_timeline_event(kind, occurred_at)` → `comparison = build_comparison(...)`；`added/removed` 由本次与上次 `shortfall_names` 的集合差得出（无上次则 `removed=[]`、`added=shortfall_names`）；
4. `summary` 由服务端拼一句中文（例：`面试均分 7.8 · 短板 3 条`，有对比时追加 `· 较上次 ↑ +0.7`）；
5. `repository.insert_timeline_event(event)`；返回事件（已存在返回 `None`）。
**异常策略**：`record_*` 内部 `try/except Exception` 一律不外抛（PRD §5.2「写入失败不得阻止页面进入报告流程」），失败返回 `None`；页面用「事件数 < 趋势表行数」派生提示（DESIGN §4-5），不新增契约字段。

三个写入钩子（各 1–2 行，落在既有完成点之后）：
- `services/interview.py:score_answer` → `status = RUN_COMPLETED` 且 `repository.save_run(...)` 之后；
- `services/exam.py:submit_run` → `repository.save_run(..., RUN_COMPLETED)` 之后（重复提交已被既有 400 拦住，双保险仍有唯一索引）；
- `services/profile.py:generate_profile` → 合并落库成功之后。

### 4.4 `backend/app/services/profile_merge.py`（新，合并与「记忆视图」的唯一出口）

```python
normalize_name(name: str) -> str        # NFKC + strip + casefold + 折叠内部空白
merge_profile(old: Profile | None, draft: ProfileDraft, *, resume_id: str, file_name: str,
              captured_at: str) -> tuple[Profile, ProfileMergeSummary]
active_skills(profile: Profile) -> list[ProfileSkill]        # status == "active"
active_projects(profile: Profile) -> list[ProfileProject]
needs_tech_fallback(profile: Profile) -> bool                # active 技能 < 3
```

合并规则（表驱动单测逐条钉住）：
1. `old is None` → 直接用 draft 建首份画像（`id = uuid4().hex`）；
2. 技能按 `normalize_name` 判同：命中 → 追加一条 `Evidence`（同 `resume_id` 且同 quote 不重复追加），`status` 保持/恢复 `active`，`name` 保留**首次出现**的写法（避免展示抖动）；
3. draft 有、old 无 → 追加 active 项（1 条证据）；
4. old 有、draft 无 → `status="historical"`，证据原样保留（**不删**）；
5. 项目经历同规则（按 `normalize_name(name)`）；
6. `tech_stack` = 新简历值（非空时），否则沿用旧值（历史技能不得回灌出题素材）；
7. `years_experience` / `target_role`：新值非空则覆盖，否则沿用旧值（不允许把已知信息弄丢）；
8. `id` 恒为 `old.id`、`resume_id` 换成新简历、`updated_at = now`；`source_quote = source_quotes[0].quote` 同步；
9. 汇总 `ProfileMergeSummary`：`added` = 新增技能数、`historical` = 本次转历史数、`evidence_added` = 证据净增、`duplicate` = 同一份简历（见下）。

`services/profile.py:generate_profile` 改为：
```python
async def generate_profile(resume_id: str, text: str, *, file_name: str = "",
                           captured_at: str = "",
                           client: AIClient | None = None) -> ProfileWithMerge
```
- 保留既有 `_clip` / `verify_quotes` / 「抽不出内容就 502」全部行为；
- `verify_quotes(draft, body)` 仍对**本次**简历正文校验（老证据在它入库时已各自校验过，不重验也不失效）；
- `duplicate` = `squash(新正文) == squash(repository.get_document(old.resume_id).text)`（old 存在时；Q4）；
- 读—合并—写：写入前后各读一次 `latest_profile()`，若 `updated_at` 在窗口内被改动则重试 1 次（PRD R7），仍冲突则用最后一次结果落库（单用户本地，可接受）；
- 失败（`AI_UNAVAILABLE` / schema 校验失败）→ **不落库**（`insert_profile` 在合并成功之后才调用），画像旧值不动、不写时间线（AC-3）；
- 成功后写 resume 事件（`record_resume_event`），返回 `ProfileWithMerge(profile, merge_summary)`。

`routers/profile.py`：`create_profile` 改读 `repository.get_document(resume_id)`（拿 `file_name`/`created_at`）→ 传给 `generate_profile` → `response_model=ProfileWithMerge`。`GET /api/profiles/latest` **响应模型不变**（仍是 `Profile`，DESIGN §7-1「不为一次性展示扩持久契约」）。

### 4.5 `backend/app/services/resume_polish.py`（新，润色单一入口，AC-13）

```python
async def build_suggestions(resume_text: str, profile: Profile | None,
                            target_role: str | None, *,
                            client: AIClient | None = None) -> list[PolishSuggestion]
def validate_suggestions(suggestions: list[PolishSuggestion], resume_text: str,
                         profile: Profile | None) -> tuple[list[PolishSuggestion], int]
def compose_full(resume_text: str, suggestions: list[PolishSuggestion],
                 adopted_ids: list[str] | None = None) -> str
def remember_suggestions(resume_id: str, target_role: str | None, suggestions: list[PolishSuggestion],
                         dropped_count: int) -> str            # 返回 polish_id
def recall_suggestions(polish_id: str) -> _CachedPolish | None  # 过期/未命中返回 None
```

- `build_suggestions`：`AIClient.complete_model(_SuggestDraft, ...)`，提示词要求「≥5 条、覆盖 ≥2 section、只改措辞与结构、不改事实与数字、缺数值写〈待补充〉、`original_text` 逐字抄录」；给每条分配 `id`（`ps-1..`）与 section。`AIClient` 走 `client=` 注入 → 单测零网络（沿用 conftest 的 `FakeAI`/`patch_ai`）。
- `validate_suggestions`（后置闸门，纯函数，可直接 import 调）：
  1. **逐字相等**：`original_text` 必须在 `resume_text` 中**逐字出现**（`str.find` 原始串，不 squash、不 trim）；未命中 → 丢弃，`dropped_count += 1`；
  2. `start/end` = 该原句首次出现位置（用于前端切片预览与成稿拼装）；
  3. **新增数字**：`suggested_text` 中的数字串（阿拉伯数字/年份）若不在 `resume_text` 也不在画像可解释数字集合（`years_experience`、`period`、`bullets` 内数字、`target_role`），就地替换为 `〈待补充〉`，`flags += ["numeric_added"]`（**不丢弃**，AC-9 的降级路径）；
  4. **新增专名**：`suggested_text` 中 ASCII 词（≥2 字符，如 `GMV`）、`「…」`/`《…》` 片段若不在 `resume_text` 与画像词汇（skills / tech_stack / projects.name）中 → 整条丢弃，`dropped_count += 1`，`flags += ["proper_noun_added"]`（错误形态：宁可少一条，也不让"某大厂/某平台"进成稿）；
  5. 返回 `(保留列表, dropped_count)`；保留列表保证 `≥3 条且 ≥2 section` 时 `insufficient_reason=None`，否则给中文说明（条目不足按实际数量返回，AC-8 的可量化口径）。
- `compose_full`（纯函数，按 `start/end` 做**区间拼装**，零字符串替换）：
  1. 取采纳集合（`adopted_ids=None` → 全部）；
  2. 按 `start` 升序、跳过与已用区间重叠的条目（确定性，杜绝重复替换）；
  3. 输出 `# 简历（润色版）\n\n> Skill Coach · 目标岗位：{target_role or 未指定} · {dropped} 条建议未通过事实校验已剔除\n\n` + 正文（原段落逐字保留，采纳区间换成 `suggested_text`）；
  4. markdown 的换行、列表前缀只做最小保证（不重排原文段落）→ 「成稿看起来像别人的简历」这条 anti-goal 不成立。
- `routers/resume.py` 两个端点只做：取正文 → 解析 `target_role`（body 优先，缺省取画像 `target_role`；**只用于本次调用，不写库**）→ 调 service → 组装响应。上传路径（`POST /api/resumes`）不动。

### 4.6 出题侧的历史项隔离（AC-7）

- `services/interview.py:_profile_brief` 改用 `profile_merge.active_skills(active_projects)`，并在 `active` 技能 <3 时补一行「能力项不足 3 条，请结合技术栈：…」；run payload 增加 `tech_fallback: bool`（fail-open：无技能时不出题的老逻辑不变）。
- `services/exam.py:_profile_tokens` 改取 `active_skills(...) + tech_stack`（`tech_stack` 原本就参与打分亲和度，兜底天然成立）。
- 页面提示（PRD §7 R3 的「页面提示能力项不足」）本轮**不做 UI**：只落 `tech_fallback` 标记，UI 展示记入 `memory.md` 待办（理由：InterviewPage/ExamPage 改动面大且本沙箱无视觉复跑，避免引入不可验的回归）。

## 5. 前端实现

### 5.1 契约与基座

- `src/api/types.ts`：按 §3 逐字段镜像（`TimelineType`/`TimelineMetrics`/`TimelineComparison`/`TimelineEvent`/`Evidence`/`ProfileSkill` 扩展/`ProfileProject` 扩展/`ProfileMergeSummary`/`ProfileWithMerge`/`PolishSuggestion`/`PolishRequest`/`PolishResponse`/`PolishFullRequest`/`PolishFullResponse`）。
- `src/api/client.ts` 增/改：
```ts
timeline: (limit = 20) => request<TimelineEvent[]>(`/api/timeline?limit=${...}`)
generateProfile: (resumeId, signal?) => request<ProfileWithMerge>(...)   // 返回类型升级
polishSuggestions: (resumeId, payload: PolishRequest) => request<PolishResponse>(...)
polishFull: (resumeId, payload: PolishFullRequest) => request<PolishFullResponse>(...)
```
  页面仍**只经 `api`** 出网（检查器断言无 `fetch(`）。
- `styles/tokens.css`：追加 DESIGN §0.2 的 12 个 token（`--tl-row-h`/`--tl-scroll-h`/`--tl-time-w`/`--cmp-panel-h`/`--delta-w`/`--delta-w-sm`/`--merge-bar-h`/`--sev-tab-h`/`--polish-pane-w`/`--polish-prev-h`/`--sugg-min-h`/`--chip-flag-h`），**既有 token 一个不改**。
- `styles/base.css`：文末按区块追加 `.sc-tl-*` / `.sc-cmp-*` / `.sc-merge-bar` / `.sc-evidence-*` / `.sc-sugg-*` / `.sc-seg-tabs` / `.sc-compose-*` / `.sc-target-role` / `.sc-toolnav` / `.sc-modal`；全部 `var(--…)`，无裸色值/裸尺寸。
- `components/ui/ConfirmModal.tsx`（**新增**：DESIGN 写「复用 ConfirmModal」，但仓库里没有此组件——记入 §10 DEVIATION）：`{open, title, message, confirmLabel, cancelLabel, onConfirm, onCancel}`，Esc 关闭、焦点锁在 Modal 内、遮罩 `rgba(4,8,12,.72)` 用 token 表达。
- `components/ui/ToolNav.tsx`（新增）：侧栏「工具」组（成绩趋势 `/history`、简历润色 `/polish`），内部读 `useLocation()` 判当前项。

### 5.2 页面与组件切分

| 文件 | 职责 | 关键 props（下游逐字使用） |
| --- | --- | --- |
| `pages/HistoryPage.tsx`【修订】 | 趋势表（既有不动）+ 下方时间线区；两个 `useAsync` 互不阻塞；派生「未记录」提示 | — |
| `components/history/TimelineSection.tsx`【新增】 | 头部（共 N 条）+ 滚动区 + 三态 | `{ events, status, error, onRetry, deriveMissing? }` |
| `components/history/TimelineEvent.tsx`【新增】 | 单条事件卡 + 展开对比；内含 `TypeBadge`/`MetricGroup`/`DeltaChip`/`ComparisonPanel`（同文件，DESIGN §3 清单的落点） | `{ event, isLatest, expanded, onToggle }` |
| `components/profile/MergeSummaryBar.tsx`【新增】 | 一次会话态摘要条（48 高） | `{ summary: ProfileMergeSummary }` |
| `components/profile/EvidenceList.tsx`【新增】 | 证据折叠（旧→新、来源文件名/日期） | `{ evidence: Evidence[], collapsedLabel?: string }` |
| `pages/ProfilePage.tsx`【修订】 | 页头下摘要条（`useLocation().state`）、技能/项目证据折叠、底部「历史能力 N 项」分组；PATCH 必须展开原条目以保留 `source_quotes`/`status` | — |
| `pages/UploadPage.tsx`【修订】 | 上传成功后**立即**调 `api.generateProfile`（多阶段 `PhaseLoader`）→ 展示合并行 + 「查看画像」`navigate('/profile', { state: { merge } })` | — |
| `pages/PolishPage.tsx`【新增】 | 目标岗位条 + 左建议列表 + 右成稿 Tab + 导出 + 离开保护 | — |
| `components/polish/SuggestionCard.tsx`【新增】 | 三段式（原句/建议句/理由）+ 采纳/忽略 + 降级/丢弃态 | `{ suggestion, state, busy, onAdopt, onIgnore }` |
| `components/polish/SegTabs.tsx`【新增】 | 原版/润色版分段 Tab（40） | `{ tabs: {key,label}[], active, onChange }` |
| `components/polish/ComposePreview.tsx`【新增】 | 预览（本地切片）/已生成（服务端 markdown）/loading/error | `{ mode, text, loading, error, onRetry }` |
| `components/polish/TargetRoleBar.tsx`【新增】 | 临时岗位输入 + 重跑 + 恢复默认 | `{ value, defaultRole, busy, onChange, onApply, onReset }` |
| `pages/ReportPage.tsx`【修订】 | 既有按钮行（复制 Markdown / 导出 .md / 重新生成）**一行不改**；下方新增 13/20 引导 + secondary sm「润色简历」 | — |
| `App.tsx`【修订】 | 新增 `<Route path="/polish" element={<PolishPage/>}/>` + 侧栏挂 `ToolNav` | — |

### 5.3 状态管理（不引入 store）

- **服务端数据**：一律 `useAsync`（既有状态机：loading/error/reload、AbortController 防竞态）；时间线与趋势表各自独立，一处失败不拖另一处（AC-4「失败不得隐藏趋势表」）。
- **画像合并摘要**：`location.state` 一次性（刷新即消失），不写 `localStorage`、不扩 `GET /profiles/latest`（DESIGN §7-1）。
- **润色页本地态**：`adoptions: Record<suggestionId, 'adopted'|'ignored'>`、`composition: {markdown, dropped_count, generated, loading, error}`、`targetRole: {draft, applied, isTemp}`、`generating`。
  - **本地预览**：用服务端下发的 `start/end` 做**切片拼装**（原文字节 + 采纳项 `suggested_text`），不做 trim/replace；meta 标「预览 · 未生成」。
  - **成稿**：只要点过「一键生成」就切到服务端 `markdown`，meta 标「已生成 · 导出取此文本（单源）」；**导出/复制只取这份 markdown**（Blob 写法照 `ReportPage` 的 `createObjectURL` + `revokeObjectURL`）。
  - `target_role` 重跑：用 `original_text` 对齐已采纳项，`original_text` 变了就回未处理并提示「建议已变化，请重新确认」。
  - 生成中离开保护：`useBlocker` 不可用（本项目非 data router）→ `window.beforeunload` + 页内跳转走 `ConfirmModal`。
- **失败反馈**：成功 Toast（唯一 `Toast.tsx`），失败页内 `InlineError`（中文 + 重试）；禁止只用 Toast（沿用 r2 约定）。

## 6. 契约同步清单（`schemas.py` ↔ `types.ts`，检查器逐项断言）

`TimelineEvent{ id, type, ref_id, occurred_at, key_metrics{interview_avg, exam_total, shortfall_count, skill_added, skill_removed}, shortfall_names, added_shortfalls, removed_shortfalls, summary, duplicate, comparison{prev_event_id, prev_occurred_at, metric, prev_value, current_value, delta, repeated_shortfalls, disappeared_shortfalls} }`、`Evidence{quote, resume_id, file_name, captured_at}`、`ProfileSkill{name, source_quote, source_quotes, status}`、`ProfileProject{name, role, period, bullets, source_quote, source_quotes, status}`、`ProfileMergeSummary{added, historical, evidence_added, duplicate}`、`PolishSuggestion{id, section, original_text, suggested_text, reason, target_role, flags, start, end}`、`PolishResponse{polish_id, resume_id, target_role, suggestions, dropped_count, insufficient_reason}`、`PolishFullResponse{id, markdown, dropped_count, regenerated}`。**任何一侧缺字段即 FAIL。**

## 7. 关键实现点与边界

1. **幂等三层**：数据库唯一索引（最终真值）＋ `ON CONFLICT DO NOTHING`（不抛错）＋ 完成钩子只在状态真正变 `completed` 后调用（exam 的重复提交仍是既有 400）。
2. **失败不写、不留半成品**：合并/润色的所有落库动作都在 AI 成功 + 校验通过之后；异常路径只抛中文 `AppError`，画像/`documents.text`/时间线三者都不动。
3. **单源**：分数（`history.score_of`）、短板（`build_shortfalls`）、时间线快照、成稿 `markdown`、报告 markdown 各自只有一个生产点。
4. **排序**：`occurred_at DESC, created_at DESC` 只在 `repository.list_timeline_events`；`previous_timeline_event` 用 `type + occurred_at <` 严格比较（同一时刻并列时用 `created_at` 决胜）。
5. **无上次对比**：`comparison=None`，前端渲染「首次测评，暂无对比」（不外显 0.0 / NaN）。
6. **超时**：`build_suggestions` 用 `settings.ai_timeout_s`（默认 20s，沿用）；`compose_full` 不调模型 ⇒ 成稿不再有 20s 风险（PRD R4）。若真机需要更长，调 `.env` 的 `AI_TIMEOUT_S`，不改代码。
7. **隐私**：`target_role`、采纳状态、成稿都不入库；前端零 Key（`grep` 断言 `NO_KEY_LEAK`）。
8. **本地并发**：合并为读—合并—写 + `updated_at` 乐观校验（重试 1 次）；润色缓存按 `polish_id` 串行，无共享写。

## 8. 测试策略

**后端 pytest（`backend/tests/`，只增不减；AI 全部 `FakeAI`/`patch_ai`，零网络）**

| 文件 | 断言要点 | AC |
| --- | --- | --- |
| `test_timeline.py` | ①面试完成写 1 条 ②笔试提交写 1 条且 `exam_total == 响应 total` ③`interview_avg` 与 `history.score_of` 同源（≤0.05）④`shortfall_count == len(build_shortfalls([run]))` ⑤同 `(type, ref_id)` 连调两次仍 1 条 ⑥AI 失败不写事件 ⑦有上次/无上次/上次另一类型三例 `comparison` ⑧`GET /api/timeline` 倒序 + `limit` 越界 422 ⑨resume 事件含 `skill_added/skill_removed/duplicate` | AC-1/2/3/5 |
| `test_profile_merge.py` | ①二次上传同一 `profile_id`、`updated_at` 刷新 ②证据 ≥2 且旧→新、每条在其**来源**正文逐字命中 ③归一表驱动（`Python`/`python ` /`Ｐｙｔｈｏｎ`）合并为 1 项 ④消失项 `status=historical` 且证据不丢 ⑤`active` 数 == 最新简历能力项数 ⑥历史项不进 `interview._profile_brief`/`exam._profile_tokens` ⑦`active<3` → `tech_fallback` 为真、出题含 `tech_stack` ⑧`merge_summary` 计数 | AC-6/7 |
| `test_resume_polish.py` | ①`original_text` 在正文逐字命中（字节相等）②≥3 条覆盖 ≥2 section，不足时 `insufficient_reason` ③临时 `target_role` 不落库（重跑前后画像不变）④注入伪输出「2023 年 GMV 8000 万」→ `dropped_count ≥1` 或 `〈待补充〉` 出现，且响应体不含 `8000` ⑤`documents.text` 字节不变 ⑥`compose_full` 输出 == `/full` 响应 `markdown`（单源）⑦带 `polish_id` 的 `/full` 不重复调模型（fake 调用计数）⑧service 直接 import 调用（无 FastAPI 上下文） | AC-8/9/10/11/12/13 |
| `conftest.py` 增 | 第二份差异化简历正文 + `profile_factory(...)` 支持 `source_quotes`/`status` + 润色 responder 模板 | — |

**门禁与检查器**

- `cd frontend && npm run typecheck && npm run lint`（0 error）；`cd backend && python -m pytest -q`（既有 73 条不得删/skip，本轮新增全绿）。
- 新检查器 `logs/teamflow/tf-mvwecqgm-yva03c/scripts/check_memory_polish.mjs`（**≥10 条断言**、PASS/FAIL 汇总、退出码 0|1）：
  1. `schemas.py` 与 `types.ts` 的 `TimelineEvent` 字段集相等；2. 两端都有 `comparison` 且前端无自算差值（组件内无 `prev_value -`/`delta =` 之类算式）；3. 页面/组件无 `fetch(`（只经 `api`）；4. `routers/`、`pages/`、`components/` 零提示词/模型名（grep `你是|prompt|gpt-|openai|api_key`）；5. `base.css` 无裸色值（`/#[0-9a-fA-F]{3,6}/` 不命中）；6. `tokens.css` 含 12 个新 token 名；7. `timeline_events` 表与唯一索引在 `db.py`，且 `INSERT INTO timeline_events` 只出现在 `repository.py`；8. 三处写入钩子存在（`interview.py`/`exam.py`/`profile.py` 出现 `record_run_event|record_resume_event`）；9. `build_suggestions`/`validate_suggestions`/`compose_full` 仅定义在 `services/resume_polish.py`，路由零 `AIClient` import；10. `ReportPage.tsx` 仍含「复制 Markdown」「导出 .md」与 `api.reportMarkdown`（r2 不回归）。
- r2 回跑：把归档的 `check_copy_behavior.cjs`（`$DSH_HOME/teamflow/ws-code_learning-d73f6621/logs/tf-mvwcb4xd-6150nu/scripts/`）**复制进本 run 的 `scripts/`** 再跑 6/6（不重建、不改断言）。
- `curl -sS http://127.0.0.1:8000/health` 200；`grep -riE "sk-|api_key|AI_API_KEY" frontend/src frontend/dist || echo NO_KEY_LEAK`。
- **需开发机/CI 复跑**（本沙箱 spawn EPERM）：`npm test`（vitest）、`npm run build`、`python -m ruff check app tests`（本机可能缺 ruff）、视觉/动效走查、真机下载与剪贴板。

## 9. 任务切分（按文件边界；`files` 互斥即可并行）

> 硬约束随任务携带：**分支 `feat/dev-skill-coach` 原地继续**（不新建 worktree、不切主分支）；**Agent 不提交**（验收后由流水线一次性提交代码 + `docs/teamflow/` 任务夹）；提交面不含 `backend/app.db`、检查器脚本、导出文件；`logs/teamflow/` 不提交。
> 三个共享约定任务（T1 契约/存储、T6 前端契约与样式基座）先跑，其余按依赖并行。

| # | 任务 | files（改写范围） | reads | 依赖 | 出口 |
| --- | --- | --- | --- | --- | --- |
| T1 | 契约与存储基座 | `backend/app/db.py`、`backend/app/schemas.py`、`backend/app/repository.py`、`backend/app/services/history.py`、`backend/tests/conftest.py` | `services/diagnosis.py`、`services/profile.py` | — | `python -m pytest -q` 既有用例全绿；新 schema 可 `model_validate_json` 旧 payload |
| T2 | 时间线服务 + 读取端点 + 写入钩子 | `backend/app/services/timeline.py`、`backend/app/routers/timeline.py`、`backend/app/services/interview.py`、`backend/app/services/exam.py`、`backend/app/main.py`、`backend/tests/test_timeline.py` | `repository.py`、`history.py`、`diagnosis.py`、`schemas.py` | T1 | AC-1/2/3/5 的 pytest 绿；`/api/timeline` 可用 |
| T3 | 画像增量合并 | `backend/app/services/profile_merge.py`、`backend/app/services/profile.py`、`backend/app/routers/profile.py`、`backend/tests/test_profile_merge.py` | `repository.py`、`schemas.py`、`interview.py`、`exam.py` | T1（钩子读 T2 的 `record_resume_event`，接口已在本文定稿，可并行） | AC-6/7 pytest 绿 |
| T4 | 润色 service + 两端点 | `backend/app/services/resume_polish.py`、`backend/app/routers/resume.py`、`backend/tests/test_resume_polish.py` | `services/ai.py`、`schemas.py`、`repository.py`、`config.py` | T1 | AC-8/9/11/12/13 pytest 绿 |
| T6 | 前端契约与样式基座 | `frontend/src/api/types.ts`、`frontend/src/api/client.ts`、`frontend/src/styles/tokens.css`、`frontend/src/styles/base.css`、`frontend/src/components/ui/ConfirmModal.tsx`、`frontend/src/components/ui/ToolNav.tsx` | 本文 §3/§5、`components/ui/*`、`ReportPage.tsx` | T1（契约冻结即可开工，不依赖后端实现） | `npm run typecheck` 0 error；无裸色值 |
| T7 | 历史页时间线 UI | `frontend/src/pages/HistoryPage.tsx`、`frontend/src/components/history/TimelineSection.tsx`、`frontend/src/components/history/TimelineEvent.tsx` | `api/types.ts`、`api/client.ts`、`lib/useAsync.ts`、`components/ui/*`、`components/history/TrendTable.tsx` | T6 | 空/错/载三态 + 展开对比 + 无对比态；typecheck/lint 0 error |
| T8 | 画像页合并/证据 + 上传合并行 | `frontend/src/pages/ProfilePage.tsx`、`frontend/src/pages/UploadPage.tsx`、`frontend/src/components/profile/MergeSummaryBar.tsx`、`frontend/src/components/profile/EvidenceList.tsx` | `components/profile/ProfileDimension.tsx`、`ProfileEditor.tsx`、`state/flow.ts` | T6 | 摘要条一次性、证据旧→新、历史分组不降对比度；PATCH 保留 `source_quotes` |
| T9 | 润色页 + 报告入口 + 路由接线 | `frontend/src/pages/PolishPage.tsx`、`frontend/src/components/polish/{SuggestionCard,SegTabs,ComposePreview,TargetRoleBar}.tsx`、`frontend/src/pages/ReportPage.tsx`、`frontend/src/App.tsx` | `api/*`、`components/ui/*`、`ReportPage.tsx` 既有按钮行 | T6 | AC-10/11/12 交互分支齐备；复制/导出不动；`/polish` 可路由 |
| T10 | 门禁、检查器与交付自查 | `logs/teamflow/tf-mvwecqgm-yva03c/scripts/check_memory_polish.mjs`、`logs/teamflow/tf-mvwecqgm-yva03c/scripts/check_copy_behavior.cjs`（复制归档件）、`.gitignore`（仅补缺口）、`docs/teamflow/memory.md`（一次性升级说明 + r3 待办勾选） | 全部实现 | T2–T9 | 新检查器 ≥10 PASS、copy 6/6、门禁全绿、`git status` 干净可提交（不含 db/检查器/导出件） |

**自查口径（非 QA）**：T10 只做「交付自查」——发现即修、只记结论；不写 `QA-REPORT.md`/`ACCEPTANCE.md`，不跑跨浏览器/真机全矩阵（那是 QA 与验收阶段的事）。

## 10. 偏离与决策（上游文档没写死的地方，在此定稿）

1. **UploadPage 触发画像生成（修复既有死链）**：现状 `api.generateProfile` 在 `pages/` 里**从未被调用**（上传后直接进 `/profile` 读 `latestProfile`，首份画像永远生成不出来）。r3 的 AC-6 必须以「上传→生成/合并」为入口，故上传成功后**立即**调 `POST /api/resumes/{id}/profile`（多阶段进度），成功后带 `merge_summary` 进画像页。这是行为变更，取代 r1#AC-2 的入口时序，写进 PRD 基线声明内。
2. **`ConfirmModal` 新建**：DESIGN §2.4 写「复用 `ConfirmModal`」，仓库中不存在该组件（只有 `components/ui/` 的 Button/Card/Chip/EmptyState/InlineError/PhaseLoader/RingProgress/Stepper/Toast）。本轮新增，props 见 §5.1。
3. **`PolishSuggestion.start/end` 契约增补**：DESIGN §7-2 只列 `id/section/original_text/suggested_text/reason/target_role/flags`。加两个偏移的好处：前端「本地预览」与「服务端成稿」共用同一份逐字映射（零裁剪、零替换），AC-11 的单源保真更强；不改变 DESIGN 的视觉与布局。
4. **`/full` 增加 `polish_id` / `regenerated`**：PRD 只写 `{target_role?, suggestion_ids?}`；但「成稿复用已生成建议、不再重复调模型」（R4）要求服务端能找回同一次建议集，故以进程内 `polish_id` 承接，缓存失效时重跑并如实标 `regenerated: true`。**不落库**，满足 AC-10 非持久化。
5. **反幻觉降级策略细分**：新增**数字** → 就地 `〈待补充〉` 降级（`flags=["numeric_added"]`）；新增**专名** → 整条丢弃（计入 `dropped_count`）。PRD 允许两条路径，这里按「数字可占位、专名不可猜测」定档（对应 Q3 保守润色）。
6. **AC-7 页面提示暂缓**：只落 payload `tech_fallback` 标记 + `memory.md` 待办，不动 Interview/Exam 页 UI（本沙箱无视觉复跑）。
7. **技术栈合并口径**：`tech_stack` 取新简历值（非空时），避免历史技能回灌出题素材（对抗 anti-goal 3）。

## 11. 风险与回滚

- **R1 契约面变大**：`Profile` 里新增 `source_quotes/status` —— 已有 pytest 用例用 `ProfileSkill(name, source_quote=…)` 构造，靠 validator 回填保证不破；两侧同步改由 T1 + T6 一次完成。
- **R2 润色缓存是进程内**：重启即失效 → `/full` 会重跑一套建议（`regenerated: true`），提示文案需能解释；单用户本地场景可接受。
- **R3 长耗时**：建议批量一次返回；成稿纯拼装。真机若仍慢，调 `AI_TIMEOUT_S`（不改代码）。
- **R4 视觉不可验**：`vitest`/`build`/真机下载本沙箱不可执行，验收条件已标注「需开发机/CI 复跑」。
- **回滚**：`git reset --hard` 到基线提交即可整体撤销；新表与新列对旧代码无副作用（旧代码读 `payload` 时未知字段由 pydantic `extra="ignore"` 丢弃）。
