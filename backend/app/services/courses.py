"""精选课程清单（AC-6）：加载 seed/courses.json，按短板名称匹配方向。

清单集中在单一 JSON 文件里，便于集中换链（PRD §7 风险缓解）；缺链课程置灰不出 404。
"""

import json
from functools import lru_cache
from pathlib import Path

from ..schemas import Course

SEED_PATH = Path(__file__).resolve().parent.parent / "seed" / "courses.json"
MIN_COURSES = 20
MIN_BEGINNER_COURSES = 3

# 短板名称里的关键词 → 清单 direction 取值
DIRECTION_HINTS: dict[str, tuple[str, ...]] = {
    "前端": ("前端", "react", "typescript", "javascript", "浏览器", "css", "组件"),
    "后端": ("后端", "服务端", "数据库", "sql", "api", "并发", "缓存"),
    "算法与数据结构": ("算法", "数据结构", "复杂度", "动态规划", "leetcode"),
    "计算机基础": ("计算机基础", "操作系统", "网络", "linux", "git", "编译", "内存"),
}


@lru_cache(maxsize=1)
def _load() -> tuple[Course, ...]:
    raw = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    return tuple(Course.model_validate(item) for item in raw)


def list_courses() -> list[Course]:
    return list(_load())


def catalog_stats() -> tuple[int, int]:
    """返回 (课程总数, 入门课数量)，供测试与 /health 之外的清单自检使用。"""
    items = _load()
    return len(items), sum(1 for item in items if item.level == "入门")


def match_for_shortfall(name: str, limit: int = 3) -> list[Course]:
    lowered = name.lower()
    directions = [
        direction
        for direction, hints in DIRECTION_HINTS.items()
        if any(hint in lowered for hint in hints)
    ]
    items = list(_load())
    if directions:
        picks = [item for item in items if item.direction in directions]
        if picks:
            return picks[:limit]
    # 兜底：绝不让某条短板没有任何课程（anti-goal 4）
    return [item for item in items if item.level == "入门"][:limit]
