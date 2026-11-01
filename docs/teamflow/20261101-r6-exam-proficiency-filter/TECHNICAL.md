# r6 技术方案 · 题库入库 + 四维标签 + 熟练度过滤组卷 + 6 层兜底阶梯

> 任务夹：`docs/teamflow/20261101-r6-exam-proficiency-filter/`
> 基线：`docs/teamflow/20261101-r5-interview-chat-config/`（r5）+ r3 时间线
> 取代：`20261031-r1-dev-skill-coach#AC-4` 的**组卷口径**（判分 10s / 客观 ≥8 / 挑战 ≤20% / `answer` 不进响应**不变**）
> 设计真源：本夹 `DESIGN.md`（一行文案的几何与位置）；契约真源：`backend/app/schemas.py` ↔ `frontend/src/api/types.ts`

## 0. 现状核对（都是读代码确认的，不是猜的）

| 现状 | 位置 | 本轮处置 |
|---|---|---|
| 题库是静态 JSON（80 题，四方向各 20；single 48 / multiple 20 / text 12；challenge 恰 8；**无 essentiality、无 intermediate**） | `backend/app/seed/questions.json` | 加 2 维字段后**退为唯一导入源**，改用 `questions` 表承载 |
| 组卷按画像相关度**确定性排序**取题（`_ordered` + `_compose`），同画像必出同卷 | `backend/app/services/exam.py:138-217` | 相关度档内**随机** + 近 3 卷去重 + 熟练度过滤 + 6 层阶梯（新模块） |
| 凑不齐 10 题即 400「题库不足」 | `exam.py:243` | 阶梯逐级放宽，**只有 L6 仍不足**才保留该 400 |
| 判分纯本地、答案只在 `runs.payload`、`per_question` 逐题回写 | `exam.py:280-376` | 判分口径**零改动**，仅在末尾追加「作答事件」写入 |
| 唯一 SQL 出口 `repository.py`；DDL 只在 `db.py`；`init_db()` 用 `CREATE TABLE IF NOT EXISTS` 幂等 | `db.py:14-85` / `repository.py` | 新增 2 张表 + 索引，同样幂等、无迁移脚本 |
| 测试基座 `tmp_db` **只 `init_db()`**，题库由 `_load_questions()` 现读 JSON | `tests/conftest.py:174-188` | 读库后**空库自动种子**，既有 140 个用例零改动 |
| 前端无 RTL / jsdom（`vitest` 只跑纯 TS 逻辑） | `frontend/package.json` | AC-12 的文案判定做成**纯函数**再测，不引新依赖 |
| 后端基线 `pytest -q` = **140 passed**；前端 `vitest` 纯逻辑用例 | 实测 | 门禁只增不减：pytest ≥ 140（新增后 ≥ 170） |

## 1. 改动面（白名单，AC-16）

**后端（9 文件，含 3 个新文件）**
`db.py` · `repository.py` · `config.py` · `schemas.py` · `services/rules.py` · `services/question_bank.py`(新) · `services/proficiency.py`(新) · `services/exam_selector.py`(新) · `services/exam.py` · `main.py` · `seed/questions.json`

**前端（4 文件，含 1 个新文件）**
`api/types.ts` · `lib/examNotice.ts`(新) · `pages/ExamPage.tsx` · `test/examNotice.test.ts`(新)

**测试**：`tests/test_question_bank.py`(新) · `tests/test_proficiency.py`(新) · `tests/test_exam_filter.py`(新) · `tests/test_engineering_gates.py`(仅追加断言)

**零改动**：`tokens.css` / `base.css` / 任何 `components/**` / `routers/**`（无新路由）/ `services/diagnosis.py` / `services/timeline.py` / `services/interview.py` / `docs/teamflow/architecture/**`（§7.2 行由验收同步，不在本轮改）。**不新增依赖**（后端只用标准库 `random` / `dataclasses`）。

## 2. 数据模型与存储

### 2.1 DDL（只写在 `backend/app/db.py` 的 `SCHEMA` 常量里）

```sql
-- r6 题库承载：seed JSON 只做导入源。11 个业务列，answer 只服务端可见（不入任何响应模型）。
CREATE TABLE IF NOT EXISTS questions (
    id           TEXT PRIMARY KEY,
    direction    TEXT NOT NULL,
    kind         TEXT NOT NULL,
    difficulty   TEXT NOT NULL,   -- basic | intermediate | challenge
    essentiality TEXT NOT NULL,   -- must_know | advanced | nice_to_know
    prompt       TEXT NOT NULL,
    options      TEXT NOT NULL,   -- JSON: [{"key","text"}]
    answer       TEXT NOT NULL,   -- JSON: ["B"] / ["A","B","C"] / []（text 型恒 []）
    source       TEXT NOT NULL,   -- 'seed'（本轮唯一取值，为将来题库管理 UI 留位）
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_questions_pool ON questions (direction, difficulty);

-- r6 作答事件：熟练度判定的唯一事实源（只记客观题，简答不计分故永不写入）。
CREATE TABLE IF NOT EXISTS question_attempts (
    id          TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    correct     INTEGER NOT NULL,  -- 0/1
    answered_at TEXT NOT NULL,     -- ISO8601 UTC
    created_at  TEXT NOT NULL,
    UNIQUE (question_id, run_id)   -- 同一卷同一题只有一条事件（重复提交再兜一层）
);
CREATE INDEX IF NOT EXISTS idx_attempts_question ON question_attempts (question_id, answered_at);
```

