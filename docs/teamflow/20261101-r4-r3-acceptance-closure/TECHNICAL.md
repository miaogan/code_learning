# TECHNICAL · r4 r3 验收遗留项闭合（R-1 / D-2 / D-3 / D-4）

基线依赖：`docs/teamflow/20261031-r3-memory-resume-polish/`

取代：`docs/teamflow/20261031-r3-memory-resume-polish/#AC-11`（原版 Tab = `original_text` 拼接、导出名 = 日期格式两项展示口径）

---

## 0. 结论

四条遗留是**两个根因**，不动表、不动路由、不加依赖：

| 条目 | 根因 | 修法 |
|---|---|---|
| R-1 原版 Tab 不是正文 + D-2 导出名是日期 | **同一个读路径缺口**：`documents` 表早有 `text` / `file_name`，`repository.get_document()` 一次就返回 `{text, file_name, created_at}`，但润色响应契约没把它们带出去 | 在既有 `POST /api/resumes/{id}/polish` 响应补 `resume_text` + `file_name`，前端改用它们（删 `buildOriginal`） |
| D-3 `profile_merge` 双份模型 | r3 并行开发窗口留下的兼容层，契约已落地后永远是死分支 | 整段删除，直连 `schemas.py`，类型名 `Merged*` 全部消失 |
| D-4 历史能力项无入口 | 合并摘要条是纯信息条（无按钮槽） | 摘要条加 1 个 secondary 按钮，联动 `ProfilePage` 既有的 `historyOpen` 折叠态 |

**尺寸/契约两条硬判据**（会在验收被逐条量）：

- 摘要条 48 高不变：`--merge-bar-h: 48px`，加 40 高按钮后由 padding 12 → `--sp-1`(4) 补偿，`4 + 40 + 4 = 48`。
- 原版正文逐字：**必须走单一文本节点渲染**，不走既有 `renderMarkdown()`（它会剥 `# ` 与 `- ` 前缀，会直接违反 AC-2）。

---

## 1. 现状核查（已逐文件核对，非推测）

| 事实 | 位置 | 结论 |
|---|---|---|
| `repository.get_document` 返回 `{text, file_name, created_at}`，查不到 `None` | `backend/app/repository.py:69-85` | 已有能力，**不新增 SQL** |
| `documents` 表有 `file_name TEXT NOT NULL` + `text` | `backend/app/db.py:17` 起 | **不改表、不加迁移** |
| `_resume_body()` 只取 `text`，`file_name` 当场丢弃 | `backend/app/routers/resume.py:68-80` | R-1/D-2 的唯一缺口 |
| `PolishResponse` 现有 6 字段，无正文/文件名 | `backend/app/schemas.py:322-328` | 补 2 字段（双侧同步） |
| 前端 `PolishResponse` 镜像同构 | `frontend/src/api/types.ts:291-299` | 补 2 字段 |
| `buildOriginal()` = 建议句 `join('\n\n')` | `frontend/src/pages/PolishPage.tsx:77-81` | 删除 |
| 原版 Tab 用 `buildOriginal`、`meta="原版 · 逐字取自简历正文"` | `frontend/src/pages/PolishPage.tsx:453-460` | 改传 `resume_text` |
| `exportFileName()` 纯日期 | `frontend/src/pages/PolishPage.tsx:51-56` | 改为取 `file_name` + 清洗 |
| `.sc-compose-body` 已 `height: var(--polish-prev-h)`(428) + `overflow-y:auto` + 只读 `role="region" tabIndex={0}` | `frontend/src/styles/base.css:1947-1958` | **AC-4 不需要新 CSS**，两 Tab 天然等高 |
| `ComposePreview` 用 `renderMarkdown()` 剥前缀 | `frontend/src/components/polish/ComposePreview.tsx:24-53` | 需新增 plain 渲染分支 |
| 摘要条第 4 个位置无按钮槽；`--merge-bar-h: 48px`；padding `var(--sp-3)`=12 | `MergeSummaryBar.tsx:18-26` / `tokens.css:134` / `base.css:1623-1635` | 按钮要压 padding，否则 64 高 |
| 历史分组在 `evidenceExtras()` 折叠 chip 内，`historyOpen` 状态 | `ProfilePage.tsx:396-399, 486-542` | D-4 联动点 |
| `profile_merge` 死分支含 `CONTRACT_READY` / `SKILL_HAS_EVIDENCE_FIELDS` / `_FallbackEvidence` / `_FallbackMergeSummary` / `MergedSkill` / `MergedProject` / `MergedProfile` | `profile_merge.py:32-114` | 全删；`Merged*` 还有 3 处使用点（259/284/306/322）与 2 个外部引用（`routers/profile.py:23`、`tests/test_profile_merge.py:30,164,292`） |
| `Button` 支持 `variant="secondary"`、高 40 | `components/ui/Button.tsx:13-27` | D-4 直接用，不自造按钮 |
| `.gitignore` 已覆盖 `*.db-wal/shm/journal`、`backend/tests/.tmp/`、`logs/teamflow/`、`node_modules/`、`dist/`、`.env` | `.gitignore` | 仅缺**通用** `.pytest_cache/`、`.ruff_cache/`（现只有 `backend/` 前缀版） |

