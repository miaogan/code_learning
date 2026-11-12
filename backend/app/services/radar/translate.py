"""r74 雷达摘要中文化：把采集到的英文技术简介翻成中文并落库。

GitHub 的 `description`、HN 标题、arXiv 摘要都是英文，清单页直接平铺时中文用户读起来很费劲。
本模块只做一件事：**英文 → 简体中文**，一次请求译一批，结果写回 `radar_techs.summary_zh`。

三条纪律（与评估层同源）：
- **原文永不被覆盖**：`summary` 保持上游原样，译文单独一列，读不懂时可以回看原文；
- **宁缺毋滥**：模型漏条目、回吐英文原文、或译文里没有中文，一律不落库，界面继续显示原文；
- **不可用即降级**：无 Key / 超时 / 上游失败都不抛给采集主流程，英文原文照常可用。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.services.ai.ai import AIClient
from app.services.radar import sources, store

logger = logging.getLogger("app.radar.translate")

#: 译文长度上限：英文 summary 上游截 300 字符，中文信息密度更高，160 字足够讲清。
MAX_ZH_CHARS = 160
#: 「需要翻译」的拉丁字母下限：太短的描述（如 "CLI tool"）翻了也没信息量。
_LATIN_MIN = 12

_LATIN = re.compile(r"[A-Za-z]")
_CJK = re.compile(r"[\u4e00-\u9fff]")

TRANSLATE_SYSTEM = """你是技术雷达的中文编辑。把输入的英文技术简介逐条翻成简体中文。

硬性规则：
1. 只翻译，不解释、不评价、不补充原文没有的信息，不要写「该仓库」「这个项目」之类的开场。
2. 产品名、项目名、命令、版本号、协议名保留原文，不音译。
3. 每条控制在一句话、最多 60 字，讲清「它是什么 / 解决什么问题」。
4. 输入的每一条都必须有对应输出，`slug` 原样照抄，不得增删条目。
5. 只输出 JSON：{"items": [{"slug": "...", "zh": "..."}]}，不要 Markdown 代码块。"""

SUMMARIZE_SYSTEM = """你是技术雷达的中文编辑。输入条目只有标题，没有真实描述。
根据给定的正文摘录，分析这个项目 / 这篇文章 / 这个产品是干什么的，逐条汇总成一句中文。

