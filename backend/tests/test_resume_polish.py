"""T4 回归：润色 service 单一入口 + 两端点（AC-8 / 9 / 11 / 12 / 13）。

口径：全程零网络（`patch_ai` 类级补丁或 `AIClient.complete_model` 计数补丁），
正文一律用 conftest 的 `RESUME_TEXT`（建议模板的 `original_text` 逐字取自它）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import repository
from app.schemas import PolishResponse, PolishSuggestion, ResumeMeta
from app.services.ai.ai import AIClient
from app.services.resume.resume_polish import (
    MIN_SECTIONS,
    MIN_SUGGESTIONS,
    UNFILLED,
    build_suggestions,
    compose_full,
    insufficient_reason,
    validate_suggestions,
)

DEFAULT_ROLE = "前端开发工程师"

#: 反幻觉用例：新增数字（8000 万）+ 新增专名（GMV）都必须被挡在成稿之外。
HALLUCINATED_CASES: tuple[dict[str, str], ...] = (
    {
        "section": "project",
        "original_text": "数据看板项目：主导表格虚拟滚动与缓存策略",
        "suggested_text": "数据看板项目：2023 年 GMV 8000 万，主导表格虚拟滚动与缓存策略",
        "reason": "补充业务结果（这条应当被降级或整条丢弃）",
    },
    {
        "section": "summary",
        "original_text": "React TypeScript Python SQLite",
        "suggested_text": "React TypeScript Python SQLite，服务过 8000 万用户",
        "reason": "补一句体量（纯数字新增，应降级为〈待补充〉而不是丢弃）",
    },
)


def _payload(cases: tuple[dict[str, str], ...], prefix: str = "ps") -> dict[str, Any]:
    return {
        "suggestions": [
            {**case, "id": f"{prefix}-{index}"}
            for index, case in enumerate(cases, start=1)
        ]
    }


def _seed_resume(
    resume_text: str, resume_id: str = "res-1", file_name: str = "简历.txt"
) -> str:
    repository.insert_document(
        ResumeMeta(
            resume_id=resume_id, file_name=file_name, chars=len(resume_text), sections=4
        ),
        resume_text,
    )
    return resume_id


def _install_ai(
    monkeypatch: pytest.MonkeyPatch,
    responder: Callable[[type[Any], str], dict[str, Any]],
) -> list[type[Any]]:
    """替身 AI + 调用计数（验证「同一份建议集只调一次模型」）。"""
    calls: list[type[Any]] = []

    async def fake_complete_model(
        self: AIClient,
        system: str,
        user: str,
        model_cls: type[Any],
        *,
        timeout_s: float | None = None,
        retry_unavailable: bool = False,
    ) -> Any:
        calls.append(model_cls)
        return model_cls.model_validate(responder(model_cls, user))

    monkeypatch.setattr(AIClient, "complete_model", fake_complete_model)
    return calls


@pytest.fixture(autouse=True)
def _clean_polish_cache() -> Any:
    from app.services.resume import resume_polish

    resume_polish.clear_cache()
    yield
    resume_polish.clear_cache()


# --- service 层（无 FastAPI 上下文，AC-13 单入口）--------------------------------


def test_original_text_byte_equal(
    monkeypatch: pytest.MonkeyPatch,
    resume_text: str,
    polish_responder: Callable[[type[Any], str], dict[str, Any]],
) -> None:
    """AC-8/11：建议与正文逐字对齐，`start/end` 切出的就是 `original_text` 本身。"""
    _install_ai(monkeypatch, polish_responder)

    suggestions = asyncio.run(build_suggestions(resume_text, None, None))
    kept, dropped = validate_suggestions(suggestions, resume_text, None)

    assert dropped == 0, "标准模板不含新增数字/专名，不应被丢弃"
    assert len(kept) >= MIN_SUGGESTIONS
    assert len({item.section for item in kept}) >= MIN_SECTIONS
    assert insufficient_reason(kept) is None
    for item in kept:
        assert resume_text[item.start : item.end] == item.original_text
        assert item.original_text in resume_text
        assert item.id.startswith("ps-")


def test_covers_two_sections(resume_text: str) -> None:
    """AC-8：≥3 条且覆盖 ≥2 个 section；非逐字原句丢弃；不足时给中文说明。"""
    cases = (
        ("experience", "2023-2026 前端开发工程师，负责组件库与构建提速"),
        ("education", "2019-2023 计算机科学与技术 本科"),
        ("summary", "React TypeScript Python SQLite"),
    )
    draft = [
        PolishSuggestion(
            id=f"ps-{index}",
            section=section,  # type: ignore[arg-type]
            original_text=original,
            suggested_text=f"{original}（措辞更主动）",
            reason="措辞更主动",
        )
        for index, (section, original) in enumerate(cases, start=1)
    ]
    kept, dropped = validate_suggestions(draft, resume_text, None)

    assert dropped == 0
    assert len(kept) >= MIN_SUGGESTIONS
    assert len({item.section for item in kept}) >= MIN_SECTIONS
    assert insufficient_reason(kept) is None

    nonverbatim = PolishSuggestion(
        id="ps-x",
        section="project",
        original_text="不存在的原句（应被丢弃）",
        suggested_text="无从定位",
        reason="占位",
    )
    kept_all, dropped_all = validate_suggestions([*kept, nonverbatim], resume_text, None)
    assert dropped_all == 1
    assert len(kept_all) == len(kept)
    for item in kept_all:
        assert resume_text[item.start : item.end] == item.original_text

    reason = insufficient_reason(kept_all[:1])
    assert reason is not None
    assert any("\u4e00" <= char <= "\u9fff" for char in reason), "说明必须是中文"
    assert "条" in reason and "部分" in reason


def test_hallucinated_numbers_downgraded_and_proper_nouns_dropped(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    resume_text: str,
) -> None:
    """AC-9：新增专名整条丢弃；纯新增数字就地降级为〈待补充〉，响应体不含伪数字。"""
    calls = _install_ai(
        monkeypatch, lambda _cls, _user: _payload(HALLUCINATED_CASES)
    )
    resume_id = _seed_resume(resume_text)

    response = client.post(f"/api/resumes/{resume_id}/polish", json={"target_role": None})
    assert response.status_code == 200
    body = response.json()

    assert len(calls) == 1
    assert body["dropped_count"] == 1, "带 GMV 的那条应整条丢弃"
    assert "8000" not in response.text, "伪数字不得出现在响应任何字段"
    assert "GMV" not in response.text
    kept = body["suggestions"]
    assert len(kept) == 1
    assert UNFILLED in kept[0]["suggested_text"]
    assert "numeric_added" in kept[0]["flags"]

    full = client.post(
        f"/api/resumes/{resume_id}/polish/full", json={"polish_id": body["polish_id"]}
    )
    assert full.status_code == 200
    assert "8000" not in full.text, "成稿同样不得原样带出伪数字"
    assert "GMV" not in full.text
    assert UNFILLED in full.json()["markdown"]


def test_compose_full_single_source_and_interval_assembly(resume_text: str) -> None:
    """AC-11：成稿按区间拼装；重叠条目只取一条；未采纳区间逐字保留。"""
    from app.schemas import PolishSuggestion

    suggestions = [
        PolishSuggestion(
            id="ps-1",
            section="project",
            original_text="数据看板项目：主导表格虚拟滚动与缓存策略",
            suggested_text="数据看板项目：主导大表格虚拟滚动与查询结果缓存",
            reason="更具体",
            start=resume_text.index("数据看板项目：主导表格虚拟滚动与缓存策略"),
            end=resume_text.index("数据看板项目：主导表格虚拟滚动与缓存策略")
            + len("数据看板项目：主导表格虚拟滚动与缓存策略"),
        ),
        PolishSuggestion(
            id="ps-2",
            section="project",
            original_text="表格虚拟滚动",
            suggested_text="大表格虚拟滚动",
            reason="重叠片段",
            start=resume_text.index("表格虚拟滚动"),
            end=resume_text.index("表格虚拟滚动") + len("表格虚拟滚动"),
        ),
    ]

    markdown = compose_full(resume_text, suggestions, ["ps-1", "ps-2"], target_role=DEFAULT_ROLE)
    header, _, body = markdown.partition("\n\n> ")
    assert header == "# 简历（润色版）"
    assert f"目标岗位：{DEFAULT_ROLE}" in markdown
    assert "数据看板项目：主导大表格虚拟滚动与查询结果缓存" in body
    assert body.count("大表格虚拟滚动") == 1, "与 ps-1 重叠的 ps-2 不得二次替换"
    assert "教育经历" in body and "技能" in body
    assert body.count("数据看板项目") == 1

    only_first = compose_full(resume_text, suggestions, ["ps-1"], target_role=DEFAULT_ROLE)
    assert "表格虚拟滚动" in only_first
    assert "大表格虚拟滚动" in only_first


# --- 端点（AC-8/9/12）---------------------------------------------------------


def test_polish_endpoint_returns_suggestions_and_does_not_touch_text(
    client: TestClient,
    patch_ai: Callable[[Callable[[type[Any], str], dict[str, Any]]], None],
    polish_responder: Callable[[type[Any], str], dict[str, Any]],
    profile_factory: Callable[..., Any],
    resume_text: str,
    assert_chinese: Callable[[str], None],
) -> None:
    """AC-8/10/12：端点给出 ≥3 条建议；正文与画像字节级不变。"""
    profile = profile_factory()
    repository.insert_profile(profile)
    resume_id = _seed_resume(resume_text)
    patch_ai(polish_responder)

    response = client.post(f"/api/resumes/{resume_id}/polish", json={"target_role": None})
    assert response.status_code == 200
    body = response.json()

    assert body["polish_id"]
    assert body["resume_id"] == resume_id
    assert body["target_role"] == DEFAULT_ROLE, "缺省沿用画像的目标岗位"
    assert len(body["suggestions"]) >= MIN_SUGGESTIONS
    assert len({item["section"] for item in body["suggestions"]}) >= MIN_SECTIONS
    assert body["insufficient_reason"] is None
    assert body["dropped_count"] == 0

    assert repository.get_document_text(resume_id) == resume_text
    latest = repository.latest_profile()
    assert latest is not None and latest.target_role == DEFAULT_ROLE


def test_polish_response_carries_verbatim_resume_text(
    client: TestClient,
    patch_ai: Callable[[Callable[[type[Any], str], dict[str, Any]]], None],
    polish_responder: Callable[[type[Any], str], dict[str, Any]],
    resume_text: str,
) -> None:
    """R-1（AC-1/2）：响应正文与 `documents.text` 逐字相等，源文件名随响应回传（AC-7）。

    「原版」Tab 只认这份 `resume_text`，因此服务端必须立住「逐字、字节级不变」这条
    真源保证：前端一旦渲染走形（例如 Markdown 剥掉 `#` / `-` 前缀），这里就是唯一能
    定位归因的断言。
    """
    resume_id = _seed_resume(resume_text, file_name="张三-前端-简历.pdf")
    patch_ai(polish_responder)

    response = client.post(f"/api/resumes/{resume_id}/polish", json={"target_role": None})
    assert response.status_code == 200
    body = response.json()

    document = repository.get_document(resume_id)
    assert document is not None
    assert document["text"] == resume_text, "落库正文本身不应被润色链路改动"
    assert body["resume_text"] == resume_text
    assert body["resume_text"] == document["text"], "响应正文必须与 documents.text 逐字相等"
    assert len(body["resume_text"]) == len(document["text"]), "长度全等（无 trim / 归一）"
    assert body["resume_text"].encode() == document["text"].encode(), "字节级相等（含换行/空白）"
    assert body["file_name"] == "张三-前端-简历.pdf", "文件名源自 documents.file_name，不得自造"


def test_polish_response_file_name_empty_when_missing(
    client: TestClient,
    patch_ai: Callable[[Callable[[type[Any], str], dict[str, Any]]], None],
    polish_responder: Callable[[type[Any], str], dict[str, Any]],
    resume_text: str,
) -> None:
    """AC-8：源文件名缺失时回落空串；日期格式的兜底命名由前端 `lib/exportName` 负责。"""
    resume_id = _seed_resume(resume_text, resume_id="res-no-name", file_name="")
    patch_ai(polish_responder)

    response = client.post(f"/api/resumes/{resume_id}/polish", json={"target_role": None})
    assert response.status_code == 200
    body = response.json()

    assert body["file_name"] == ""
    assert body["resume_text"] == resume_text, "文件名缺失不影响正文真源"


def test_polish_full_does_not_carry_resume_text(
    client: TestClient,
    patch_ai: Callable[[Callable[[type[Any], str], dict[str, Any]]], None],
    polish_responder: Callable[[type[Any], str], dict[str, Any]],
    resume_text: str,
) -> None:
    """TECHNICAL §5/AC-5：长正文只走 `/polish` 一趟；成稿响应只回 `markdown`，不重复携带正文/文件名。

    `resume_text` 是独立只读通道，不参与成稿拼装：`PolishFullResponse` 字段集必须与 r3
    完全一致，加字段就等于给成稿通道开了第二份正文真源。
    """
    resume_id = _seed_resume(resume_text)
    patch_ai(polish_responder)

    first = client.post(f"/api/resumes/{resume_id}/polish", json={"target_role": None})
    assert first.status_code == 200
    polish_id = first.json()["polish_id"]

    full = client.post(
        f"/api/resumes/{resume_id}/polish/full", json={"polish_id": polish_id}
    )
    assert full.status_code == 200
    payload = full.json()

    assert set(payload) == {"id", "markdown", "dropped_count", "regenerated"}
    assert "resume_text" not in payload
    assert "file_name" not in payload
    assert '"resume_text"' not in full.text, "成稿响应体也不得挟带正文字段"
    assert payload["regenerated"] is False, "命中同一份建议集缓存，不重复调模型"


def test_end_to_end_upload_polish_full_terminal_state(
    client: TestClient,
    patch_ai: Callable[[Callable[[type[Any], str], dict[str, Any]]], None],
    polish_responder: Callable[[type[Any], str], dict[str, Any]],
    resume_text: str,
) -> None:
    """E2E 终态：真实上传 → `/polish` → `/polish/full` 三跳走完，逐跳核对落库真源。

    这一例不自己 `insert_document`，走的是用户真实路径（`POST /api/resumes` 多部分上传 +
    解析入库），因此同时验证了「上传落库的 `file_name` / `text` 经润色契约原样回传」
    这条 T1 才闭合的链路；终态是 `/polish/full` 返回的成稿响应。
    """
    patch_ai(polish_responder)

    upload = client.post(
        "/api/resumes",
        files={
            "file": ("张三-前端-简历.txt", resume_text.encode("utf-8"), "text/plain")
        },
    )
    assert upload.status_code == 200, upload.text
    meta = upload.json()
    resume_id = meta["resume_id"]
    assert meta["file_name"] == "张三-前端-简历.txt"

    stored = repository.get_document_text(resume_id)
    assert stored is not None and stored.strip()

    polish = client.post(f"/api/resumes/{resume_id}/polish", json={"target_role": None})
    assert polish.status_code == 200, polish.text
    body = polish.json()
    assert body["resume_text"] == stored, "上传落库的正文经契约原样回传（无再加工）"
    assert body["file_name"] == meta["file_name"], "文件名同源（documents.file_name）"

    full = client.post(
        f"/api/resumes/{resume_id}/polish/full", json={"polish_id": body["polish_id"]}
    )
    assert full.status_code == 200, full.text
    final = full.json()
    assert set(final) == {"id", "markdown", "dropped_count", "regenerated"}
    assert final["id"] == body["polish_id"]
    assert final["markdown"].strip(), "成稿不得为空"
    assert final["regenerated"] is False
    assert "resume_text" not in full.text


def test_temp_target_role_not_persisted(
    client: TestClient,
    patch_ai: Callable[[Callable[[type[Any], str], dict[str, Any]]], None],
    polish_responder: Callable[[type[Any], str], dict[str, Any]],
    profile_factory: Callable[..., Any],
    resume_text: str,
) -> None:
    """AC-12：临时岗位只用于本次调用，重跑前后画像 payload 与正文都不变。"""
    profile = profile_factory()
    repository.insert_profile(profile)
    resume_id = _seed_resume(resume_text)
    patch_ai(polish_responder)
    before = repository.latest_profile()
    assert before is not None
    before_payload = before.model_dump(mode="json")

    response = client.post(
        f"/api/resumes/{resume_id}/polish", json={"target_role": "后端开发工程师"}
    )
    assert response.status_code == 200
    assert response.json()["target_role"] == "后端开发工程师"

    after = repository.latest_profile()
    assert after is not None
    assert after.target_role == DEFAULT_ROLE
    assert after.model_dump(mode="json") == before_payload
    assert repository.get_document_text(resume_id) == resume_text


def test_unknown_resume_and_empty_body_are_contract_errors(
    client: TestClient, resume_text: str, assert_chinese: Callable[[str], None]
) -> None:
    """AC-10/13：复用既有错误码，不新增闭集之外的 code。"""
    missing = client.post("/api/resumes/no-such/polish")
    assert missing.status_code == 404
    error = missing.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert_chinese(error["message"])

    repository.insert_document(
        ResumeMeta(resume_id="res-empty", file_name="空.txt", chars=0, sections=0), "  \n  "
    )
    blank = client.post("/api/resumes/res-empty/polish")
    assert blank.status_code == 400
    assert blank.json()["error"]["code"] == "VALIDATION_ERROR"
    assert_chinese(blank.json()["error"]["message"])

    _seed_resume(resume_text)
    too_long = client.post(
        "/api/resumes/res-1/polish", json={"target_role": "岗" * 60}
    )
    assert too_long.status_code == 400
    assert too_long.json()["error"]["code"] == "VALIDATION_ERROR"
    assert_chinese(too_long.json()["error"]["message"])


# --- 成稿端点（AC-11）---------------------------------------------------------


def test_compose_matches_response_markdown(
    client: TestClient,
    patch_ai: Callable[[Callable[[type[Any], str], dict[str, Any]]], None],
    polish_responder: Callable[[type[Any], str], dict[str, Any]],
    resume_text: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-11：`/full` 的 markdown 仅由 `compose_full` 产出；带 `polish_id` 不重复调模型。"""
    calls = _install_ai(monkeypatch, polish_responder)
    resume_id = _seed_resume(resume_text)

    polished = client.post(f"/api/resumes/{resume_id}/polish", json={"target_role": None})
    assert polished.status_code == 200
    parsed = PolishResponse.model_validate(polished.json())
    assert len(calls) == 1

    full = client.post(
        f"/api/resumes/{resume_id}/polish/full", json={"polish_id": parsed.polish_id}
    )
    assert full.status_code == 200
    body = full.json()
    assert len(calls) == 1, "同一份建议集不得再调一次模型（R4）"
    assert body["regenerated"] is False
    assert body["dropped_count"] == parsed.dropped_count
    assert body["id"] == parsed.polish_id
    assert body["markdown"] == compose_full(
        resume_text,
        parsed.suggestions,
        None,
        target_role=parsed.target_role,
        dropped_count=parsed.dropped_count,
    )

    rebuilt = client.post(f"/api/resumes/{resume_id}/polish/full", json={})
    assert rebuilt.status_code == 200
    rebuilt_body = rebuilt.json()
    assert rebuilt_body["regenerated"] is True, "缓存缺失时如实标 regenerated"
    assert len(calls) == 2
    assert rebuilt_body["markdown"] == body["markdown"], "同一份输入 → 同一份成稿"
    assert repository.get_document_text(resume_id) == resume_text


def test_full_applies_only_adopted_suggestions(
    client: TestClient,
    patch_ai: Callable[[Callable[[type[Any], str], dict[str, Any]]], None],
    polish_responder: Callable[[type[Any], str], dict[str, Any]],
    resume_text: str,
) -> None:
    """AC-11：`suggestion_ids` 只替换采纳区间，未采纳的原文逐字留在成稿里。"""
    resume_id = _seed_resume(resume_text)
    patch_ai(polish_responder)

    polished = client.post(f"/api/resumes/{resume_id}/polish", json={"target_role": None})
    parsed = PolishResponse.model_validate(polished.json())
    adopted = parsed.suggestions[0]

    full = client.post(
        f"/api/resumes/{resume_id}/polish/full",
        json={"polish_id": parsed.polish_id, "suggestion_ids": [adopted.id]},
    )
    assert full.status_code == 200
    markdown = full.json()["markdown"]

    assert adopted.suggested_text in markdown
    skipped = [
        item
        for item in parsed.suggestions[1:]
        if not (
            item.start < adopted.end and item.end > adopted.start
        )
    ]
    assert skipped, "模板应至少保留一条未采纳且不重叠的建议"
    assert skipped[0].original_text in markdown, "未采纳的区间必须逐字保留"