---

## 2. 数据模型与存储

**零变更**。不新增表、不改列、不加迁移脚本、不回填存量数据：

- `documents.text` 是 R-1 的唯一正文真源，字节不动（r3 AC-10 口径继续成立）。
- `documents.file_name` 是 D-2 的唯一文件名真源（上传时已落库，见 `routers/resume.py:50-53`）。
- `profiles` 表与 `timeline_events` 不受 D-3/D-4 影响：D-3 只删 Python 层的类型别名，JSON payload 形状与 `historical` 标记不变。
- 旧 `documents` 行若 `file_name` 为空 → 前端回退日期名（**不猜、不补**，PRD §3 非目标）。

---

## 3. 契约与 API 设计

### 3.1 唯一契约改动：`POST /api/resumes/{resume_id}/polish`（响应扩 2 字段，不新增路由）

`backend/app/schemas.py`：

```python
class PolishResponse(BaseModel):
    polish_id: str
    resume_id: str
    target_role: str | None = None
    resume_text: str = Field(description="整篇简历正文，与 documents.text 逐字相等（只读通道，不参与成稿拼装）")
    file_name: str = Field(default="", description="来源文件名（documents.file_name），导出命名用；空串由前端回退")
    suggestions: list[PolishSuggestion]
    dropped_count: int = 0
    insufficient_reason: str | None = None
```

`frontend/src/api/types.ts`（同序镜像，snake_case 零转换）：

```ts
export interface PolishResponse {
  polish_id: string
  resume_id: string
  target_role: string | null
  /** documents.text 整篇正文，逐字（只读通道；不参与成稿拼装） */
  resume_text: string
  /** 来源文件名（documents.file_name），导出命名用；空串走前端回退 */
  file_name: string
  suggestions: PolishSuggestion[]
  dropped_count: number
  insufficient_reason: string | null
}
```

**契约边界（刻意选择）**：

- `/polish/full` **不带** `resume_text`（PRD §7 风险对策：长正文只随建议集走一趟，不复制到成稿通道）。
- 不加路由、不加错误码、不加 query 参数；错误 envelope 与 r3 完全一致（`NOT_FOUND` / `VALIDATION_ERROR` 两条既有路径）。
- `resume_text` 是**只读旁路**：成稿/导出/复制仍只取 `PolishFullResponse.markdown`（AC-5）。

### 3.2 后端签名（实现时逐字按此写）

```python
# backend/app/routers/resume.py
def _load_resume(resume_id: str) -> tuple[str, str]:
    """读 (正文, 来源文件名)；不存在 / 正文为空沿用既有错误码。取代 _resume_body。"""

async def polish_resume(resume_id: str, payload: PolishRequest | None = None) -> PolishResponse
```

`_load_resume` 语义：`document is None` → `AppError(NOT_FOUND, "没有找到这份简历，请重新上传后再润色", 404)`；`text.strip()` 为空 → `AppError(VALIDATION_ERROR, ..., 400)`；`file_name = str(document.get("file_name") or "")`。**一次 `get_document` 调用**（不重复查库）。