幂等性（AC-1）：沿用既有「无迁移框架」口径——`init_db()` 对既有 `app.db` 反复执行即得新表与新索引；迁移说明记入 `memory.md` 同主题行（r6 行已落）；`docs/teamflow/architecture/ARCHITECTURE.md` 的「题库承载」表述由 dev 在 T1 顺带改一句（§3.4 表清单 5 张 → 7 张）。

### 2.2 SQL 契约（只写在 `backend/app/repository.py`）

| 函数 | 签名 | 语义 |
|---|---|---|
| `insert_question(question: dict) -> bool` | 入参 `{id,direction,kind,difficulty,essentiality,prompt,options,answer,source?}` | `INSERT ... ON CONFLICT(id) DO NOTHING`；返回是否新增（`cursor.rowcount == 1`）。**已存在行绝不覆盖**（AC-1） |
| `list_questions() -> list[dict]` | — | 全表按 `id` 升序；`options`/`answer` 就地 `json.loads`，返回组卷字典（含 `answer`/`essentiality`/`difficulty`） |
| `count_questions() -> int` | — | `SELECT COUNT(*)`，供幂等断言与空库判定 |
| `insert_attempts(rows: list[dict]) -> int` | `[{id,question_id,run_id,correct,answered_at,created_at}]` | **单事务**批量 `ON CONFLICT(question_id, run_id) DO NOTHING`；返回实际写入条数 |
| `list_attempts() -> list[dict]` | — | 全表，按 `answered_at` 升序（单用户应用，量级小；窗口计算在服务层） |
| `list_recent_exam_question_ids(limit: int) -> list[set[str]]` | — | `SELECT payload FROM runs WHERE kind='exam' ORDER BY created_at DESC LIMIT ?`，Python 侧解出各卷题 id；**返回 newest-first 的 set 列表**（近 N 卷去重的唯一读取口径） |

约定照旧：查不到返回 `None`/空容器，不抛异常；JSON 列的解码只在本文件。

### 2.3 幂等导入（`backend/app/services/question_bank.py`，新）

```python
SEED_PATH = Path(__file__).resolve().parent.parent / "seed" / "questions.json"

def load_seed(path: Path = SEED_PATH) -> list[dict]        # 读 JSON + 逐条 _usable 校验
def import_seed(path: Path = SEED_PATH) -> int             # 幂等导入，返回新增行数
def ensure_seeded() -> int                                 # 空库才导入；返回表内总行数
def load_questions() -> list[dict]                         # 组卷唯一入口：读库；空库自动 ensure_seeded() 后重读
def sync_labels(path: Path = SEED_PATH) -> int             # 仅供 dev 一次性回填校验用（读库比对标签差异），不参与运行时
```

- `_usable(question)` 从 `exam.py` **迁移到本模块**（校验 id/kind/prompt/客观题 answer+options），`exam.py` 只 import，不保留第二份。
- **空库自动种子**是既有 140 用例零回归的关键：`tests/conftest.py` 的 `tmp_db` 只 `init_db()`，`create_run()` → `load_questions()` 发现 `count_questions() == 0` → `import_seed()` → 重读，行为等价于 r5 现读 JSON。
- `main.py` 的 `lifespan` 在 `init_db()` 之后追加 `question_bank.ensure_seeded()`：生产首启即 80 行，重复启动 0 新增（AC-1）。
- 空库/损坏语义（AC-13）：JSON 缺失 → `AppError(VALIDATION_ERROR, "题库文件不可用，暂无法出卷", 400)`（沿用 r1 文案，不新增错误码、不白屏）。

### 2.4 标签回填（数据改动，`seed/questions.json`）

`difficulty` 补 `intermediate` 档（新增 12 题，challenge 仍恰 8）：

| 方向 | intermediate 题 id | 理由（区分「记忆点」与「需辨析」） |
|---|---|---|
| 前端 | `fe-q5` `fe-q10` `fe-q13` | 块级作用域 / 函数式 setState / `unknown` vs `any` |
| 后端 | `be-q11` `be-q15` `be-q17` | N+1、`await` 真实语义、`WHERE` vs `HAVING` |
| 算法与数据结构 | `al-q7` `al-q10` `al-q13` | 链表 vs 数组、DP vs 分治、堆删除复杂度 |
| 计算机基础 | `cs-q11` `cs-q13` `cs-q15` | 死锁必要条件、上下文切换、引用计数 GC |

