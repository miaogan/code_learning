"""题库导入与读库（r6 · TECHNICAL §2.3；r11 改启动口径）：可用性校验、幂等导入、空库种子的唯一出处。

运行时由 `questions` 表承载题库（DDL 只在 `db.py`，SQL 只在 `repository.py`），
`app/seed/questions.json` 退为**唯一导入源**：数据与代码分离，题库仍可读文件审阅。

四条写死的口径：
- `_usable()` 只有这一份（`exam.py` 不再定义同名副本）：缺 id / kind / prompt、客观题无答案
  或无选项的条目一律不入库、也不出卷。`tests/test_engineering_gates.py::
  test_single_usable_and_structure_gate` 反向钉住「只此一份」。
- 导入幂等由 `repository.insert_questions()`（r43 批量版；单条版 `insert_question()` 同 SQL）的
  `ON CONFLICT(id) DO NOTHING` 兑现：重复导入既不新增也不覆盖既有行（标签回填只在首次导入那一刻生效，AC-1）。
- **r11 起每次启动都导入**（`ensure_seeded()`）：旧实现「仅空库导入」会让存量 `app.core.db`
  （含 r10 的 `skillcoach-data` 卷）永远拿不到新增的 180 题。幂等由主键 + `DO NOTHING` 保证，
  重复启动恒 0 新增 —— 这仍满足 r6 AC-1「重复导入不新增、既有行不被覆盖」。
- **r14 起启动还覆写既有行**（`refresh_from_seed()`）：`ON CONFLICT DO NOTHING` 只增不覆盖，
  已部署库里的旧选项顺序 / 旧判断题极性永远刷不到；`refresh_questions()` 逐字段比对后只写差异行，
  库内已一致时恒 0（P3-1）。历史 `question_attempts` 只存 `correct`，覆写题目行不影响既有判分。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args

from app.core import repository
from app.core.errors import VALIDATION_ERROR, AppError
from app.schemas import ExamKind
from app.services.report import rules

#: 种子文件（唯一导入源）：与 `db.py` 的 DDL 一样属于部署期常量，测试可注入临时 path。
SEED_PATH = Path(__file__).resolve().parents[2] / "seed" / "questions.json"

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
    """种子条目 → `repository.insert_question()` 入参：补默认难度 / 必备度，题干原样不加工。

    r11 起 `language` / `explanation` 随行写入：`language` 缺省空串（`""` 是「通用/算法题」的
    合法闭集成员，不是「未填」），`explanation` 缺省空串（由 `refresh_from_seed` 随全字段覆写补齐）。
    """
    difficulty = str(question.get("difficulty") or "")
    return {
        "id": str(question["id"]).strip(),
        "direction": str(question.get("direction") or "").strip(),
        "sub_direction": question.get("sub_direction"),
        "kind": str(question.get("kind") or "").strip(),
        "difficulty": difficulty if difficulty in rules.DIFFICULTIES else _DEFAULT_DIFFICULTY,
        "essentiality": rules.essentiality_of(question),
        "prompt": str(question.get("prompt") or ""),
        "options": question.get("options") or [],
        "answer": question.get("answer") or [],
        "source": str(question.get("source") or "seed"),
        "language": str(question.get("language") or ""),
        "explanation": str(question.get("explanation") or ""),
    }


def import_seed(path: Path = SEED_PATH) -> int:
    """幂等导入种子：返回本次**新增**行数（重复导入恒 `0`，既有行绝不覆盖，AC-1）。

    r43 起改走 `repository.insert_questions()` 的单事务批量写入（同 SQL、同语义）：
    1088 条逐条开连接要 11.26s，批量后亚秒级；幂等仍由 `ON CONFLICT(id) DO NOTHING` 兑现。
    """
    return repository.insert_questions([_row_of(question) for question in load_seed(path)])


def refresh_from_seed(path: Path = SEED_PATH) -> int:
    """把种子的**全字段**覆写到库内既有行，返回真正被改写的行数（r14 · P3-1）。

    与 `import_seed()` 的分工：导入只增不覆盖（AC-1），这里只覆盖已存在的同 id 行、绝不新增。
    `ensure_seeded()` 在启动时调用它，让已部署的 `app.core.db`（旧选项顺序 / 旧判断题答案）也能
    刷成当前种子。幂等真值：库内已与种子一致时返回 `0`。SQL 只在 `repository.refresh_questions`。
    """
    return repository.refresh_questions([_row_of(question) for question in load_seed(path)])


def ensure_seeded() -> int:
    """启动即幂等导入 + 覆写既有行（r11 导入口径 + r14 P3-1 存量刷新），返回表内总行数。

    旧实现「仅在空库导入」会让存量库永远拿不到新增题；r11 起每次都导入，但
    `ON CONFLICT(id) DO NOTHING` 只增不覆盖，已部署库里 r13 的选项重排 / 判断题极性永远刷不到。
    现在每次启动：`import_seed()` 补新增（重复启动 0 新增），`refresh_from_seed()` 覆写既有行
    （库内已一致时 0 改写）。历史 `question_attempts` 只存 `correct`，不受覆写影响。
    """
    import_seed()
    refresh_from_seed()
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


def practice_pool() -> list[dict[str, Any]]:
    """练习池的唯一出口：可用题里**仅客观题**（`rules.is_objective_kind`，r11 含判断题）。

    练习只判客观题，简答题（`text`）没有唯一答案、不进入练习池；与笔试的差别只在
    `rules.EXAM_EXCLUDED_KINDS`（那只是笔试侧降级开关，练习侧不看它）。
    """
    return [row for row in load_questions() if rules.is_objective_kind(str(row.get("kind") or ""))]


def find_question(question_id: str) -> dict[str, Any] | None:
    """按 id 取一道**可用**题（练习提交判分用）；不存在或不可用返回 `None`（由调用方映射 404）。"""
    target = str(question_id or "").strip()
    if not target:
        return None
    for row in load_questions():
        if str(row.get("id") or "") == target:
            return row
    return None


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