```python
# backend/app/services/profile_merge.py（D-3 后的形状，签名不变，仅类型名收敛）
def merge_profile(old: Profile | None, draft: ProfileDraft, *, resume_id: str,
                  file_name: str = "", captured_at: str = "", duplicate: bool = False
                  ) -> tuple[Profile, ProfileMergeSummary]
def backfill_evidence(profile: Profile) -> Profile
def normalize_name(name: str) -> str
```

导入改为直连：`from ..schemas import Evidence, Profile, ProfileMergeSummary, ProfileProject, ProfileSkill, ProfileWithMerge`；删 `from pydantic import BaseModel, Field`（删完后无使用，否则 ruff `F401`）。

```python
# backend/app/routers/profile.py（只改导入与返回注解）
from ..schemas import Profile, ProfilePatch, ProfileWithMerge
from ..services.profile_merge import backfill_evidence

@router.get("/profiles/latest", response_model=Profile, ...)  def read_latest_profile() -> Profile
@router.patch("/profiles/{profile_id}", response_model=Profile, ...)  def update_profile(profile_id: str, patch: ProfilePatch) -> Profile
```

说明：`response_model=Profile` 与旧 `MergedProfile`（= `Profile`）等价，OpenAPI 面零变化；`update_profile` 内 `MergedProfile.model_validate(...)` → `Profile.model_validate(...)`。

---

## 4. 前端实现

### 4.1 新增纯函数模块 `frontend/src/lib/exportName.ts`（D-2 单一命名真源）

```ts
export const EXPORT_PREFIX = '简历润色-'
export const EXPORT_MAX_BASE_CHARS = 120

/** 清洗后的基名（不含前缀与 .md）；返回 '' 表示需回退日期格式。 */
export function sanitizeFileBase(fileName: string | null | undefined): string

/** 导出文件名：`简历润色-<清洗后原名>.md`；无可用原名回退 `简历润色-<yyyy-mm-dd>.md`。 */
export function exportFileName(fileName: string | null | undefined, now?: Date): string
```

清洗规则（**白名单式，绝不剥中文/空格/常见标点**；顺序固定）：

1. `null` / `undefined` / 空串 / 全空白 → `''`；
2. 取基名：按 `/` 与 `\` 切分取最后一段（`a/b.pdf`、`C:\x\c.pdf` 都只剩 `c.pdf`）；
3. 剥 Windows 非法字符 `< > : " / \ | ? *` 与 C0 控制符（`\u0000-\u001f`）；
4. 去扩展名：`\.(pdf|docx|doc|txt|md|rtf|html?)$`（不区分大小写）；无扩展名原样保留；
5. 去首尾空白与尾部 `.`（Windows 会吞尾点）；
6. 若为空 → `''`；
7. 长度按**字符（code point）**截断到 120（`Array.from(s).slice(0, 120).join('')`，避免中文按字节被切一半），截断后再去尾部空白；
8. `exportFileName` = `EXPORT_PREFIX + base + '.md'`；`base === ''` 时 base 换成 `yyyy-mm-dd`（本地时间、补零，沿用 r3 现有 `pad` 写法）。

`PolishPage` 内旧的 `exportFileName()` **删除**，导出改用 `exportFileName(session?.fileName)`（`session === null` 时 → 日期回退，不抛错）。

### 4.2 `ComposePreview`（R-1 渲染真源，AC-2/AC-4/AC-6）

```ts
export interface ComposePreviewProps {
  mode: 'preview' | 'generated' | 'original'   // 由 2 值扩为 3 值
  text: string
  loading: boolean
  error: string | null
  onRetry?: () => void
  phases?: string[]
  activePhase?: number
  elapsedSec?: number
  meta?: string
  emptyText?: string                            // 新增：空态中文占位（逐个 Tab 可覆盖）
}
```

渲染分支：