`essentiality` 按 **id → 档位** 表回填（80 行全覆盖，规则：`must_know`=从业者笔面必问的通用基础概念且**不进** challenge 档；`advanced`=需实践经验或辨析、含全部 challenge；`nice_to_know`=加分/工具细节/冷门记忆点）：

| 方向 | must_know（5） | advanced（5） | nice_to_know（10） |
|---|---|---|---|
| 前端 | `fe-q1` `fe-q2` `fe-q9` `fe-q11` `fe-q18` | `fe-q3` `fe-q8` `fe-q10` `fe-q13` `fe-q14` | `fe-q4` `fe-q5` `fe-q6` `fe-q7` `fe-q12` `fe-q15` `fe-q16` `fe-q17` `fe-q19` `fe-q20` |
| 后端 | `be-q1` `be-q2` `be-q5` `be-q10` `be-q18` | `be-q3` `be-q6` `be-q11` `be-q12` `be-q15` | `be-q4` `be-q7` `be-q8` `be-q9` `be-q13` `be-q14` `be-q16` `be-q17` `be-q19` `be-q20` |
| 算法与数据结构 | `al-q1` `al-q2` `al-q5` `al-q6` `al-q18` | `al-q3` `al-q7` `al-q10` `al-q12` `al-q13` | `al-q4` `al-q8` `al-q9` `al-q11` `al-q14` `al-q15` `al-q16` `al-q17` `al-q19` `al-q20` |
| 计算机基础 | `cs-q2` `cs-q5` `cs-q6` `cs-q7` `cs-q19` | `cs-q3` `cs-q11` `cs-q12` `cs-q13` `cs-q15` | `cs-q1` `cs-q4` `cs-q8` `cs-q9` `cs-q10` `cs-q14` `cs-q16` `cs-q17` `cs-q18` `cs-q20` |

自检口径（与 AC-2 逐条对齐，用例直接断言）：三档皆非空（20/20/40）；每方向 `must_know`=5 ∈ [4,10]；`must_know` 覆盖 `single` + `text` **两种 kind**（≥2）；`difficulty` **全库**三档 60/12/8（`text` 12 道全是 `basic`，故比客观题口径多 12），**客观题口径**（`single`+`multiple` 共 68 道）才是 48/12/8 —— 两个口径分别断言、不混写（QA D-5），`challenge` 恰 8；**每方向三档皆非空**（比 PRD 更严的自加约束，防标签塌成一个方向的投影）。

## 3. 熟练度模型（`backend/app/services/proficiency.py`，新）

纯粹事实：作答事件 + 注入的 `now` + 注入的阈值 → 判定，**不读时钟、不读配置、不写库**。

```python
@dataclass(frozen=True)
class Attempt:      # 服务层视图（repository 行 → dataclass）
    question_id: str
    correct: bool
    answered_at: datetime
    run_id: str

@dataclass(frozen=True)
class Proficiency:
    question_id: str
    proficient: bool
    correct_in_window: int
    attempts_total: int
    last_correct: bool | None
    last_answered_at: datetime | None

def window_start(now: datetime, window_days: int) -> datetime          # now - timedelta(days=window_days)
def evaluate(question_id: str, attempts: Sequence[Attempt], now: datetime,
             *, window_days: int, correct_threshold: int) -> Proficiency
def to_attempts(rows: Sequence[dict]) -> list[Attempt]                 # repository 行 → Attempt（坏行跳过）
def proficient_ids(now: datetime | None = None) -> set[str]            # 读库聚合 + 用 config 阈值
def attempts_by_question(rows) -> dict[str, list[Attempt]]
```

判定式（唯一出处，AC-5）：

```
window 事件 = [a for a in attempts if window_start(now) <= a.answered_at <= now]
proficient  =  len([a for a in window if a.correct]) >= correct_threshold
               and attempts[-1].correct is True        # 最近一次作答（不限窗口）必须正确
```

- **边界**：`answered_at == now - 30d` 恰好命中 → 算窗口内（`>=`）。31 天前 → 不在窗口 → 回流。
- **最近一次答错 → 立即回流**（即使 30 天内已答对 2 次）。
- **0 次作答** → `proficient=False`、`last_correct=None`。
- **简答题不写事件**（AC-4/PRD §7：`text` 不计分，永远不参与熟练判定），因此本模块无需 kind 分支——事实层就没有简答事件。
- 阈值**只在 `config.py` 单一出处**（可环境变量覆盖，禁止散落魔数）：
  `proficiency_window_days: int = 30` · `proficiency_correct_threshold: int = 2` · `recent_paper_exclude: int = 3`。
  `rules.py` 只管**闭集与结构闸门**（`DIFFICULTIES` / `ESSENTIALITIES` / `DIRECTIONS` / `PAPER_STAGES` / 题量与占比），不放可调阈值——这条分工写进两个模块的 docstring，防「阈值又漂回 rules」。

