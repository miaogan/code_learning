"""r74 雷达摘要中文化：判英、译文过滤、落库、补翻接口、原文变化重翻。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import db
from app.core.config import get_settings
from app.core.errors import AI_UNAVAILABLE, AppError
from app.services import radar
from app.services.ai import user_ai
from app.services.radar import store, translate

ENGLISH = "High-throughput LLM inference and serving engine with PagedAttention."
CHINESE = "高吞吐的大模型推理与服务引擎，支持分页注意力与连续批处理。"


@pytest.fixture()
def radar_env(monkeypatch: pytest.MonkeyPatch, tmp_db: Any) -> None:
    """离线 + 关排程 + 不做模型细化：采集用例零网络、零时序依赖。"""
    monkeypatch.setenv("RADAR_OFFLINE", "1")
    monkeypatch.setenv("RADAR_SCHEDULE", "off")
    monkeypatch.setenv("RADAR_MAX_ASSESS_PER_ROUND", "0")
    get_settings.cache_clear()
    db.init_db()


class _TranslateFake:
    """把每条原文换成中文占位译文；`echo=True` 时回吐原文，用来验证「宁缺毋滥」。"""

    def __init__(self, *, echo: bool = False) -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self.echo = echo

    async def complete_model(
        self, _system: str, user: str, model_cls: type[Any], **_kwargs: Any
    ) -> Any:
        self.calls += 1
        self.prompts.append(user)
        items: list[dict[str, str]] = []
        for line in user.splitlines():
            if not line.startswith("- slug="):
                continue
            slug, source = line[len("- slug=") :].split("｜原文：", 1)
            items.append({"slug": slug, "zh": source if self.echo else CHINESE})
        return model_cls.model_validate({"items": items})


def _tech(summary: str) -> dict[str, Any]:
    """`store.upsert_tech` 需要的最小字段集（不含 slug 之外的计算字段）。"""
    return {
        "slug": "demo/translated-repo",
        "name": "demo/translated-repo",
        "direction": "AI 工程",
        "sub_direction": "Agent",
        "source_key": "github",
        "url": "https://github.com/demo/translated-repo",
        "summary": summary,
    }


def test_needs_translation_only_for_english() -> None:
    assert translate.needs_translation(ENGLISH)
    assert not translate.needs_translation(CHINESE)
    assert not translate.needs_translation("")
    # 太短的英文（无信息量）与中英混排（已能读懂）都不翻。
    assert not translate.needs_translation("CLI tool")
    assert not translate.needs_translation("支持 RAG 的检索增强框架")


def test_clean_zh_collapses_whitespace_and_truncates() -> None:
    assert translate.clean_zh("  第一行\n第二行   第三行  ") == "第一行 第二行 第三行"
    assert len(translate.clean_zh("中" * 500)) == translate.MAX_ZH_CHARS


def test_translate_items_drops_echo_and_unknown_slug() -> None:
    """回吐英文原文、多给不在输入里的 slug 都不算翻译成功（不能让界面显示"英文译文"）。"""

    class _Mixed:
        async def complete_model(
            self, _system: str, _user: str, model_cls: type[Any], **_kwargs: Any
        ) -> Any:
            return model_cls.model_validate(
                {
                    "items": [
                        {"slug": "a", "zh": CHINESE},
                        {"slug": "b", "zh": "an english sentence passed through"},
                        {"slug": "c", "zh": ENGLISH},
                        {"slug": "not-in-input", "zh": "编造条目"},
                    ]
                }
            )

    items = [
        {"slug": "a", "summary": ENGLISH},
        {"slug": "b", "summary": ENGLISH},
        {"slug": "c", "summary": ENGLISH},
    ]
    result = asyncio.run(translate.translate_items(items, _Mixed()))
    assert result == {"a": CHINESE}


def test_upsert_keeps_translation_until_summary_changes(radar_env: None) -> None:
    """摘要没变就不重翻（省 token）；原文变了旧译文必须清空（旧译文对应旧原文）。"""
    store.upsert_tech(_tech(ENGLISH))
    store.set_summary_zh("demo/translated-repo", CHINESE)
    store.upsert_tech(_tech(ENGLISH))
    assert store.list_techs(1, tech_slug="demo/translated-repo")[0]["summary_zh"] == CHINESE

    store.upsert_tech(_tech("A completely different description of the same repository."))
    row = store.list_techs(1, tech_slug="demo/translated-repo")[0]
    assert row["summary_zh"] == ""
    assert row["summary"].startswith("A completely different")


def test_round_translates_new_english_summaries(
    radar_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """采集一轮后：英文原文保留，中文译文落库，notice 里说明翻了几条。"""
    fake = _TranslateFake()
    monkeypatch.setattr(user_ai, "client_for", lambda _user, _tier: fake)
    summary = asyncio.run(radar.run_round(trigger="manual", user={"user_id": "u-test"}))

    rows = store.list_techs(100)
    assert rows and all(row["summary_zh"] for row in rows)
    # 英文条目翻成中文（译文与原文不同），样本里本就中文的那条按「已就绪」直接回填。
    assert any(row["summary"] != row["summary_zh"] for row in rows)
    assert "已翻译" in summary["notice"]
    assert fake.calls == 1  # 一批翻完，不是一条一次


def test_round_keeps_english_when_model_echoes_source(
    radar_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模型只回吐原文时不落库，界面仍显示英文原文，也不影响采集成功。"""
    monkeypatch.setattr(user_ai, "client_for", lambda _user, _tier: _TranslateFake(echo=True))
    asyncio.run(radar.run_round(trigger="manual", user={"user_id": "u-test"}))
    english = [
        row for row in store.list_techs(100) if translate.needs_translation(row["summary"])
    ]
    assert english and all(row["summary_zh"] == "" for row in english)


def test_translate_api_fills_backlog(
    client: TestClient, radar_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """定时采集（无账号 Key）留下的英文清单，可以按页补翻；剩余条数如实回传。"""
    asyncio.run(radar.run_round(trigger="manual", user=None))
    backlog = store.count_pending_translation()
    assert backlog > 5
    monkeypatch.setattr(user_ai, "client_for", lambda _user, _tier: _TranslateFake())

    body = client.post("/api/radar/translate", json={"limit": 5}).json()
    # 一批 5 条全部出队：英文翻成中文，本来就是中文的直接回填（不计入「翻成」条数）。
    assert body["translated"] >= 1
    assert body["remaining"] == backlog - 5
    assert "已翻译" in body["notice"]

    listed = client.get("/api/radar/techs", params={"limit": 100}).json()["items"]
    assert sum(1 for item in listed if item["summary_zh"]) == 5
    # 列表接口同时给出原文与译文：原文可追溯，译文用于展示。
    assert all(item["summary"] for item in listed)


def test_translate_api_without_key_is_503(
    client: TestClient, radar_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """没配模型时明确报不可用，不假装「已翻译 0 条」。"""

    def _no_client(_user: Any, _tier: str) -> Any:
        raise AppError(AI_UNAVAILABLE, "未配置模型服务", status=503)

    monkeypatch.setattr(user_ai, "client_for", _no_client)
    assert client.post("/api/radar/translate", json={}).status_code == 503


def test_translate_api_rejects_out_of_range_limit(
    client: TestClient, radar_env: None
) -> None:
    assert client.post("/api/radar/translate", json={"limit": 0}).status_code == 422
    assert client.post("/api/radar/translate", json={"limit": 51}).status_code == 422