- `mode === 'original'`：`.sc-compose-body` 追加 `is-plain` 类，**正文以单一文本节点渲染**（`{text}`），不做行切分、不剥前缀；`aria-label="简历原版正文"`。此时 `textContent === text` 逐字成立（AC-2 断言口径）。只读性由既有 `role="region" + tabIndex={0}`、零 `input/textarea/contenteditable` 保证（AC-4）。
- 其余 mode 维持 `renderMarkdown()` 路径，零改动（AC-5 成稿通道不动）。
- 空态：`text.trim() === ''` 时渲染 `emptyText ?? EMPTY_PREVIEW`（中文，AC-6）。
- `error` 非空 → 既有 `InlineError`（中文原因 + 重试），原版 Tab 复用同一条通道。

### 4.3 `PolishPage`（R-1 + D-2 接线）

- `PolishSession` 增 `resumeText: string`、`fileName: string`；`analyze()` 内映射 `resume_text` / `file_name`。
- 删 `buildOriginal()`（`inResumeOrder` 仍被 `buildPreview` 使用 → 保留）。
- 原版 Tab：

```tsx
<ComposePreview
  mode="original"
  meta="原版 · 逐字取自简历正文"
  text={session?.resumeText ?? ''}
  loading={analyzing}
  error={analyzeError}
  onRetry={() => void analyze(roleInput)}
  emptyText={
    analyzing
      ? '正在读取简历正文…'
      : session === null
        ? '点「开始分析」后，这里显示这份简历的原始正文（整篇、逐字、只读）。'
        : '这份简历没有可显示的正文，请重新上传后再试。'
  }
/>
```

（三态覆盖 AC-6：加载中 / 未分析 / 已分析但正文为空；失败态由 `analyzeError` 走 `InlineError`。）

- 导出：`anchor.download = exportFileName(session?.fileName)`，Blob 仍是 `new Blob([full.markdown])` 裸传（AC-5/AC-7）。

### 4.4 `MergeSummaryBar`（D-4 入口槽）

```ts
export interface MergeSummaryBarProps {
  summary: ProfileMergeSummary
  /** 历史能力 + 历史项目现存条数；≤0 → 不渲染入口按钮（AC-12 无死点击）。 */
  historyCount?: number
  /** 入口按钮 aria-controls 指向的页内历史分组 id（AC-11）。 */
  historyControls?: string[]
  /** 点击回调：展开分组 + 滚动 + 焦点（由页面实现）。 */
  onViewHistory?: () => void
}
```

渲染：当 `historyCount > 0 && onViewHistory` 时追加

```tsx
<Button variant="secondary" className="sc-merge-bar-action"
        aria-controls={(historyControls ?? []).join(' ')} onClick={onViewHistory}>
  查看历史能力项
</Button>
```

外层 `<div className="sc-merge-bar">` 在有按钮时追加 `has-action` 类（编号见 §7）。`mergeSummaryText()` 与 48 高语义不变，`role="status"`/`aria-live` 保留。

### 4.5 `ProfilePage`（D-4 联动）

```ts
const HISTORY_GROUP_ID = { skills: 'profile-history-skills', projects: 'profile-history-projects' } as const
const historyRefs = { skills: useRef<HTMLDivElement | null>(null), projects: useRef<HTMLDivElement | null>(null) }
const [historyJump, setHistoryJump] = useState(0)
```

- 计数：`historyCounts = { skills: profile.skills.filter(isHistorical).length, projects: ... }`（复用既有 `isHistorical`）。
- 入口：`viewHistory = () => { setHistoryOpen({ skills: true, projects: true }); setHistoryJump((n) => n + 1) }`；`historyControls` = 计数 >0 的维度 id 列表。
- `evidenceExtras(dimension)` 的历史容器加 `id={HISTORY_GROUP_ID[dimension]}`、`ref={historyRefs[dimension]}`、`tabIndex={-1}`、`className="sc-evidence-list sc-hist-group"`。
- `useEffect(() => {...}, [historyJump, profile])`：`historyJump === 0` 直接返回；否则取**第一个已渲染**（计数 >0）的容器 → `scrollIntoView({ block: 'center', behavior: 'smooth' })` + `focus({ preventScroll: true })`。放在 effect 而非 click 中，保证在「展开态已提交 DOM」之后再滚动/聚焦。
- `<MergeSummaryBar summary={mergeSummary} historyCount={skills+projects} historyControls={...} onViewHistory={viewHistory} />`。
- 需在既有 React import 里补 `useEffect` / `useRef`（当前文件未用）。

