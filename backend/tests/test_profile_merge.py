"""画像增量合并用例（AC-6 / AC-7 的可执行证据）。

四组断言：
- AC-6 合并：二次上传后 `profile_id` 不变、`updated_at` 刷新、证据旧→新累积且每条在
  其**来源**简历正文里逐字命中、旧简历独有的能力项转 `historical`（不删、证据不丢）。
- AC-7 归一：`normalize_name` 表驱动（全角/大小写/多余空白），同一次草稿里的变体
  只落 1 条记录；`active_skills` 是出题/诊断取数的唯一出口，历史项被隔离；
  active < 3 时 `needs_tech_fallback` 为真（出题侧据此以 `tech_stack` 兜底）。
- 摘要计数：`merge_summary.added/historical/evidence_added` 与合并结果自洽。
- 契约边界：POST 响应带 `merge_summary`，`GET /api/profiles/latest` 的持久契约不扩。

零网络：AI 全部走 `patch_ai`（类级补丁覆盖路由层未注入 client 的真实链路）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from app import repository
from app.schemas import ProfileDraft, ResumeMeta
from app.services import profile_merge
from app.services.profile import generate_profile

#: 跨请求证据累积是否可验：`repository` 的读路径用 `schemas.Profile` 反序列化，未声明
#: `source_quotes`/`status` 时证据链会在读回时被丢弃（等价于 T1 契约尚未落地）。
CONTRACT_READY = profile_merge.SKILL_HAS_EVIDENCE_FIELDS

#: 只有「旧证据必须熬过 DB 往返」的用例受这条约束；合并规则本身由纯函数用例覆盖。
requires_contract = pytest.mark.skipif(
    not CONTRACT_READY,
    reason="待 T1 契约：schemas.ProfileSkill 未声明 source_quotes/status，repository 读路径"
    "（_profile_of → Profile.model_validate_json）会丢弃证据链，跨请求累积不可验；"
    "契约落地后本用例自动生效",
)

#: 第二份差异化简历：保留 `react`（小写变体，用于归一判同）、去掉 SQLite，新增 Go/K8s。
SECOND_RESUME_TEXT = (
    "教育经历\n2019-2023 计算机科学与技术 本科\n"
    "工作经历\n2023-2026 前端开发工程师，负责组件库与构建提速\n"
    "项目经历\n数据看板项目：主导表格虚拟滚动与缓存策略\n"
    "服务端项目：用 Go 实现导出服务\n"
    "技能\nreact TypeScript Python Go Kubernetes"
)

#: 与 `SECOND_RESUME_TEXT` 对应、可逐字溯源的模型草稿。
SECOND_DRAFT: dict[str, Any] = {
    "skills": [
        {"name": "React", "source_quote": "react TypeScript Python Go Kubernetes"},
        {"name": "Go", "source_quote": "react TypeScript Python Go Kubernetes"},
        {"name": "Kubernetes", "source_quote": "react TypeScript Python Go Kubernetes"},
    ],
    "tech_stack": ["React", "TypeScript", "Go", "Kubernetes"],
    "years_experience": 3.5,
    "projects": [
        {
            "name": "数据看板",
            "role": "前端主力",
            "period": "2025-2026",
            "bullets": ["表格虚拟滚动", "查询结果缓存"],
            "source_quote": "数据看板项目：主导表格虚拟滚动与缓存策略",
        },
        {
            "name": "导出服务",
            "role": "服务端开发",
            "period": "2026",
            "bullets": ["批量导出"],
            "source_quote": "服务端项目：用 Go 实现导出服务",
        },
    ],
    "target_role": "后端开发工程师",
}


#: 与 `RESUME_TEXT`（conftest 那份第一简历正文）对应、可逐字溯源的模型草稿。
FIRST_DRAFT: dict[str, Any] = {
    "skills": [
        {"name": "React", "source_quote": "React TypeScript Python SQLite"},
        {"name": "Python", "source_quote": "React TypeScript Python SQLite"},
    ],
    "tech_stack": ["React", "TypeScript", "Python", "SQLite"],
    "years_experience": 3.0,
    "projects": [
        {
            "name": "数据看板",
            "role": "前端主力",
            "period": "2025-2026",
            "bullets": ["表格虚拟滚动"],
            "source_quote": "数据看板项目：主导表格虚拟滚动与缓存策略",
        }
    ],
    "target_role": "前端开发工程师",
}


def _squash(text: str) -> str:
    """与 `verify_quotes` 同一口径（去空白比对），断言「逐字命中」时不重复实现校验。"""
    return "".join(text.split())


def _respond_with(payload: dict[str, Any]) -> Callable[[type[Any], str], dict[str, Any]]:
    def _responder(_model_cls: type[Any], _user: str) -> dict[str, Any]:
        return payload

    return _responder


def _seed_old_profile(
    profile_factory: Callable[..., Any], *, resume_id: str = "res-1"
) -> None:
    """落一份「第一份简历」的画像（React / Python 两项技能 + 1 个项目）。"""
    repository.insert_profile(profile_factory(resume_id=resume_id))


def _old_profile_with_evidence(
    profile_factory: Callable[..., Any],
    *,
    resume_id: str = "res-1",
    file_name: str = "旧简历.txt",
    captured_at: str = "2026-10-31T05:00:00+00:00",
    include_projects: bool = True,
) -> Any:
    """把基座画像升格成「带证据链」的合并模型（契约真源就绪时它就是 `Profile`）

    为什么不用 `profile_factory` 直接塞证据：`source_quotes`/`status` 的声明归属是
    `schemas.py`（T1），conftest 的工厂尚未扩展；本用例在自己这一侧构造契约超集，
    规则验证因此不依赖任何未落地的外部文件。
    """
    base = profile_factory(resume_id=resume_id)
    payload = base.model_dump()
    payload["skills"] = [
        {
            **skill,
            "source_quotes": [
                {
                    "quote": skill["source_quote"],
                    "resume_id": resume_id,
                    "file_name": file_name,
                    "captured_at": captured_at,
                }
            ],
            "status": profile_merge.STATUS_ACTIVE,
        }
        for skill in payload["skills"]
    ]
    payload["projects"] = [
        {
            **project,
            "source_quotes": [
                {
                    "quote": project["source_quote"],
                    "resume_id": resume_id,
                    "file_name": file_name,
                    "captured_at": captured_at,
                }
            ],
            "status": profile_merge.STATUS_ACTIVE,
        }
        for project in payload["projects"]
    ] if include_projects else []
    return profile_merge.MergedProfile.model_validate(payload)


def _seed_document(resume_id: str, text: str, file_name: str) -> None:
    repository.insert_document(
        ResumeMeta(
            resume_id=resume_id,
            file_name=file_name,
            chars=len(text),
            sections=5,
        ),
        text,
    )


def test_same_profile_id_after_second_upload(
    tmp_db: Any, profile_factory: Callable[..., Any], patch_ai: Callable[..., None]
) -> None:
    """AC-6：二次上传只累积，不新增画像行；`updated_at` 刷新。"""
    _seed_old_profile(profile_factory)
    patch_ai(_respond_with(SECOND_DRAFT))

    merged = asyncio.run(generate_profile("res-2", SECOND_RESUME_TEXT))

    assert merged.id == "prof-1", "合并必须沿用同一个 profile_id"
    latest = repository.latest_profile()
    assert latest is not None and latest.id == "prof-1"
    assert latest.resume_id == "res-2", "画像的来源简历应指向本次简历"
    assert latest.updated_at != "2026-10-31T05:00:00+00:00", "updated_at 必须刷新"


@requires_contract
def test_evidence_accumulates_old_to_new(
    tmp_db: Any,
    profile_factory: Callable[..., Any],
    patch_ai: Callable[..., None],
    resume_text: str,
) -> None:
    """AC-6：证据 ≥2 条、顺序旧→新、每条在其**来源**正文逐字命中。"""
    _seed_old_profile(profile_factory)
    _seed_document("res-1", resume_text, "旧简历.txt")
    patch_ai(_respond_with(SECOND_DRAFT))

    merged = asyncio.run(generate_profile("res-2", SECOND_RESUME_TEXT))

    react = next(skill for skill in merged.skills if profile_merge.normalize_name(skill.name) == "react")
    assert len(react.source_quotes) >= 2, "同一能力项的证据必须累积到 ≥2 条"

    sources = {"res-1": resume_text, "res-2": SECOND_RESUME_TEXT}
    for index, evidence in enumerate(react.source_quotes):
        assert evidence.resume_id in sources, "证据必须记录来源简历"
        assert _squash(evidence.quote) in _squash(sources[evidence.resume_id]), (
            f"第 {index + 1} 条证据在其来源简历里找不到逐字出处"
        )
    assert react.source_quotes[0].resume_id == "res-1", "证据顺序必须是旧→新"
    assert react.source_quotes[-1].resume_id == "res-2"
    assert react.source_quote == react.source_quotes[0].quote, "兼容字段恒等于首条证据"


def test_evidence_chain_accumulates_old_to_new(
    tmp_db: Any, profile_factory: Callable[..., Any], resume_text: str
) -> None:
    """AC-6（合并规则层）：旧证据在前、本次简历证据在后，每条在其**来源**正文逐字命中。

    与 `test_evidence_accumulates_old_to_new`（走 DB 往返）互补：这里把旧证据直接带进
    合并输入，验证的是判定与拼装规则本身，不受读路径契约影响。
    """
    old = _old_profile_with_evidence(profile_factory, resume_id="res-1", file_name="旧简历.txt")
    draft = ProfileDraft.model_validate(SECOND_DRAFT)

    merged, summary = profile_merge.merge_profile(
        old,
        draft,
        resume_id="res-2",
        file_name="新简历.txt",
        captured_at="2026-10-31T12:00:00+00:00",
    )

    react = next(
        skill for skill in merged.skills if profile_merge.normalize_name(skill.name) == "react"
    )
    assert [item.resume_id for item in react.source_quotes] == ["res-1", "res-2"], (
        "证据顺序必须是旧→新"
    )
    sources = {"res-1": resume_text, "res-2": SECOND_RESUME_TEXT}
    for evidence in react.source_quotes:
        assert _squash(evidence.quote) in _squash(sources[evidence.resume_id]), (
            "每条证据都必须在其来源简历里逐字命中"
        )
        assert evidence.file_name, "证据必须记录来源文件名（画像页「来源 · 文件名」）"
    assert react.source_quote == react.source_quotes[0].quote, "兼容字段恒等于首条证据"
    assert summary.evidence_added == 2, "React 与项目各追加 1 条证据"


def test_same_resume_evidence_not_appended(profile_factory: Callable[..., Any]) -> None:
    """AC-6：同一份简历（同来源 + 同原文）再次合并不得给同一条目追加重复证据。"""
    old = _old_profile_with_evidence(profile_factory, resume_id="res-1", include_projects=False)
    draft = ProfileDraft.model_validate(FIRST_DRAFT)

    merged, summary = profile_merge.merge_profile(
        old,
        draft,
        resume_id="res-1",
        file_name="简历.txt",
        captured_at="2026-10-31T12:00:00+00:00",
        duplicate=True,
    )

    react = next(
        skill for skill in merged.skills if profile_merge.normalize_name(skill.name) == "react"
    )
    assert len(react.source_quotes) == 1, "同源同文的证据不得重复追加"
    assert summary.evidence_added == 0
    assert summary.duplicate is True


def test_merged_payload_roundtrip_keeps_evidence(tmp_db: Any) -> None:
    """落库形状：合并结果序列化后再反序列化，证据链与历史标记不得丢（DB payload 是证据的载体）。"""
    old = None
    draft = ProfileDraft.model_validate(SECOND_DRAFT)
    merged, _summary = profile_merge.merge_profile(
        old,
        draft,
        resume_id="res-2",
        file_name="新简历.txt",
        captured_at="2026-10-31T12:00:00+00:00",
    )

    restored = profile_merge.MergedProfile.model_validate_json(merged.model_dump_json())
    react = next(
        skill for skill in restored.skills if profile_merge.normalize_name(skill.name) == "react"
    )
    assert react.source_quotes and react.source_quotes[0].resume_id == "res-2"
    assert react.status == profile_merge.STATUS_ACTIVE


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Python", "python "),
        ("Python", "Ｐｙｔｈｏｎ"),
        ("React  Native", "react native"),
        ("Go", " Go "),
    ],
)
def test_normalize_table_driven(left: str, right: str) -> None:
    """AC-7：去首尾空白 + 大小写不敏感 + 全角/半角归一后判同。"""
    assert profile_merge.normalize_name(left) == profile_merge.normalize_name(right)
    assert profile_merge.normalize_name("") == ""


def test_draft_variants_collapse_single_entry(
    tmp_db: Any, profile_factory: Callable[..., Any]
) -> None:
    """AC-7：同一次草稿里的同一能力项（不同写法）只落 1 条记录。"""
    variants: dict[str, Any] = {
        **SECOND_DRAFT,
        "skills": [
            {"name": "Python", "source_quote": "react TypeScript Python Go Kubernetes"},
            {"name": "python ", "source_quote": "react TypeScript Python Go Kubernetes"},
            {"name": "Ｐｙｔｈｏｎ", "source_quote": "react TypeScript Python Go Kubernetes"},
        ],
    }
    draft = ProfileDraft.model_validate(variants)
    merged, summary = profile_merge.merge_profile(
        profile_factory(),
        draft,
        resume_id="res-2",
        file_name="新简历.txt",
        captured_at="2026-10-31T12:00:00+00:00",
    )

    python_items = [
        skill for skill in merged.skills if profile_merge.normalize_name(skill.name) == "python"
    ]
    assert len(python_items) == 1, "同一能力项的多种写法必须归并为 1 条"
    assert python_items[0].name == "Python", "名称保留首次出现的写法，避免展示抖动"
    assert summary.added == 0, "命中旧项不算新增"


def test_historical_kept_and_isolated(
    tmp_db: Any, profile_factory: Callable[..., Any], patch_ai: Callable[..., None]
) -> None:
    """AC-6/7：旧简历独有的能力项标 historical（不删、证据不丢），且不进 active 集合。"""
    _seed_old_profile(profile_factory)
    patch_ai(_respond_with(SECOND_DRAFT))

    merged = asyncio.run(generate_profile("res-2", SECOND_RESUME_TEXT))

    python_item = next(
        skill for skill in merged.skills if profile_merge.normalize_name(skill.name) == "python"
    )
    assert python_item.status == profile_merge.STATUS_HISTORICAL
    assert python_item.source_quotes, "转历史的能力项证据不得丢失"

    active = profile_merge.active_skills(merged)
    assert {profile_merge.normalize_name(skill.name) for skill in active} == {
        "react",
        "go",
        "kubernetes",
    }, "active 能力项数必须等于最新简历出现的能力项数"
    assert profile_merge.normalize_name(python_item.name) not in {
        profile_merge.normalize_name(skill.name) for skill in active
    }, "历史项不得出现在出题/诊断取数的 active 集合里"


def test_merge_summary_counts(
    tmp_db: Any, profile_factory: Callable[..., Any], patch_ai: Callable[..., None]
) -> None:
    """摘要计数自洽：新增 2（Go/K8s）、转历史 1（Python）、证据净增 2（React + 项目）。"""
    _seed_old_profile(profile_factory)
    patch_ai(_respond_with(SECOND_DRAFT))

    merged = asyncio.run(generate_profile("res-2", SECOND_RESUME_TEXT))
    summary = merged.merge_summary

    assert summary is not None
    assert summary.added == 2
    assert summary.historical == 1
    assert summary.evidence_added == 2
    assert summary.duplicate is False
    assert merged.tech_stack == ["React", "TypeScript", "Go", "Kubernetes"], "技术栈取新简历"
    assert merged.target_role == "后端开发工程师"
    assert merged.years_experience == 3.5


def test_tech_stack_fallback_when_active_lt_3(
    tmp_db: Any, profile_factory: Callable[..., Any]
) -> None:
    """AC-7：active 能力项 <3 时出题须以 `tech_stack` 补齐（`needs_tech_fallback` 为真）。"""
    old = profile_factory()
    old.skills = [old.skills[0]]  # 只留 React 一项 active
    repository.insert_profile(old)

    draft = ProfileDraft.model_validate(
        {
            "skills": [{"name": "React", "source_quote": "react TypeScript Python Go Kubernetes"}],
            "tech_stack": ["React", "TypeScript", "Go", "Kubernetes"],
            "years_experience": 3.5,
            "projects": [],
            "target_role": None,
        }
    )
    merged, _summary = profile_merge.merge_profile(
        old,
        draft,
        resume_id="res-2",
        file_name="新简历.txt",
        captured_at="2026-10-31T12:00:00+00:00",
    )

    assert profile_merge.needs_tech_fallback(merged) is True
    assert merged.tech_stack == ["React", "TypeScript", "Go", "Kubernetes"], "兜底素材正是 tech_stack"
    assert merged.target_role == "前端开发工程师", "新简历没写目标岗位时沿用旧值（不丢已知信息）"


@requires_contract
def test_duplicate_same_resume_keeps_evidence(
    tmp_db: Any, patch_ai: Callable[..., None], resume_text: str
) -> None:
    """Q4：同一份简历再次生成 → `duplicate=true`，证据不重复追加，画像行仍只有一条。"""
    _seed_document("res-1", resume_text, "简历.txt")
    patch_ai(_respond_with(FIRST_DRAFT))

    first = asyncio.run(generate_profile("res-1", resume_text))
    assert first.merge_summary is not None and first.merge_summary.duplicate is False

    second = asyncio.run(generate_profile("res-1", resume_text))
    assert second.merge_summary is not None and second.merge_summary.duplicate is True
    assert second.id == first.id, "同一画像行，不新增"
    assert second.merge_summary.evidence_added == 0, "同一份简历不涨证据"

    react = next(
        skill for skill in second.skills if profile_merge.normalize_name(skill.name) == "react"
    )
    assert len(react.source_quotes) == 1, "重复上传不得追加同源同文的证据"


def test_post_returns_merge_summary_but_get_does_not(
    client: Any, profile_factory: Callable[..., Any], patch_ai: Callable[..., None]
) -> None:
    """契约边界：一次性 `merge_summary` 只挂 POST；GET 的持久契约不扩（DESIGN §7-1）。"""
    _seed_old_profile(profile_factory, resume_id="res-1")
    _seed_document("res-2", SECOND_RESUME_TEXT, "新简历.txt")
    patch_ai(_respond_with(SECOND_DRAFT))

    created = client.post("/api/resumes/res-2/profile")
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["id"] == "prof-1"
    assert body["merge_summary"]["added"] == 2

    latest = client.get("/api/profiles/latest")
    assert latest.status_code == 200, latest.text
    assert "merge_summary" not in latest.json(), "GET 不得带一次性摘要字段"
