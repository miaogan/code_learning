"""规则唯一出处：闭集 + 结构闸门（跨面试 / 笔试 / 报告共用）。

题量下限、挑战题占比、短板条数与严重度分档都写在这里：一旦散落到各 services 里就地写魔数，
面试与笔试的口径会各自漂移，测试也失去单一断言点。

**分工（r6 写死）**：本题只放**闭集与结构闸门**（方向 / 难度 / 必备度 / 组卷阶梯 / 题量与占比）；
**可调阈值**（熟练度窗口天数、答对次数、近卷去重卷数）只住 `config.Settings`，可被环境变量覆盖。
阈值漂回本题、或闭集散到 `config.py`，都会让面试 / 笔试 / 报告口径各自漂移 —— 两个模块的
docstring 互相点名，`tests/test_engineering_gates.py` 反向钉住。

字段差异适配（既有 schemas 决定的差异，下游请用下面几个帮助函数，别自己猜字段）：
- 面试题挑战判定 = `InterviewQuestion.kind == "challenge"` → `is_challenge_kind()`
- 笔试题挑战判定 = 题库条目的 `difficulty == "challenge"`（不进响应）→ `is_challenge_difficulty()`
- 笔试客观题判定 = 题库条目的 `kind ∈ OBJECTIVE_KINDS`（r11 起含 `judge`）→ `is_objective_kind()`
- 组卷侧客观题判定 = 客观题闭集 − `EXAM_EXCLUDED_KINDS`（降级开关）→ `is_exam_objective_kind()`
- 笔试必备度读取 = 题库条目的 `essentiality`（脏值兜底）→ `essentiality_of()`
- 题干语言闭集 / 语言→方向归属 = `LANGUAGES` / `LANGUAGE_DIRECTION` → `direction_of_language()`
"""

import math
from typing import Any, get_args

from pydantic import ValidationError

from ..schemas import ExamKind, InterviewSettings, Severity

# --- 面试 ---------------------------------------------------------------
MIN_INTERVIEW_QUESTIONS = 8
MIN_TECHNICAL_QUESTIONS = 5
MIN_PROJECT_QUESTIONS = 3
MAX_CHALLENGE_RATIO = 0.2

# --- 面试配置（r5：目标岗位 / 工作经验 / 面试市场 / 公司规模） --------------
# 闭集只此一份：`backend/app/schemas.py` 的 Literal 与 `frontend/src/api/types.ts` 的联合
# 类型逐字对齐这三条元组；档位 → 提示词口径的映射也放在这里，避免散进 prompt 后漂移。
EXPERIENCE_BANDS: tuple[str, ...] = ("应届", "1-3年", "3-5年", "5-10年", "10年以上")
MARKETS: tuple[str, ...] = ("国内", "北美", "欧洲", "其他")
COMPANY_SIZES: tuple[str, ...] = ("大厂", "中型", "初创")

DEFAULT_TARGET_ROLE = "通用软件工程师"
DEFAULT_EXPERIENCE_BAND = "1-3年"
DEFAULT_MARKET = "国内"
DEFAULT_COMPANY_SIZE = "中型"

#: 每场追问上限。
MAX_FOLLOW_UPS = 4
#: 标准卷轮次预算（正题下限 8 + 追问上限 4 = 12），同时充当 `max_turns()` 的下限。
#: r8 D-4：本场口径必须经 `max_turns()` / `follow_ups_left()` 派生，别再拿它和本场发言数
#: 直接比较（提示词题量已是 9 题，写死 12 会放不下第 13 条发言）。r20：派生口径改为
#: `max(标准卷预算, 计划题量 + 追问上限)` —— 9 题卷 13 轮，追问 4 次仍可用满。
MAX_INTERVIEW_TURNS = MIN_INTERVIEW_QUESTIONS + MAX_FOLLOW_UPS

# --- 笔试 ---------------------------------------------------------------
MIN_EXAM_QUESTIONS = 10
MIN_OBJECTIVE_QUESTIONS = 8
MAX_EXAM_QUESTIONS = 12

