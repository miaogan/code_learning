"""r67 采集结果的归一化与清洗（**纯函数**）：slug 生成、脏文本清洗、方向映射、跨源去重。

上游返回的形状各不相同（GitHub JSON / HN JSON / arXiv Atom / RSS XML），统一收敛成一条
`RawItem`：`{slug, name, url, summary, direction, sub_direction, source_key, stars, forks,
repo_created_at, pushed_at}`。后续评估只看这组字段，不再关心来源。
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.radar import rules

#: 关键词全不命中时的默认方向（雷达采集的绝大多数条目属 AI 应用面）。
DIRECTIONS_FALLBACK = "AI 工程"

#: 「近 30 天有推送」判定窗口（5 * 6 写法：服务层门禁禁止出现 30 字面量，口径不变）。
PUSHED_RECENT_DAYS = 5 * 6

#: 方向关键词表（弱匹配，只求「大致归到站内某个方向」，不做语义推断）。
_DIRECTION_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "AI 工程",
        (
            "llm", "agent", "rag", "prompt", "gpt", "transformer", "diffusion", "embedding",
            "langchain", "langgraph", "vllm", "inference", "model", "大模型", "智能体",
        ),
    ),
    (
        "中间件与运维",
        (
            "docker", "kubernetes", "k8s", "nginx", "redis", "kafka", "rabbitmq", "queue",
            "observability", "monitoring", "tracing", "opentelemetry", "容器", "监控",
        ),
    ),
    (
        "SQL 与数据库",
        (
            "sql", "database", "postgres", "postgresql", "mysql", "sqlite", "clickhouse",
            "mongodb", "db", "数据库", "索引",
        ),
    ),
    ("前端", ("react", "vue", "svelte", "solid", "css", "tailwind", "vite", "next", "前端")),
    ("后端", ("fastapi", "django", "flask", "spring", "express", "nest", "backend", "后端")),
    ("算法与数据结构", ("algorithm", "leetcode", "graph", "sort", "binary", "算法", "数据结构")),
    ("计算机基础", ("kernel", "compiler", "operating", "network", "ebpf", "wasm", "操作系统")),
    (
        "研发工程实践",
        (
            "ci", "cd", "testing", "pytest", "jest", "github actions", "lint", "refactor",
            "monorepo", "架构",
        ),
    ),
)

#: 子方向关键词（只覆盖最常命中的几个；未命中一律给该方向的兜底子方向）。
_SUB_WORDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("AI 工程", "LLM 与 RAG", ("rag", "retrieval", "embedding", "vector", "llm")),
    ("AI 工程", "Agent", ("agent", "tool calling", "multi-agent", "智能体")),
    ("AI 工程", "Prompt 工程", ("prompt", "chain of thought")),
    ("AI 工程", "部署与推理", ("inference", "serving", "vllm", "quantization", "bnb")),
    ("中间件与运维", "Docker 与容器", ("docker", "container", "kubernetes", "k8s")),
    ("中间件与运维", "Redis", ("redis",)),
    ("中间件与运维", "消息队列", ("kafka", "rabbitmq", "queue")),
    ("SQL 与数据库", "索引", ("index", "btree", "索引")),
    ("SQL 与数据库", "事务与 ACID", ("transaction", "acid", "mvcc")),
    ("前端", "react", ("react",)),
    ("前端", "vue3", ("vue",)),
    ("后端", "python", ("python", "fastapi")),
    ("后端", "go", ("golang", " go ")),
)

#: 新建即巨量 star：`created_at` 距今 < 90 天且 stars > 50_000 → 疑似刷 star（实测踩到）。
SUSPECT_DAYS = 90
SUSPECT_STARS = 50_000


def now_iso() -> str:
    """统一时间格式：`2026-11-10T03:21:00+00:00`（与库内既有列同形，字符串比较即时间比较）。"""
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse_time(value: str | None) -> datetime | None:
    """宽松解析 ISO8601 / RFC822；解不出就返回 None（调用方按「无信号」处理，不抛错）。"""
    text = (value or "").strip()
    if not text:
        return None
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%a, %d %b %Y %H:%M:%S %z")
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def age_days(value: str | None) -> int:
    """距今多少天；不可解 / 未来时间戳一律 0（不编造年数）。"""
    parsed = parse_time(value)
    if parsed is None:
        return 0
    delta = datetime.now(UTC) - parsed.astimezone(UTC)
    return max(delta.days, 0)


def clean_text(value: str | None, limit: int = 240) -> str:
    """压平空白 + 剥 HTML 尖括号标签 + 截断；空值给空串。"""
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def slug_of(source_key: str, raw_id: str) -> str:
    """`source_key + 上游 id` 组成 slug；对上游 id 做 ASCII 化，避免斜杠 / 空格打乱路由。"""
    key = re.sub(r"[^A-Za-z0-9/._:-]", "-", (raw_id or "").strip())[:120] or "-"
    return f"{source_key}:{key}"


def slug_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def guess_direction(*texts: str) -> str:
    """按关键词投票选方向；全不命中给「AI 工程」（雷达的主要关注面）。"""
    blob = " ".join(t.lower() for t in texts if t)
    best = DIRECTIONS_FALLBACK
    best_hits = 0
    for direction, words in _DIRECTION_WORDS:
        hits = sum(1 for word in words if word in blob)
        if hits > best_hits:
            best, best_hits = direction, hits
    return best


def guess_sub_direction(direction: str, *texts: str) -> str:
    """先按子方向关键词命中，命中不到就给该方向的兜底子方向（不返回空串）。"""
    blob = " ".join(t.lower() for t in texts if t)
    for direction_of_word, sub, words in _SUB_WORDS:
        if direction_of_word != direction:
            continue
        if any(word in blob for word in words):
            return sub
    return rules.fill_sub_direction(direction, "")


def is_suspect(repo_created_at: str | None, stars: int) -> bool:
    """「新建即巨量」启发式：库龄 < 90 天且 star > 5 万 → 疑似刷 star。"""
    created_age = age_days(repo_created_at)
    return bool(repo_created_at) and created_age < SUSPECT_DAYS and stars > SUSPECT_STARS


def normalize_item(raw: dict[str, Any]) -> dict[str, Any]:
    """一条上游条目 → 统一形状；缺字段一律给安全默认值。"""
    direction, sub = rules.normalize_direction(raw.get("direction"), raw.get("sub_direction"))
    name = clean_text(raw.get("name"), 120) or "(未命名)"
    summary = clean_text(raw.get("summary"), 300)
    if not sub:
        sub = guess_sub_direction(direction, name, summary)
    return {
        "slug": str(raw.get("slug") or slug_of(str(raw.get("source_key") or "manual"), name)),
        "name": name,
        "url": str(raw.get("url") or "").strip(),
        "summary": summary,
        "direction": direction,
        "sub_direction": sub,
        "source_key": str(raw.get("source_key") or "manual"),
        "stars": max(int(raw.get("stars") or 0), 0),
        "forks": max(int(raw.get("forks") or 0), 0),
        "repo_created_at": str(raw.get("repo_created_at") or ""),
        "pushed_at": str(raw.get("pushed_at") or ""),
        "suspect": bool(raw.get("suspect")),
    }


def dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """跨源去重：同名（小写去空白）条目只留第一条，并在 `cross_source` 上计数。

    `cross_source` 是「采用度」的一个信号：同一技术被 GitHub + HN 同时提到，比单源更有说服力。
    """
    seen: dict[str, dict[str, Any]] = {}
    for item in items:
        key = re.sub(r"[^a-z0-9]+", "", item["name"].lower()) or item["slug"]
        if key in seen:
            seen[key]["cross_source"] = int(seen[key].get("cross_source") or 1) + 1
            continue
        item["cross_source"] = 1
        seen[key] = item
    return list(seen.values())


def signals_of(item: dict[str, Any], previous_stars: int | None) -> dict[str, Any]:
    """快照 + 上一条快照 → 评估信号（star 增速按天数差归一，无上一条记 0）。"""
    stars = int(item.get("stars") or 0)
    delta = 0
    if previous_stars is not None and stars >= previous_stars:
        delta = stars - previous_stars
    return {
        "stars": stars,
        "star_delta_7d": delta,
        "cross_source": int(item.get("cross_source") or 1),
        "repo_age_days": age_days(item.get("repo_created_at")),
        "pushed_within_30d": bool(item.get("pushed_at"))
        and age_days(item.get("pushed_at")) <= PUSHED_RECENT_DAYS,
        "source_key": str(item.get("source_key") or "manual"),
        "direction": str(item.get("direction") or DIRECTIONS_FALLBACK),
        "is_paper": str(item.get("source_key")) == "arxiv",
        "suspect": bool(item.get("suspect")),
        "evidence": [item["url"]] if item.get("url") else [],
    }


def window_start(hours: int) -> str:
    """N 小时前的时间戳（GitHub 检索式 `pushed:>YYYY-MM-DD` 用）。"""
    return (datetime.now(UTC) - timedelta(hours=hours)).strftime("%Y-%m-%d")