## 4. 组卷算法（`backend/app/services/exam_selector.py`，新）

`exam.py` 只做编排放今日职责（`create_run` / `submit_run` / `grade_objective`），**结构闸门与阶梯整块搬到新模块**，避免 exam.py 长到 700 行（也避免与 `diagnosis.py` 的延迟导入形成环）。

### 4.1 公共 API

```python
PAPER_STAGES: tuple[str, ...] = ("L1", "L2", "L3", "L4", "L5", "L6")

@dataclass(frozen=True)
class Paper:
    questions: list[dict[str, Any]]      # 入选题目（含 answer，落 runs.payload）
    stage: str                           # 'L1'..'L6'
    filtered_count: int                  # 本次真正被熟练度过滤掉的题数（见 4.3 定义）
    backfill: dict[str, int]             # {"must_know": n, "other": m, "history": k}

def rank_pool(questions, profile, rng: random.Random | None = None) -> list[dict]     # 相关度(降)+难度档(升) 分组，组内 rng 洗牌
def build_paper(ranked, *, require_directions: int = 2) -> list[dict] | None           # 结构闸门（原 _compose + _respect_challenge_cap）
def select_paper(questions, profile, *, proficient: set[str],
                 recent: list[set[str]], rng: random.Random | None = None) -> Paper | None
```

`exam.py` 调用点：

```python
proficient = proficiency.proficient_ids(now=now)
recent = repository.list_recent_exam_question_ids(get_settings().recent_paper_exclude)
paper = exam_selector.select_paper(question_bank.load_questions(), profile,
                                   proficient=proficient, recent=recent, rng=rng)
if paper is None:  # 只有 L6 仍不足才到这里
    raise AppError(VALIDATION_ERROR, "题库不足，暂无法出卷，请稍后重试", status=400)
```

### 4.2 随机化（AC-9，且**不得把结构随机掉**）

先按 `(affinity, difficulty)` 分桶 → 每桶 `rng.shuffle` → 桶按 `(-affinity, difficulty_rank)` 排序拼回一条有序列表 → **原结构闸门原样跑在这条列表上**。

- 结果：同相关度同难度档内随机（满足 PRD「随机限同相关度同难度档」），题量/客观 ≥8/挑战 ≤20%/方向覆盖 由闸门恒定，与随机顺序无关。
- `rng` 可注入：测试传 `random.Random(20261101)` 得可复现序列；生产传 `None` → 模块内 `random.Random()`。
- 去重键仍是题目 `id`（`build_paper` 内 `seen`），**卷内不重复**在所有层恒成立。

### 4.3 6 层兜底阶梯（唯一实现，顺序不可重排）

| 层 | 候选池 | 结构约束 | 触发条件 |
|---|---|---|---|
| L1 | `全库 − 熟练 − 近 3 卷` | 10–12 题 / 客观 ≥8 / 挑战 ≤20% / 方向 ≥2 | 首选 |
| L2 | L1 ∪ `熟练 ∩ must_know` | 同上 | L1 建卷失败 |
| L3 | L2 ∪ `熟练 ∩ (advanced ∪ nice_to_know)` | 同上 | L2 失败 |
| L4 | L3 ∪ 近 3 卷题目（**从最旧一卷起逐卷保留**，直至建卷成功） | 同上 | L3 失败 |
| L5 | L4 全放松后池 | 同上但**方向 ≥1**（题量优先于方向纯度，承接 r1 口径） | L4 失败 |
| L6 | **全库**（忽略熟练与历史，仍禁卷内重复） | 客观 ≥8 / 挑战 ≤20% / 10–12 题 | L5 失败 |

- L4 的逐卷放松是三个子步骤（旧 → 次新 → 最新），**`stage` 统一记 `'L4'`**，`backfill["history"]` 记实际回到池子的历史题数，QA 凭 `backfill` 断言阶梯顺序（AC-8）。
- 每层建卷都复用同一个 `build_paper()`；**任何一层因过滤失败都不 400**，只有 `select_paper` 返回 `None`（即 L6 也不足）才 400，文案沿用 r1。

**payload / 契约字段语义（写死，防两处口径漂移）**

- `stage`：最终命中的层号字符串（`'L1'`..`'L6'`），**永不为 None**（新建卷必有一层）。
- `filtered_count`：`|熟练 ∩ 可用题| − |熟练 ∩ 本卷题|`（**净过滤数**）。理由：L2/L3 会把部分熟练题回流进卷面，若仍把它们算作「已过滤」，页面文案「本次已过滤 N 道你已熟练掌握的题」会与卷面自相矛盾。恒 `>= 0`；L6 时通常为 0（全库都出了）。
- `backfill`：`{"must_know": int, "other": int, "history": int}` 三层回流题数，供 QA 断言顺序；旧 payload 无此键 → 读侧给默认 `{}`。
- 旧 payload（r5 及更早）无 `stage`/`filtered_count`/`backfill`：`submit_run` 与报告/诊断/时间线**一律 `.get()` + 默认值**，不得 `KeyError`（AC-8/AC-10）。

