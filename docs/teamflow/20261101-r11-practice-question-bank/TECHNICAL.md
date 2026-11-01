# TECHNICAL · 在线练习题库与练习页（r11）

> 基线依赖：`docs/teamflow/20261101-r11-practice-question-bank/PRD.md`、`DESIGN.md`（同夹，建后不可变）。
> 读者：并行开发任务 T1–T6、QA。**先读 §0 与 §9**：§0 是技术裁定，§9 是文件边界与波次。
> 本轮无「取代历史 AC」的事项（跨代行为不改：笔试/报告/面试/时间线/润色全部零行为变化）。

---

## 0. 技术判断（一屏）

| # | 裁定 | 依据 / 代价 |
|---|---|---|
| A1 | **判断题零新控件、零新判分**：`judge` 进 `rules.OBJECTIVE_KINDS`，`grade_objective()` 原样复用（集合相等天然等价「两选项单选」）；渲染沿用 `ExamQuestionCard` 的 `kind !== 'multiple'` 单选分支 | 代码已核实（§1 表）；`KIND_LABEL` 是唯一必须补的共享点（穷举类型） |
| A2 | **`ensure_seeded()` 必须改**：旧实现「仅空库导入」（`question_bank.py:106-110`）会让**存量 `app.db`（含 r10 的 `skillcoach-data` 卷）永远拿不到新增 180 题** | 改为「每次启动 `import_seed()`（`ON CONFLICT(id) DO NOTHING` 保证 0 新增）+ 只补空的新列」。这是本轮唯一打破 r6「库非空即不导」的点，证明见 §2.2 |
| A3 | **存量行的 `language`/`explanation` 走「只填空、不覆盖」定向 UPDATE**（`repository.fill_empty_question_columns()`） | `ON CONFLICT DO NOTHING` 不会补列；不补则存量 80 题筛选全空、解析全空（AC-2/AC-16 直接红） |
| A4 | **四端点、零新增错误码**：`POST /paper`、`POST /answer`、`GET /stats`、`GET /wrong-book`；筛选 0 命中 = 200 + 空列表 + 中文 `notice` | AC-12「不扩张错误码闭集」；`VALIDATION_ERROR` / `NOT_FOUND` / `HTTP_ERROR` 够用 |
| A5 | **练习与笔试共享题库与熟练度账本，练习会话不建表**：`run_id = 'practice:<session_id>'` + 新列 `source`；`proficiency.evaluate()` 与六级阶梯零改动 | AC-11；本轮统计「刷新可重置」是前端态（AC-18），无需持久化会话 |

**判定：判断题进笔试卷面的降级闸门不触发**，`ExamPage` 零改动可通过（证据见 §1）。降级开关仍按 §4.4 预留，一行常量即可切换。

---

## 1. 现状核实（代码证据，不是推测）

| 结论 | 证据 |
|---|---|
| 笔试页判「客观题」只看 `kind !== 'text'` | `frontend/src/pages/ExamPage.tsx:89,114` |
| 题卡控件选择只看 `kind === 'multiple'`，其余一律 radio | `frontend/src/components/exam/ExamQuestionCard.tsx:126` |
| `judge` 会把 `KIND_LABEL` 打成编译错（`Record<ExamQuestion['kind'], string>` 要求穷举） | 同上 `:24-28` |
| 判分 = 标准答案 key 集合与作答 key 集合相等（少选/多选皆错） | `backend/app/services/exam.py:161-173` |
| `TEXT_KIND` 由「kind 闭集 − 客观题」推导，扩 `judge` 后仍解析为 `"text"` | `backend/app/services/rules.py:64-70` |
| 组卷对客观题 / `text` 的分离读 `is_objective_kind()`，不写死种类 | `backend/app/services/exam_selector.py:268-273` |
| 种子导入「仅空库执行」→ 存量库拿不到新题 | `backend/app/services/question_bank.py:106-110` |
| 作答事件幂等键 = `UNIQUE(question_id, run_id)` | `backend/app/db.py:92-100` |
| 既有测试基线（本轮实跑） | 后端 `348 passed + 1 skipped`；前端 `109 passed`（8 文件） |

> 结论：笔试页面对 `judge` **没有**任何 kind 白名单分支，加一个文案键即通；因此不必牺牲「判断题进卷」（PRD §11 第 1 条的首选方案成立）。

---

## 2. 数据模型与存储

### 2.1 DDL 变更（只在 `backend/app/db.py`）

`SCHEMA` 内两张表各追加列（新建库直接生效）：

```sql
CREATE TABLE IF NOT EXISTS questions (
    ...既有 11 列一字不改...
    language     TEXT NOT NULL DEFAULT '',   -- '' = 通用/算法；闭集单一出处 rules.LANGUAGES
    explanation  TEXT NOT NULL DEFAULT ''    -- 逐题解析（全库非空且 ≥10 字，AC-4 ④）
);

CREATE TABLE IF NOT EXISTS question_attempts (
    ...既有 6 列不改...
    source TEXT NOT NULL DEFAULT 'exam',     -- 'exam' | 'practice'（AC-11，缺省 exam）
    UNIQUE (question_id, run_id)             -- 语义不变
);
```

索引从 `SCHEMA` 抽出为独立的 `SCHEMA_INDEXES`（**必须在补列之后执行**，因为新索引引用 `language` / `source`）：

```sql
CREATE INDEX IF NOT EXISTS idx_questions_pool       ON questions (direction, difficulty);
CREATE INDEX IF NOT EXISTS idx_questions_lang_pool  ON questions (language, direction, difficulty);
CREATE INDEX IF NOT EXISTS idx_attempts_question    ON question_attempts (question_id, answered_at);
CREATE INDEX IF NOT EXISTS idx_attempts_run         ON question_attempts (run_id);
```

### 2.2 存量库自动升级路径（AC-5 实跑口径）

`init_db()` 固定三步（顺序即约束）：

```python
def init_db() -> None:
    with connection() as conn:
        conn.executescript(SCHEMA)            # 1. 建表（新库即含新列）
        _ensure_r11_columns(conn)             # 2. 存量库补列（幂等）
        conn.executescript(SCHEMA_INDEXES)    # 3. 建索引（依赖步骤 2 的列）
```

```python
_ADDED_COLUMNS = (
    ("questions", "language", "TEXT NOT NULL DEFAULT ''"),
    ("questions", "explanation", "TEXT NOT NULL DEFAULT ''"),
    ("question_attempts", "source", "TEXT NOT NULL DEFAULT 'exam'"),
)

def _ensure_r11_columns(conn: sqlite3.Connection) -> None:
    for table, column, ddl in _ADDED_COLUMNS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
```

- **幂等**：缺列才 ALTER；第二次启动执行 0 条 DDL（单测：连跑两次 `init_db()` 后 `PRAGMA table_info` 列集合不变且不抛异常）。
- SQLite 允许 `ADD COLUMN ... NOT NULL DEFAULT <常量>`，无需重建表、无需数据迁移脚本（沿用 r3「无迁移框架」的既有约定）。
- 不做「读取侧兜底 `row.get('language', '')`」：列一定存在，读侧不必两套形状。

### 2.3 种子导入的启动口径（A2/A3 的落地）

`question_bank.py` 两处改动：