# --- 题库闭集（r6：方向 / 难度 / 必备度 / 组卷阶梯）------------------------
# 闭集只此一份：`backend/app/schemas.py` 的 `ExamDifficulty` / `QuestionEssentiality` Literal
# 与这里逐字对齐（双向断言见 `tests/test_engineering_gates.py::test_closed_sets_single_source`）；
# 可调阈值**不在这里**，见 `config.Settings` 的三个熟练度字段。
DIRECTIONS: tuple[str, ...] = ("前端", "后端", "算法与数据结构", "计算机基础", "AI 工程")
DIFFICULTIES: tuple[str, ...] = ("basic", "intermediate", "challenge")
ESSENTIALITIES: tuple[str, ...] = ("must_know", "advanced", "nice_to_know")
#: 组卷兜底阶梯：L1 最优 → L6 全库兜底，**顺序即优先级**，任何一层都不得因过滤而返回 400。
PAPER_STAGES: tuple[str, ...] = ("L1", "L2", "L3", "L4", "L5", "L6")
#: 客观题闭集（`ExamKind` 里 `text` 是简答题）：只有它们判分并写熟练度事件。
#: r11 扩 `judge`（判断题与单选框同形：`options` 恰 2、`answer` 恰 1，判分仍走
#: `exam.grade_objective()` 的集合相等）—— 全站**不得**再出现第二份客观题闭集。
OBJECTIVE_KINDS: tuple[str, ...] = ("single", "multiple", "judge")
#: 组卷侧排除的 kind（降级开关，默认空 = 判断题进笔试卷面）。
#: 若实施发现 `ExamPage` 必须改 kind 分支，只需把这里置 `("judge",)` —— 数据级一行，
#: 不改判分、不改页面、不写第二套逻辑；练习池不受它影响（练习只认 `is_objective_kind`）。
EXAM_EXCLUDED_KINDS: tuple[str, ...] = ()
#: 可出卷 kind 闭集：直接取 API 契约 `schemas.ExamKind` 的取值，不另立字面量。
QUESTION_KINDS: tuple[str, ...] = tuple(get_args(ExamKind))
#: 简答题 kind（不计分、不写熟练度事件）：闭集里不属于客观题的那一档。
#: 别处引用本常量，不要就地写 `"text"`（闭集改档时字面量副本会静默失效，见 QA D-4）。
TEXT_KIND: str = next(kind for kind in QUESTION_KINDS if kind not in OBJECTIVE_KINDS)
#: 必备度最高档（`ESSENTIALITIES` 首档）：组卷 L2 只回这一档，L3 才放开其余档。
MUST_KNOW: str = ESSENTIALITIES[0]

# --- 题库语言维度与练习闭集（r11）------------------------------------------
# 闭集只此一份：`backend/app/schemas.py` 的 `QuestionLanguage` / `Practice*` Literal 与
# `frontend/src/api/types.ts` 的同名联合类型逐字对齐，双向钉在 `tests/test_r11_contract.py`。
#: 题干语言闭集。**`""` 是闭集成员**（通用 / 算法题，不属于任何具体语言），
#: 与筛选里的「全部」（`FILTER_ANY`）是**两条不同语义**：别处不得用 `""` 表示「全部」。
LANGUAGES: tuple[str, ...] = (
    "",
    "python",
    "java",
    "go",
    "html",
    "css",
    "js",
    "ts",
    "vue3",
    "react",
)
#: 前端方向的六种语言。
FRONTEND_LANGUAGES: tuple[str, ...] = ("html", "css", "js", "ts", "vue3", "react")
#: 后端方向的三种语言。
BACKEND_LANGUAGES: tuple[str, ...] = ("python", "java", "go")
#: 语言 → 方向归属（只由上面两份语言元组派生，别处不得再写一份映射）。
#: 空串 / 未收录语言**不在映射里**：通用题不归属任何方向（`direction_of_language` → `None`）。
LANGUAGE_DIRECTION: dict[str, str] = {
    **{lang: "前端" for lang in FRONTEND_LANGUAGES},
    **{lang: "后端" for lang in BACKEND_LANGUAGES},
}
#: 筛选「全部」的唯一字面量。`language` 的「全部」也用它（`""` 已被通用题占用）。
FILTER_ANY: str = "all"
#: 练习范围闭集：全部 / 未做过 / 最近一次答错。
PRACTICE_SCOPES: tuple[str, ...] = ("all", "unseen", "wrong")
#: 练习题量闭集（`0` = 全部命中）。
PRACTICE_LIMITS: tuple[int, ...] = (10, 20, 0)
#: 练习默认题量（与 `PracticePaperRequest.limit` 的默认值同一口径）。
DEFAULT_PRACTICE_LIMIT: int = 10

