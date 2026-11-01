"""题库导入与读库（r6 · TECHNICAL §2.3）：可用性校验、幂等导入、空库自动种子的唯一出处。

运行时由 `questions` 表承载题库（DDL 只在 `db.py`，SQL 只在 `repository.py`），
`app/seed/questions.json` 退为**唯一导入源**：数据与代码分离，题库仍可读文件审阅。

三条写死的口径：
- `_usable()` 只有这一份（`exam.py` 不再定义同名副本）：缺 id / kind / prompt、客观题无答案
  或无选项的条目一律不入库、也不出卷。`tests/test_engineering_gates.py::
  test_single_usable_and_structure_gate` 反向钉住「只此一份」。
- 导入幂等由 `repository.insert_question()` 的 `ON CONFLICT(id) DO NOTHING` 兑现：重复导入
  既不新增也不覆盖既有行（标签回填只在首次导入那一刻生效，AC-1）。
- **空库自动种子**是既有用例零回归的关键：`tests/conftest.py` 的 `tmp_db` 只 `init_db()`，
  `load_questions()` 发现库空就 `import_seed()` 再重读，行为等价于 r5 的「现读 JSON」。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args

from .. import repository
from ..errors import VALIDATION_ERROR, AppError
from ..schemas import ExamKind
from . import rules

#: 种子文件（唯一导入源）：与 `db.py` 的 DDL 一样属于部署期常量，测试可注入临时 path。
SEED_PATH = Path(__file__).resolve().parent.parent / "seed" / "questions.json"

#: 可出卷 kind 闭集：直接取 API 契约 `schemas.ExamKind` 的取值，不另立第三份字面量。
USABLE_KINDS: frozenset[str] = frozenset(get_args(ExamKind))

#: `difficulty` 脏值兜底：落闭集首档（`basic`）。不猜「更难」——难度只影响结构闸门的挑战题占比。
_DEFAULT_DIFFICULTY = rules.DIFFICULTIES[0]

#: 错误文案沿用 r1 题库口径（不新增错误码、不白屏，AC-13）。
_UNAVAILABLE = "题库文件不可用，暂无法出卷"
_MALFORMED = "题库文件格式异常，暂无法出卷"


def _usable(question: Any) -> bool:
    """题库条目的最低可用性：缺 id / kind / prompt，或客观题无答案 / 无选项，一律不出卷。

    只判「能不能出卷」，不校验标签（标签兜底在 `rules.essentiality_of()`，难度兜底在 `_row_of()`）。
    """
    if not isinstance(question, dict):
        return False
    if not str(question.get("id") or "").strip():
        return False
    kind = str(question.get("kind") or "")
    if kind not in USABLE_KINDS:
        return False
    if not str(question.get("prompt") or "").strip():
        return False
    if rules.is_objective_kind(kind):
        answer = question.get("answer")
        # 空列表 / 空串 / 全空白串都算「没有标准答案」；非空即视为有（判分口径在 exam.grade_objective）。
        filled = bool(answer) and not (isinstance(answer, str) and not answer.strip())
        return filled and isinstance(question.get("options"), list)
    return True


def load_seed(path: Path = SEED_PATH) -> list[dict[str, Any]]:
    """读 JSON 种子并逐条过 `_usable()`，返回可用条目（字典原样，不做标签归一化）。

    文件缺失 / JSON 损坏 / 顶层不是列表 → `VALIDATION_ERROR` 中文 400（沿用 r1 文案，不 500）。
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:  # 题库文件缺失属于部署异常，映射成可读中文错误
        raise AppError(VALIDATION_ERROR, _UNAVAILABLE, status=400) from exc
    except json.JSONDecodeError as exc:
        raise AppError(VALIDATION_ERROR, _MALFORMED, status=400) from exc
    if not isinstance(raw, list):
        raise AppError(VALIDATION_ERROR, _MALFORMED, status=400)
    return [item for item in raw if _usable(item)]


def _row_of(question: dict[str, Any]) -> dict[str, Any]:
    """种子条目 → `repository.insert_question()` 入参：补默认难度 / 必备度，题干原样不加工。"""
    difficulty = str(question.get("difficulty") or "")
    return {
        "id": str(question["id"]).strip(),
        "direction": str(question.get("direction") or "").strip(),
        "kind": str(question.get("kind") or "").strip(),
        "difficulty": difficulty if difficulty in rules.DIFFICULTIES else _DEFAULT_DIFFICULTY,
        "essentiality": rules.essentiality_of(question),
        "prompt": str(question.get("prompt") or ""),
        "options": question.get("options") or [],
        "answer": question.get("answer") or [],
        "source": str(question.get("source") or "seed"),
    }


def import_seed(path: Path = SEED_PATH) -> int:
    """幂等导入种子：返回本次**新增**行数（重复导入恒 `0`，既有行绝不覆盖，AC-1）。"""
    inserted = 0
    for question in load_seed(path):
        if repository.insert_question(_row_of(question)):
            inserted += 1
    return inserted


def ensure_seeded() -> int:
    """空库才导入种子（生产首启即 80 行，重复启动 0 新增）；返回表内总行数。"""
    if repository.count_questions() == 0:
        import_seed()
    return repository.count_questions()


def load_questions() -> list[dict[str, Any]]:
    """组卷唯一入口：读库；空库先 `ensure_seeded()` 再重读。

    返回前用 `_usable()` 复核一遍：库里的坏行（人工误写、旧数据）同样不进可考池，
    这样「可用性」只有一处判定，`exam_selector` 不必再过滤。
    """
    rows = repository.list_questions()
    if not rows:
        ensure_seeded()
        rows = repository.list_questions()
    return [row for row in rows if _usable(row)]


def sync_labels(path: Path = SEED_PATH) -> int:
    """dev 一次性回填校验：比对库内 `difficulty`/`essentiality` 与种子文件的差异行数。

    只读不写（不参与运行时、不改库）：用于确认 T1 的标签回填是否已落到既有库；
    返回 `0` 表示库内标签与当前种子逐条一致。
    """
    stored = {str(row.get("id") or ""): row for row in repository.list_questions()}
    drifted = 0
    for question in load_seed(path):
        expected = _row_of(question)
        row = stored.get(expected["id"])
        if row is None:
            drifted += 1
            continue
        actual = (str(row.get("difficulty") or ""), str(row.get("essentiality") or ""))
        if actual != (expected["difficulty"], expected["essentiality"]):
            drifted += 1
    return drifted
