"""阈值与判定规则唯一出处（跨面试 / 笔试 / 报告共用）。

题量下限、挑战题占比、短板条数与严重度分档都写在这里：一旦散落到各 services 里就地写魔数，
面试与笔试的口径会各自漂移，测试也失去单一断言点。

字段差异适配（既有 schemas 决定的差异，下游请用下面两个帮助函数，别自己猜字段）：
- 面试题挑战判定 = `InterviewQuestion.kind == "challenge"` → `is_challenge_kind()`
- 笔试题挑战判定 = 题库条目的 `difficulty == "challenge"`（不进响应）→ `is_challenge_difficulty()`
"""

import math

from ..schemas import Severity

# --- 面试 ---------------------------------------------------------------
MIN_INTERVIEW_QUESTIONS = 8
MIN_TECHNICAL_QUESTIONS = 5
MIN_PROJECT_QUESTIONS = 3
MAX_CHALLENGE_RATIO = 0.2

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


def severity_of(avg: float) -> Severity:
    """按平均得分分档：<4 high，<7 medium，其余 low。"""
    if avg < SEVERITY_HIGH_BELOW:
        return "high"
    if avg < SEVERITY_MEDIUM_BELOW:
        return "medium"
    return "low"