---

## 5. 状态管理

- **无新增全局状态、无新增 store、无新依赖**（`state/flow.ts` 不动）。
- `PolishPage`：`session`（含 `resumeText`/`fileName`）是唯一数据源；`tab` 仍控制哪个面板渲染，不用新 state 缓存正文。
- `ProfilePage`：`historyOpen`（既有）+ `historyJump`（一次性跳转信号，计数器而非布尔，重复点击也能重放滚动）+ 两个 `ref`。
- 会话级、刷新即失效（与 r3 「不扩 `GET /profiles/latest` 契约」口径一致）。

---

## 6. 关键实现点与边界

1. **AC-2 的渲染陷阱**：若原版 Tab 继续走 `renderMarkdown()`，`# 技能` 会变 `技能`、`- Python` 会丢 `- `，`textContent` 与 `resume_text` 不等 → 必须 plain 单节点渲染。
2. **AC-3 自然成立**：`resume_text` 是整篇正文，与建议覆盖段数 k 无关；断言仍按「4 段顺序 `indexOf` 命中」写，防止未来退回切片实现。
3. **末尾换行**：`documents.text` 可能以 `\n` 结尾；`white-space: pre-wrap` 单节点渲染会原样保留 → 不能 `trim()` 后再渲染（`trim()` 只用于空态判定）。
4. **AC-7/AC-8 脏名四组**：`a/b.pdf`（路径段）、`resume:2024?.docx`（非法字符）、超长名（>120 字符）、空名 → 全部落到可读 `.md`，不抛错、不弹错误。
5. **AC-11 焦点**：容器 `tabIndex={-1}` 才可 `focus()`；`focus({ preventScroll: true })` 紧跟 `scrollIntoView` 避免二次跳动；`aria-controls` 只含**实际存在**的容器 id。
6. **AC-12 高度算术**：见 §7，`padding` 必须从 `--sp-3` 降到 `--sp-1`，否则 `48 → 64`。
7. **AC-9/AC-10（D-3）**：删的是**类型别名与死分支**，不是行为；`merge_profile` 内部逻辑（`_merge_skills`/`_merge_projects`/`_quotes_of`/`_backfill_entry`）零改动。删除前先跑 `pytest tests/test_profile_merge.py -q` 存基线，删除后再跑全量，比对「证据条数 / `historical` 条数」不变（PRD §4 anti-goal 5）。
8. **`test_profile_merge.py` 必须同步改**（否则 AC-10 直接红）：
   - 删 `:28-38` 的 `CONTRACT_READY = profile_merge.SKILL_HAS_EVIDENCE_FIELDS`、`requires_contract` skip 标记（契约已落地，跳过机制本身就是死代码），并删 `:195`、`:420` 上两处 `@requires_contract` 装饰器；
   - `profile_merge.MergedProfile.model_validate(...)`（`:164`、`:292`）→ `Profile.model_validate(...)`（从 `app.schemas` 导入 `Profile`）；
   - 新增 `test_profile_merge_has_no_duplicate_models()`：读源码断言 `CONTRACT_READY` / `_FallbackEvidence` / `_FallbackMergeSummary` / `MergedSkill` / `MergedProject` / `MergedProfile` 命中 0，且文件内无 `class ...(BaseModel)`（把 AC-9 变成常驻断言）。
9. **`test_resume_polish.py` 新增**（AC-1/D-2 来源契约）：
   - `test_polish_response_carries_verbatim_resume_text`：`body["resume_text"] == resume_text`（`len` 与内容全等，**不 trim**）+ `body["file_name"] == "简历.txt"`；
   - `test_polish_response_file_name_empty_when_missing`：以 `file_name=""` 播种 → `body["file_name"] == ""`（不报错，前端回退）；
   - `test_polish_full_does_not_carry_resume_text`：断言 `/polish/full` JSON 键集不含 `resume_text`（防契约漂移）。
   - 复核既有 `assert "8000" not in response.text`：响应体新增正文后，断言仍然成立（正文里没有 8000），不需改；若夹具含该数字，改为只断言 `suggestions` 段。
