"""T4 回归：简历改进要点投影（AC-4 / AC-5 / AC-6 / AC-11）。

口径：全程零网络（`FakeAI` / 类级 `complete_model` 补丁 / 直接注入坏 client），正文一律
逐字取自本文件或 conftest 的 `RESUME_TEXT`。这里只测 `resume_hints` 这一层：
**它是否真的复用了润色引擎、锚点是否逐字、降级是否不抛**。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.schemas import PolishSuggestion, Profile
from app.services import resume_hints, resume_polish
from app.services.ai import AIClient
from app.services.coach_copy import RESUME_AI_FALLBACK, RESUME_NO_TEXT, SECTION_LABEL

#: 超长正文行（> ANCHOR_MAX）：锚点必须退化成它的前 40 字逐字切片。
LONG_LINE = (
    "数据看板项目：主导大表格虚拟滚动与查询缓存策略，把首屏渲染耗时从 2.4 秒压到 380 毫秒"
)
LONG_RESUME = (
    "教育经历\n2019-2023 计算机科学与技术 本科\n"
    f"项目经历\n{LONG_LINE}\n"
    "技能\nReact TypeScript Python SQLite"
)

def _payload(cases: tuple[dict[str, str], ...]) -> dict[str, Any]:
    """本文件自带的润色草稿响应（与 conftest 的模板同形，字段是 `_SuggestDraft` 的超集）。"""
    return {"suggestions": [dict(case) for case in cases], "dropped_count": 0}


def _install_ai(monkeypatch: pytest.MonkeyPatch, cases: tuple[dict[str, str], ...]) -> list[str]:
    """类级补丁：记录每次调用拿到的正文，返回的 `_SuggestDraft` 交给真实 schema 校验。"""
    seen: list[str] = []

    async def fake_complete_model(
        self: AIClient,
        system: str,
        user: str,
        model_cls: type[Any],
        *,
        timeout_s: float | None = None,
        retry_unavailable: bool = False,
    ) -> Any:
        seen.append(user)
        return model_cls.model_validate(_payload(cases))

    monkeypatch.setattr(AIClient, "complete_model", fake_complete_model)
    return seen


class _BrokenClient:
    """模型不可用（超时 / 坏 JSON / 未配置 Key 的统一替身）：任何调用都抛。"""

    async def complete_model(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("AI 不可用（测试替身）")


def _run(
    resume_text: str | None,
    profile: Profile | None = None,
    target_role: str | None = "前端开发工程师",
    *,
    client: Any = None,
) -> resume_hints.ResumeHints:
    return asyncio.run(
        resume_hints.build_resume_pointers(resume_text, profile, target_role, client=client)
    )


@pytest.fixture()
def _no_ai_key(neutral_ai_env: None) -> None:
    """模拟「服务端没有任何 AI 配置」：走真实 `AIClient` 的未配置分支。

    r9 起环境中性化统一由 `neutral_ai_env` 提供（此前此处自行 `setenv("AI_API_KEY","")`，
    是本文件唯一一处「宿主把 `AI_PROVIDER` 设成 lmstudio 就真出网」的漏点）。
    """


# --- 23 / 25：复用润色引擎 + 条数上限 + 顺序 -----------------------------------


def test_reuses_polish_engine_verbatim(
    monkeypatch: pytest.MonkeyPatch, resume_text: str, profile_factory: Any
) -> None:
    """AC-4 ①：`build_suggestions` 被调用且拿到的正文与画像逐字相等（唯一入口）。"""
    seen = _install_ai(monkeypatch, resume_polish_cases())
    profile = profile_factory()
    recorded: list[tuple[str, Profile | None, str | None]] = []
    real = resume_polish.build_suggestions

    async def spy(
        text: str, prof: Profile | None, role: str | None, *, client: AIClient | None = None
    ) -> list[PolishSuggestion]:
        recorded.append((text, prof, role))
        return await real(text, prof, role, client=client)

    monkeypatch.setattr(resume_polish, "build_suggestions", spy)
    hints = _run(resume_text, profile, "前端开发工程师")

    assert len(recorded) == 1, "同一份报告只应调用一次润色引擎"
    text, prof, role = recorded[0]
    assert text == resume_text, "正文必须逐字透传（任何归一化都会让锚点对不上正文）"
    assert prof is profile
    assert role == "前端开发工程师"
    assert seen, "模型确实被调用（证据链：非缓存/非空实现）"
    assert hints.notice is None
    assert 3 <= len(hints.pointers) <= resume_hints.MAX_POINTERS


def test_max_pointers_and_ascending_start(
    monkeypatch: pytest.MonkeyPatch, resume_text: str
) -> None:
    """AC-4 ④：最多 5 条，且按正文 `start` 升序（与正文顺序一致）。"""
    _install_ai(monkeypatch, resume_polish_cases())
    hints = _run(resume_text)

    assert len(hints.pointers) == resume_hints.MAX_POINTERS
    starts = [resume_text.find(item.anchor_text) for item in hints.pointers]
    assert all(index >= 0 for index in starts), "每条锚点都必须能在正文里逐字找到"
    assert starts == sorted(starts), "要点顺序必须与正文顺序一致"


def test_shorter_than_min_is_honest(monkeypatch: pytest.MonkeyPatch, resume_text: str) -> None:
    """少于 3 条时如实给（不编造补足），且不误报降级原因。"""
    cases = (
        {
            "section": "project",
            "original_text": "数据看板项目：主导表格虚拟滚动与缓存策略",
            "suggested_text": "数据看板项目：主导大表格虚拟滚动与查询缓存策略",
            "reason": "补充技术场景与收益",
        },
        {
            "section": "summary",
            "original_text": "React TypeScript Python SQLite",
            "suggested_text": "React TypeScript Python SQLite（按岗位优先级排列）",
            "reason": "技能清单按岗位优先级排序",
        },
    )
    _install_ai(monkeypatch, cases)
    hints = _run(resume_text)

    assert len(hints.pointers) == 2
    assert len(hints.pointers) < resume_hints.MIN_POINTERS
    assert hints.notice is None, "条数不足不是降级：不应给用户错误原因"


def test_same_anchor_kept_once(monkeypatch: pytest.MonkeyPatch, resume_text: str) -> None:
    """锚点即定位键：两个建议落在同一段原文时只保留一条，避免跳转无区分度。"""
    first = resume_polish_cases()[0]
    _install_ai(monkeypatch, (first, first))
    hints = _run(resume_text)

    keys = [item.focus_key for item in hints.pointers]
    assert len(keys) == len(set(keys)) == 1


# --- 24：未逐字命中整条丢弃（复用反幻觉层，不自写校验）-------------------------


def test_not_verbatim_suggestion_dropped(
    monkeypatch: pytest.MonkeyPatch, resume_text: str
) -> None:
    """AC-4 ③：正文里找不到的原句整条丢弃 —— 要点绝不指向不存在的句子（anti-goal 3）。"""
    cases = (
        {
            "section": "project",
            "original_text": "这段话不在简历正文里",
            "suggested_text": "随便改改",
            "reason": "不存在的句子",
        },
        {
            "section": "project",
            "original_text": "数据看板项目：主导表格虚拟滚动与缓存策略",
            "suggested_text": "数据看板项目：主导大表格虚拟滚动与查询缓存策略",
            "reason": "补充技术场景与收益",
        },
    )
    _install_ai(monkeypatch, cases)
    hints = _run(resume_text)

    anchors = [item.anchor_text for item in hints.pointers]
    assert anchors == ["数据看板项目：主导表格虚拟滚动与缓存策略"]
    assert all(resume_text.find(anchor) >= 0 for anchor in anchors)


# --- 锚点切片与形状（AC-5）---------------------------------------------------


def test_long_anchor_is_verbatim_slice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-5：锚点 ≤40 字且仍是正文逐字切片（不是对原句做归一化或改写）。"""
    cases = (
        {
            "section": "project",
            "original_text": LONG_LINE,
            "suggested_text": f"{LONG_LINE}（量化收益）",
            "reason": "收益缺主语",
        },
    )
    _install_ai(monkeypatch, cases)
    hints = _run(LONG_RESUME)

    assert len(LONG_LINE) > resume_hints.ANCHOR_MAX
    (pointer,) = hints.pointers
    assert pointer.anchor_text == LONG_LINE[: resume_hints.ANCHOR_MAX]
    assert len(pointer.anchor_text) == resume_hints.ANCHOR_MAX
    assert LONG_RESUME.find(pointer.anchor_text) >= 0, "截断后仍必须是正文切片"
    assert pointer.focus_key == pointer.anchor_text


