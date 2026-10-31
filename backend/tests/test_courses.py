"""精选课程清单的 AC-6 下限校验与匹配兜底。"""

from app.services import courses


def test_catalog_meets_quantity_floor() -> None:
    total, beginner = courses.catalog_stats()
    assert total >= courses.MIN_COURSES
    assert beginner >= courses.MIN_BEGINNER_COURSES


def test_four_directions_are_covered() -> None:
    directions = {item.direction for item in courses.list_courses()}
    assert {"前端", "后端", "算法与数据结构", "计算机基础"} <= directions


def test_every_course_has_learning_rationale() -> None:
    for item in courses.list_courses():
        assert item.title
        assert item.why
        assert item.level in {"入门", "进阶"}


def test_match_for_shortfall_never_returns_empty() -> None:
    assert courses.match_for_shortfall("缓存与索引")
    assert courses.match_for_shortfall("完全没听过的方向")