### 4.4 结构闸门细节（保持 r1/r5 口径不变）

`build_paper(ranked, require_directions=2)`：先取 `MIN_OBJECTIVE_QUESTIONS=8` 道客观题 → 用 `text` 补到 `MIN_EXAM_QUESTIONS=10` → 不足再用客观题补 → `_respect_challenge_cap` 压回 `≤ ceil(题数*0.2)` 挑战题 → 校验 `题数 ∈ [10,12]`、`客观 ≥8`、`方向数 ≥ require_directions`；任一不满足返回 `None`（由阶梯换池重试，不是异常）。常量全部来自 `rules.py`（`MIN_EXAM_QUESTIONS` / `MIN_OBJECTIVE_QUESTIONS` / `MAX_EXAM_QUESTIONS` / `MAX_CHALLENGE_RATIO` / `max_challenge_count()`）。

## 5. 契约（`schemas.py` ↔ `types.ts` 逐字）

```python
# backend/app/schemas.py 新增
ExamDifficulty = Literal["basic", "intermediate", "challenge"]
QuestionEssentiality = Literal["must_know", "advanced", "nice_to_know"]

class ExamRun(BaseModel):
    run_id: str
    questions: list[ExamQuestion]
    filtered_count: int = 0        # 旧客户端兼容：缺省 0；服务端恒显式赋值

# backend/app/services/rules.py 新增（闭集单一出处）
DIRECTIONS: tuple[str, ...] = ("前端", "后端", "算法与数据结构", "计算机基础")
DIFFICULTIES: tuple[str, ...] = ("basic", "intermediate", "challenge")
ESSENTIALITIES: tuple[str, ...] = ("must_know", "advanced", "nice_to_know")
PAPER_STAGES: tuple[str, ...] = ("L1", "L2", "L3", "L4", "L5", "L6")
def is_objective_kind(kind: str) -> bool
def essentiality_of(question: dict) -> str        # 缺失/非法 → 'nice_to_know'（旧数据读侧兜底）
```

```ts
// frontend/src/api/types.ts 新增/变更
export type ExamDifficulty = 'basic' | 'intermediate' | 'challenge'
export type QuestionEssentiality = 'must_know' | 'advanced' | 'nice_to_know'

export interface ExamRun {
  run_id: string
  questions: ExamQuestion[]
  filtered_count: number
}
```

- **不做**：不加 `essentiality`/`difficulty` 到 `ExamQuestion`（题智隔离，AC-4「`answer` 不进响应」的同类约束）；不新增路由、不改 `POST /api/exams/{run_id}/submit` 的请求/响应形状（`ExamResult` 不变）。
- `filtered_count` 声明**必填**（后端 `Field(default=0)` 保证恒有值），前端读侧仍走 `filteredNotice()` 的 `number | undefined` 形参，旧 fixture/旧后端不会崩——DESIGN §7 的遗留问题由此闭掉。
- 闭集对齐用用例钉死：`set(rules.DIFFICULTIES) == set(get_args(ExamDifficulty))`、`set(rules.ESSENTIALITIES) == set(get_args(QuestionEssentiality))`、`set(rules.DIRECTIONS)` 与题库实际方向逐字相等；`types.ts` 侧由 `check_r6_contract.py` 逐字 grep 比对。

## 6. 前端（一行文案，AC-12）

**`frontend/src/lib/examNotice.ts`（新，纯函数，唯一文案出处）**

```ts
export function filteredNotice(count: number | null | undefined): string | null {
  if (typeof count !== 'number' || !Number.isFinite(count) || count <= 0) return null
  return `本次已过滤 ${count} 道你已熟练掌握的题`
}
```

**`frontend/src/pages/ExamPage.tsx`（唯一渲染点，running/submitting fragment 首子节点）**

```tsx
const notice = filteredNotice(run.filtered_count)
...
{(view === 'running' || view === 'submitting') && run ? (
  <>
    {notice ? (
      <span className="sc-meta-line">
        <Chip label={notice} />
      </span>
    ) : null}
    <div className="sc-actions">…</div>
```

- `notice === null` → **不挂载节点**（不是 `display:none`），`filtered_count = 0` 时页面无任何断言性文案（AC-12 / PRD 反面目标 1 的解药只在 >0 时出现）。
- 位置/几何/无障碍按 `DESIGN.md` §0.5：作答态首行、`.sc-meta-line` + 无 `onClick` 的 `Chip`（`<span>`，不进 tab 序）、不新增 CSS 类与 token、390px 单行。
- 状态管理不变：`run` 仍是 `useState<ExamRun|null>`，`filtered_count` 随 `createExam` 响应进入 state；提交态沿用同一 `run`，不重复渲染（结果面板焦点是总分）。
- 只在 `submitted` 之前的两个视图渲染；刷新后无 `filtered_count`（r5 契约）→ `filteredNotice(undefined) === null` → 静默，符合「缺失按 0」。