10. **ruff**：删死分支后 `BaseModel`/`Field` 无使用 → 必须同时删 import（`F401`）；`profile_merge` 其余 import 顺序按 `I` 规则。
11. **无裸色值（含 CSS 注释）**：新注释里不得写 `#aabbcc` / `rgba(...)` 字面值（`backend/tests/test_engineering_gates.py:101-110` 会扫 `frontend/src/**/*.css` 全文，包含注释）。
12. **不新增依赖**：前端 `vitest` 环境是 `node`（`vite.config.ts` `test.environment: 'node'`），**不能**用 testing-library 渲染组件；组件行为交给运行态检查器/QA，纯函数逻辑进 vitest。

---

## 7. 样式与尺寸推导（`frontend/src/styles/base.css`，只引用 tokens）

```css
/* 摘要条入口按钮：48 = --sp-1(4) + --btn-h(40) + --sp-1(4)，padding 由 --sp-3(12) 降级以保 48 高不变（AC-12） */
.sc-merge-bar.has-action { flex-wrap: nowrap; padding-top: var(--sp-1); padding-bottom: var(--sp-1); }
.sc-merge-bar-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sc-merge-bar-action { margin-left: auto; flex: 0 0 auto; }

/* 原版正文：pre-wrap 保留换行与缩进，单文本节点渲染后与 resume_text 逐字相等（AC-2）；高度/滚动沿用 .sc-compose-body */
.sc-compose-body.is-plain { white-space: pre-wrap; overflow-wrap: anywhere; font-size: var(--fs-body); line-height: var(--lh-body); }

/* 历史分组容器被入口按钮聚焦时的可见焦点环（AC-11/AC-12，键盘可达） */
.sc-hist-group:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
```

- 只新增上面 5 条规则，**不改** `--polish-prev-h`、`--merge-bar-h` 等既有 token（改 token 需回写 DESIGN，本轮禁止）。
- `2px` 焦点环宽度沿用既有微值约定（tokens 无该值），注释说明推导，不含色值字面值。
- `.sc-compose-body` 已有 `height: var(--polish-prev-h)`(428) + `overflow-y: auto`，两 Tab 天然等高 → AC-4 无新增高度逻辑。

---

## 8. 测试策略

| 层 | 覆盖 | 位置 |
|---|---|---|
| 后端单测 | 契约字段逐字相等 / 空文件名 / `/full` 不带正文 | `backend/tests/test_resume_polish.py` |
| 后端单测 | 无死分支（源码断言）+ 合并行为不回归（既有用例改名后全绿，≥113） | `backend/tests/test_profile_merge.py` |
| 后端门禁 | pytest / ruff / `/health` 200 / 无裸色值 | 既有 `test_engineering_gates.py` 等 |
| 前端单测 | `exportFileName` 8 组：正常 / 路径段 / 非法字符 / 空 / 无扩展名 / 超长截断 / 日期回退 / 大小写扩展名 | 新增 `frontend/src/test/exportName.test.ts`（vitest，纯函数，零 DOM） |
| 前端静态 | typecheck / lint / build（0 error，warning 不新增） | 既有脚本 |
| 运行态检查器 | 原版 === `resume_text`、N 段全命中、导出名含原名、摘要条 48 高、按钮 `aria-controls`/焦点 | 由 QA 在 `logs/teamflow/<runId>/scripts/` 建/扩（本阶段不建） |

不在本轮引入：E2E 框架、组件渲染测试库、跨浏览器矩阵（QA 阶段职责）。

---

## 9. 任务拆分（与 PRD M1–M4 对齐，按文件边界）

> 工程约束（PRD §9，逐条带进任务）：分支 `feat/dev-skill-coach` **原地继续**（不新开/不切/不 rebase）；**Agent 不提交**，只改工作树，流水线验收后统一提交；未提交改动（`docs/teamflow/memory.md` + 本任务夹）**不 stash、不 revert、不清理**；不处理 R-2（`nul`）；无新依赖/新框架。