# --- 报告 ----------------------------------------------------------------
MIN_SHORTFALLS = 3
MAX_SHORTFALLS = 5

# 严重度分档：avg < 4 → high，< 7 → medium，否则 low（报告排序的第一关键字）
SEVERITY_HIGH_BELOW = 4.0
SEVERITY_MEDIUM_BELOW = 7.0
SEVERITY_ORDER: dict[Severity, int] = {"high": 0, "medium": 1, "low": 2}


def max_challenge_count(total: int, ratio: float = MAX_CHALLENGE_RATIO) -> int:
    """挑战题允许的上限（向上取整：8 题 → 2 题，与 AC「挑战题 ≤20%（8 题即 ≤2 题）」一致）。"""
    return math.ceil(total * ratio)


def is_challenge_kind(kind: str) -> bool:
    """面试侧挑战题判定：`InterviewQuestion.kind`（取值 technical / project / challenge）。"""
    return kind == "challenge"


def is_objective_kind(kind: str) -> bool:
    """笔试客观题判定（闭集 `OBJECTIVE_KINDS`，r11 起含 `judge`）：`text` 不判分、不写熟练度事件。"""
    return kind in OBJECTIVE_KINDS


def is_exam_objective_kind(kind: str) -> bool:
    """组卷侧客观题口径 = 客观题闭集 − `EXAM_EXCLUDED_KINDS`（默认空，等价 `is_objective_kind`）。

    组卷侧（`exam_selector`）用它、练习侧用 `is_objective_kind`：降级时只把判断题挪出**笔试**
    卷面，练习照旧能练 —— 两个口径共享同一份闭集，不各自写一份。
    """
    return is_objective_kind(kind) and kind not in EXAM_EXCLUDED_KINDS


def languages_for_direction(direction: str) -> tuple[str, ...]:
    """方向 → 该方向下的语言元组（`FILTER_ANY` 或未知方向 → `LANGUAGES`，即不筛）。"""
    if direction == FILTER_ANY:
        return LANGUAGES
    return tuple(lang for lang in LANGUAGES if LANGUAGE_DIRECTION.get(lang) == direction)


def direction_of_language(language: str) -> str | None:
    """语言 → 方向归属（`""` 通用题 / 未收录语言 → `None`：通用题不归属任何方向）。"""
    return LANGUAGE_DIRECTION.get(language)


def is_language_allowed(language: str, direction: str) -> bool:
    """语言与方向是否自洽：`""` 通用题恒放行，`FILTER_ANY` 方向不筛，其余按归属严格比对。"""
    if not language or direction == FILTER_ANY:
        return True
    return direction_of_language(language) == direction


def is_challenge_difficulty(difficulty: str) -> bool:
    """笔试侧挑战题判定：题库条目的 `difficulty`（取值 `DIFFICULTIES` 三档），该字段不进响应模型。"""
    return difficulty == "challenge"


def essentiality_of(question: dict[str, Any]) -> str:
    """题库条目的必备度（`must_know` / `advanced` / `nice_to_know`），脏值一律兜底。

    缺失 / 越出 `ESSENTIALITIES` 一律当 `nice_to_know`：坏标签若被当成 `must_know`，
    阶梯回流会把一道其实不重要的题提前排进卷面，反而污染组卷结构；最晚回流最保守。
    读侧兜底放在这里（唯一一份），别在下游各自 `.get("essentiality")`。
    """
    value = str(question.get("essentiality") or "").strip()
    return value if value in ESSENTIALITIES else "nice_to_know"


def experience_band_of(years: float | None) -> str:
    """画像里的工作年数 → 五档之一（档案缺失时回落默认档，绝不猜一个「更合适」的档）。

    边界：`<1` 应届 / `[1,3)` 1-3年 / `[3,5)` 3-5年 / `[5,10)` 5-10年 / `≥10` 10年以上。
    与前端 `bandOfYears` 逐档对称（AC-1 的预填口径靠两侧单测钉住）。
    """
    if years is None or years < 1:
        return "应届" if years is not None else DEFAULT_EXPERIENCE_BAND
    if years < 3:
        return "1-3年"
    if years < 5:
        return "3-5年"
    if years < 10:
        return "5-10年"
    return "10年以上"