## 7. 关键实现点与边界

1. **判分零 AI / 10s（AC-10）**：`submit_run` 的 `grade_objective` / `elapsed_s` / `per_question` / `total` 代码块**一行不改**，只在 `repository.save_run(...)` **之前**算好全部事件、**之后**单次 `repository.insert_attempts(rows)` 写入（先算后写，异常不留半条）。
2. **写入零副作用（AC-4）**：事件只来自 `per_question`（即只含客观题，简答天然不进）；`status=running` 的卷不产生任何事件；重复提交在 400 分支提前返回，**不会二次写**；`INSERT ... ON CONFLICT(question_id, run_id) DO NOTHING` 再兜一层。
3. **旧数据可读（AC-10/AC-13）**：`runs.payload` 只**追加** `stage`/`filtered_count`/`backfill`，不改既有键；报告、诊断、时间线、历史页均不改读取代码（它们只读 `questions`/`per_question`）。
4. **题库不足（AC-8）**：唯一 400 出口是 `select_paper() is None`（L6 也不足 10 题/客观 <8），文案沿用 `"题库不足，暂无法出卷，请稍后重试"`，中文、无路径/堆栈。
5. **性能**：每次出卷 = 1 次 `list_questions()`（80 行）+ 1 次 `list_attempts()`（量级 = 历史客观题作答数）+ 1 次近 N 卷 SELECT；单用户场景为毫秒级，不引入缓存（避免「库改了但卷子没变」）。若后续题目上万再加索引/缓存，本轮不做。
6. **单用户全局熟练度**：不按 `profile_id` 过滤（PRD §7 明示单用户），因此 `proficient_ids()` 无画像参数——避免下游误以为要做多用户隔离。
7. **`essentiality_of()` 兜底**：DB 里若出现旧行/脏值 → 当 `nice_to_know`（最保守：最晚回流，不把一个坏标签当成必备题提前回流）。
8. **禁止**：在 `ExamPage` 上暴露 `stage` 或熟练度分数（DESIGN §6）；在服务层写死 30/2/3 魔数；把 `answer` 放进任何响应模型。

## 8. 任务拆分（8 任务 / 5 波次，按文件边界）

> 工程约束（PRD §11，逐条落到任务里，不得丢）：**分支 `feat/dev-skill-coach` 原地继续，不新开分支**；**Agent 不提交 git**（不 `git add`/`git commit`/`git push`）；工作区现有未提交改动（`M docs/teamflow/memory.md`、`?? docs/teamflow/20261101-r6-exam-proficiency-filter/`）**保留不动**；checker 脚本只写 `logs/teamflow/tf-mvxehsn0-8z1p4e/scripts/`（run 结束由 host 归档，不常驻仓库、不在项目根写日志）。