def test_pointer_shape(monkeypatch: pytest.MonkeyPatch, resume_text: str) -> None:
    """AC-5：`focus_key == anchor_text`、`location` 带行号、`issue` 非空且 ≤60 字。"""
    _install_ai(monkeypatch, resume_polish_cases())
    hints = _run(resume_text)

    assert hints.pointers
    for pointer in hints.pointers:
        assert pointer.focus_key == pointer.anchor_text
        assert pointer.anchor_text and resume_text.find(pointer.anchor_text) >= 0
        label, line_part = pointer.location.split(" · 第 ")
        assert label == SECTION_LABEL[pointer.section]
        line = int(line_part.removesuffix(" 行"))
        start = resume_text.find(pointer.anchor_text)
        assert line == resume_text[:start].count("\n") + 1, "行号必须由 start 推出，零猜测"
        assert 0 < len(pointer.issue) <= resume_hints.ISSUE_MAX


def test_issue_is_first_sentence(monkeypatch: pytest.MonkeyPatch, resume_text: str) -> None:
    """`issue` 取 `reason` 的第一句，长尾被切掉（一句话问题）。"""
    cases = (
        {
            "section": "experience",
            "original_text": "2023-2026 前端开发工程师，负责组件库与构建提速",
            "suggested_text": "2023-2026 前端开发工程师，主导组件库建设与构建流程提速",
            "reason": "把「负责」改成「主导」。后半句是解释，不该出现在要点里。",
        },
    )
    _install_ai(monkeypatch, cases)
    (pointer,) = _run(resume_text).pointers

    assert pointer.issue == "把「负责」改成「主导」"
    assert "解释" not in pointer.issue


