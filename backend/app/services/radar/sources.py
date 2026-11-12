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
import re
import ssl
import time
import xml.etree.ElementTree as ET
from html import unescape as html_unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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


#: 指定方向采集时 GitHub 检索式的关键词；不在表里的方向（含空串）走默认 `topic:llm`。
_DIRECTION_QUERIES: dict[str, str] = {
    "AI 工程": "llm",
    "中间件与运维": "kubernetes",
    "SQL 与数据库": "database",
    "前端": "frontend",
    "后端": "backend",
    "算法与数据结构": "algorithm",
    "计算机基础": "compiler",
    "研发工程实践": "ci",
}


def _github_query(settings: Settings, direction: str = "") -> str:
    since = normalize.window_start(hours=24 * 7)
    term = _DIRECTION_QUERIES.get(direction, "topic:llm")
    return (
        "https://api.github.com/search/repositories?q="
        f"{term}+pushed:>{since}+stars:>{settings.radar_min_stars}"
        "&sort=stars&order=desc&per_page=10"
    )


def _github_item(repo: dict[str, Any]) -> dict[str, Any] | None:
    """GitHub 仓库对象 → 统一条目（列表检索与「按仓库补元数据」共用同一形状）。"""
    full_name = str(repo.get("full_name") or "")
    if not full_name:
        return None
    topics = [str(t) for t in (repo.get("topics") or [])]
    text = f"{full_name} {repo.get('description') or ''} {' '.join(topics)}"
    direction = normalize.guess_direction(text)
    stars = int(repo.get("stargazers_count") or 0)
    return {
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


def parse_github(payload: bytes) -> list[dict[str, Any]]:
    data = json.loads(payload.decode("utf-8", "ignore") or "{}")
    items = [_github_item(repo) for repo in (data.get("items") or [])[:10]]
    return [item for item in items if item is not None]


_GITHUB_HOSTS = {"github.com", "www.github.com"}
_REPO_PART = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")


def github_full_name(url: str) -> str:
    """从仓库链接取 `owner/repo`；用户主页 / issue / 非 github 链接一律返回空串。"""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or (parts.hostname or "") not in _GITHUB_HOSTS:
        return ""
    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) < 2:
        return ""
    owner, repo = segments[0], segments[1]
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    if not _REPO_PART.match(owner) or not _REPO_PART.match(repo):
        return ""
    return f"{owner}/{repo}"


def repo_full_name(text: str) -> str:
    """「指定仓库采集」的入参解析：仓库链接或 `owner/repo` 简写都接，其余返回空串。"""
    value = (text or "").strip()
    full_name = github_full_name(value)
    if full_name:
        return full_name
    parts = value.split("/")
    if len(parts) == 2 and all(_REPO_PART.match(part) for part in parts):
        return value
    return ""


async def fetch_repo(full_name: str, settings: Settings | None = None) -> dict[str, Any] | None:
    """按仓库补一次公开元数据（手工录入 GitHub 链接时用）；拿不到返回 None 由调用方兜底。"""
    settings = settings or get_settings()
    headers = _headers({"Accept": "application/vnd.github+json"})
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    timeout = httpx.Timeout(settings.radar_fetch_timeout_s)
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, verify=not settings.radar_insecure_tls
        ) as client:
            payload = await _get(
                client, f"https://api.github.com/repos/{full_name}", headers, settings
            )
        return _github_item(json.loads(payload.decode("utf-8", "ignore") or "{}"))
    except (httpx.HTTPError, ValueError, OSError) as error:
        logger.warning("按仓库采集 %s 失败：%s", full_name, error)
        return None


async def fetch_github(
    client: httpx.AsyncClient, settings: Settings, query: str = ""
) -> list[dict[str, Any]]:
    headers = _headers({"Accept": "application/vnd.github+json"})
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return parse_github(await _get(client, query or _github_query(settings), headers, settings))


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


def _tls_failed(error: BaseException) -> bool:
    """异常链里是否有 TLS 证书校验失败（httpx 会把它包成 `ConnectError`）。"""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = str(current).lower()
        if isinstance(current, ssl.SSLError) or "certificate" in text or "[ssl" in text:
            return True
        current = current.__cause__ or current.__context__
    return False