```python
def ensure_seeded() -> int:
    """启动即幂等导入（r11 改口径）：靠 `ON CONFLICT(id) DO NOTHING` 保证重复启动 0 新增，
    再对存量行「只补空列」。旧实现仅在空库导入，会让既有 app.db 永远拿不到新增题。"""
    import_seed()
    sync_new_columns()
    return repository.count_questions()

def sync_new_columns(path: Path = SEED_PATH) -> int:
    """把种子的 language/explanation 补到**空单元格**上，返回被补齐的行数（幂等：第二次 0）。"""
    return repository.fill_empty_question_columns(load_seed(path))
```

`repository.fill_empty_question_columns(rows)` 的单语句实现（SQL 只在 repository）：

```sql
UPDATE questions SET
    language    = CASE WHEN language    = '' THEN ? ELSE language    END,
    explanation = CASE WHEN explanation = '' THEN ? ELSE explanation END,
    updated_at  = ?
WHERE id = ? AND (language = '' OR explanation = '')
```

要点：
- **只填空**：题面/选项/答案/难度/必备度一律不碰，`insert_question` 的 `ON CONFLICT DO NOTHING` 不变 → r6 AC-1「既有行不被覆盖」不回退；AC-5「重复导入恒 0 新增」由 `import_seed()` 返回值证明。
- 启动成本：260 条 `INSERT ... DO NOTHING` + 一次 `SELECT`，实测量级 <50ms（T6 记录），不进关键路径。
- 若种子文件缺失/损坏：`load_seed` 已按既有约定抛 `VALIDATION_ERROR` 中文 400（不 500）——启动期同一异常向上冒泡，行为与 r6 一致。

### 2.4 `question_attempts` 的取舍说明（AC-16 要求）

**为什么加列不建新表**：
1. 熟练度是**跨题型统一账本**（r6 口径：30 天内答对 ≥2 且最近一次正确）。练习若写另一张表，`proficiency.evaluate()` 必须同时读两表 → 改判定实现 → 违反 AC-11「公式与阈值零改动」。
2. 练习与笔试对「做过/错过」应有同一事实源（AC-9 明确「笔试做过的题也算做过」）。分表会让 `unseen` 需要跨表 UNION，口径两处。
3. 会话统计（本次 x/N、正确 n）刷新即重置（AC-18 允许），属前端态；真需要持久化时再加表，不影响本轮形状。

**为什么 `source` 列而不是靠 `run_id` 前缀判断**：`run_id` 是自由文本（面试卷也叫 run），前缀匹配是隐式约定、容易写错；显式列可被 SQL 索引与统计直接使用，同时保留 `practice:<session>` 的可读性。**读侧一律以列为准**（`source`），前缀只作命名空间隔离。

**幂等语义**：同一会话同一题只记一条（`UNIQUE(question_id, run_id)`，练习提交重复 → `insert_attempts` 返回 0 且不抛异常）；跨会话重练是同题不同 `run_id` → 记新事件（这正是「重练答对即移出错题本」需要的）。

### 2.5 字段 / 闭集单一出处清单（AC-1、AC-12 的门禁对象）

| 概念 | 唯一出处 | 镜像 / 消费方 | 门禁 |
|---|---|---|---|
| `language` 闭集 | `rules.LANGUAGES` | `schemas.QuestionLanguage`、`types.ts` `QuestionLanguage`、`PracticeLanguageFilter` | `test_r11_language_closed_set_single_source` |
| 语言→方向归属 | `rules.LANGUAGE_DIRECTION`（由 `FRONTEND_LANGUAGES` / `BACKEND_LANGUAGES` 派生） | `rules.direction_of_language()`、回填算法、QA 报告 | `test_r11_language_direction_single_source` |
| `kind` 闭集（含 `judge`） | `schemas.ExamKind` ← `rules.QUESTION_KINDS` | `types.ts` `ExamQuestion['kind']`、`KIND_LABEL` | 既有 `test_closed_sets_single_source` + 本轮追加 judge 断言 |
| 客观题闭集 | `rules.OBJECTIVE_KINDS` | `rules.is_objective_kind()`、`grade_objective`、练习池 | `test_r11_single_grading_function` |
| 练习 scope / limit 闭集 | `rules.PRACTICE_SCOPES` / `rules.PRACTICE_LIMITS` | `schemas.PracticeScope/PracticeLimit`、`types.ts` | `test_r11_practice_closed_sets` |
| 熟练度阈值 | `config.Settings`（30 天 / ≥2 次） | `proficiency.evaluate()` | 既有 `test_proficiency_thresholds_only_from_config`（零改动） |
| 组卷结构闸门 | `rules.MIN_EXAM_*` / `PAPER_STAGES` | `exam_selector` | 既有 `test_single_usable_and_structure_gate`（零改动） |

### 2.6 `rules.py` 追加（本轮新增常量与函数，逐字照抄）

```python
LANGUAGES: tuple[str, ...] = ("", "python", "java", "go", "html", "css", "js", "ts", "vue3", "react")
FRONTEND_LANGUAGES: tuple[str, ...] = ("html", "css", "js", "ts", "vue3", "react")
BACKEND_LANGUAGES: tuple[str, ...] = ("python", "java", "go")
LANGUAGE_DIRECTION: dict[str, str] = {
    **{lang: "前端" for lang in FRONTEND_LANGUAGES},
    **{lang: "后端" for lang in BACKEND_LANGUAGES},
}
FILTER_ANY: str = "all"                        # 筛选「全部」的唯一字面量
PRACTICE_SCOPES: tuple[str, ...] = ("all", "unseen", "wrong")
PRACTICE_LIMITS: tuple[int, ...] = (10, 20, 0)  # 0 = 全部
DEFAULT_PRACTICE_LIMIT: int = 10
OBJECTIVE_KINDS: tuple[str, ...] = ("single", "multiple", "judge")   # r11 扩 judge
EXAM_EXCLUDED_KINDS: tuple[str, ...] = ()       # 降级开关，默认空 = 判断题进制（见 §4.4）

def languages_for_direction(direction: str) -> tuple[str, ...]: ...
def direction_of_language(language: str) -> str | None: ...          # 空串/未知 → None
def is_language_allowed(language: str, direction: str) -> bool: ...   # 空串恒 True
def is_exam_objective_kind(kind: str) -> bool: ...                    # 组卷侧口径（= 客观题 − EXAM_EXCLUDED_KINDS）
```

方向查表统一用 `DIRECTIONS` 常量取值，不在 `rules.py` 之外再写字面方向（既有 `test_direction_literals_not_duplicated` 约束范围内）。

---

## 3. 题库数据（180 新题 + 存量 80 题回填）

### 3.1 新题规格（AC-3，逐条可断言）

`backend/app/seed/questions.json` 由 80 行扩到 ≥260 行；新题 id 前缀按语言命名，避免与既有 `fe-/be-/al-/cs-` 冲突：

| language | id 前缀 | 方向 | 题量 | basic | intermediate | challenge | single | multiple | judge | must_know | 含代码块 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| python | `py-q1..20` | 后端 | 20 | 10–13 | 5–8 | 2–4 | ≥12 | ≥3 | ≥3 | ≥6 | ≥2 |
| java | `java-q1..20` | 后端 | 20 | 同上 | | | | | | | |
| go | `go-q1..20` | 后端 | 20 | | | | | | | | |
| html | `html-q1..20` | 前端 | 20 | | | | | | | | |
| css | `css-q1..20` | 前端 | 20 | | | | | | | | |
| js | `js-q1..20` | 前端 | 20 | | | | | | | | |
| ts | `ts-q1..20` | 前端 | 20 | | | | | | | | |
| vue3 | `vue3-q1..20` | 前端 | 20 | | | | | | | | |
| react | `react-q1..20` | 前端 | 20 | | | | | | | | |