# --- 26 / 27 / AC-11：两种降级都不抛 -----------------------------------------


def test_no_resume_text_skips_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-6：没有正文 → 中文占位，且**一次模型都不调**（省延迟也省钱）。"""

    async def boom(*_args: Any, **_kwargs: Any) -> list[PolishSuggestion]:
        raise AssertionError("没有正文时不得调用润色引擎")

    monkeypatch.setattr(resume_polish, "build_suggestions", boom)
    for empty in (None, "", "   \n  "):
        hints = _run(empty)
        assert hints.pointers == []
        assert hints.notice == RESUME_NO_TEXT


def test_ai_broken_degrades_without_raising(resume_text: str) -> None:
    """AC-11：模型异常（超时 / 坏 JSON）→ 空列表 + 中文降级原因，绝不向上抛。"""
    hints = _run(resume_text, client=_BrokenClient())

    assert hints.pointers == []
    assert hints.notice == RESUME_AI_FALLBACK


@pytest.mark.usefixtures("_no_ai_key")
def test_ai_not_configured_degrades(resume_text: str) -> None:
    """AC-11：服务端没配 Key 时同样降级（走真实 `AIClient` 的未配置分支）。"""
    hints = _run(resume_text, client=None)

    assert hints.pointers == []
    assert hints.notice == RESUME_AI_FALLBACK


def test_empty_after_validation_degrades(monkeypatch: pytest.MonkeyPatch, resume_text: str) -> None:
    """模型给了东西但全被反幻觉层丢掉：也按降级处理，不返回「静默空」。"""
    _install_ai(
        monkeypatch,
        (
            {
                "section": "project",
                "original_text": "不存在的句子",
                "suggested_text": "换个说法",
                "reason": "无",
            },
        ),
    )
    hints = _run(resume_text)

    assert hints.pointers == []
    assert hints.notice == RESUME_AI_FALLBACK


# --- 28 / 29：静态门禁（无第二份润色提示词、单一入口）------------------------


def test_no_second_polish_prompt() -> None:
    """AC-4 ②：`resume_hints` 里不得出现第二份润色系统提示词（唯一出处是 `resume_polish`）。"""
    source = Path(resume_hints.__file__).read_text(encoding="utf-8")

    for marker in ("你是中文简历润色顾问", "只输出 JSON", "硬性要求", "POLISH_SYSTEM"):
        assert marker not in source, f"resume_hints 不得自带润色提示词片段：{marker}"
    assert "resume_polish.build_suggestions" in source
    assert "resume_polish.validate_suggestions" in source


def test_no_private_validation_duplicate() -> None:
    """AC-4 ③：校验只在 `resume_polish` 里存在 —— 本模块不得重新实现逐字比对。"""
    source = Path(resume_hints.__file__).read_text(encoding="utf-8")

    for marker in ("def validate_", "def _validate", "dropped_count", "_downgrade_numbers"):
        assert marker not in source, f"resume_hints 不得重写校验逻辑：{marker}"


#: 与 conftest `POLISH_CASES` 同形的五条（本文自带一份，保持文件所有权不相交）。
def resume_polish_cases() -> tuple[dict[str, str], ...]:
    return (
        {
            "section": "experience",
            "original_text": "2023-2026 前端开发工程师，负责组件库与构建提速",
            "suggested_text": "2023-2026 前端开发工程师，主导组件库建设与构建流程提速",
            "reason": "把「负责」改成「主导」，让职责与影响力可读",
        },
        {
            "section": "project",
            "original_text": "数据看板项目：主导表格虚拟滚动与缓存策略",
            "suggested_text": "数据看板项目：主导大表格虚拟滚动与查询结果缓存，降低渲染开销",
            "reason": "补充技术场景与收益，避免只有名词堆叠",
        },
        {
            "section": "project",
            "original_text": "表格虚拟滚动",
            "suggested_text": "大表格虚拟滚动",
            "reason": "同一区间的更短表述",
        },
        {
            "section": "education",
            "original_text": "2019-2023 计算机科学与技术 本科",
            "suggested_text": "2019-2023 计算机科学与技术 本科，专业课程与工程实践并重",
            "reason": "教育背景补一句侧重，信息量更足",
        },
        {
            "section": "summary",
            "original_text": "React TypeScript Python SQLite",
            "suggested_text": "React TypeScript Python SQLite（按目标岗位顺序排列）",
            "reason": "技能清单按岗位优先级排序，便于快速匹配",
        },
    )