**T1 · M1 后端契约与读路径**（可与 T2/T4/T5 并行）
文件：`backend/app/schemas.py`、`backend/app/routers/resume.py`、`backend/tests/test_resume_polish.py`
- `PolishResponse` 补 `resume_text`（必填）/ `file_name`（默认 `""`）；
- `_resume_body` → `_load_resume(resume_id) -> tuple[str, str]`，一次 `get_document`；`polish_resume` 回填两字段；`/polish/full` 不动；
- 三条新用例（逐字相等 / 空文件名 / full 无正文）。
出口：AC-1（后端侧）、AC-6（错误路径不变）、pytest 全绿。

**T2 · M1 前端原版 Tab + 导出名**（与 T1 并行，读 T1 的字段名）
文件：`frontend/src/api/types.ts`、`frontend/src/lib/exportName.ts`（新）、`frontend/src/test/exportName.test.ts`（新）、`frontend/src/components/polish/ComposePreview.tsx`、`frontend/src/pages/PolishPage.tsx`、`frontend/src/styles/base.css`（成稿区段：`.sc-compose-body.is-plain`）
- 契约镜像 2 字段；`ComposePreview` 扩 `mode:'original'` + `emptyText` + plain 单节点渲染；
- 删 `buildOriginal`，原版 Tab 传 `resume_text`，三态中文；
- `exportFileName` 纯函数 + 8 组 vitest；`PolishPage` 导出改用它；Blob 裸传不变。
出口：AC-2/3/4/5/6/7/8。

**T3 · M3 画像页历史入口**（**串行在 T2 之后**：与 T2 共享 `base.css`）
文件：`frontend/src/components/profile/MergeSummaryBar.tsx`、`frontend/src/pages/ProfilePage.tsx`、`frontend/src/styles/base.css`（摘要条/历史分组段）
- `MergeSummaryBar` 加 `historyCount`/`historyControls`/`onViewHistory` 三 prop 与 secondary 按钮；
- `ProfilePage` 计数 + `historyJump` + refs + effect（展开→滚动→聚焦）+ 容器 `id`/`tabIndex={-1}`；
- CSS 5 条（§7），48 高算术不变。
出口：AC-11、AC-12。

**T4 · M2 D-3 死代码清理**（与 T1/T2 并行，文件集不相交）
文件：`backend/app/services/profile_merge.py`、`backend/app/routers/profile.py`、`backend/tests/test_profile_merge.py`
- 删 `CONTRACT_READY` / `SKILL_HAS_EVIDENCE_FIELDS` / try-import 兼容层 / `_FallbackEvidence` / `_FallbackMergeSummary` / `MergedSkill` / `MergedProject` / `MergedProfile` / `if CONTRACT_READY:` 块；直连 `schemas`；删 `BaseModel, Field` import；
- 3 处使用点改 `Profile`；`routers/profile.py` 导入改源（`response_model` 语义等价）；
- 测试同步：删 skip 机制与两处装饰器、`MergedProfile` → `Profile`、新增「零重复模型」源码断言。
出口：AC-9、AC-10（pytest ≥113 全绿、`historical`/证据条数不变）。

**T5 · 工程约束（`.gitignore` 审计）**（并行）
文件：`.gitignore`
- 逐项核对 PRD §9 清单；只补缺项（现状缺通用 `.pytest_cache/`、`.ruff_cache/`），不新增无关条目（`target/`、`.pnpm-store` 不属本栈，后者已存在且保留）；
- 结论（补了什么 / 本来就有什么）写进验收报告。

**T6 · 交付自检（收尾，串行）**
文件：无（只读 + 发现问题就地修复，修复仍须落白名单）
- 跑全部门禁（§10 命令）与 `git status --porcelain=v1 -uall` 复核改动面；
- 逐条对照 AC-1~AC-14 的「实现点 + 命令 + 结果」；
- **不写 QA-REPORT/ACCEPTANCE**（属 QA 与验收阶段）。

---

## 10. AC 映射与验证命令

