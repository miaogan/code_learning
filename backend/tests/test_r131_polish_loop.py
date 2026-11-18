"""r131 回归：镜试缺项回灌修文（user_facts 织入 + 成稿存为新版本）。

口径与 test_resume_polish.py 一致：零网络（替身 AI）、正文用 conftest 的
`resume_text`、TestClient 走 conftest 的 `client`（带 auth_user）。

三条硬断言：
1. user_facts 进提示词、且空列表时提示词与旧路径逐字节一致（纯润色零变化）；
2. 反幻觉门禁对 user_facts 逐字出现的数字 / 专名放行，AI 自行发明的照拦；
3. save-version 落库为新 documents 行（按账号隔离），旧简历正文零变化。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import repository
from app.core.context import set_current_user_id
from app.schemas import PolishUserFact, ResumeMeta
from app.services.ai.ai import AIClient
from app.services.resume.resume_polish import (
    UNFILLED,
    build_suggestions,
    validate_suggestions,
)


def _install_ai(
    monkeypatch: pytest.MonkeyPatch,
    responder: Callable[[type[Any], str], dict[str, Any]],
) -> list[str]:
    """替身 AI，并原样记录每次的 user 提示词（断言 user_facts 是否织入）。"""
    prompts: list[str] = []

    async def fake_complete_model(
        self: AIClient,
        system: str,
        user: str,
        model_cls: type[Any],
        *,
        timeout_s: float | None = None,
        retry_unavailable: bool = False,
    ) -> Any:
        prompts.append(user)
        return model_cls.model_validate(responder(model_cls, user))

    monkeypatch.setattr(AIClient, "complete_model", fake_complete_model)
    return prompts


def _draft_cases() -> tuple[dict[str, str], ...]:
    """两条「幻觉」建议：数字与专名都来自 user_facts 将提供的内容。"""
    return (
        {
            "section": "project",
            "original_text": "数据看板项目：主导表格虚拟滚动与缓存策略",
            "suggested_text": "数据看板项目：QPS 峰值 8000，部署在 Kubernetes 上，主导表格虚拟滚动与缓存策略",
            "reason": "织入候选人补充的规模与组件",
        },
        {
            "section": "summary",
            "original_text": "React TypeScript Python SQLite",
            "suggested_text": "React TypeScript Python SQLite，服务过 8000 万用户",
            "reason": "AI 自己发明的体量（应当被拦）",
        },
    )


# --- service 层：user_facts 织入与门禁放行 ---------------------------------------


def test_user_facts_reach_prompt_and_empty_keeps_bytes(
    monkeypatch: pytest.MonkeyPatch, resume_text: str
) -> None:
    prompts = _install_ai(monkeypatch, lambda _cls, _user: {"suggestions": []})

    facts = [PolishUserFact(text="项目 QPS 峰值 8000，部署在 Kubernetes 上")]
    asyncio.run(build_suggestions(resume_text, None, None, user_facts=facts))
    asyncio.run(build_suggestions(resume_text, None, None))
    assert len(prompts) == 2
    assert "【候选人补充的事实" in prompts[0]
    assert "Kubernetes" in prompts[0]
    assert "【候选人补充的事实" not in prompts[1], "空列表 = 纯润色，提示词不得多出小节"


def test_validate_passes_user_facts_but_still_blocks_ai_inventions(
    resume_text: str,
) -> None:
    from app.schemas import PolishSuggestion

    def _draft(suggested_text: str) -> PolishSuggestion:
        original = "数据看板项目：主导表格虚拟滚动与缓存策略"
        index = resume_text.find(original)
        return PolishSuggestion(
            id="ps-1",
            section="project",
            original_text=original,
            suggested_text=suggested_text,
            reason="织入补充",
            flags=[],
            start=index,
            end=index + len(original),
        )

    facts_text = "项目 QPS 峰值 8000，部署在 Kubernetes 上"

    kept, dropped = validate_suggestions(
        [_draft("数据看板项目：QPS 峰值 8000，部署在 Kubernetes 上")],
        resume_text,
        None,
        extra_text=facts_text,
    )
    assert dropped == 0
    assert UNFILLED not in kept[0].suggested_text
    assert "numeric_added" not in kept[0].flags
    assert "Kubernetes" in kept[0].suggested_text

    # 同一条建议、没有 user_facts → 专名整条丢（旧行为不变：数字降级救不了专名）。
    kept_bare, dropped_bare = validate_suggestions(
        [_draft("数据看板项目：QPS 峰值 8000，部署在 Kubernetes 上")],
        resume_text,
        None,
    )
    assert dropped_bare == 1
    assert kept_bare == []

    # AI 自己发明的新数字（facts 与正文都没有「3」）→ 就地降级，不丢弃（数字路径语义）。
    kept_mixed, dropped_mixed = validate_suggestions(
        [_draft("数据看板项目：QPS 峰值 8000，服务过 3 亿用户")],
        resume_text,
        None,
        extra_text=facts_text,
    )
    assert dropped_mixed == 0
    assert UNFILLED in kept_mixed[0].suggested_text
    assert "3 亿" not in kept_mixed[0].suggested_text
    assert "numeric_added" in kept_mixed[0].flags

    # 专名不在 facts 里 → 专名丢弃路径生效。
    kept_noun, dropped_noun = validate_suggestions(
        [_draft("数据看板项目：主导表格虚拟滚动与缓存策略，基于 Envoy")],
        resume_text,
        None,
        extra_text=facts_text,
    )
    assert dropped_noun == 1
    assert kept_noun == []


# --- 端点层：user_facts 契约 + save-version 落库 ---------------------------------


def _seed_resume(resume_text: str, resume_id: str = "res-131") -> str:
    repository.insert_document(
        ResumeMeta(
            resume_id=resume_id, file_name="简历.txt", chars=len(resume_text), sections=4
        ),
        resume_text,
    )
    return resume_id


def test_polish_endpoint_accepts_user_facts(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    resume_text: str,
) -> None:
    _install_ai(monkeypatch, lambda _cls, _user: {"suggestions": []})
    resume_id = _seed_resume(resume_text)

    response = client.post(
        f"/api/resumes/{resume_id}/polish",
        json={
            "target_role": None,
            "user_facts": [
                {"text": "项目 QPS 峰值 8000，部署在 Kubernetes 上", "section": "project"},
                {"text": "x"},  # 超短：schema 拒绝
            ],
        },
    )
    assert response.status_code == 422, "text 少于 2 字必须被契约拒绝"


def test_polish_endpoint_wires_facts_through(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    resume_text: str,
) -> None:
    prompts = _install_ai(monkeypatch, lambda _cls, _user: {"suggestions": []})
    resume_id = _seed_resume(resume_text)

    response = client.post(
        f"/api/resumes/{resume_id}/polish",
        json={
            "target_role": None,
            "user_facts": [{"text": "项目 QPS 峰值 8000，部署在 Kubernetes 上", "section": None}],
        },
    )
    assert response.status_code == 200
    assert len(prompts) == 1
    assert "【候选人补充的事实" in prompts[0]


def test_save_version_creates_new_document(client: TestClient, resume_text: str) -> None:
    resume_id = _seed_resume(resume_text)
    markdown = (
        "# 修文成稿\n\n数据看板项目：QPS 峰值 8000，部署在 Kubernetes 上，"
        "主导表格虚拟滚动与缓存策略。\n"
    )

    response = client.post(
        f"/api/resumes/{resume_id}/polish/save-version",
        json={"markdown": markdown, "file_name": "修文成稿-测试.md"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["resume_id"] != resume_id
    assert body["sections"] == 1
    assert body["chars"] == len(markdown.strip())

    # 新版本可读、正文逐字入库；旧版本正文零变化。
    assert repository.get_document_text(body["resume_id"]) == markdown.strip()
    assert repository.get_document_text(resume_id) == resume_text

    # 版本列表可见（校勘页数据源），文件名沿用自定义值。
    listed = client.get("/api/resumes?limit=20")
    assert listed.status_code == 200
    names = [item["file_name"] for item in listed.json()]
    assert "修文成稿-测试.md" in names


def test_save_version_generates_default_file_name(
    client: TestClient, resume_text: str
) -> None:
    resume_id = _seed_resume(resume_text)
    markdown = "这是一份足够长的修文成稿正文，用来通过五十个字符的最短门槛。" * 3
    response = client.post(
        f"/api/resumes/{resume_id}/polish/save-version",
        json={"markdown": markdown},
    )
    assert response.status_code == 200
    new_id = response.json()["resume_id"]
    with repository.connection() as conn:
        row = conn.execute(
            "SELECT file_name FROM documents WHERE id = ?", (new_id,)
        ).fetchone()
    assert str(row["file_name"]).startswith("修文成稿-")


def test_save_version_rejects_short_markdown(client: TestClient, resume_text: str) -> None:
    resume_id = _seed_resume(resume_text)
    response = client.post(
        f"/api/resumes/{resume_id}/polish/save-version",
        json={"markdown": "太短了"},
    )
    assert response.status_code == 422, "契约 min_length 先拦"
    assert any("\u4e00" <= ch <= "\u9fff" for ch in response.text)


def test_save_version_rejects_cross_account(client: TestClient, resume_text: str) -> None:
    # 播种时换成别的账号；请求时用默认登录账号 → 按账号隔离必须 404。
    set_current_user_id("somebody-else")
    try:
        resume_id = _seed_resume(resume_text, resume_id="res-other-user")
    finally:
        set_current_user_id(None)
    response = client.post(
        f"/api/resumes/{resume_id}/polish/save-version",
        json={"markdown": "足够长的成稿内容，" * 20},
    )
    assert response.status_code == 404
    assert any("\u4e00" <= ch <= "\u9fff" for ch in response.json()["error"]["message"])
