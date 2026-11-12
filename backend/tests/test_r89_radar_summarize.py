"""r89 概要汇总：「标题即简介」的条目抓正文让模型汇总成中文，而不是翻标题。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.core import db
from app.core.config import get_settings
from app.services.radar import store, translate

ARTICLE_TEXT = (
    "Vaultbase is a self-hosted backend platform that ships authentication, "
    "file storage and background jobs as a single binary, so small teams can "
    "deploy a production-ready backend in minutes without gluing services together."
)
SUMMARY_ZH = "自托管后端平台：单个二进制内置认证、文件存储与后台任务，开箱即用。"


@pytest.fixture()
def radar_env(monkeypatch: pytest.MonkeyPatch, tmp_db: Any) -> None:
    """离线 + 关排程：零网络、零时序依赖。"""
    monkeypatch.setenv("RADAR_OFFLINE", "1")
    monkeypatch.setenv("RADAR_SCHEDULE", "off")
    get_settings.cache_clear()
    db.init_db()


def _hn(summary: str, slug: str = "hackernews:demo") -> dict[str, Any]:
    """HN 形状的最小条目：summary 就是标题（上游只有标题，没有描述）。"""
    return {
        "slug": slug,
        "name": summary,
        "direction": "AI 工程",
        "sub_direction": "",
        "source_key": "hackernews",
        "url": "https://example.com/article",
        "summary": summary,
    }


class _SummarizeFake:
    """按输入行回吐 `SUMMARY_ZH`；`echo_title=True` 时回吐标题（验证宁缺毋滥）。"""

    def __init__(self, *, echo_title: bool = False) -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self.echo_title = echo_title

    async def complete_model(
        self, _system: str, user: str, model_cls: type[Any], **_kwargs: Any
    ) -> Any:
        self.calls += 1
        self.prompts.append(user)
        items: list[dict[str, str]] = []
        for line in user.splitlines():
            if not line.startswith("- slug="):
                continue
            rest = line[len("- slug=") :]
            slug, tail = rest.split("｜标题：", 1)
            title = tail.split("｜正文摘录：", 1)[0]
            items.append({"slug": slug, "zh": title if self.echo_title else SUMMARY_ZH})
        return model_cls.model_validate({"items": items})


async def _fetch_ok(_url: str) -> str:
    return ARTICLE_TEXT


async def _fetch_fail(_url: str) -> str:
    return ""


def test_pending_summary_selects_title_only_rows(radar_env: None) -> None:
    """只有 summary 与 name 相同的条目进汇总队列；真实描述的条目绝不进。"""
    store.upsert_tech(_hn("Show HN: Vaultbase", slug="hackernews:a"))
    store.upsert_tech(
        {
            **_hn("ignored", slug="github:b"),
            "name": "vaultbase",
            "summary": "A real description that differs from the name.",
        }
    )
    rows = store.pending_summary(10)
    assert [row["slug"] for row in rows] == ["hackernews:a"]
    assert store.count_pending_summary() == 1


def test_summarize_items_drops_title_echo_and_unknown_slug() -> None:
    """回吐标题、多给不在输入里的 slug 都不算汇总成功。"""
    items = [
        {"slug": "a", "name": "Show HN: Vaultbase", "text": ARTICLE_TEXT},
        {"slug": "b", "name": "Another story", "text": ARTICLE_TEXT},
    ]
    result = asyncio.run(translate.summarize_items(items, _SummarizeFake(echo_title=True)))
    assert result == {}
    result = asyncio.run(translate.summarize_items(items, _SummarizeFake()))
    assert result == {"a": SUMMARY_ZH, "b": SUMMARY_ZH}


def test_summarize_pending_writes_summary_and_counts_remaining(radar_env: None) -> None:
    """抓到正文 → 汇总落库；抓不到 → 留在队列里（宁缺毋滥）。"""
    store.upsert_tech(_hn("Show HN: Vaultbase", slug="hackernews:a"))
    store.upsert_tech(_hn("Show HN: Broken", slug="hackernews:b"))

    done, remaining = asyncio.run(translate.summarize_pending(10, _SummarizeFake(), _fetch_fail))
    assert done == 0
    assert remaining == 2  # 抓不到正文的留在队列，等下一轮

    done, remaining = asyncio.run(translate.summarize_pending(10, _SummarizeFake(), _fetch_ok))
    assert done == 2
    assert remaining == 0
    rows = {row["tech_slug"]: row for row in store.list_techs(10)}
    assert rows["hackernews:a"]["summary_zh"] == SUMMARY_ZH
    # 原文（标题）永不被覆盖
    assert rows["hackernews:a"]["summary"] == "Show HN: Vaultbase"


def test_extract_article_text_strips_markup() -> None:
    from app.services.radar.sources import extract_article_text

    html = (
        "<html><head><style>body{color:red}</style></head><body>"
        "<script>var x=1;</script><h1>Vaultbase</h1>"
        "<p>Self-hosted   backend\nplatform.</p></body></html>"
    )
    text = extract_article_text(html)
    assert "var x" not in text and "color:red" not in text
    assert "Vaultbase" in text and "Self-hosted backend platform." in text


def test_extract_article_text_rejects_non_http() -> None:
    from app.services.radar.sources import fetch_article_text

    assert asyncio.run(fetch_article_text("javascript:alert(1)")) == ""
    assert asyncio.run(fetch_article_text("")) == ""