| AC | 实现点 | 验证 |
|---|---|---|
| AC-1 | `schemas.py` `PolishResponse.resume_text` + `_load_resume` | `pytest tests/test_resume_polish.py -q`（逐字相等用例） |
| AC-2 | `PolishPage` 原版 Tab 传 `resume_text`；删 `buildOriginal`；`ComposePreview` plain 单节点 | `grep -rn "buildOriginal" frontend/src` → 0；运行态 `textContent` 全等 |
| AC-3 | 整篇正文（与 k 无关） | 运行态：4 段顺序 `indexOf` 命中 |
| AC-4 | 既有 `.sc-compose-body`（428 + `overflow-y:auto` + 只读 region） | 运行态：无 `input/textarea/contenteditable`、两 Tab 等高 |
| AC-5 | `new Blob([full.markdown])` 未改；`resume_text` 不入拼装 | `grep -n "full.markdown" frontend/src/pages/PolishPage.tsx` |
| AC-6 | 三态 + `InlineError` + `emptyText` 中文 | 断网/失败路径手测，无英文异常 |
| AC-7 | `exportFileName(session.fileName)` + `file_name` 契约 | vitest `exportName.test.ts` |
| AC-8 | 清洗 + 回退 + 120 截断 | vitest 四组脏名 |
| AC-9 | `profile_merge.py` 删死分支 | `grep -rn "CONTRACT_READY\|MergedProfile\|MergedSkill\|MergedProject\|_Fallback" backend/app` → 0；`python -c "import app.services.profile_merge"` |
| AC-10 | 合并逻辑零改；测试同步 | `pytest -q` ≥113 passed |
| AC-11 | `MergeSummaryBar` 按钮 + `ProfilePage` effect | 运行态：点击 → 展开 + 滚动 + 焦点 + `aria-controls` |
| AC-12 | `historyCount > 0` 才渲染；`has-action` padding 补偿 | 运行态：摘要条量高 48；0 项无按钮 |
| AC-13 | 门禁 | 见下方命令块 |
| AC-14 | 改动面白名单 / 无新依赖 / 错误 envelope / `/health` | `git status --porcelain=v1 -uall` + `curl /health` |

```bash
cd backend && python -m pytest -q
cd backend && python -m ruff check app tests
cd backend && python -c "import app.services.profile_merge; print('import-ok')"
cd frontend && npm run typecheck
cd frontend && npm run lint
cd frontend && npm test
cd frontend && npm run build
curl -sS http://127.0.0.1:8000/health
cd frontend && grep -riE "sk-|api_key|AI_API_KEY" dist/ src/ || echo NO_KEY_LEAK
cd backend && grep -rn "CONTRACT_READY\|MergedProfile\|MergedSkill\|MergedProject" app/ tests/ || echo DEAD_CODE_GONE
cd frontend && grep -rn "buildOriginal" src/ || echo ORIGINAL_BUILDER_GONE
```

> 沙箱已知阻塞（沿用前几轮记录）：`npm test` / `npm run build` 可能 `spawn EPERM`、`python -m ruff` 可能 `No module named ruff`。同一条命令**同样报错不要重试**，按环境阻塞记录并交开发机复跑。

---

## 11. 风险与对策（增量，与 PRD §7 不重复）

| 风险 | 对策 |
|---|---|
| plain 渲染被误改成 `<pre>` 内再切行 | 断言 `textContent` 全等；plain 分支内零字符串操作 |
| `resume_text` 必填导致其它构造点报错 | 全仓仅 `routers/resume.py:118` 一处构造（已核），测试只 import 类型 |
| 摘要条按钮挤掉 `duplicate` Chip | `has-action` 用 `nowrap` + 文本 `ellipsis`，Chip 与按钮 `flex: 0 0 auto` |
| D-3 删除后 `routers/profile.py` 导入断链 | 同一任务内同步改；`pytest tests/test_routes.py -q` 覆盖 GET/PATCH |
| 检查器把旧「原版=拼接」断言当期望 | 属**修正误报**：QA 阶段同步改断言并在报告写明「动了哪条、为什么」 |