| # | 波次 | 任务（文件边界） | 拥有文件 | 只读 | 验收标准 |
|---|---|---|---|---|---|
| T1 | W1 | **数据层：题库落库 + 回填标签** | `seed/questions.json` `db.py` `repository.py` `architecture/ARCHITECTURE.md`(1 处表述) | `exam.py` `config.py` `conftest.py` | ① `seed/questions.json` 80 条全部有 `essentiality`，`difficulty` 全库分布 60/12/8（客观题口径 48/12/8），与 §2.4 表逐条一致；② `db.py` 只增 DDL/索引（`questions` 11 列、`question_attempts` 6 列 + UNIQUE + 索引），其它表零改动；③ `repository.py` 实现 §2.2 六个函数，SQL 只在此文件，`answer` 解码后仍是 `list[str]`；④ 用例：`init_db()` 连跑 3 次表结构幂等；两次 `import_seed()` 后 `count_questions()` 恒 80 且第二次返回 0；改一行后再导入**不覆盖**；⑤ 无新依赖 |
| T2 | W2 | **契约与闭集** | `schemas.py` `services/rules.py` `config.py` | `types.ts`（T7 拥有） | ① `ExamDifficulty`/`QuestionEssentiality` Literal 与 `rules.DIFFICULTIES`/`ESSENTIALITIES` 逐字一致（用例双向断言）；② `ExamRun.filtered_count: int = 0`；③ `rules.py` 增 `DIRECTIONS`/`PAPER_STAGES`/`is_objective_kind()`/`essentiality_of()`（脏值→`nice_to_know`）；④ `config.py` 三阈值默值 30/2/3 且可环境变量覆盖；⑤ docstring 写清「阈值在 config，闭集在 rules」分工 |
| T3 | W2 | **熟练度判定纯函数** | `services/proficiency.py`(新) `tests/test_proficiency.py`(新) | `repository.py` `config.py` | ① §3 签名逐字；`evaluate()` 不读时钟/配置/库；② 逐档用例：0 次 / 1 次 / 2 次 / 2 次但最近错 / 2 次都在 31 天前 / **恰好 30 天边界算窗口内**；③ `proficient_ids(now)` 只读 `list_attempts()`；④ 用例断言代码内无 30/2 魔数（用 `inspect.getsource` grep 数字字面量） |
| T4 | W2 | **题库导入与启动种子** | `services/question_bank.py`(新) `main.py` | `repository.py` `db.py` `exam.py` | ① §2.3 五个函数；② `_usable` 只此一份（`exam.py` 不再定义）；③ **空库自动种子**：新库 `load_questions()` 返回 80 条；④ `lifespan` 调 `ensure_seeded()`，重复启动 0 新增；⑤ JSON 缺失 → `VALIDATION_ERROR` 中文 400，不 500 |
| T5 | W2 | **一行文案 + 契约镜像（前端）** | `api/types.ts` `lib/examNotice.ts`(新) `pages/ExamPage.tsx` `test/examNotice.test.ts`(新) | `DESIGN.md` `schemas.py` | ① `ExamRun.filtered_count: number`，`ExamDifficulty`/`QuestionEssentiality` 与 schemas 逐字；② `filteredNotice()` 文案逐字「本次已过滤 N 道你已熟练掌握的题」，`0/undefined/null/NaN/负数` → `null`；③ ExamPage 在 running/submitting fragment 首子节点渲染，`null` 不挂载；④ `tokens.css`/`base.css`/`components/**` **零 diff**；⑤ vitest 新增用例全绿、`npm run lint` 不增加 warning |
| T6 | W3 | **选池 + 随机 + 6 层阶梯** | `services/exam_selector.py`(新) `tests/test_exam_filter.py`(新) | `exam.py` `proficiency.py` `question_bank.py` `rules.py` `config.py` | ① §4.1 签名逐字；`rank_pool` 组内洗牌、`build_paper` 结构闸门（10–12/客观 ≥8/挑战 ≤20%/方向 ≥2）；② 六层顺序不可重排、逐层回池来源与 §4.3 表一致；③ `filtered_count`/`backfill` 语义按 §4.3（净过滤数）；④ 用例：熟练 must_know 不豁免、连续 5 卷不含熟练题、两类极端场景 `select_paper` 不返回 None 且结构达标、`rng=Random(seed)` 可复现、两次不同 seed 卷面不完全相同、近 3 卷独占时第 4 卷交集为空 |
| T7 | W4 | **编排：读库组卷 + 事件写入** | `services/exam.py` `routers/exam.py`(仅当 `filtered_count` 需透传) | `question_bank.py` `exam_selector.py` `proficiency.py` `repository.py` `schemas.py` | ① `create_run(profile_id, *, now=None, rng=None)` 保持位置参数兼容（既有 6 处测试调用不改）；② 组卷走 `question_bank.load_questions()` + `select_paper()`；payload 追加 `stage`/`filtered_count`/`backfill`，`ExamRun.filtered_count` 显式赋值；③ 判分块零改动，末尾单事务写事件（仅客观题）；④ 用例：`running` 卷零事件、重复提交 400 且零新增、简答永不写事件、旧 payload 无新键可正常判分、`ExamResult` 形状不变；⑤ 全量 `pytest` 140 旧例仍绿 |
| T8 | W5 | **交付自检（不改产品代码）** | `tests/test_engineering_gates.py`(追加) `logs/teamflow/tf-mvxehsn0-8z1p4e/scripts/check_r6_contract.py`（**已存在则原地扩展，禁止重建**） | 全部 | ① 门禁实测：`pytest -q`（≥170 且无 fail）、`npm run typecheck`、`npm run lint`（≤28 warnings）、`npm test`、`npm run build`、`GET /health` 200；② checker 断言：§2.4 映射表 80/80 落地、两侧闭集逐字、`answer` 不进响应、无裸色值、改动面白名单（`git status --porcelain -uall` 只含白名单文件 + 任务夹）、无 Key 泄漏；③ 只记录结论，**不写 `QA-REPORT.md`/`ACCEPTANCE.md`**，不跑跨浏览器/真机全矩阵（那是 QA 的职责）；④ 环境阻塞（本机 `ruff` 缺失、沙箱 `npm test/build` spawn EPERM）**如实记录为环境阻塞**并给出开发机复跑命令，不得改写为通过 |

依赖与并行：W1(T1) → W2(T2 ∥ T3 ∥ T4 ∥ T5，文件互不相交) → W3(T6，需 T1/T2/T3 的接口) → W4(T7，需 T4/T6) → W5(T8)。`conftest.py` 的 `seed_questions` fixture **不改**（它读 JSON 原文，仍可校验难度/标签）。

