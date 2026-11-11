"""r77 太傅问答：摘要投影 / 引用白名单 / 空档案短路 / 会话读写与隔离。

重点口径：
- 模型的引用只要不在「本次真读到的档案段」里 → 丢弃并计数（防幻觉）；
- 完全没记录的用户**不调用模型**（零成本），只给中文指引；
- 会话只写 `taifu_messages`，清空对话不影响画像 / 报告等业务数据。
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import context, repository
from app.schemas import Report, RoleFit, RoleFitItem, WeaknessItem
from app.services.taifu import brief, policy


def _report(report_id: str = "rep-r77") -> Report:
    return Report(
        id=report_id,
        run_ids=[],
        interview_avg=6.5,
        exam_total=72.0,
        shortfalls=[],
        generated_at="2026-11-11T10:00:00+00:00",
        weakness_map=[
            WeaknessItem(
                key="AI 工程|高级,|must_know,",
                point="AI 工程 · 部署与推理",
                direction="AI 工程",
                sub_direction="部署与推理",
                wrong=3,
                total=5,
                rate=0.6,
                avg=4.2,
                summary="部署与推理的错误集中在超时与并发取舍上",
            )
        ],
        role_fit=RoleFit(
            target_role="AI 应用工程师",
            items=[RoleFitItem(name="Python", required=3, user_level=2, gap=1, must=True)],
            first_fix=["Python", "Redis"],
        ),
    )


def test_build_sections_is_empty_without_any_record() -> None:
    assert brief.build_sections(profile=None, report=None, runs=[], attempts=[], learn={}) == []


def test_build_sections_skips_segments_without_facts(profile_factory: Any) -> None:
    sections = brief.build_sections(
        profile=profile_factory(), report=None, runs=[], attempts=[], learn={}
    )
    assert [section["href"] for section in sections] == ["/profile"]


def test_report_section_renders_weakness_and_role_fit(profile_factory: Any) -> None:
    sections = brief.build_sections(
        profile=profile_factory(), report=_report(), runs=[], attempts=[], learn={}
    )
    report_section = next(section for section in sections if section["href"] == "/report")
    text = "\n".join(report_section["lines"])
    assert "AI 应用工程师" in text
    assert "错误率 60%（3/5）" in text
    assert "先补 Python、Redis" in text


def test_report_section_exposes_weakness_anchors(profile_factory: Any) -> None:
    sections = brief.build_sections(
        profile=profile_factory(), report=_report(), runs=[], attempts=[], learn={}
    )
    report_section = next(section for section in sections if section["href"] == "/report")

    assert report_section["anchors"] == [
        {"href": "/report#weakness-1", "label": "最近诊断 · AI 工程 · 部署与推理"}
    ]
    assert any("/report#weakness-1" in line for line in report_section["lines"])


def test_sanitize_reply_accepts_anchor_but_rejects_out_of_range() -> None:
    sections = [
        {
            "key": "report",
            "label": "最近诊断",
            "href": "/report",
            "lines": ["x"],
            "anchors": [{"href": "/report#weakness-1", "label": "最近诊断 · 部署与推理"}],
        }
    ]
    draft = policy.TaifuDraftReply.model_validate(
        {"reply": "看第一条。", "citations": ["/report#weakness-1", "/report#weakness-9"]}
    )

    payload = policy.sanitize_reply(draft, sections)

    assert payload["citations"] == [
        {"label": "最近诊断 · 部署与推理", "href": "/report#weakness-1"}
    ]
    assert payload["dropped_citations"] == 1


def test_practice_and_learn_sections_are_projected() -> None:
    attempts = [
        {"question_id": "q1", "correct": 1, "answered_at": "2026-11-10T09:00:00+00:00"},
        {"question_id": "q2", "correct": 0, "answered_at": "2026-11-11T09:00:00+00:00"},
    ]
    learn = {"last_chapter_id": "ai-glossary", "chapters": {"ai-glossary": {"seen": ["s1", "s2"]}}}
    sections = brief.build_sections(
        profile=None, report=None, runs=[], attempts=attempts, learn=learn
    )
    assert [section["href"] for section in sections] == ["/practice", "/learn"]
    practice_text = "\n".join(sections[0]["lines"])
    assert "已练题数：2 题" in practice_text
    assert "正确率：50%（1/2）" in practice_text


def test_sanitize_reply_drops_unknown_and_duplicate_citations() -> None:
    sections = [
        {"key": "profile", "label": "目标与画像", "href": "/profile", "lines": ["目标岗位：后端"]},
        {"key": "report", "label": "最近诊断", "href": "/report", "lines": ["薄弱：缓存"]},
    ]
    draft = policy.TaifuDraftReply.model_validate(
        {"reply": "先补缓存。", "citations": ["/report", "/nope", "/report", "/practice"]}
    )

    payload = policy.sanitize_reply(draft, sections)

    assert payload["citations"] == [{"label": "最近诊断", "href": "/report"}]
    assert payload["dropped_citations"] == 2
    assert payload["materials_used"] == 2
    assert payload["notice"] == ""


def test_sanitize_reply_keeps_newlines_and_notices_empty_answer() -> None:
    sections = [{"key": "profile", "label": "目标与画像", "href": "/profile", "lines": ["x"]}]
    kept = policy.sanitize_reply(
        policy.TaifuDraftReply(reply="第一段\r\n\r\n\r\n第二段"), sections
    )
    assert kept["reply"] == "第一段\n\n第二段"

    empty = policy.sanitize_reply(policy.TaifuDraftReply(reply="   "), sections)
    assert empty["reply"] == ""
    assert empty["notice"] == policy.EMPTY_REPLY_NOTICE


def test_sanitize_question_clamps_and_flattens() -> None:
    assert policy.sanitize_question("  我   先补什么  ") == "我 先补什么"
    clamped = policy.sanitize_question("长" * 500)
    assert clamped.endswith("…")
    assert len(clamped) == policy.QUESTION_MAX + 1


def test_sanitize_page_accepts_only_the_closed_set() -> None:
    page = policy.sanitize_page('/report?run_id=r1#weakness')
    assert page is not None
    assert page["path"] == "/report"
    assert page["label"].startswith("医案")

    learned = policy.sanitize_page("/learn/ai-glossary#tutorial-s1")
    assert learned is not None
    assert learned["path"] == "/learn"

    assert policy.sanitize_page("/evil") is None
    assert policy.sanitize_page("") is None
    # 路径穿越 / 未登记页一律不认：页面上下文不能变成任意文本注入入口。
    assert policy.sanitize_page("/report/../settings") is None


def test_prompt_carries_page_context_but_only_as_reference_resolution() -> None:
    sections = [{"key": "report", "label": "最近诊断", "href": "/report", "lines": ["x"]}]
    page = policy.sanitize_page("/report")
    prompt = policy.build_user_prompt(sections, [], "这条什么意思", page)
    assert "【当前页面】医案（诊断报告）（/report）" in prompt
    assert "【当前页面】（未识别当前页面，按问题本身回答）" in policy.build_user_prompt(
        sections, [], "这条什么意思", None
    )


def test_prompt_carries_hrefs_and_recent_turns() -> None:
    sections = [
        {"key": "report", "label": "最近诊断", "href": "/report", "lines": ["薄弱：缓存"]}
    ]
    prompt = policy.build_user_prompt(
        sections,
        [{"role": "user", "content": "上一轮问题"}, {"role": "assistant", "content": "上一轮回答"}],
        "那这次呢",
    )
    assert "href: /report" in prompt
    assert "用户：上一轮问题" in prompt
    assert "太傅：上一轮回答" in prompt
    assert "【问题】那这次呢" in prompt


def test_chat_without_records_skips_model(client: TestClient, patch_ai: Any) -> None:
    def _boom(_model_cls: type[Any], _user: str) -> dict[str, Any]:
        raise AssertionError("空档案不应调用模型")

    patch_ai(_boom)
    response = client.post("/api/taifu/chat", json={"question": "我先补什么"})

    assert response.status_code == 200
    body = response.json()
    assert body["materials_used"] == 0
    assert "站内记录还是空的" in body["notice"]
    assert client.get("/api/taifu/thread").json()["messages"] == []


def test_chat_persists_thread_with_allowlisted_citations(
    client: TestClient, patch_ai: Any, profile_factory: Any
) -> None:
    repository.insert_profile(profile_factory())
    repository.insert_report(_report())
    seen: dict[str, str] = {}

    def _responder(_model_cls: type[Any], user_prompt: str) -> dict[str, Any]:
        seen["prompt"] = user_prompt
        return {
            "reply": "先补部署与推理。\n\n再补 Redis。",
            "citations": ["/report", "/tmp/fake"],
        }

    patch_ai(_responder)
    response = client.post(
        "/api/taifu/chat", json={"question": "我先补什么", "page": "/report"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "先补部署与推理。\n\n再补 Redis。"
    assert body["citations"] == [{"label": "最近诊断", "href": "/report"}]
    assert body["dropped_citations"] == 1
    assert body["materials_used"] == 2
    assert "href: /report" in seen["prompt"]
    assert "【当前页面】医案（诊断报告）" in seen["prompt"]

    messages = client.get("/api/taifu/thread").json()["messages"]
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "我先补什么"
    assert messages[1]["citations"] == [{"label": "最近诊断", "href": "/report"}]


def test_overlong_question_is_clamped_not_rejected(
    client: TestClient, patch_ai: Any, profile_factory: Any
) -> None:
    repository.insert_profile(profile_factory())
    patch_ai(lambda _model_cls, _user: {"reply": "好。", "citations": []})

    response = client.post("/api/taifu/chat", json={"question": "问" * 2500})

    assert response.status_code == 200
    stored = repository.list_taifu_messages()[-2]
    assert stored["role"] == "user"
    assert stored["content"].endswith("…")
    assert len(stored["content"]) == policy.QUESTION_MAX + 1


def test_empty_question_returns_notice_without_history(client: TestClient) -> None:
    response = client.post("/api/taifu/chat", json={"question": "   "})

    assert response.status_code == 200
    assert response.json()["notice"] == policy.EMPTY_QUESTION_NOTICE
    assert client.get("/api/taifu/thread").json()["messages"] == []


def test_clear_thread_keeps_business_data(
    client: TestClient, patch_ai: Any, profile_factory: Any
) -> None:
    repository.insert_profile(profile_factory())
    patch_ai(lambda _model_cls, _user: {"reply": "好。", "citations": []})
    client.post("/api/taifu/chat", json={"question": "在吗"})

    cleared = client.delete("/api/taifu/thread")

    assert cleared.status_code == 200
    assert cleared.json()["deleted"] == 2
    assert client.get("/api/taifu/thread").json()["messages"] == []
    assert repository.latest_profile() is not None


def test_thread_is_isolated_per_account(client: TestClient, patch_ai: Any, profile_factory: Any) -> None:
    repository.insert_profile(profile_factory())
    patch_ai(lambda _model_cls, _user: {"reply": "好。", "citations": []})
    client.post("/api/taifu/chat", json={"question": "在吗"})

    context.set_current_user_id("someone-else")
    try:
        assert repository.list_taifu_messages() == []
    finally:
        context.reset_current_user_id()

    assert len(repository.list_taifu_messages()) == 2


def test_thread_requires_login(tmp_db: Any) -> None:
    from app.main import app

    with TestClient(app) as anonymous:
        assert anonymous.get("/api/taifu/thread").status_code == 401


@pytest.mark.parametrize("role", ["user", "assistant"])
def test_message_roundtrip_keeps_citations(tmp_db: Any, role: str) -> None:
    stored = repository.insert_taifu_message(
        role=role, content="内容", citations=[{"label": "最近诊断", "href": "/report"}]
    )
    read = repository.list_taifu_messages(limit=5)

    assert read == [
        {
            "id": stored["id"],
            "role": role,
            "content": "内容",
            "citations": [{"label": "最近诊断", "href": "/report"}],
            "created_at": stored["created_at"],
        }
    ]
    assert repository.delete_taifu_messages() == 1


# === r80 线程记忆（长线程压缩） =================================================


def test_sanitize_memory_flattens_caps_and_rejects_placeholders() -> None:
    # 单行是硬要求：记忆会作为提示词里的一个【段】出现，多行会把后面的段头挤散。
    assert policy.sanitize_memory("第一句\n第二句") == "第一句 第二句"
    assert policy.sanitize_memory("   ") == ""
    # 「无」「（无）」这类占位不算记忆，否则会拿它覆盖掉真记忆。
    for placeholder in ["无", "（无）", "N/A", "没有"]:
        assert policy.sanitize_memory(placeholder) == ""

    clamped = policy.sanitize_memory("记" * (policy.MEMORY_MAX + 50))
    assert clamped.endswith("…")
    assert len(clamped) == policy.MEMORY_MAX + 1


def test_prompt_carries_memory_and_only_asks_for_it_when_overflowing() -> None:
    sections = [{"key": "report", "label": "最近诊断", "href": "/report", "lines": ["x"]}]

    without = policy.build_user_prompt(sections, [], "我先补什么")
    assert f"【早期对话摘要】{policy.MEMORY_NONE}" in without
    assert policy.MEMORY_TASK[False] in without
    assert policy.MEMORY_TASK[True] not in without

    with_memory = policy.build_user_prompt(
        sections, [], "那缓存呢", memory="用户目标是 AI 应用工程师，已建议先补部署。", compact=True
    )
    assert "【早期对话摘要】用户目标是 AI 应用工程师，已建议先补部署。" in with_memory
    assert policy.MEMORY_TASK[True] in with_memory


def test_memory_is_never_a_citation_source() -> None:
    """记忆里出现的 href 不能当引用：白名单只由档案段构成，记忆是模型自己写的话。"""
    sections = [{"key": "report", "label": "最近诊断", "href": "/report", "lines": ["x"]}]
    draft = policy.TaifuDraftReply.model_validate(
        {"reply": "好。", "citations": ["/history"], "memory": "上次提到 /history 里的均分"}
    )

    payload = policy.sanitize_reply(draft, sections)

    assert payload["citations"] == []
    assert payload["dropped_citations"] == 1


def test_short_thread_does_not_store_memory(
    client: TestClient, patch_ai: Any, profile_factory: Any
) -> None:
    repository.insert_profile(profile_factory())
    patch_ai(
        lambda _model_cls, _user: {
            "reply": "好。",
            "citations": [],
            "memory": "用户在问先补什么，已建议先补部署与推理。",
        }
    )

    client.post("/api/taifu/chat", json={"question": "我先补什么"})

    assert repository.get_taifu_memory() == ""


def test_overflowing_thread_stores_and_feeds_back_memory(
    client: TestClient, patch_ai: Any, profile_factory: Any
) -> None:
    repository.insert_profile(profile_factory())
    # 窗口装最近 6 条；8 条（4 轮）时第 1 轮才真的被挤出去，这才是「需要压缩」的起点。
    for index in range(policy.HISTORY_LIMIT // 2 + 1):
        repository.insert_taifu_message(role="user", content=f"旧问题 {index}")
        repository.insert_taifu_message(role="assistant", content=f"旧回答 {index}")

    seen: dict[str, str] = {}

    def _responder(_model_cls: type[Any], user_prompt: str) -> dict[str, Any]:
        seen["prompt"] = user_prompt
        return {
            "reply": "接着上次讲缓存。",
            "citations": [],
            "memory": "用户目标是 AI 应用工程师，先后问过先补什么与缓存一致性。",
        }

    patch_ai(_responder)
    first = client.post("/api/taifu/chat", json={"question": "缓存呢"})

    assert first.status_code == 200
    assert first.json()["memory_used"] is False  # 这一轮还只有旧对话，没有记忆
    assert policy.MEMORY_TASK[True] in seen["prompt"]
    stored = repository.get_taifu_memory()
    assert stored.startswith("用户目标是 AI 应用工程师")

    # 下一轮：上一轮存下的记忆进提示词，且继续滚动更新（摘要每轮由模型重写）。
    second = client.post("/api/taifu/chat", json={"question": "那 Redis 呢"})
    assert second.json()["memory_used"] is True
    assert f"【早期对话摘要】{stored}" in seen["prompt"]


def test_empty_answer_neither_stores_memory_nor_messages(
    client: TestClient, patch_ai: Any, profile_factory: Any
) -> None:
    repository.insert_profile(profile_factory())
    for index in range(policy.HISTORY_LIMIT // 2 + 1):
        repository.insert_taifu_message(role="user", content=f"旧问题 {index}")
        repository.insert_taifu_message(role="assistant", content=f"旧回答 {index}")
    patch_ai(
        lambda _model_cls, _user: {
            "reply": "   ",
            "citations": [],
            "memory": "这段记忆不该被写进去，因为本轮根本没有回答。",
        }
    )

    before = len(repository.list_taifu_messages(limit=50))
    response = client.post("/api/taifu/chat", json={"question": "缓存呢"})

    assert response.json()["reply"] == ""
    assert repository.get_taifu_memory() == ""
    assert len(repository.list_taifu_messages(limit=50)) == before


def test_clearing_thread_also_clears_memory(
    client: TestClient, patch_ai: Any, profile_factory: Any
) -> None:
    repository.insert_profile(profile_factory())
    repository.save_taifu_memory("用户目标是 AI 应用工程师。")

    client.delete("/api/taifu/thread")

    # 不清记忆的话，清空后第一问的提示词里还挂着上一段对话的要点。
    assert repository.get_taifu_memory() == ""