#: r89 概要抓取：正文摘录喂给模型的上限（约 6 页 A4，足够概括「它是干啥的」）。
_ARTICLE_MAX_BYTES = 300_000
_ARTICLE_MAX_CHARS = 3000
_SCRIPT_STYLE = re.compile(r"<(script|style|noscript|svg)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def extract_article_text(html: str) -> str:
    """HTML → 可读正文：去脚本/样式/标签、折叠空白，截到 `_ARTICLE_MAX_CHARS`。"""
    body = _SCRIPT_STYLE.sub(" ", html or "")
    body = _TAG.sub(" ", body)
    text = html_unescape(body)
    return _WS.sub(" ", text).strip()[:_ARTICLE_MAX_CHARS]


async def fetch_article_text(url: str, settings: Settings | None = None) -> str:
    """抓取条目链接的正文摘录（r89），供「标题即简介」的条目汇总中文概要。

    任何失败（网络 / 4xx 5xx / 超时 / 非文本）都返回空串——概要宁缺毋滥，
    抓不到就保持标题译文，绝不让采集或补翻主流程失败。
    """
    target = (url or "").strip()
    if not target.lower().startswith(("http://", "https://")):
        return ""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=True,
            verify=not (settings or get_settings()).radar_insecure_tls,
        ) as client:
            response = await client.get(target, headers=_headers({"Accept": "text/html"}))
            response.raise_for_status()
            ctype = response.headers.get("content-type", "")
            if ctype and "html" not in ctype and "xml" not in ctype and "text" not in ctype:
                return ""
            return extract_article_text(response.content[:_ARTICLE_MAX_BYTES].decode("utf-8", "ignore"))
    except (httpx.HTTPError, ValueError, OSError):
        logger.info("概要正文抓取失败 url=%s", target)
        return ""


async def _run_source(
    key: str, client: httpx.AsyncClient, settings: Settings, github_query: str = ""
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        if key == "github" and github_query:
            items = await fetch_github(client, settings, github_query)
        else:
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
        message = (
            "上游 TLS 证书校验失败（可在 backend/.env 设置 RADAR_INSECURE_TLS=true 临时跳过）"
            if _tls_failed(error)
            else "上游不可用或返回格式异常"
        )
        return {"source_key": key, "status": "failed", "items": 0,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "message": message}
    return {
        "source_key": key,
        "status": "ok",
        "items": len(items),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "message": "",
        "_raw": items,
    }


async def fetch_all(
    settings: Settings | None = None, direction: str = "", repo: str = ""
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    """返回 `(归一化后的条目, 来源状态, 是否降级)`。离线模式只读样本、不建连接。

    `repo` 非空时只采这一个仓库（跑一次 `GET /repos/{owner}/{repo}`，不扫其他源）；
    `direction` 非空时把 GitHub 检索式换成本方向关键词，接由调用方按方向过滤。
    """
    settings = settings or get_settings()
    if settings.radar_offline:
        items = load_samples()
        status = [
            {"source_key": key, "status": "offline", "items": len(items) if key == "manual" else 0,
             "latency_ms": 0, "message": "离线模式，只读本地样本"}
            for key in SOURCE_KEYS
        ]
        return items, status, True
    if repo:
        started = time.monotonic()
        item = await fetch_repo(repo, settings)
        latency = int((time.monotonic() - started) * 1000)
        if item is None:
            return [], [{"source_key": "github", "status": "failed", "items": 0,
                         "latency_ms": latency,
                         "message": "仓库不存在、限流、网络或 TLS 证书校验失败"}], True
        return [normalize.normalize_item(item)], [
            {"source_key": "github", "status": "ok", "items": 1,
             "latency_ms": latency, "message": "指定仓库采集"}
        ], False
    timeout = httpx.Timeout(settings.radar_fetch_timeout_s)
    if settings.radar_insecure_tls:
        logger.warning("RADAR_INSECURE_TLS=true：采集链路已跳过 TLS 证书校验（仅限内网排障）")
    query = _github_query(settings, direction) if direction else ""
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=True, verify=not settings.radar_insecure_tls
    ) as client:
        results = await asyncio.gather(
            *[_run_source(key, client, settings, query) for key in _FETCHERS]
        )
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
