"""r116：溯源校验的「概率性失败」——归一化口径与失败降级路径。

背景（用户实测反馈）：同一份简历上传，有时成功有时报「在简历原文中找不到出处」。
根因两条，本文件逐条钉住：

1. **假失配**：`_squash` 只去空白，吃不掉 PDF 抽取留下的不可见格式字符（`Cf` 类）与
   模型「顺手改掉」的全半角差异，于是引用跨过这些位置就失败、没跨过就成功。
2. **失败被放大**：任一条不合格即整份 502 ⇒ 成功率 `(1-p)^N`，15 条 × 单条 5% 只剩 46%。
   改为「补抽一次 → 逐条剔除 → 一条不剩才报错」，anti-goal 1（不落无源之词）不变。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.core.errors import AI_SCHEMA_INVALID, AppError
from app.schemas import ProfileDraft
from app.services.profile import profile as profile_service

INVENTED = "精通 Kubernetes 多集群运维与 Istio 服务网格治理"

#: 正文里带软连字符（`U+00AD`）：pypdf 在行尾断词处就会留下它，模型「看不见」也不会复制。
SOFT_HYPHEN_RESUME = (
    "工作经历\n2023-2026 负责 micro\u00adservice 架构设计与落地\n"
    "项目经历\n数据看板项目：主导表格虚拟滚动与缓存策略\n"
    "技能\nReact TypeScript Python"
)


def _draft(quotes: list[str], projects: list[dict[str, Any]] | None = None) -> ProfileDraft:
    return ProfileDraft.model_validate(
        {
            "skills": [
                {"name": f"技能{index}", "source_quote": quote}
                for index, quote in enumerate(quotes)
            ],
            "tech_stack": ["React"],
            "years_experience": 3.0,
            "projects": projects or [],
            "target_role": "前端开发工程师",
        }
    )


# --- 1. 归一化口径：把「不可见 / 全半角」差异当同一句话 -------------------------


@pytest.mark.parametrize(
    "invisible",
    [
        "\u00ad",  # 软连字符（PDF 行尾断词）
        "\u200b",  # 零宽空格
        "\u200c",  # 零宽非连接符
        "\u200d",  # 零宽连接符
        "\ufeff",  # BOM
        "\u2060",  # word joiner
    ],
)
def test_invisible_format_chars_do_not_break_sourcing(invisible: str) -> None:
    """正文带不可见格式字符、引用没有它 —— 这是同一句话，不得判成编造。"""
    haystack = f"负责 micro{invisible}service 架构设计与落地"
    assert profile_service._squash("负责 microservice 架构设计与落地") == (
        profile_service._squash(haystack)
    )


def test_fullwidth_halfwidth_difference_is_tolerated() -> None:
    """模型把 `（）：` 写成 `():` 不改变语义，不应因此判死。"""
    haystack = profile_service._squash("技能：Python（Django）React")
    assert profile_service._squash("技能:Python(Django)React") in haystack


def test_nfkc_normalization_does_not_swallow_real_differences() -> None:
    """归一化只抹平「同一段文字的不同写法」，不能把改写字句放过去。"""
    haystack = profile_service._squash("2023-2026 负责组件库与构建提速")
    assert profile_service._squash("2023-2026 主导组件库建设") not in haystack


# --- 2. 尾部省略号：截断可以，改写与拼接不行 ---------------------------------


def test_trailing_ellipsis_is_tolerated() -> None:
    """模型抄到一半用「…」收尾很常见，那是截断不是编造。"""
    draft = _draft(["主导表格虚拟滚动…"])
    assert profile_service.unsourced_labels(draft, SOFT_HYPHEN_RESUME) == []


def test_ellipsis_in_the_middle_is_not_tolerated() -> None:
    """中间出现省略号意味着拼接了两段不相邻的原文，必须仍判没命中。"""
    draft = _draft(["主导表格…与缓存策略"])
    assert profile_service.unsourced_labels(draft, SOFT_HYPHEN_RESUME) == ["技能0"]


def test_paraphrase_is_still_rejected() -> None:
    """放宽归一化不等于放宽真实性：改写过的引用仍然没有出处。"""
    draft = _draft(["主导了表格虚拟滚动和缓存优化"])
    assert profile_service.unsourced_labels(draft, SOFT_HYPHEN_RESUME) == ["技能0"]


# --- 3. 逐条剔除：宁缺毋滥，但不牵连整份 -------------------------------------


def test_drop_unsourced_removes_only_the_bad_entries() -> None:
    draft = _draft(
        ["React TypeScript Python", INVENTED],
        projects=[
            {
                "name": "数据看板",
                "role": None,
                "period": None,
                "bullets": [],
                "source_quote": "数据看板项目：主导表格虚拟滚动与缓存策略",
            },
            {
                "name": "编造项目",
                "role": None,
                "period": None,
                "bullets": [],
                "source_quote": INVENTED,
            },
        ],
    )

    dropped = profile_service.drop_unsourced(draft, SOFT_HYPHEN_RESUME)

    assert dropped == ["技能1", "编造项目"]
    assert [skill.source_quote for skill in draft.skills] == ["React TypeScript Python"]
    assert [project.name for project in draft.projects] == ["数据看板"]
    # 剔除之后整份画像必须能过最终闸门（否则剔除路径本身就不可用）
    assert profile_service.verify_quotes(draft, SOFT_HYPHEN_RESUME) is None


def test_unsourced_labels_does_not_mutate_draft() -> None:
    """`unsourced_labels` 是只读的：它只负责「报告」，剔除与否由调用方决定。"""
    draft = _draft(["React TypeScript Python", INVENTED])
    before = [skill.source_quote for skill in draft.skills]

    profile_service.unsourced_labels(draft, SOFT_HYPHEN_RESUME)

    assert [skill.source_quote for skill in draft.skills] == before


# --- 4. 编排：成功路径一次、失败路径补抽、补抽更差则回退 ---------------------


def _payload(*quotes: str) -> dict[str, Any]:
    return {
        "skills": [
            {"name": f"技能{index}", "source_quote": quote}
            for index, quote in enumerate(quotes)
        ],
        "tech_stack": ["React"],
        "years_experience": 3.0,
        "projects": [],
        "target_role": "前端开发工程师",
    }


def test_soft_hyphen_resume_no_longer_fails_end_to_end(tmp_db: Any, fake_ai: Any) -> None:
    """用户报的那条路径：PDF 抽出软连字符 → 模型抄成干净写法 → 现在应当成功且只调一次模型。"""
    fake_ai.responder = lambda _model_cls, _user: _payload("负责 microservice 架构设计与落地")

    profile = asyncio.run(
        profile_service.generate_profile("res-h", SOFT_HYPHEN_RESUME, client=fake_ai)
    )

    assert [skill.source_quote for skill in profile.skills] == ["负责 microservice 架构设计与落地"]
    assert len(fake_ai.calls) == 1, "成功路径不得因为归一化而多调一次模型"


def test_repair_attempt_succeeds_and_carries_the_offenders(tmp_db: Any, fake_ai: Any) -> None:
    """补抽一次并把「哪几条没命中」写进提示：模型据此纠正后，整份画像不该丢条目。"""
    payloads = [
        _payload("React TypeScript Python", "完全编造的一段话"),
        _payload("React TypeScript Python", "数据看板项目：主导表格虚拟滚动与缓存策略"),
    ]
    fake_ai.responder = lambda _model_cls, _user: payloads.pop(0)

    profile = asyncio.run(
        profile_service.generate_profile("res-r", SOFT_HYPHEN_RESUME, client=fake_ai)
    )

    assert len(profile.skills) == 2, "补抽成功后不得再剔除任何条目"
    assert len(fake_ai.calls) == 2
    second_prompt = fake_ai.calls[1][1]
    assert "技能1" in second_prompt, "补抽提示必须点名没命中的条目"
    assert profile_service.QUOTE_REPAIR_HINT.split("{labels}")[0].strip() in second_prompt


def test_worse_repair_is_discarded(tmp_db: Any, fake_ai: Any) -> None:
    """补抽反而更差时保留第一版：不能拿更烂的草稿去赌，否则等于随机降级。"""
    payloads = [
        _payload("React TypeScript Python", "编造一"),
        _payload("编造一", "编造二", "编造三"),
    ]
    fake_ai.responder = lambda _model_cls, _user: payloads.pop(0)

    profile = asyncio.run(
        profile_service.generate_profile("res-w", SOFT_HYPHEN_RESUME, client=fake_ai)
    )

    assert [skill.source_quote for skill in profile.skills] == ["React TypeScript Python"]


def test_all_entries_unsourced_still_raises(tmp_db: Any, fake_ai: Any) -> None:
    """一条都站不住 = 整份在编，必须 502（可重试），不能落一份空画像。"""
    fake_ai.responder = lambda _model_cls, _user: _payload(INVENTED, INVENTED + "（二）")

    with pytest.raises(AppError) as excinfo:
        asyncio.run(
            profile_service.generate_profile("res-a", SOFT_HYPHEN_RESUME, client=fake_ai)
        )

    assert excinfo.value.code == AI_SCHEMA_INVALID
    assert excinfo.value.status == 502
    assert excinfo.value.retryable is True


def test_verify_quotes_stays_strict() -> None:
    """最终闸门不放宽：`verify_quotes` 仍是「一条不合格 → 整份拒绝」。"""
    draft = _draft(["React TypeScript Python", INVENTED])
    with pytest.raises(AppError) as excinfo:
        profile_service.verify_quotes(draft, SOFT_HYPHEN_RESUME)
    assert excinfo.value.code == AI_SCHEMA_INVALID