## 9. 测试策略（AC-11 只增不减）

**后端（新增 ≥30 例，目标 pytest ≥170）**

| 文件 | 覆盖 | 关键断言 |
|---|---|---|
| `tests/test_question_bank.py` | AC-1 / AC-2 / AC-3 | 幂等导入（2 次恒 80、0 覆盖）；11 列结构；`answer` 只在库内；历史 payload 题 id 80/80 可反查；四维分布（方向各 20、kind 48/20/12、difficulty 全库 60/12/8（客观题口径 48/12/8）且 challenge 恰 8、essentiality 20/20/40、每方向 must_know ∈[4,10]、must_know ≥2 kind、每方向三档非空）；闭集 ↔ Literal 双向一致；`rules.py` 无重复方向字面量 |
| `tests/test_proficiency.py` | AC-4 / AC-5 | 判定 6 档全测（含恰好 30 天边界）；最近答错即回流；`proficient_ids()` 读库聚合；阈值来自 config（monkeypatch 环境变量 → 行为随动） |
| `tests/test_exam_filter.py` | AC-6 / AC-7 / AC-8 / AC-9 | must_know 不豁免；连续 5 卷不含熟练题；两类极端场景 HTTP 200 / ≥10 题 / 客观 ≥8 / 挑战 ≤20%；payload `stage`+`filtered_count`+`backfill` 可断言 L1→L2→…→L6 顺序（用受控小题库构造）；旧 payload 默认值；随机可复现 + 两次不同 seed 不同卷；近 3 卷去重（第 4 卷交集空） |
| `tests/test_engineering_gates.py` | AC-15 | 追加静态检查：`db.py` 之外无 `CREATE TABLE`；`repository.py` 之外无 `SELECT/INSERT/UPDATE`；`exam.py` 无 30/2/3 魔数；无裸色值；`tokens.css`/`base.css` 与本轮无 diff（比对 git 状态） |

**前端（新增 1 文件）**：`src/test/examNotice.test.ts` —— `filteredNotice` 的 6 档（`0` / `undefined` / `null` / `NaN` / `-3` / `3` / `80` 文案逐字）。

**回归**：`tests/test_exam_service.py`（13 例）、`test_report_service.py`、`test_timeline.py`、`test_routes.py`、`test_interview_chat.py` 全部零改动跑绿；前端 `interviewChat/interviewSettings/format/exportName` 4 个既有测试文件零改动。

**门禁命令（本机实测口径）**

```bash
cd backend && python -m pytest -q -p no:cacheprovider          # ≥170 passed（基线 140）
cd backend && python -m ruff check app tests                    # 环境阻塞：No module named ruff（记环境，不记通过）
cd frontend && npm run typecheck && npm run lint                # typecheck 0 / lint 0 errors ≤28 warnings
cd frontend && npm test && npm run build                        # 沙箱内 spawn EPERM → 记环境阻塞 + 开发机复跑
curl -sS http://127.0.0.1:8000/health                           # 200 + ai_configured 字段
cd frontend && grep -riE "sk-|api_key|AI_API_KEY" src/ dist/ || echo NO_KEY_LEAK
cd backend && python -X utf8 ../logs/teamflow/tf-mvxehsn0-8z1p4e/scripts/check_r6_contract.py
```

## 10. 风险与对策

| 风险 | 触发面 | 对策（已落到任务） |
|---|---|---|
| 读库替换导致既有 140 用例集体 400 | T4/T7 | `load_questions()` 空库自动种子（等价 r5 现读 JSON）；`create_run` 签名只加关键字参数；T7 验收要求「全量旧例仍绿」 |
| 阶梯把「过滤」变成噪音（L6 常驻） | T6 | `stage`/`backfill` 进 payload；用例用受控小库构造出 L1..L6 每一层；L1 命中率靠分布约束保证（20 道 must_know 不会一次全熟练） |
| `filtered_count` 与文案自相矛盾（回流题已在卷面） | T6/T5 | 定义成**净过滤数**（§4.3），单测钉死；`0` → 不渲染 |
| 随机化顺手把结构随机掉 | T6 | 只对池子顺序洗牌，结构闸门 `build_paper()` 单一实现、单一校验点；用例断言 10–12/客观 ≥8/挑战 ≤20%/方向 ≥2 恒定 |
| 两个 `_usable`/两份阈值漂移 | T4/T2 | `_usable` 只在 `question_bank.py`；阈值只在 `config.py`；工程门禁用例静态断言 |
| 单测时间依赖时钟 | T3/T6 | `evaluate(now=...)` 与 `create_run(now=...)` 均可注入；`proficient_ids(now=None)` 只做一次 `datetime.now(UTC)` |
| 标签回填被做成 difficulty 的投影 | T1 | 映射表落本文件 §2.4（80/80）；用例断言 must_know 覆盖 ≥2 kind 且每方向三档非空 |