- 新增题**只用** `single / multiple / judge`，不得出现 `text`；全库不得出现 `blank`（闭集本身不含）。
- 内容口径：语言核心（语法/语义/陷阱/标准库/构建工具）为主，框架题每语言 ≤5 道；难度以 basic 为主（与「补基础」定位一致）。
- 含代码块：题面用三反引号围栏（```lang）；前端统一渲染（§6.5），解析里若引用代码亦同法。
- `algorithm`（`算法与数据结构`）/ `计算机基础` 两个方向维持既有的各 20 道、`language` 恒 `""`。
- 文件格式：`json`、UTF-8、`ensure_ascii=False`、缩进 2、键序与既有行一致（`id, direction, kind, difficulty, essentiality, language, prompt, options, answer, explanation`）——键序固定是 AC-2「两次运行字节相等」的前提。

### 3.2 存量 80 题的确定性回填（AC-2，算法而非手感）

新增模块 `backend/app/services/question_backfill.py`（纯函数、无 DB、无网络；运行时不调用）：

```python
BACKFILL_KEYWORDS: dict[str, tuple[str, ...]]                        # 每语言关键词，长词在前
def ordered_keywords(languages: Sequence[str]) -> list[tuple[str, str]]   # (keyword, language)，全局长词优先
def infer_language(direction: str, text: str) -> str                 # 五步算法 → language
def backfill_seed(questions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]
```

**算法五步**（顺序即语义）：

1. **方向预判**：`direction ∈ {"算法与数据结构", "计算机基础"}` → 恒返回 `""`（不看关键词）。
2. **候选集约束**：候选 language = `rules.languages_for_direction(direction)`；前端方向只看 6 个前端语言、后端方向只看 3 个后端语言。
3. **长词优先**：把所有候选语言的 `(keyword, language)` 对按 `(-len(keyword), LANGUAGES.index(language), keyword)` 全序排序（稳定、可复现），依次尝试。
4. **边界安全匹配**：文本 = `prompt + " " + 各选项 text`，小写化；纯 ASCII 字母关键词要求 `\b` 词边界（否则 `go` 会命中 `algorithm` / `django`，`js` 会命中 `json`），中文关键词按子串匹配。
5. **命中即停**：第一个命中项若不属于候选集（方向不符，例如前端方向命中 `python`）→ **丢弃并继续**下一个关键词；全部不命中 → 返回 `""`（留空，绝不硬凑）。

**回填关键词表**（首轮基线，命中数不足时只允许「加长词/加专有名词」，不允许改算法）：

| language | 关键词（长 → 短） |
|---|---|
| python | `列表推导`, `装饰器`, `生成器`, `上下文管理器`, `python`, `gil`, `pandas`, `django`, `flask` |
| java | `垃圾回收策略`, `线程池`, `spring boot`, `java`, `jvm`, `gc`, `spring`, `jdk`, `泛型` |
| go | `goroutine`, `channel`, `defer`, `interface{}`, `go 语言`, `go语言`, `golang`, `slice` |
| ts | `typescript`, `interface `, `类型体操`, `类型收窄`, `泛型`, `tsconfig`, `as const`, `枚举` |
| js | `javascript`, `event loop`, `事件循环`, `闭包`, `原型链`, `promise`, `微任务`, `async`, `await` |
| css | `盒模型`, `选择器权重`, `层叠上下文`, `css`, `flex`, `grid`, `z-index`, `position`, `浮动` |
| html | `语义化`, `html`, `dom`, `<div`, `表单`, `无障碍`, `href`, `alt`, `标签` |
| vue3 | `vue 3`, `vue3`, `组合式 api`, `响应式原理`, `vuex`, `pinia`, `vue-router`, `vue` |
| react | `usestate`, `useeffect`, `react`, `jsx`, `tsx`, `redux`, `hooks`, `虚拟 dom` |

**反例（必须被表驱动用例钉住）**：

| 输入（direction / 文本片段） | 期望 | 理由 |
|---|---|---|
| 前端 / 「Python 的列表推导与 JS 的 map 有何区别」 | `""` 或 `js`（取首个合法候选） | 命中 `列表推导` → 方向不符 → **丢弃继续**；若随后命中 `js` 则 `js`，否则留空。这就是「前端方向关键词命中 python 必须被方向约束拦下」的反例 |
| 后端 / 「Go 的 goroutine 与线程区别」 | `go` | 长词优先：`goroutine` 先于 `go 语言`/`golang` |
| 后端 / 「算法复杂度中 O(log n) 的 go 步骤」 | `""` 或合法候选 | `go` 必须靠 `\b` 边界，不得命中 `algorithm` |
| 算法与数据结构 / 「Python 实现快速排序」 | `""` | 第 1 步恒留空，即使文本含语言名 |
| 前端 / 「CSS 选择器权重如何计算」 | `css` | 长词 `选择器权重` 命中 |
| 计算机基础 / 「TCP 三次握手」 | `""` | 第 1 步恒留空 |

**为什么 `language` 一旦生成就禁止手改**：AC-2 的验收方式是「同一份种子跑两次结果字节相等」——若有人手改某题语言，重跑算法就会产生 diff。想改语言，只允许改关键词表或改写题面文本，然后整份重跑。

**一次性落地方式**（脚本落 `logs/teamflow/<runId>/scripts/`，不提交）：

```bash
cd backend && python -c "
import json, pathlib
from app.services.question_backfill import backfill_seed
p = pathlib.Path('app/seed/questions.json')
rows = json.loads(p.read_text(encoding='utf-8'))
out, hits = backfill_seed(rows)
p.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(hits)   # {语言: 命中数}，附「留空数」
"
```

两次运行后 `sha256sum backend/app/seed/questions.json` 必须相等（AC-2 实跑证据）。`explanation` 是内容工作（人写），不由算法生成，故不参与字节相等比较的位置（同位置、同键序，值稳定即可）。

### 3.3 质量校验器（AC-4 八条，一键可跑）

新增 `backend/tests/test_question_bank_quality.py`，全部断言**同时**跑在「种子 JSON」与「导入后的库」两处：

| # | 断言 | 实现要点 |
|---|---|---|
| ① | `single` answer 恰 1、`multiple` ≥2、`judge` options 恰 2 且 answer 恰 1 且 ∈ options | 结构遍历 |
| ② | 客观题 `answer ⊆ options[].key` | 集合包含 |
| ③ | 选项 2–6 个、key 唯一且 ∈ A–F | 正序枚举 |
| ④ | `explanation` 去空白后 ≥10 字符（全库 260 题） | `len(re.sub(r"\s+","",exp))` |
| ⑤ | 同语言内归一化题干（去空白/全半角/标点）重复数为 0 | `unicodedata.normalize("NFKC", …)` + 去标点后 set |
| ⑥ | §3.1 分布闸门（每语言 ==20、难度/题型/必备度配额、代码块 ≥2） | 计数器 |
| ⑦ | `question_bank.load_questions()` 可用题数 == `repository.count_questions()`（坏行 0） | 两侧计数相等 |
| ⑧ | `kind` 闭集不含 `blank`；新增语言题无 `text` | 闭集断言 |

---

## 4. 判断题落地口径（AC-6）

### 4.1 书写规范（正反例齐全）

**规范**：题面必须是**限定条件明确的陈述句**，只含一个真值，可被「正确 / 错误」二选一无歧义判定；不得含「可能 / 通常 / 一般 / 有时 / 大部分」等模糊限定，不得依赖未给出的代码或上下文。

| 类型 | 例子 | 判定 |
|---|---|---|
| ✅ 正例 | 「在 JavaScript 中，用 `const` 声明的对象，其属性仍然可以被重新赋值。」 | 限定语言与具体语义，真值唯一（正确） |
| ✅ 正例 | 「Go 的 `defer` 语句注册的调用，在包含它的函数返回时按后进先出顺序执行。」 | 限定语义，真值唯一（正确） |
| ❌ 反例 1（两可） | 「闭包通常会造成内存泄漏。」 | 「通常」两可，改成限定条件或换题 |
| ❌ 反例 2（缺前提） | 「这段代码的输出是 3。」 | 没给代码，不可判定 |
| ❌ 反例 3（以偏概全） | 「Python 的 GIL 让多线程完全无用。」 | 绝对化表述，工程上可反驳，不达标 |
| ❌ 反例 4（选项歧义） | 选项写成「对 / 错 / 不确定」三个 | `judge` 恰 2 个选项，违反 AC-4 ① |

**选项固定文案**：`[{"key":"A","text":"正确"},{"key":"B","text":"错误"}]`，`answer` 恰为 `["A"]` 或 `["B"]`（PRD §11 末条：不用 ✓/✗ 图形字符，纯文字对读屏友好）。

### 4.2 存储与渲染路径（零新控件）

- 存储：`kind="judge"`，`options` 恰 2，`answer` 恰 1 —— 与单选同形。
- 渲染：`ExamQuestionCard` 的 `kind === 'multiple' ? checkbox : radio` 分支把 `judge` 落到 **radio**，选项键 `A/B` 显示「正确/错误」；`KIND_LABEL` 追加 `judge: '判断'`（纯文案）。
- 判分：`grade_objective(question, answer)`（`exam.py:161`）集合相等 —— `["A"] == ["A"]` 即正确，多选题的「少选/多选算错」语义对判断题退化成正好的单值匹配。
- **不新增**：控件分支、判分分支、归一化函数、`case_sensitive` 类字段（本版无填空）。

### 4.3 「全库只有一个客观题判分函数」（静态断言）

`test_r11_single_grading_function`（追加进 `tests/test_engineering_gates.py`）：
1. `backend/app/**/*.py` 里 `def grade_` 开头的函数**恰好 1 个**，且名为 `grade_objective`；
2. 除 `exam.py` 外，源码中不得出现「`expected == given` / `set(answer) == set(correct)`」这类第二套比较实现（AST 扫描 `ast.Compare` 右值为 `set(...)` 的 `Eq` 形态，白名单 `exam.py` + `proficiency.py`（后者不比较答案））；
3. `backend/app/**` 中 `"blank"` 字面量出现次数为 0；
4. `rules.is_objective_kind("judge") is True` 且 `rules.OBJECTIVE_KINDS == ("single","multiple","judge")`。

### 4.4 进笔试卷面的降级开关（闸门保留，默认不触发）

```python
# rules.py
EXAM_EXCLUDED_KINDS: tuple[str, ...] = ()   # 若实施发现 ExamPage 必须改 kind 分支 → 置 ("judge",)

def is_exam_objective_kind(kind: str) -> bool:
    """组卷侧客观题口径 = 客观题闭集 − EXAM_EXCLUDED_KINDS（默认空，等价 is_objective_kind）。"""
    return is_objective_kind(kind) and kind not in EXAM_EXCLUDED_KINDS
```

`exam_selector.py` 的**两处**客观题判定（`:271` 与 `:172` 的计数）改用 `is_exam_objective_kind`；`build_paper` 的阶梯与结构闸门**一行不改**。默认 `()` 下行为与现状逐字等价（单测：`is_exam_objective_kind(k) == is_objective_kind(k)` 对所有 kind 成立）。
降级路径因此是**数据级一行常量**，不需要写第二套判分、不需要改 `ExamPage`。`question_bank._usable()` 仍用 `is_objective_kind`（判断题必须可用，练习要用）。

---

## 5. API 设计（4 端点）

### 5.1 通用口径

- 参数闭集统一用字面量 `"all"` 表示「全部」；**`language` 例外**：`""` 是闭集成员（通用/算法），因此「全部」用 `"all"`，`""` 专指通用题（前端永远显式传值）。此不对称在契约门禁里显式断言，避免误读。
- 参数非法（越出闭集）→ FastAPI `RequestValidationError` → 既有 envelope `VALIDATION_ERROR`（422）。**不手写第二套校验文案**。
- 筛选 0 命中 → `200` + 空数组 + 中文 `notice`（AC-12：空结果不是错误）。
- 响应中**永不含** `answer`（纸卷/题单）与任何 Key；`explanation` 只出现在判分响应。
- 全部端点纯本地（零 AI）：不 import `services.ai`、不读 `AI_API_KEY`。

### 5.2 `POST /api/practice/paper`（题单）

请求体 `PracticePaperRequest`：

```json
{ "language": "all", "direction": "all", "difficulty": "all",
  "essentiality": "all", "scope": "all", "limit": 10 }
```

字段：`language: PracticeLanguageFilter = "all"`、`direction: PracticeDirectionFilter = "all"`、`difficulty: PracticeDifficultyFilter = "all"`、`essentiality: PracticeEssentialityFilter = "all"`、`scope: PracticeScope = "all"`、`limit: PracticeLimit = 10`（`Literal[10,20,0]`）。

响应 `PracticePaper`：

```json
{ "session_id": "ps_9f3c1a",
  "questions": [
    { "id": "js-q7", "kind": "judge", "language": "js", "direction": "前端",
      "difficulty": "basic", "essentiality": "must_know",
      "prompt": "在 JavaScript 中，`const` 声明的对象其属性仍可被修改。",
      "options": [{"key":"A","text":"正确"},{"key":"B","text":"错误"}] }
  ],
  "hit_count": 37,
  "notice": "" }
```

- `session_id`：服务端生成 `"ps_" + uuid4().hex[:8]`；作答事件写 `run_id = "practice:" + session_id`。
- `hit_count`：**全部筛选后命中总数**（不受 `limit` 截断），前端「当前组合命中 N 题」直接用它。
- `notice` 五态（中文，逐字）：
  | 场景 | notice |
  |---|---|
  | 命中 ≥ limit 或无截断 | `""` |
  | 命中 0 | `该组合下没有题目，试试放宽难度或必备度` |
  | 0 < 命中 < limit | `该组合下只有 N 道，已全部给出` |
  | 题库不可用（种子缺失/库空） | `题库未就绪，请稍后重试` |
- 排序与取样：候选按 `(难度档 rank, language, id)` 稳定排序后用 `random.sample` 取 `min(limit, len)`（`limit=0` 取全部）；**题单内题 id 唯一**（sampling 天然去重，AC-8「同一会话内不重复出现」）。
- 练习题池 = `question_bank.practice_pool()`（= `load_questions()` 过滤 `is_objective_kind`），存量 12 道 `text` 永不进入。

### 5.3 `POST /api/practice/answer`（单题判分 + 落库）

请求 `PracticeAnswerRequest`：

```json
{ "session_id": "ps_9f3c1a", "question_id": "js-q7", "answer": ["A"] }
```

响应 `PracticeAnswerResult`：

```json
{ "question_id": "js-q7", "correct": true, "correct_answer": ["A"],
  "explanation": "`const` 只锁定绑定的引用，对象属性可修改。因此该陈述正确。" }
```

规则：
1. `answer` 为空 / `null` / 空数组 → `VALIDATION_ERROR` 400「先选一个答案，再提交」（服务端兜底；前端同时阻止）。
2. 题目不存在或不可用 → `NOT_FOUND` 404「题目不存在或已下线」。
3. `kind` 非客观题（`text`）→ `VALIDATION_ERROR` 400「该题不支持练习判分」。
4. 判分只调 `exam.grade_objective()`；写入 `question_attempts`（`source="practice"`，`run_id="practice:<session>"`，`answered_at` UTC ISO8601）；同会话同题重复提交 → 事件不重复写（`UNIQUE` 兜底），**响应仍照常返回判分结果**（前端重试友好）。
5. `correct_answer` 取库里 `answer` 原样回显（`list[str]`）；`explanation` 恒 `str`（空串也返回，前端显示「本题暂无解析」降级文案）。

### 5.4 `GET /api/practice/stats`（统计）

查询串：`?language=all&direction=all&difficulty=all&essentiality=all&scope=all`

响应 `PracticeStats`：

```json
{ "total": 260, "practiced": 42, "wrong_total": 3, "hit": 37 }
```

- `total`：可用练习题总数（全库，不带筛选）。
- `practiced`：有**任何**作答事件的题数（`COUNT(DISTINCT question_id)`，练习 + 笔试都算，供 AC-18 的 m）。
- `wrong_total`：全库错题数（最近一次作答错误，不带筛选）。
- `hit`：当前筛选（含 scope）命中数，与 `/paper` 的 `hit_count` 同源同值。

### 5.5 `GET /api/practice/wrong-book`（错题本）

查询串：`?language=all`

响应 `PracticeWrongBook`：

```json
{ "items": [
    { "question_id": "css-q4", "prompt": "下列哪一项…", "language": "css",
      "direction": "前端", "difficulty": "basic",
      "last_wrong_at": "2026-11-01T12:30:00Z", "wrong_count": 2 } ],
  "total": 1 }
```

- 成员判定：该题**最近一次作答为错误**（跨 exam/practice，共用一张表）。
- 排序：`last_wrong_at` 倒序，同刻按 `question_id` 升序（确定性，测试可断言）。
- 只列当前仍可用且为客观题的题（题被下线则静默跳过）。
- `language` 过滤：`"all"` = 不筛；其余按精确值。
- 空 → `200` + `items: []`（前端中文空态）。

### 5.6 错误矩阵（全站闭集，零新增码）

| 场景 | 状态 | code | message（中文，逐字） |
|---|---|---|---|
| 参数越出闭集 / limit 非 10·20·0 | 422 | `VALIDATION_ERROR` | 请求参数不合法，请检查后重试（既有全局处理器） |
| 未作答提交 | 400 | `VALIDATION_ERROR` | 先选一个答案，再提交 |
| 非客观题判分 | 400 | `VALIDATION_ERROR` | 该题不支持练习判分 |
| 题目不存在 | 404 | `NOT_FOUND` | 题目不存在或已下线 |
| 筛选无结果 | 200 | — | 空数组 + `notice` |
| 未预期异常 | 500 | `HTTP_ERROR` | 既有全局处理器 |

### 5.7 契约镜像（`schemas.py` ↔ `types.ts`，逐字）

新增/改动（两侧字段名、可空性、闭集取值逐字对齐）：

| Python | TypeScript |
|---|---|
| `QuestionLanguage = Literal["", "python","java","go","html","css","js","ts","vue3","react"]` | `export type QuestionLanguage = '' \| 'python' \| ... \| 'react'` |
| `ExamKind = Literal["single","multiple","judge","text"]` | `ExamQuestion['kind'] = 'single' \| 'multiple' \| 'judge' \| 'text'` |
| `PracticeScope = Literal["all","unseen","wrong"]` | `export type PracticeScope = 'all' \| 'unseen' \| 'wrong'` |
| `PracticeLimit = Literal[10,20,0]` | `export type PracticeLimit = 10 \| 20 \| 0` |
| `PracticeLanguageFilter = Literal["all", *QuestionLanguage]` | `export type PracticeLanguageFilter = 'all' \| QuestionLanguage` |
| `PracticePaperRequest / PracticeQuestion / PracticePaper / PracticeAnswerRequest / PracticeAnswerResult / PracticeStats / PracticeWrongItem / PracticeWrongBook` | 同名 interface，字段逐个一致 |

`ExamPage` 相关契约**不改**：`ExamQuestion` 不新增 `language`/`explanation`（笔试零行为变化）。

---

## 6. 前端页面与组件

### 6.1 路由与导航（只改 `App.tsx` 两处）

- `<Route path="/practice" element={<PracticePage />} />`
- `TOOL_ITEMS` 首位插入 `{ key: 'practice', label: '练习', to: '/practice' }` → 工具组顺序 = 练习 / 成绩趋势 / 简历润色。**不进 5 步主线**（不用 `flow` 状态驱动 `isDone`）。`ToolNav` / `Stepper` 不改。

### 6.2 页面状态机（`PracticePage` 内部 `useState`，无新全局 store）

```ts
type View = 'setup' | 'running' | 'done'
type Tab = 'practice' | 'wrong'
type Load = 'idle' | 'loading' | 'ready' | 'error'
// 持有：tab / view / filters / paper(PracticePaper|null) / index / answers / feedback Pending / selected / stats / wrongBook
```

- `setup`：筛选 + 命中行（`stats.hit`）+ 开始。
- `running`：题卡（共享 `ExamQuestionCard`）+ 进度行 + 提交/下一题。
- `done`：完成态（正确率 + 三出口）。
- `error`：题单加载失败 → `InlineError`（中文原因 + 重试，按 r2 约定失败不得只用 Toast）；判分失败 → 同卡内 `InlineError`，**保留已选**（不清空 `selected`）。
- 刷新即回 `setup`（AC-18 允许本次统计重置）。

### 6.3 组件切分与 props（与 DESIGN §4 一致）

| 文件 | 责任 | props |
|---|---|---|
| `pages/PracticePage.tsx` | 页面壳 + 状态机 + 唯一出网点（经 `api`） | — |
| `components/practice/PracticeFilters.tsx` | 5 组筛选 chip + 命中行 + 开始按钮；纯展示 + 回调 | `{ filters, onChange(patch), hitCount, hitLoading, globalStats, onStart, startLoading }` |
| `components/practice/PracticeProgress.tsx` | 本次进度行 + `.sc-qa-track`（`role="progressbar"`） | `{ index, total, correct, answered }` |
| `components/practice/Explanation.tsx` | 解析折叠块（默认展开，`aria-expanded`/`aria-controls`） | `{ text, defaultOpen?: boolean }` |
| `components/practice/PracticeSummary.tsx` | 完成态（正确率大数 + 三出口） | `{ total, correct, wrongCount, filtersLabel, onWrongBook, onAgain, onReset }` |
| `components/practice/WrongBookList.tsx` | 错题行 + 展开 + 语言过滤 + 列表级重练 | `{ items, expandedId, onToggle, onRetrain, onFilterLanguage }` |
| `components/exam/ExamQuestionCard.tsx` | **三处改动**：① `KIND_LABEL` 增 `judge: '判断'`；② 可选 `footer?: ReactNode`（选项组之后、`Card` 之内）；③ 题面渲染改用 `parsePromptBlocks()`（§6.5，无围栏题面输出与现状逐字相同）。**零 kind 分支新增** | 既有 + `footer?` |
| `components/polish/SegTabs.tsx` | 新增可选 `ariaLabel?: string`（默认取现有文案，零回归） | 既有 + `ariaLabel?` |
| `lib/practice.ts` | 中文展示映射单一出处 + 纯逻辑（筛选 chip 列表、正确率文案、错题时间格式化、0 命中放宽建议） | — |
| `lib/promptCode.ts` | 题面围栏代码块解析（纯函数，练习页与题卡共用） | — |

筛选 chip 用**原生 `<button className="sc-chip sc-qa-chip" aria-pressed>`**（不改共享 `Chip.tsx`）：选中态由 `base.css` 新增段 `.sc-qa-chip[aria-pressed='true']` 染色，文字带「✓」。

### 6.4 样式（append-only）

- `styles/tokens.css` 末尾追加 r11 段 **5 个 token**（值已在 DESIGN §0.7 逐条核算，此处只列名）：`--qa-col-w`、`--qa-track-h`、`--qa-code-max-h`、`--qa-row-min-h`、`--qa-label-w`。
- `styles/base.css` 末尾追加 `.sc-qa-*` 段（DESIGN §4 的类表逐条落地）。**既有声明 0 修改**——`test_style_baseline_append_only` 会用 `git diff` 检查「不允许出现删除/修改行」。
- 全部颜色/尺寸取 token，0 裸色值（`test_no_raw_colors_outside_tokens` 覆盖 `styles/*.css` 之外的组件内联样式）。

### 6.5 题面代码块渲染（`lib/promptCode.ts`，双向一致）

```ts
export type PromptBlock = { type: 'text'; content: string } | { type: 'code'; content: string; lang: string }
export function parsePromptBlocks(prompt: string): PromptBlock[]
```

- 解析 ```` ```lang … ``` ```` 围栏（容忍 `\r\n`、语言标注缺省）；无围栏 → 返回**单个 text 块**，`ExamQuestionCard` 渲染仍走既有 `<p className="sc-qcard-prompt">{prompt}</p>`（**逐字同现状，零回归**）。
- 有围栏 → text 段用 `<p>`、code 段用 `<pre className="sc-qa-code">`（`.sc-qa-code` 内部 `overflow:auto`，AC-17 的「代码块内滚、页面不横滚」靠它实现）。
- 为什么改共享题卡：新题含代码块（AC-3 每语言 ≥2）；若只练习页渲染，判断题/客观题进笔试卷会显示裸围栏，观感断裂。改动只影响「含围栏的题面」，既有 80 题全部无围栏 → 笔试观感 0 变化。

### 6.6 文案映射（单一出处 = `lib/practice.ts`）

`LANGUAGE_LABEL`（`""`→通用、`js`→JavaScript、`vue3`→Vue 3 …）、`KIND_LABEL`（`judge`→判断）、`DIFFICULTY_LABEL`、`ESSENTIALITY_LABEL`、`SCOPE_LABEL`、`limitLabel(limit)`；空态/错误文案常量与 DESIGN §2.6 逐字一致（组件不写字面文案）。

---

## 7. 关键实现点与边界（B 系列，逐条可测）

| # | 点 | 实现要求 | 断言位置 |
|---|---|---|---|
| B-1 | `unseen` 口径 | 该题在 `question_attempts` **无任何事件**（练习 + 笔试同一张表，笔试做过也算做过） | `test_r11_practice_service.py::test_scope_unseen_means_no_attempt` |
| B-2 | `wrong` 口径 | 该题**最近一次作答为错误**（`answered_at` 最大者 `correct=0`）；答对即移出 | 同文件 `test_scope_wrong_is_last_attempt` / `test_wrong_book_removed_after_correct` |
| B-3 | 三口径互斥可叠加 | `all/unseen/wrong` 三选一，可与其他筛选叠加；`unseen ∩ wrong = ∅` | `test_scopes_are_disjoint_and_stackable` |
| B-4 | 命中 100% 合规 | 返回的每道题逐字段满足全部筛选（`language/direction/difficulty/essentiality` + scope） | `test_paper_rows_match_all_filters` |
| B-5 | limit 语义 | `10`/`20` → `min(limit, hit)` 条；`0` → 全部 `hit` 条 | `test_paper_limit_10_20_all` |
| B-6 | 题单去重 | 一次 `paper` 内题 id 唯一 | `test_paper_questions_unique` |
| B-7 | 会话命名空间 | 事件 `run_id = "practice:" + session_id`、`source="practice"`；`UNIQUE` 保证同会话同题一条 | `test_answer_writes_attempt_with_source` |
| B-8 | 熟练度零改动 | `proficiency.evaluate()` / `config` 阈值 / `exam_selector` 阶梯**零 diff**；练习事件按原阈值参与判定 | `test_practice_attempts_count_as_proficiency`（构造 2 次答对 + 最近正确 → 笔试卷过滤该题且 `filtered_count` 增加） |
| B-9 | 全库熟练仍出卷 | 构造「全库熟练（含练习事件）」→ `/api/exams` 仍 200，题数 10–12、客观 ≥8、挑战 ≤20%（r6 结构闸门不回退） | `test_exam_still_ok_when_all_proficient` |
| B-10 | `text` 不进练习池 | 存量 12 道 `text` 恒不出现在 paper；`kind` 非客观题判分 400 | `test_text_questions_never_in_practice` |
| B-11 | 零 AI / 无 Key 可用 | 练习全链路不 import `services.ai`、不读 Key；`AI_API_KEY=` 下四端点全 200 | `test_r11_practice_api.py::test_no_ai_without_key` + `ai.py` import 静态断言 |
| B-12 | 时延 | 单题判分 P95 ≤50ms、260 题题单首屏 ≤300ms（本机 3 次取样，脚本记录） | `logs/teamflow/<runId>/scripts/check_r11_perf.py`（自检，不提交） |
| B-13 | SQL 边界 | 新 SQL 只在 `repository.py`；`db.py` 只放 DDL/补列；路由零 SQL；闭集只在 `rules.py` | 既有 `test_sql_only_through_repository` / `test_ddl_lives_only_in_db_module` 自动覆盖 |
| B-14 | 0 命中不是错误 | 四端点空结果一律 `200` + 空数组 + 中文 `notice` / 空态 | `test_empty_result_is_200` |
| B-15 | 未作答 | 前端：不禁止按钮，点提交给红字「先选一个答案，再提交」并移焦点；服务端：400 兜底 | `test_answer_requires_selection` + 前端行为（vitest 纯逻辑 + 手工实跑） |
| B-16 | 提交失败保留已选 | `selected` 与 `paper` 不被清空；`InlineError` 在题卡内，重试沿用同一选择 | 手工实跑 + 组件结构断言（截图/证据落 QA 报告） |

---

## 8. 测试策略

### 8.1 后端新增测试（6 文件）

| 文件 | 归属任务 | 用例（约） |
|---|---|---|
| `tests/test_r11_data_layer.py` | T1 | 8：补列幂等（跑两遍 `init_db`）、新列默认空串、`insert_question` 写新列、`fill_empty_question_columns` 只填空/不覆盖/二次 0、`source` 默认 `exam`、`count_practiced_questions` 去重、重复导入 0 新增、`list_questions` 带新列 |
| `tests/test_r11_contract.py` | T2 | 6：`LANGUAGES` ↔ `QuestionLanguage` 逐字、`LANGUAGE_DIRECTION` 与方向闭集自洽、`ExamKind` 含 `judge`、`PRACTICE_SCOPES/LIMITS` ↔ schemas、`types.ts` 文本镜像（读文件比对联合类型）+ 「`""` 只在 language 闭集出现一次」 |
| `tests/test_question_backfill.py` | T3 | ≥10 表驱动：§3.2 反例全表 + 每个语言 1 条正例 + 两次运行结果相等 + 算法/基础恒空 + 空文本留空 |
| `tests/test_question_bank_quality.py` | T3 | 8（AC-4 ①②③④⑤⑥⑦⑧） |
| `tests/test_r11_practice_service.py` | T4 | 14：B-1..B-10 的 service 级断言（含熟练度回归、全库熟练出卷） |
| `tests/test_r11_practice_api.py` | T4 | 12：四端点 200/422/404/400、空结果 200、`hit_count == hit`、`notice` 四态中文、无 Key 200、响应不含 `answer` |

### 8.2 前端新增测试（2 文件，纯逻辑，不引依赖）

| 文件 | 用例（≥18） |
|---|---|
| `src/test/practice.test.ts` | 语言/题型/难度/必备度/范围/题量映射全覆盖（11+1 语言、`judge`、`text` 不出现）、`accuracyText`（0/0、3/10、10/10）、`formatWrongTime`（ISO→`MM-dd HH:mm`、非法串回退原串）、`relaxSuggestions`（0 命中的三条建议）、`filtersLabel` |
| `src/test/promptCode.test.ts` | 无围栏 → 单 text 块且内容逐字相等；单围栏 → [text, code]；多围栏；`\r\n`；未闭合围栏不抛错（整体当 text） |

### 8.3 门禁与数量（只增不减）

| 门禁 | 基线（本轮实跑） | 目标 |
|---|---|---|
| `python -m pytest -q` | 348 passed + 1 skipped | **≥368 passed**（本方案新增 ~42） |
| `npm test`（vitest） | 109 passed | **≥124 passed**（新增 ≥18） |
| `npm run typecheck` | 0 error | 0 error |
| `npm run lint` | 0 error / ≤28 warning | 0 error / ≤28 warning |
| `npm run build` | 通过 | 通过 |
| `GET /health` | 200 | 200 |
| `python -m ruff check app tests` | 环境受限（r10 已记录 `No module named ruff`） | 有则必绿；不可用则如实记录 |

### 8.4 实跑验证清单（`verifyScripts`）

```bash
# 后端全量
cd backend && python -m pytest -p no:cacheprovider -q
# 本轮新增用例
cd backend && python -m pytest -p no:cacheprovider tests/test_r11_data_layer.py tests/test_r11_contract.py tests/test_question_backfill.py tests/test_question_bank_quality.py tests/test_r11_practice_service.py tests/test_r11_practice_api.py -q
# 回填确定性（两次运行字节相等 → 0 差异）
cd backend && python -m app.services.question_backfill --check
# 题库规模与分布
cd backend && python -c "import json,collections;d=json.load(open('app/seed/questions.json',encoding='utf-8'));print(len(d),collections.Counter(q['language'] for q in d))"
# 单一判分函数
cd backend && grep -rn "def grade_" app/ 
cd backend && grep -rn '"blank"' app/ || echo NO_BLANK
# 无 Key 仍全绿（零 AI 证明）
cd backend && AI_API_KEY= python -m pytest -q -p no:cacheprovider
# 探活
cd backend && DB_PATH=tests/.tmp/qa-health-r11.db AI_API_KEY= python -m uvicorn app.main:app --port 8131   # 另开：curl -sS http://127.0.0.1:8131/health
# 前端四件
cd frontend && npm run typecheck && npm run lint && npm test && npm run build
# 样式基座 append-only + 无裸色值
cd backend && python -m pytest -p no:cacheprovider tests/test_engineering_gates.py -q
# 交付自检脚本（临时，不提交）
cd backend && python -X utf8 ../logs/teamflow/tf-mvxtymng-j6eln4/scripts/check_r11_delivery.py
# 状态
cd /d/work_space/code_learning && git status --porcelain=v1 -uall && git branch --show-current
```

> 已知环境噪声：`test_no_command_output_dumps_in_repo_root` 会因项目根出现 `.log/.txt/.tmp/_*` 文件而红（本轮曾偶发一次，重跑即绿）。收尾前确认项目根干净、本轮脚本一律落 `logs/teamflow/<runId>/scripts/`。

---

## 9. 任务拆分（6 任务 / 3 波次，按文件边界）

### 9.1 波次与文件所有权

**波次 1（三条并行，文件互不相交）**

| 任务 | files（改动） | reads | 交付与验收 |
|---|---|---|---|
| **T1 · 数据层与存量升级** | `backend/app/db.py`、`backend/app/repository.py`、`backend/tests/test_r11_data_layer.py` | `app/schemas.py` | §2.1/§2.2/§2.3 落地；`_ensure_r11_columns` 幂等、`fill_empty_question_columns` 只填空、`source` 列、`count_practiced_questions`；8 用例全绿 |
| **T2 · 闭集与契约** | `backend/app/services/rules.py`、`backend/app/schemas.py`、`frontend/src/api/types.ts`、`backend/tests/test_r11_contract.py` | `app/services/exam.py`（`grade_objective` 签名） | §2.6 常量与函数、§5.7 契约；`judge` 入闭集；`test_r11_contract.py` 6 用例绿；**先落地，供 T3/T4/T5 引用** |
| **T3 · 题库数据与回填** | `backend/app/seed/questions.json`、`backend/app/services/question_backfill.py`、`backend/app/services/question_bank.py`、`backend/tests/test_question_backfill.py`、`backend/tests/test_question_bank_quality.py` | `app/services/rules.py`（T2 的常量）、`app/repository.py` | 180 新题 + 存量 80 题 `explanation` 补齐 + 语言确定性回填；`ensure_seeded` 改口径；`load_seed` 兼容新键；两次运行字节相等；AC-4 八条全绿 |

**波次 2（两条并行，依赖波次 1 的规则与契约）**

| 任务 | files | reads | 交付与验收 |
|---|---|---|---|
| **T4 · 练习后端四端点** | `backend/app/services/practice.py`（新）、`backend/app/routers/practice.py`（新）、`backend/app/main.py`、`backend/tests/test_r11_practice_service.py`、`backend/tests/test_r11_practice_api.py` | `app/services/exam.py`、`app/services/question_bank.py`、`app/services/proficiency.py`、`app/repository.py`、`app/schemas.py` | §5 四端点、§7 B-1..B-11、B-14/B-15；`main.py` 注册 + `init_db/ensure_seeded` 顺序保持；14+12 用例绿 |
| **T5 · 练习前端页面** | `frontend/src/pages/PracticePage.tsx`（新）、`frontend/src/components/practice/*`（5 新）、`frontend/src/lib/practice.ts`（新）、`frontend/src/lib/promptCode.ts`（新）、`frontend/src/api/client.ts`、`frontend/src/App.tsx`、`frontend/src/components/exam/ExamQuestionCard.tsx`、`frontend/src/components/polish/SegTabs.tsx`、`frontend/src/styles/tokens.css`、`frontend/src/styles/base.css`、`frontend/src/test/practice.test.ts`（新）、`frontend/src/test/promptCode.test.ts`（新） | `src/api/types.ts`、`src/components/ui/*`、`src/lib/useAsync.ts`、`src/lib/format.ts`、`DESIGN.md` §4 | §6 全部；typecheck/lint/vitest/build 绿；0 裸色值；样式 append-only |

**波次 3（收口）**

| 任务 | files | reads | 交付与验收 |
|---|---|---|---|
| **T6 · 门禁扩展与交付自检** | `backend/tests/test_engineering_gates.py` | 全仓（只读）+ 每个任务的完成标记 | 追加 §4.3 / §2.5 门禁（语言闭集单一出处、镜像、单一判分函数、`EXAM_EXCLUDED_KINDS` 默认空、r11 touched paths 可解析、样式 append-only 通过、`judge` 在闭集）；跑完 §8.4 全部命令并把结论记录在**本轮对话/自检脚本输出**；发现缺陷**当场修**（改自己或就近任务的文件时须在报告里注明）；**不写** `QA-REPORT.md` / `ACCEPTANCE.md`，不跑跨浏览器矩阵 |

### 9.2 并行/串行理由

- T1 与 T2 文件不相交，但 T4/T5 需要 T2 的闭集常量与契约类型 → **T2 必须先于波次 2 完成**。
- T3 依赖 T2 的 `LANGUAGES`（生成题库时按闭集校验），但数据文件本身不 import 代码 → 可与 T2 并行启动，收尾前对齐。
- T4 与 T5 只经 HTTP 契约耦合（§5），文件不相交 → **真并行**；T5 可用固定样例 JSON 自测，不等 T4 起服务。
- T6 依赖全部；只读全仓 + 只改门禁文件。

### 9.3 git / 工程约束（PRD §9 原文，落到每个任务）

**每个任务开工即遵守（写进任务卡 spec）**：

1. 分支 `feat/dev-skill-coach` **原地继续**：不新建、不切换、不重命名。
2. **Agent 不提交**：不执行 `git commit` / `git add` / `git push`；验收后由流水线统一提交。
3. **不得清理工作区**：禁止 `git stash` / `git reset` / `git checkout -- .`；当前未提交改动（`M docs/teamflow/memory.md`、`?? .dsh/memory/`、`?? docs/teamflow/20261101-r11-practice-question-bank/`）必须原样保留并在其上叠加。
4. **`.gitignore` 审计**：实施前跑 `git check-ignore -v backend/app.db backend/tests/.tmp/ dist/ node_modules/ logs/teamflow/` 确认既有规则够用；本轮脚本落 `logs/teamflow/<runId>/scripts/`（已被 `logs/teamflow/` 挡住）；`backend/app/seed/questions.json` 是交付物**必须可提交**（确认未被忽略：`git check-ignore -v backend/app/seed/questions.json` 应无输出）。不制造无意义条目。
5. **零新运行时依赖**：两侧 `package.json` / `pyproject`/`requirements` 一律不动；题库离线。
6. **边界**：DDL 只 `db.py`、SQL 只 `repository.py`、闭集/闸门只 `rules.py`、题库读写只 `question_bank.py`、路由只做参数与错误映射、前端只经 `api/client.ts`、样式只用 tokens。
7. **文档落盘**：只写 `docs/teamflow/20261101-r11-practice-question-bank/`（本轮 TECHNICAL 已交付；QA/验收由后续阶段写）与 `docs/teamflow/memory.md` 的 r11 约定行；不写宿主 `docs/<role>/`、不落文件到项目根。

---

## 10. 风险与取舍

| 风险 | 处置 |
|---|---|
| 存量库（r10 卷）拿不到新题 | A2/A3：启动幂等导入 + 只补空列；AC-5 用「旧库启动 → 练习筛选 200 → 笔试出卷 200」实跑验收 |
| 启动期多 260 次 `INSERT DO NOTHING` | 实测 <50ms（T6 记录）；如成为瓶颈，后续按 `updated_at` 版本号跳过（本轮不做，避免过度设计） |
| 判断题陈述两可 → 用户按正确理解被判错 | §4.1 书写规范 + 反例表；AC-4 结构校验 + QA 每语言 ≥2 抽检；不达标**换题**而非改答案 |
| 练习高频作答把笔试卷候选池掏空 | 这是 PRD 选定的口径（练熟不考）；L1–L6 阶梯保证不断卷，B-9 用「全库熟练」极端用例钉住 |
| 判断题进笔试卷触碰 `ExamPage` | 已核实零改动（§1）；仍留 `EXAM_EXCLUDED_KINDS` 一行开关（§4.4），降级不改判分、不改页面 |
| 题面代码块在笔试页显裸围栏 | §6.5：共享题卡加 `parsePromptBlocks`，无围栏题面输出逐字同现状；vitest 钉住退化路径 |
| 260 题种子文件体量（~250KB） | 纯静态 JSON，导入一次性；不进请求路径；gzip 化由 nginx 既有配置负责（r10） |
| 判分时延 | 全本地字典/集合运算，无 IO 磁盘热路径；B-12 实测 P95 |
| 旧 `app.db` 里答案/题面被误覆盖 | `fill_empty_question_columns` 只碰空单元格 + `ON CONFLICT DO NOTHING`；单测断言「非空值不会被改写」 |

---

## 11. AC → 技术落点自检

| AC | 技术落点 |
|---|---|
| AC-1 | §2.5 单一出处表 + §2.6 常量 + `test_r11_language_closed_set_single_source` |
| AC-2 | §3.2 五步算法 + 关键词表 + 反例表 + 两次运行字节相等 |
| AC-3 | §3.1 规格表（id 前缀/配额/代码块） |
| AC-4 | §3.3 八条校验器 |
| AC-5 | §2.1 DDL + §2.2 补列路径 + §2.3 补空列 |
| AC-6 | §4 全节（规范/反例/单判分/静态断言/降级开关） |
| AC-7 | §5.2 + §6.1/§6.3（`/practice` 与工具组首位、四维 + scope + limit） |
| AC-8 | §5.3 + §6.2（逐题、未作答阻止、反馈 + 解析默认展开、完成态）、题单去重 B-6 |
| AC-9 | B-1/B-2/B-3 |
| AC-10 | §5.5 + `WrongBookList`；重练 = `POST /paper` 同筛选（`scope=wrong`） |
| AC-11 | §2.4 + B-7/B-8/B-9（熟练度与阶梯零改动） |
| AC-12 | §5.6 错误矩阵 + §5.7 契约镜像 + `test_r11_contract.py` |
| AC-13 | §5.2 `notice` 四态 + §6.2 失败态 + B-14/B-15/B-16 |
| AC-14 | §8.3 门禁表 + §8.4 实跑清单 |
| AC-15 | B-11（零 AI）+ B-12（时延）+ §2.3（题库固化、运行时零生成） |
| AC-16 | 本文与 `DESIGN.md`；QA 阶段据 §3.1/§3.2/§2.4/§4 出表 |
| AC-17 | DESIGN §0.8/§2.7 + §6.4（`.sc-qa-code` 内滚）+ 390 断言 |
| AC-18 | §5.4（`practiced`/`total`）+ `PracticeProgress` |