def max_turns(planned_total: int) -> int:
    """本场轮次上限 = max(标准卷预算 `MAX_INTERVIEW_TURNS`, 计划正题数 + 追问上限)。

    r8 D-4：上限不能写死标准卷的 8 + 4 = 12，必须由**实际计划题量**派生，否则 9 题卷的
    第 13 条发言越界。r20（关闭 r8 D-5）：只取 `max(12, 计划题量)` 同样不对 —— 9 题卷只剩
    3 次追问，与「每场 4 次」的配额承诺不符。正解是给每道计划正题留位、再叠加完整追问预算：
    8 题卷仍 12 轮，9 题卷 13 轮，13 题卷 17 轮，`follow_ups_left()` 因此不再压缩额度。
    """
    return max(MAX_INTERVIEW_TURNS, planned_total + MAX_FOLLOW_UPS)


def follow_ups_left(planned_total: int, asked: int, follow_up_count: int) -> int:
    """剩余追问额度 = min(配额余量, 轮次预算里没被**剩余计划正题**占用的机动轮次)。

    `asked` 是本场已提出的发言数（正题 + 追问）。先把「剩余正题」的轮次扣出来，追问就透支
    不到正题：上限按「计划题量 + 追问上限」派生后，本式恒等于 `MAX_FOLLOW_UPS - follow_up_count`
    —— 每道计划正题各占一轮，机动轮次恰好留给 4 条追问（r20 关闭 D-5 的压缩问题）。
    """
    asked_plan = max(0, asked - follow_up_count)
    remaining_plan = max(0, planned_total - asked_plan)
    spare = max_turns(planned_total) - asked - remaining_plan
    return max(0, min(MAX_FOLLOW_UPS - follow_up_count, spare))


def is_follow_up_allowed(
    kind: str, follow_up_count: int, asked: int, planned_total: int
) -> bool:
    """追问守门（AC-6/AC-7）：配额未满 ∧ 非 challenge 父题 ∧ 不挤占剩余正题的轮次。

    非 challenge 的追问只会抬高 technical/project 计数、拉低 challenge 占比，因此
    「开局结构闸门通过 ⇒ 结束闸门必通过」；challenge 一律不给追问（否则挑战题会破 20% 上限）。
    """
    if is_challenge_kind(kind):
        return False
    return follow_ups_left(planned_total, asked, follow_up_count) > 0


def severity_of(avg: float) -> Severity:
    """按平均得分分档：<4 high，<7 medium，其余 low。"""
    if avg < SEVERITY_HIGH_BELOW:
        return "high"
    if avg < SEVERITY_MEDIUM_BELOW:
        return "medium"
    return "low"


#: 契约里 `settings` 的四键（TECHNICAL §2.6：全必填）。缺任一键 = 老 run / 脏数据。
SETTINGS_KEYS: tuple[str, ...] = ("target_role", "years_experience", "market", "company_size")


def settings_or_none(payload: dict[str, Any]) -> InterviewSettings | None:
    """`payload.settings` 的**唯一**读侧解析口径：缺失 / 缺键 / 越出闭集一律 `None`。

    三处「本场设定」共用它 —— 会话页（`interview._settings_or_none`）、历史行与报告
    （`history._interviews_settings_of`）。分成两份解析器会各自漂移：一份严格到 `None`、
    另一份用 schema 默认值补齐，同一 payload 就会在两个页面显示不同设定（QA D-5）。

    「不补给」是刻意的：r5 之前（payload v1）没有 `settings`，笔试 payload 从不写它 ——
    一律 `None` 让页面显示「未记录设定」，绝不用今天的默认值兜底，否则历史记录的
    「当时设定」会被填成一场从未发生过的配置。返回的是**投影**，不回写任何 run。
    """
    raw = payload.get("settings")
    if not isinstance(raw, dict) or any(key not in raw for key in SETTINGS_KEYS):
        return None
    try:
        settings = InterviewSettings.model_validate(raw)
    except ValidationError:
        return None
    if not str(settings.target_role).strip():
        return None
    if (
        settings.years_experience not in EXPERIENCE_BANDS
        or settings.market not in MARKETS
        or settings.company_size not in COMPANY_SIZES
    ):
        return None
    return settings

