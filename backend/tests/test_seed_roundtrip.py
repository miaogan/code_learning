"""种子 → 数据库全链路往返门禁（防止「加了列但没透传」的静默断链）。

r17 收口用例：`sub_direction` 上线时，`db.py` / `repository` 的 INSERT 都加了新列，但
`question_bank._row_of()`、`_QUESTION_REFRESH`、`_normalized_question()` 三处漏加，本地旧库
看不出来、CI 全新库直接红。这里把「种子声明的每个字段都必须原样落库」和「覆写必须收敛到 0」
钉成常驻断言，将来任何新增列漏改任一环节，都会在本文件里以字段级 diff 直接报出。

口径与既有代码保持一致：
- `import_seed` / `refresh_from_seed` / `load_seed` 都是既有出口，用例不复制任何 SQL；
- 字段名从种子文件里**动态取**（所有条目键的并集），新增字段无需改本文件。
"""

from __future__ import annotations

from typing import Any

from app.core import repository
from app.core.db import connection
from app.services.assessment import question_bank
from app.services.report import rules

#: r98：`seeded_db` 由 `conftest` 提供（PG 版：独立库 `sc_test_seed` + 模块内共用），
#: 这里不再本地定义，避免两套「灌种」实现漂移。


def _seed_fields(rows: list[dict[str, Any]]) -> set[str]:
    """种子里出现过的字段名并集（新增字段自动纳入检查）。"""
    return {key for row in rows for key in row}


def test_every_seed_field_lands_in_database(seeded_db: str) -> None:
    """种子声明的每个字段都必须原样落库（含 sub_direction 这类新增列）。"""
    seed_rows = question_bank.load_seed()
    assert seed_rows, "题库种子为空"
    stored = {row["id"]: row for row in repository.list_questions()}

    missing_ids = [row["id"] for row in seed_rows if str(row["id"]).strip() not in stored]
    assert not missing_ids, f"种子条目未入库：{missing_ids[:5]}"

    offenders: dict[str, str] = {}
    for seed_row in seed_rows:
        question_id = str(seed_row["id"]).strip()
        db_row = stored[question_id]
        for field in _seed_fields(seed_rows):
            if field not in seed_row:
                continue
            # 种子的 difficulty / essentiality 允许缺省，落库时由 `_row_of` 补默认值，
            # 这两项不按原值比对（口径归 `_row_of` 与 rules，用例不复写）。
            if field in {"difficulty", "essentiality"}:
                continue
            if field not in db_row:
                offenders.setdefault(field, f"{question_id}（库行没有该列）")
                continue
            if db_row[field] != seed_row[field]:
                offenders.setdefault(field, f"{question_id}：库={db_row[field]!r} 种子={seed_row[field]!r}")

    assert not offenders, f"种子字段未原样落库（检查 _row_of / INSERT / SELECT 是否都带上该字段）：{offenders}"


def test_every_seeded_question_has_sub_direction(seeded_db: str) -> None:
    """r17 回归：题库里的每道题都必须有二级方向（通用兜底也算，`None` 即断链）。"""
    rows = repository.list_questions()
    missing = [row["id"] for row in rows if not row.get("sub_direction")]
    assert not missing, f"{len(missing)} 道题缺 sub_direction：{missing[:5]}"


def test_sub_direction_belongs_to_its_direction(seeded_db: str) -> None:
    """二级方向必须落在其一级方向的闭集内（闭集只有 `rules.SUBDIRECTIONS` 一份）。"""
    offenders = [
        (row["id"], row["direction"], row["sub_direction"])
        for row in repository.list_questions()
        if not rules.is_valid_sub_direction(row["direction"], row.get("sub_direction"))
    ]
    assert not offenders, f"sub_direction 越出所在方向的闭集：{offenders[:5]}"


def test_refresh_converges_to_zero_after_import(seeded_db: str) -> None:
    """导入后再次覆写必须返回 0（幂等）。

    这条专治 `_QUESTION_REFRESH` 漏写某列：`_normalized_question()` 若比对该列而 UPDATE 不写，
    每次启动都会返回 >0 且永远收敛不了（历史上 sub_direction 就是这样断的）。
    """
    rewrote = question_bank.refresh_from_seed()
    assert rewrote == 0, f"库内已与种子一致时覆写应为 0 行，实际改写 {rewrote} 行"


def test_refresh_rewrites_stale_row(seeded_db: str) -> None:
    """反面用例：把库里某题改脏，覆写必须能刷回种子值（证明 UPDATE 真的写了该列）。

    放在文件末尾：用例结束时库已恢复成种子状态，不影响同一模块内的其它只读用例。
    """
    row = repository.list_questions()[0]
    expected = row["sub_direction"]
    assert expected, "样本题缺 sub_direction，先修导入链路"

    with connection() as conn:
        conn.execute("UPDATE questions SET sub_direction = ? WHERE id = ?", ("__stale__", row["id"]))

    assert question_bank.refresh_from_seed() >= 1, "库内被改脏后覆写未生效（UPDATE 未写 sub_direction）"
    refreshed = next(item for item in repository.list_questions() if item["id"] == row["id"])
    assert refreshed["sub_direction"] == expected, (
        f"覆写后 sub_direction 未恢复：库={refreshed['sub_direction']!r} 期望={expected!r}"
    )
