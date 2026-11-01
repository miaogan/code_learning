"""阈值与判定规则唯一出处（跨面试 / 笔试 / 报告共用）。

题量下限、挑战题占比、短板条数与严重度分档都写在这里：一旦散落到各 services 里就地写魔数，
面试与笔试的口径会各自漂移，测试也失去单一断言点。

字段差异适配（既有 schemas 决定的差异，下游请用下面两个帮助函数，别自己猜字段）：
- 面试题挑战判定 = `InterviewQuestion.kind == "challenge"` → `is_challenge_kind()`
- 笔试题挑战判定 = 题库条目的 `difficulty == "challenge"`（不进响应）→ `is_challenge_difficulty()`
"""

import math
from typing import Any

from pydantic import ValidationError

from ..schemas import InterviewSettings, Severity

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

#: 每场追问上限（8 正题 + 4 追问 = 12 轮，与 `MAX_INTERVIEW_TURNS` 同步推导）。
MAX_FOLLOW_UPS = 4
MAX_INTERVIEW_TURNS = MIN_INTERVIEW_QUESTIONS + MAX_FOLLOW_UPS

# --- 笔试 ---------------------------------------------------------------
MIN_EXAM_QUESTIONS = 10
MIN_OBJECTIVE_QUESTIONS = 8
MAX_EXAM_QUESTIONS = 12

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


def is_challenge_difficulty(difficulty: str) -> bool:
    """笔试侧挑战题判定：题库条目的 `difficulty`（取值 basic / challenge），该字段不进响应模型。"""
    return difficulty == "challenge"


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


def is_follow_up_allowed(kind: str, follow_up_count: int, total_questions: int) -> bool:
    """追问守门（AC-6/AC-7）：配额未满 ∧ 非 challenge 父题 ∧ 再加一条仍不超过轮次上限。

    非 challenge 的追问只会抬高 technical/project 计数、拉低 challenge 占比，因此
    「开局结构闸门通过 ⇒ 结束闸门必通过」；challenge 一律不给追问（否则挑战题会破 20% 上限）。
    """
    if is_challenge_kind(kind):
        return False
    if follow_up_count >= MAX_FOLLOW_UPS:
        return False
    return total_questions + 1 <= MAX_INTERVIEW_TURNS


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

