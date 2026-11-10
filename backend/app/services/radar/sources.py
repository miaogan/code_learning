"""r67 采集层：六个来源 + 一条离线样本通路。

六条硬约束（都是实测结论，不是推测）：
1. 固定 `httpx.AsyncClient` —— Windows 下 curl / schannel 对 arXiv 握手失败，httpx 正常。
2. 固定 `User-Agent` —— 无 UA 直接被 GitHub / 部分 RSS 403。
3. 全源 `asyncio.gather` 并发；单源超时 `RADAR_FETCH_TIMEOUT_S=8`。
4. 流式读、字节上限 `RADAR_FETCH_MAX_BYTES`（超限截断并标记 `truncated`）。
5. 网络异常 / 5xx 重试一次（退避 0.5s）；4xx 不重试。
6. 单源失败**不连坐**：结果里记 `failed` + 中文原因，本轮由调用方标 `degraded`。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.services.radar import normalize

logger = logging.getLogger("app.radar.sources")

#: 六个来源（`source_key` 是闭集，写进 `radar_techs.source_key`）。
SOURCE_KEYS: tuple[str, ...] = (
    "github",
    "hackernews",
    "arxiv",
    "openai",
    "googleai",
    "manual",
)
USER_AGENT = "EscapePlanRadar/1.0 (+https://github.com/miaogan/code_learning)"
SAMPLE_FILE = Path(__file__).resolve().parents[3] / "seed" / "radar_samples.json"
_ATOM = "{http://www.w3.org/2005/Atom}"


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    base = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    base.update(extra or {})
    return base


async def _get(client: httpx.AsyncClient, url: str, headers: dict[str, str], settings: Settings) -> bytes:
    """流式读取 + 字节上限 + 5xx/网络异常重试一次。"""
    attempts = 2
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            async with client.stream("GET", url, headers=headers) as response:
                if response.status_code >= 500 and attempt + 1 < attempts:
                    last_error = httpx.HTTPStatusError(
                        f"上游返回 {response.status_code}", request=response.request, response=response
                    )
                    await asyncio.sleep(0.5)
                    continue
                response.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= settings.radar_fetch_max_bytes:
                        break
                return b"".join(chunks)[: settings.radar_fetch_max_bytes]
        except (httpx.HTTPError, httpx.StreamError) as error:
            last_error = error
            status = getattr(getattr(error, "response", None), "status_code", None)
            if status is not None and 400 <= status < 500:
                raise
            if attempt + 1 < attempts:
                await asyncio.sleep(0.5)
                continue
            raise
    raise last_error or RuntimeError("采集失败")


def _github_query(settings: Settings) -> str:
    since = normalize.window_start(hours=24 * 7)
    return (
        "https://api.github.com/search/repositories?q="
        f"topic:llm+pushed:>{since}+stars:>{settings.radar_min_stars}"
        "&sort=stars&order=desc&per_page=10"
    )


def parse_github(payload: bytes) -> list[dict[str, Any]]:
    data = json.loads(payload.decode("utf-8", "ignore") or "{}")
    items: list[dict[str, Any]] = []
    for repo in (data.get("items") or [])[:10]:
        full_name = str(repo.get("full_name") or "")
        if not full_name:
            continue
        topics = [str(t) for t in (repo.get("topics") or [])]
        text = f"{full_name} {repo.get('description') or ''} {' '.join(topics)}"
        direction = normalize.guess_direction(text)
        stars = int(repo.get("stargazers_count") or 0)
        items.append(
            {
                "slug": normalize.slug_of("github", full_name),
                "name": full_name,
                "url": str(repo.get("html_url") or ""),
                "summary": normalize.clean_text(repo.get("description"), 300),
                "direction": direction,
                "sub_direction": "",
                "source_key": "github",
                "stars": stars,
                "forks": int(repo.get("forks_count") or 0),
                "repo_created_at": str(repo.get("created_at") or ""),
                "pushed_at": str(repo.get("pushed_at") or ""),
                "suspect": normalize.is_suspect(str(repo.get("created_at") or ""), stars),
            }
        )
    return items


async def fetch_github(client: httpx.AsyncClient, settings: Settings) -> list[dict[str, Any]]:
    headers = _headers({"Accept": "application/vnd.github+json"})
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return parse_github(await _get(client, _github_query(settings), headers, settings))


async def fetch_hackernews(client: httpx.AsyncClient, settings: Settings) -> list[dict[str, Any]]:
    base = "https://hacker-news.firebaseio.com/v0"
    ids = json.loads((await _get(client, f"{base}/newstories.json", _headers(), settings)).decode("utf-8", "ignore"))
    items: list[dict[str, Any]] = []
    for story_id in (ids or [])[:5]:
        payload = json.loads(
            (await _get(client, f"{base}/item/{story_id}.json", _headers(), settings)).decode("utf-8", "ignore")
        )
        title = str(payload.get("title") or "")
        if not title:
            continue
        url = str(payload.get("url") or f"https://news.ycombinator.com/item?id={story_id}")
        direction = normalize.guess_direction(title)
        items.append(
            {
                "slug": normalize.slug_of("hackernews", str(story_id)),
                "name": title,
                "url": url,
                "summary": normalize.clean_text(title, 300),
                "direction": direction,
                "sub_direction": "",
                "source_key": "hackernews",
                "stars": int(payload.get("score") or 0),
                "repo_created_at": "",
                "pushed_at": "",
            }
        )
    return items


def parse_arxiv(payload: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(payload)
    items: list[dict[str, Any]] = []
    for entry in root.findall(f"{_ATOM}entry")[:10]:
        raw_id = (entry.findtext(f"{_ATOM}id") or "").strip()
        title = normalize.clean_text(entry.findtext(f"{_ATOM}title"), 160)
        summary = normalize.clean_text(entry.findtext(f"{_ATOM}summary"), 300)
        published = (entry.findtext(f"{_ATOM}published") or "").strip()
        if not raw_id or not title:
            continue
        items.append(
            {
                "slug": normalize.slug_of("arxiv", raw_id.rsplit("/", 1)[-1]),
                "name": title,
                "url": raw_id,
                "summary": summary,
                "direction": normalize.guess_direction(title, summary),
                "sub_direction": "",
                "source_key": "arxiv",
                "stars": 0,
                "repo_created_at": published,
                "pushed_at": "",
            }
        )
    return items


async def fetch_arxiv(client: httpx.AsyncClient, settings: Settings) -> list[dict[str, Any]]:
    url = (
        "http://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG"
        "&sortBy=submittedDate&sortOrder=descending&max_results=10"
    )
    return parse_arxiv(await _get(client, url, _headers(), settings))


def parse_rss(payload: bytes, source_key: str) -> list[dict[str, Any]]:
    root = ET.fromstring(payload)
    items: list[dict[str, Any]] = []
    for node in root.findall(".//item")[:10]:
        title = normalize.clean_text(node.findtext("title"), 160)
        link = (node.findtext("link") or "").strip()
        if not title or not link:
            continue
        summary = normalize.clean_text(node.findtext("description") or "", 300)
        items.append(
            {
                "slug": normalize.slug_of(source_key, normalize.slug_hash(link)),
                "name": title,
                "url": link,
                "summary": summary,
                "direction": normalize.guess_direction(title, summary),
                "sub_direction": "",
                "source_key": source_key,
                "stars": 0,
                "repo_created_at": "",
                "pushed_at": (node.findtext("pubDate") or "").strip(),
            }
        )
    return items


async def fetch_openai(client: httpx.AsyncClient, settings: Settings) -> list[dict[str, Any]]:
    return parse_rss(
        await _get(client, "https://openai.com/blog/rss.xml", _headers(), settings), "openai"
    )


async def fetch_googleai(client: httpx.AsyncClient, settings: Settings) -> list[dict[str, Any]]:
    return parse_rss(
        await _get(client, "https://blog.google/technology/ai/rss/", _headers(), settings), "googleai"
    )


_FETCHERS = {
    "github": fetch_github,
    "hackernews": fetch_hackernews,
    "arxiv": fetch_arxiv,
    "openai": fetch_openai,
    "googleai": fetch_googleai,
}


def load_samples() -> list[dict[str, Any]]:
    """离线样本（`RADAR_OFFLINE=1` / 无外网时的唯一通路，AC-1）。"""
    if not SAMPLE_FILE.exists():
        return []
    try:
        payload = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        logger.warning("离线样本读取失败：%s", error)
        return []
    return [normalize.normalize_item(item) for item in payload.get("items", [])]


async def _run_source(key: str, client: httpx.AsyncClient, settings: Settings) -> dict[str, Any]:
    started = time.monotonic()
    try:
        items = await _FETCHERS[key](client, settings)
    except TimeoutError:
        return {"source_key": key, "status": "failed", "items": 0,
                "latency_ms": int((time.monotonic() - started) * 1000), "message": "上游超时"}
    except httpx.HTTPStatusError as error:
        return {"source_key": key, "status": "failed", "items": 0,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "message": f"上游返回 {error.response.status_code}"}
    except (httpx.HTTPError, ET.ParseError, ValueError, OSError) as error:
        logger.warning("采集源 %s 失败：%s", key, error)
        return {"source_key": key, "status": "failed", "items": 0,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "message": "上游不可用或返回格式异常"}
    return {
        "source_key": key,
        "status": "ok",
        "items": len(items),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "message": "",
        "_raw": items,
    }


async def fetch_all(settings: Settings | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    """返回 `(归一化后的条目, 来源状态, 是否降级)`。离线模式只读样本、不建连接。"""
    settings = settings or get_settings()
    if settings.radar_offline:
        items = load_samples()
        status = [
            {"source_key": key, "status": "offline", "items": len(items) if key == "manual" else 0,
             "latency_ms": 0, "message": "离线模式，只读本地样本"}
            for key in SOURCE_KEYS
        ]
        return items, status, True
    timeout = httpx.Timeout(settings.radar_fetch_timeout_s)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        results = await asyncio.gather(*[_run_source(key, client, settings) for key in _FETCHERS])
    raw_items: list[dict[str, Any]] = []
    status: list[dict[str, Any]] = []
    degraded = False
    for result in results:
        raw_items.extend(result.pop("_raw", []))
        if result["status"] != "ok":
            degraded = True
        status.append(result)
    normalized = [normalize.normalize_item(item) for item in raw_items]
    return normalize.dedupe(normalized), status, degraded
