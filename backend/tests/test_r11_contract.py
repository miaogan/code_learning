"""r11 契约门禁：语言 / 题型 / 练习闭集与 `types.ts` 逐字镜像。

两侧没有共享代码（Python Literal ↔ TS 联合类型），唯一牵制手段就是静态断言：
任一侧回退（删掉 `judge`、把「全部」换成 `""`、给练习模型加字段）都必须在 CI 转红，
否则接口会在下一次改名时静默漂移 —— 而前端的 Record 查表会得到 `undefined` 而不是报错。

单一出处：`backend/app/services/report/rules.py`。`schemas.py` 是镜像，`types.ts` 是第二份镜像。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from app import schemas
from app.schemas import (
    ExamKind,
    PracticeAnswerRequest,
    PracticeAnswerResult,
    PracticeDifficultyFilter,
    PracticeEssentialityFilter,
    PracticeLanguageFilter,
    PracticeLimit,
    PracticePaper,
    PracticePaperRequest,
    PracticeQuestion,
    PracticeScope,
    PracticeStats,
    PracticeWrongBook,
    PracticeWrongItem,
    QuestionLanguage,
)
from app.services.report import rules

REPO_ROOT = Path(__file__).resolve().parents[2]
TYPES_TS = REPO_ROOT / "frontend" / "src" / "api" / "types.ts"


# --- 解析 helpers（只读文本，不引 TS 工具链：后端测试不许依赖 node） ----------


def _ts_source() -> str:
    assert TYPES_TS.is_file(), "缺 frontend/src/api/types.ts"
    return TYPES_TS.read_text(encoding="utf-8")


def _ts_type_body(source: str, name: str) -> str:
    """取 `export type <name> = <body>` 的类型体（到空行 / 下一个 export 为止）。"""
    match = re.search(
        rf"export type {name}\s*=\s*(.+?)(?:\n\s*\n|\nexport |\Z)",
        source,
        re.DOTALL,
    )
    assert match, f"types.ts 缺 export type {name}"
    return match.group(1)


def _ts_interface_body(source: str, name: str) -> str:
    """取 `export interface <name> { ... }` 的字段块。"""
    match = re.search(rf"export interface {name}\s*\{{(.*?)\n\}}", source, re.DOTALL)
    assert match, f"types.ts 缺 interface {name}"
    return match.group(1)


_TS_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)


def _ts_code(text: str) -> str:
    """去掉 TS 注释再解析：注释里的示例字面量不是类型成员（否则 `''` 会被误读成闭集值）。"""
    return _TS_COMMENT.sub("", text)


def _ts_string_unions(body: str) -> set[str]:
    return set(re.findall(r"'([^']*)'", _ts_code(body)))


def _ts_field_names(body: str) -> set[str]:
    return set(re.findall(r"^\s{2}(\w+)\??\s*:", _ts_code(body), re.MULTILINE))


def _literal_values(model: Any) -> set[Any]:
    return set(get_args(model))


# --- 1. 语言闭集：rules 唯一出处，schemas / types.ts 逐字镜像 ----------------


def test_r11_language_closed_set_single_source() -> None:
    """`rules.LANGUAGES` ↔ `schemas.QuestionLanguage` ↔ `types.ts QuestionLanguage` 三处逐字相等。

    并钉住一条反直觉约定：**`""` 是闭集成员**（通用 / 算法题），不是「全部」。
    """
    assert rules.LANGUAGES == ("", "python", "java", "go", "html", "css", "js", "ts", "vue3", "react")
    assert _literal_values(QuestionLanguage) == set(rules.LANGUAGES), (
        f"schemas.QuestionLanguage={sorted(_literal_values(QuestionLanguage))} "
        f"与 rules.LANGUAGES={sorted(rules.LANGUAGES)} 不一致"
    )
    assert "" in rules.LANGUAGES, "空串必须是语言闭集成员（通用 / 算法题）"
    assert rules.LANGUAGES.count("") == 1, "空串在语言闭集里只应出现一次"

    ts_union = _ts_string_unions(_ts_type_body(_ts_source(), "QuestionLanguage"))
    assert ts_union == set(rules.LANGUAGES), (
        f"types.ts QuestionLanguage={sorted(ts_union)} 与 rules.LANGUAGES 不一致"
    )
    assert "" in ts_union, "types.ts 后丢掉空串成员会让通用题无法表达"


def test_r11_practice_language_filter_keeps_any_and_generic_apart() -> None:
    """练习语言筛选 = `"all"` + 闭集：`"all"` 与 `""` 并列存在，两条语义不得合并。"""
    expected = {rules.FILTER_ANY} | set(rules.LANGUAGES)
    assert _literal_values(PracticeLanguageFilter) == expected, (
        f"schemas.PracticeLanguageFilter 应为 {sorted(expected)}，"
        f"实际 {sorted(_literal_values(PracticeLanguageFilter))}"
    )
    assert rules.FILTER_ANY == "all", "筛选「全部」的唯一字面量是 all"
    assert rules.FILTER_ANY not in rules.LANGUAGES, "「全部」不得混进语言闭集"

    body = _ts_type_body(_ts_source(), "PracticeLanguageFilter")
    assert _ts_string_unions(body) == {rules.FILTER_ANY}, "types.ts PracticeLanguageFilter 只应显式写 'all'"
    assert "QuestionLanguage" in body, "types.ts PracticeLanguageFilter 必须复用 QuestionLanguage"


# --- 2. 语言 → 方向归属：只由两份语言元组派生 --------------------------------


def test_r11_language_direction_single_source() -> None:
    """`LANGUAGE_DIRECTION` 恰好覆盖前端 / 后端语言，取值落在 `DIRECTIONS` 内且无交叉。"""
    assert set(rules.FRONTEND_LANGUAGES) | set(rules.BACKEND_LANGUAGES) == set(rules.LANGUAGE_DIRECTION)
    assert not set(rules.FRONTEND_LANGUAGES) & set(rules.BACKEND_LANGUAGES), "前后端语言集合不得交叉"
    assert set(rules.FRONTEND_LANGUAGES) | set(rules.BACKEND_LANGUAGES) | {""} == set(rules.LANGUAGES)
    for language, direction in rules.LANGUAGE_DIRECTION.items():
        assert direction in rules.DIRECTIONS, f"{language} 的方向 {direction} 越出 rules.DIRECTIONS"

    # 派生函数与映射表同向（前端 chip 只消费这里的结论，不再自己推方向）。
    front = rules.direction_of_language(rules.FRONTEND_LANGUAGES[0])
    back = rules.direction_of_language(rules.BACKEND_LANGUAGES[0])
    assert front is not None and back is not None and front != back
    assert rules.direction_of_language("") is None, "通用题不归属任何方向"
    assert rules.direction_of_language("python") in rules.DIRECTIONS
    assert rules.languages_for_direction(front) == tuple(
        lang for lang in rules.LANGUAGES if rules.LANGUAGE_DIRECTION.get(lang) == front
    ), "languages_for_direction 必须直接从 LANGUAGE_DIRECTION 派生"
    assert rules.is_language_allowed(rules.FRONTEND_LANGUAGES[0], back) is False, (
        "前端语言不得被后端方向放行"
    )
    assert rules.is_language_allowed(rules.FRONTEND_LANGUAGES[0], front) is True
    assert rules.languages_for_direction(rules.FILTER_ANY) == rules.LANGUAGES, "「全部」方向不做限制"
    assert rules.is_language_allowed("", back) is True, "通用题恒放行"


# --- 3. 题型闭集含 judge，且客观题口径只有一份 -------------------------------


def test_r11_kind_includes_judge() -> None:
    """`ExamKind` 含 `judge`；`OBJECTIVE_KINDS` 恰为三档；`text` 仍是非客观题那一档。"""
    assert _literal_values(ExamKind) == set(rules.QUESTION_KINDS), "schemas.ExamKind 与 rules.QUESTION_KINDS 不一致"
    assert "judge" in rules.QUESTION_KINDS, "题型闭集必须含 judge"
    assert rules.OBJECTIVE_KINDS == ("single", "multiple", "judge"), (
        f"客观题闭集应为 single/multiple/judge，实际 {rules.OBJECTIVE_KINDS}"
    )
    assert rules.TEXT_KIND == "text", "text 必须仍是唯一的非客观题档"
    assert rules.is_objective_kind("judge") is True, "判断题必须可判分（练习要用）"
    assert rules.is_objective_kind(rules.TEXT_KIND) is False

    ts_union = _ts_string_unions(_ts_type_body(_ts_source(), "ExamKind"))
    assert ts_union == set(rules.QUESTION_KINDS), f"types.ts ExamKind={sorted(ts_union)} 与 rules.QUESTION_KINDS 不一致"

    # 降级开关默认空：组卷侧口径此刻与客观题闭集逐字等价。
    assert rules.EXAM_EXCLUDED_KINDS == (), "EXAM_EXCLUDED_KINDS 默认必须为空（判断题进制）"
    for kind in rules.QUESTION_KINDS:
        assert rules.is_exam_objective_kind(kind) == rules.is_objective_kind(kind), (
            f"默认开关下 is_exam_objective_kind({kind}) 必须等价 is_objective_kind"
        )


# --- 4. 练习 scope / limit / 三档筛选闭集 ----------------------------------


def test_r11_practice_closed_sets() -> None:
    """scope / limit / 方向 / 难度 / 必备度五组筛选闭集在两侧逐字一致。"""
    assert _literal_values(PracticeScope) == set(rules.PRACTICE_SCOPES)
    assert rules.PRACTICE_SCOPES == ("all", "unseen", "wrong")
    assert _literal_values(PracticeLimit) == set(rules.PRACTICE_LIMITS)
    assert rules.PRACTICE_LIMITS == (10, 20, 0)
    assert rules.DEFAULT_PRACTICE_LIMIT in rules.PRACTICE_LIMITS

    # 方向筛选刻意不写第二份字面量：闭集只在 `rules.DIRECTIONS`（见下一条用例）。
    assert schemas.PracticePaperRequest.model_fields["direction"].default == rules.FILTER_ANY
    assert _literal_values(PracticeDifficultyFilter) == {rules.FILTER_ANY} | set(rules.DIFFICULTIES)
    assert _literal_values(PracticeEssentialityFilter) == {rules.FILTER_ANY} | set(rules.ESSENTIALITIES)

    # 请求模型的默认值 = 「全部」+ 默认题量（七项都可省略）。
    # r50 追加 `sub_direction`；缺省 "" = 不聚焦，老客户端请求体逐字可用。
    request_defaults = {name: field.default for name, field in PracticePaperRequest.model_fields.items()}
    assert request_defaults == {
        "language": rules.FILTER_ANY,
        "direction": rules.FILTER_ANY,
        "difficulty": rules.FILTER_ANY,
        "essentiality": rules.FILTER_ANY,
        "scope": "all",
        "limit": rules.DEFAULT_PRACTICE_LIMIT,
        "sub_direction": "",
    }, f"PracticePaperRequest 默认值漂移：{request_defaults}"

    ts = _ts_source()
    assert _ts_string_unions(_ts_type_body(ts, "PracticeScope")) == set(rules.PRACTICE_SCOPES)
    assert {int(value) for value in re.findall(r"\d+", _ts_type_body(ts, "PracticeLimit"))} == set(
        rules.PRACTICE_LIMITS
    )
    assert _ts_string_unions(_ts_type_body(ts, "PracticeDirectionFilter")) == {
        rules.FILTER_ANY
    } | set(rules.DIRECTIONS), "types.ts PracticeDirectionFilter 与 rules.DIRECTIONS 不同步"
    assert _ts_string_unions(_ts_type_body(ts, "PracticeDifficultyFilter")) == {rules.FILTER_ANY}
    assert "ExamDifficulty" in _ts_type_body(ts, "PracticeDifficultyFilter")
    assert _ts_string_unions(_ts_type_body(ts, "PracticeEssentialityFilter")) == {rules.FILTER_ANY}
    assert "QuestionEssentiality" in _ts_type_body(ts, "PracticeEssentialityFilter")


def test_r11_direction_filter_rejects_out_of_closed_set() -> None:
    """方向筛选不得在 `schemas.py` 复写字面量，越界值仍必须 422（由 `rules.DIRECTIONS` 判定）。"""
    schemas_source = (REPO_ROOT / "backend" / "app" / "schemas.py").read_text(encoding="utf-8")
    offenders = [direction for direction in rules.DIRECTIONS if f'"{direction}"' in schemas_source]
    assert not offenders, f"schemas.py 复写了方向字面量（第二份闭集）：{offenders}"

    for direction in (*rules.DIRECTIONS, rules.FILTER_ANY):
        assert PracticePaperRequest(direction=direction).direction == direction
    with pytest.raises(ValidationError):
        PracticePaperRequest(direction="前端语言")


# --- 5. 练习四端点模型字段双侧镜像 ------------------------------------------


def test_r11_practice_models_mirror_text() -> None:
    """`schemas.Practice*` 的字段名必须逐字出现在 `types.ts` 同名 interface 里（零转换）。"""
    ts = _ts_source()
    pairs: list[tuple[Any, str]] = [
        (PracticePaperRequest, "PracticePaperRequest"),
        (PracticeQuestion, "PracticeQuestion"),
        (PracticePaper, "PracticePaper"),
        (PracticeAnswerRequest, "PracticeAnswerRequest"),
        (PracticeAnswerResult, "PracticeAnswerResult"),
        (PracticeStats, "PracticeStats"),
        (PracticeWrongItem, "PracticeWrongItem"),
        (PracticeWrongBook, "PracticeWrongBook"),
    ]
    for model, ts_name in pairs:
        python_fields = set(model.model_fields)
        ts_fields = _ts_field_names(_ts_interface_body(ts, ts_name))
        assert ts_fields, f"types.ts interface {ts_name} 解析不到字段"
        missing = python_fields - ts_fields
        extra = ts_fields - python_fields
        assert not missing, f"types.ts {ts_name} 缺镜像字段 {sorted(missing)}"
        assert not extra, f"types.ts {ts_name} 多出后端没有的字段 {sorted(extra)}"

    # 题单不含答案；只有判分响应回显正确答案与解析。
    assert "answer" not in PracticeQuestion.model_fields, "PracticeQuestion 不得暴露 answer"
    assert "answer" not in _ts_field_names(_ts_interface_body(ts, "PracticeQuestion"))
    assert "correct_answer" in PracticeAnswerResult.model_fields
    assert "correct_answer" in _ts_field_names(_ts_interface_body(ts, "PracticeAnswerResult"))
    # 题库语言/难度/必备度是闭集，镜像类型必须是具名联合而不是裸 string。
    assert "ExamKind" in _ts_interface_body(ts, "PracticeQuestion")
    assert "ExamKind" in _ts_interface_body(ts, "ExamQuestion"), "笔试题卡也要认 judge（共享题卡）"
    assert schemas.ExamQuestion.model_fields["kind"].annotation == ExamKind


# --- 6. 一处字面量 = 一条语义：`""` 不得被当作「全部」 -----------------------


def test_r11_empty_language_never_means_any() -> None:
    """`""` 只在语言闭集里代表「通用题」；「全部」只能用 `rules.FILTER_ANY`。"""
    assert rules.FILTER_ANY != ""
    assert rules.FILTER_ANY in rules.PRACTICE_SCOPES
    for scope in rules.PRACTICE_SCOPES:
        assert scope != "", "scope 的「全部」不得写成空串"
    assert "" in rules.LANGUAGES and rules.FILTER_ANY not in rules.LANGUAGES

    # 两个 Literal 筛选里，「全部」都必须叫 all（方向筛选见下一条用例：它走 Annotated 校验器）。
    for model in (PracticeLanguageFilter, PracticeDifficultyFilter, PracticeEssentialityFilter):
        assert rules.FILTER_ANY in _literal_values(model), f"{model} 的「全部」必须是 all"
    # 服务端不得出现第二份「全部」字面量：schemas 只在语言筛选里写一次 'all' 语义。
    assert "any" not in rules.PRACTICE_SCOPES