硬性规则：
1. 概括「它是什么 / 做了什么 / 有什么关键信息」，不是翻译标题——标题说的正文里要有依据。
2. 正文摘录抓取失败或内容为空的条目直接跳过（宁缺毋滥，不许凭标题编造）。
3. 产品名、项目名、公司名保留原文，不音译；每条一句话、最多 60 字。
4. 输入的每一条都必须有对应输出，`slug` 原样照抄，不得增删条目。
5. 只输出 JSON：{"items": [{"slug": "...", "zh": "..."}]}，不要 Markdown 代码块。"""


class TranslationDraft(BaseModel):
    """单条译文（脏值只丢弃，不抛 500）。"""

    model_config = ConfigDict(extra="ignore")

    slug: str = ""
    zh: str = ""


class TranslationBatch(BaseModel):
    """一批译文（外层包一层对象，比裸数组更稳地过结构化输出）。"""

    model_config = ConfigDict(extra="ignore")

    items: list[TranslationDraft] = Field(default_factory=list)


def needs_translation(text: str) -> bool:
    """是否值得翻：有足够拉丁字母、且完全没有中日韩字符（中文摘要直接视为已就绪）。"""
    body = (text or "").strip()
    if not body or _CJK.search(body):
        return False
    return len(_LATIN.findall(body)) >= _LATIN_MIN


def clean_zh(text: str) -> str:
    """译文清洗：折叠空白与换行，按上限截断（换行会把列表行高撑开）。"""
    return re.sub(r"\s+", " ", (text or "").strip())[:MAX_ZH_CHARS]


async def translate_items(
    items: list[dict[str, Any]], client: AIClient
) -> dict[str, str]:
    """批量翻译：一次请求翻完，返回 `{slug: 中文}`。

    只接受「slug 在输入里、非空、含中文、且不等于原文」的译文；模型多给的条目直接丢弃，
    少给的就留着不翻（下一轮或补翻接口会再试），避免把英文当成中文译文写进库里。
    """
    if not items:
        return {}
    lines = [f"- slug={row['slug']}｜原文：{row['summary']}" for row in items]
    prompt = "逐条翻译下列技术简介：\n" + "\n".join(lines)
    batch = await client.complete_model(
        TRANSLATE_SYSTEM,
        prompt,
        TranslationBatch,
        timeout_s=get_settings().radar_translate_timeout_s,
    )
    source = {str(row["slug"]): str(row["summary"]) for row in items}
    result: dict[str, str] = {}
    for draft in batch.items:
        slug = draft.slug.strip()
        if slug not in source:
            continue
        zh = clean_zh(draft.zh)
        # 回声（与原文相同）与纯英文译文都不算翻译成功：宁可显示原文。
        if not zh or not _CJK.search(zh) or zh == source[slug]:
            continue
        result[slug] = zh
    return result


async def translate_pending(limit: int, client: AIClient) -> tuple[int, int]:
    """翻译待翻条目并落库，返回 `(本轮翻成条数, 剩余待翻条数)`。

    待翻队列里混着「本来就是中文」的摘要（手工录入常见），它们直接回填成译文出队，
    否则每次点补翻都会重复请求同一条、永远翻不完。
    """
    batch = store.pending_translation(max(int(limit), 1))
    if not batch:
        return 0, 0
    english = [row for row in batch if needs_translation(str(row["summary"]))]
    for row in batch:
        if not needs_translation(str(row["summary"])):
            store.set_summary_zh(str(row["slug"]), clean_zh(str(row["summary"])))
    translated = 0
    if english:
        result = await translate_items(english, client)
        for slug, zh in result.items():
            store.set_summary_zh(slug, zh)
        translated = len(result)
    return translated, store.count_pending_translation()


def _is_title_only(row: dict[str, Any]) -> bool:
    """「标题即简介」：summary 与 name 相同说明上游没给真实描述（HN 只回标题的典型形状）。"""
    return str(row.get("summary") or "").strip() == str(row.get("name") or "").strip()


async def summarize_items(
    items: list[dict[str, Any]], client: AIClient
) -> dict[str, str]:
    """批量汇总「标题即简介」的条目：`items` 每条带 `slug / name / text`（正文摘录）。

    只接受「slug 在输入里、非空、含中文、且不等于标题」的汇总——模型回吐标题或
    凭空编造的条目一律丢弃，这些条目保持标题译文，等下一轮再试。
    """
    if not items:
        return {}
    lines = [
        f"- slug={row['slug']}｜标题：{row['name']}｜正文摘录：{row['text']}" for row in items
    ]
    prompt = "逐条分析并汇总下列条目：\n" + "\n".join(lines)
    batch = await client.complete_model(
        SUMMARIZE_SYSTEM,
        prompt,
        TranslationBatch,
        timeout_s=get_settings().radar_translate_timeout_s,
    )
    titles = {str(row["slug"]): str(row["name"]) for row in items}
    result: dict[str, str] = {}
    for draft in batch.items:
        slug = draft.slug.strip()
        if slug not in titles:
            continue
        zh = clean_zh(draft.zh)
        # 空串、无中文、或与标题相同（回吐标题）都不算汇总成功。
        if not zh or not _CJK.search(zh) or zh == titles[slug]:
            continue
        result[slug] = zh
    return result


async def summarize_pending(
    limit: int, client: AIClient, fetch_text: Callable[[str], Awaitable[str]] | None = None
) -> tuple[int, int]:
    """给「标题即简介」的条目抓正文、汇总中文概要并落库，返回 `(本轮汇总条数, 剩余条数)`。

    `fetch_text` 可注入（测试用）；默认用 `sources.fetch_article_text`。抓不到正文的
    条目本轮跳过、留在队列里（宁缺毋滥），绝不抛错拖垮采集或补翻主流程。
    """
    if fetch_text is None and get_settings().radar_offline:
        # 离线模式契约：只读内置样本、不发起真实网络抓取，队列保持原样。
        return 0, store.count_pending_summary()
    fetch = fetch_text or sources.fetch_article_text
    batch = [row for row in store.pending_summary(max(int(limit), 1)) if _is_title_only(row)]
    if not batch:
        return 0, store.count_pending_summary()
    enriched: list[dict[str, Any]] = []
    for row in batch:
        text = await fetch(str(row["url"]))
        if not text:
            continue
        enriched.append({"slug": row["slug"], "name": row["name"], "text": text})
    summarized = 0
    if enriched:
        result = await summarize_items(enriched, client)
        for slug, zh in result.items():
            store.set_summary_zh(slug, zh)
        summarized = len(result)
    return summarized, store.count_pending_summary()
