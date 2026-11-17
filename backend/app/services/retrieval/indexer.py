"""r100 RAG 索引构建：题库全量重建 + 教程小节整份摄取。

两种写入都走**全量替换**语义（`rag_write_chunks(replace_kind=...)`）：
- 题库行可能被 `question_merge` / 国子监 adopt 改写，增量 diff 的正确性依赖
  「主键永不复用」这一并不成立的前提；全量替换让索引与题库强一致。
- 教程正文只在前端（`content/tutorials/`），摄取端点收到的就是整份语料，
  天然适合整份替换，也顺带消灭了「换 embedding 模型后新旧向量混排」的问题
  ——不同向量空间不可比，混排的余弦排序是噪声。

`content_sha = sha256(embedder + NUL + content)`：换 embedding 模型自然失效，
同模型下同内容则逐字节稳定，供评测与排障对账。
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from app.core import repository
from app.core.db import rag_embedding_mode
from app.core.errors import AI_UNAVAILABLE, AppError
from app.services.retrieval import tutorial_seed
from app.services.retrieval.chunking import split_tutorial_blocks
from app.services.retrieval.embeddings import EmbedderRuntime, resolve_embedder

logger = logging.getLogger("app.rag.indexer")

#: 单个 chunk 的正文上限：题目 prompt + explanation 实测最长 ≈2k 字符，
#: 教程小节可能更长；截断保证 embedding 输入与检索回显的尺寸有界。
MAX_CHUNK_CHARS = 4000

#: 题库 chunk 的 title 口径：`方向 · 二级方向`（difficulty 不进 title，
#: 避免同一难度词在向量里形成伪语义）。
def _question_title(row: dict[str, Any]) -> str:
    parts = [str(row["direction"] or "").strip()]
    sub = str(row.get("sub_direction") or "").strip()
    if sub:
        parts.append(sub)
    return " · ".join(part for part in parts if part)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def content_sha(content: str, embedder_name: str) -> str:
    """内容指纹：embedder 名进哈希——换模型即换指纹，天然标记「该向量已过期」。"""
    digest = hashlib.sha256()
    digest.update(embedder_name.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(content.encode("utf-8"))
    return digest.hexdigest()


def _runtime_or_raise(runtime: EmbedderRuntime | None) -> EmbedderRuntime:
    current = runtime or resolve_embedder()
    if not current.ready:
        raise AppError(AI_UNAVAILABLE, current.reason or "embedding 未配置", retryable=False)
    return current


def _embed_all(runtime: EmbedderRuntime, texts: list[str]) -> list[list[float]]:
    """批量 embedding + 维度断言：错维向量一旦落库，余弦排序会变成噪声排序。"""
    vectors = runtime.embedder.embed(texts)
    for vector in vectors:
        if len(vector) != runtime.dim:
            raise AppError(
                AI_UNAVAILABLE,
                "embedding 返回维度 "
                + str(len(vector))
                + " 与配置 AI_EMBED_DIM="
                + str(runtime.dim)
                + " 不一致，请对齐后重建索引",
                retryable=False,
            )
    return vectors


def _question_chunk_rows(runtime: EmbedderRuntime) -> list[dict[str, Any]]:
    """题库 → chunk 行（answer 刻意不进索引：与检索/练习的答案口径一致，永不外泄）。"""
    rows = repository.question_chunk_rows()
    built: list[dict[str, Any]] = []
    contents: list[str] = []
    seen: set[str] = set()
    for row in rows:
        # 题库允许历史脏数据存在重复 id 行（生产实测 64 对，ctid 显示是早期迁移重复导入，
        # 内容完全相同）。chunk 以 `question:<id>` 为主键，重复会让「写入条数」虚高、
        # 而库里按唯一约束只留一行 —— 这里显式去重（先到先得），并如实记 warning，
        # 避免出现「written 1348 / stored 1284」这种对不上的数字。
        question_id = str(row["id"])
        if question_id in seen:
            logger.warning("rag.indexer.duplicate_question id=%s skipped", question_id)
            continue
        seen.add(question_id)
        prompt = str(row["prompt"] or "").strip()
        explanation = str(row["explanation"] or "").strip()
        content = (prompt + "\n\n" + explanation).strip()[:MAX_CHUNK_CHARS]
        if not content:
            continue
        built.append(
            {
                "id": "question:" + str(row["id"]),
                "kind": "question",
                "ref_id": str(row["id"]),
                "section_id": "",
                "title": _question_title(row),
                "content": content,
                "embedder": runtime.name,
            }
        )
        contents.append(content)
    vectors = _embed_all(runtime, contents)
    stamp = _now_iso()
    for chunk, vector in zip(built, vectors, strict=True):
        chunk["content_sha"] = content_sha(chunk["content"], runtime.name)
        chunk["created_at"] = stamp
        chunk["embedding"] = vector
    return built


def rebuild_question_index(runtime: EmbedderRuntime | None = None) -> dict[str, Any]:
    """题库索引全量替换 + 索引状态原子更新。返回摘要（HTTP 层直接投影）。"""
    current = _runtime_or_raise(runtime)
    mode = rag_embedding_mode()
    if mode == "missing":
        raise AppError(
            AI_UNAVAILABLE, "RAG 表结构未初始化，请先重启服务执行 init_db", retryable=False
        )
    rows = _question_chunk_rows(current)
    written = repository.rag_write_chunks(rows, mode=mode, replace_kind="question")
    repository.rag_state_put(
        current.name, current.dim, repository.rag_chunk_counts()["total"], _now_iso()
    )
    summary = index_status()
    summary["written"] = written
    return summary


def ingest_tutorial_chunks(
    items: list[dict[str, Any]], runtime: EmbedderRuntime | None = None
) -> dict[str, Any]:
    """教程小节整份替换：`items` 是前端组装的**整份**语料（章节 + 小节 + 标题 + 正文）。

    语义上这是「重建 tutorial 索引」而不是「追加」——少推一节不会报错，但那一节
    的旧 chunk 会被删掉（整份替换）。前端契约因此必须是全量推送。
    """
    current = _runtime_or_raise(runtime)
    mode = rag_embedding_mode()
    if mode == "missing":
        raise AppError(
            AI_UNAVAILABLE, "RAG 表结构未初始化，请先重启服务执行 init_db", retryable=False
        )
    contents: list[str] = []
    built: list[dict[str, Any]] = []
    for item in items:
        chapter_id = str(item.get("chapter_id") or "").strip()
        if not chapter_id:
            continue
        title = str(item.get("title") or "").strip()[:200]
        base_section = str(item.get("section_id") or "").strip()
        # r103：结构化 block 优先（按类型切分）；旧客户端只有 content 时退回整段一个 chunk。
        blocks = item.get("blocks") or []
        if blocks:
            pieces = split_tutorial_blocks(blocks)
        else:
            content = str(item.get("content") or "").strip()
            pieces = [content] if content else []
        for index, piece in enumerate(pieces):
            text = (title + "\n" + piece).strip() if title else piece.strip()
            text = text[:MAX_CHUNK_CHARS]
            if not text:
                continue
            # 小节被切成多片时，`section_id` 加 `#n` 后缀保证唯一（锚点仍是前半段）。
            section_id = (
                base_section
                if len(pieces) == 1
                else (base_section or "sec") + "#" + str(index + 1)
            )
            built.append(
                {
                    "id": "tutorial:" + chapter_id + ":" + section_id,
                    "kind": "tutorial",
                    "ref_id": chapter_id,
                    "section_id": section_id,
                    "title": title,
                    "content": text,
                    "embedder": current.name,
                }
            )
            contents.append(text)
    vectors = _embed_all(current, contents)
    stamp = _now_iso()
    for chunk, vector in zip(built, vectors, strict=True):
        chunk["content_sha"] = content_sha(chunk["content"], current.name)
        chunk["created_at"] = stamp
        chunk["embedding"] = vector
    written = repository.rag_write_chunks(built, mode=mode, replace_kind="tutorial")
    repository.rag_state_put(
        current.name, current.dim, repository.rag_chunk_counts()["total"], _now_iso()
    )
    summary = index_status()
    summary["written"] = written
    return summary


def index_status() -> dict[str, Any]:
    """RAG 索引状态快照（只读）：status / rebuild / ingest 三处共用同一口径。"""
    runtime = resolve_embedder()
    state = repository.rag_state_get()
    counts = repository.rag_chunk_counts()
    breakdown = repository.rag_embedder_breakdown()
    stale = any(name and name != runtime.name for name in breakdown)
    notice = ""
    if state is None and counts["total"] > 0:
        notice = "索引状态缺失（chunk 行存在但没有构建记录），请重建索引"
    elif state is None:
        notice = "RAG 索引尚未构建：先重建题库索引，再从学堂页推送教程正文"
    elif stale:
        notice = "部分索引与当前 embedding 配置不一致，请重建索引"
    return {
        "built": state is not None or counts["total"] > 0,
        "embedder": runtime.name,
        "dim": runtime.dim,
        "engine": rag_embedding_mode(),
        "chunk_count": counts["total"],
        "question_chunks": counts.get("question", 0),
        "tutorial_chunks": counts.get("tutorial", 0),
        "built_at": (state or {}).get("built_at", ""),
        "stale": stale,
        "embedder_kind": runtime.kind,
        "notice": notice,
    }


def ensure_tutorials_indexed(runtime: EmbedderRuntime | None = None) -> dict[str, Any] | None:
    """启动时补齐教程索引：**只在教程 chunk 为 0 时**灌种子（幂等、不覆盖用户推送）。

    为什么不无条件重灌：远程 embedding 下 165 个小节要几十秒，每次启动都跑既慢又浪费；
    教程内容有变化时走两条明确路径——前端点「推送教程正文」，或删掉 tutorial chunk 后重启。
    `ingest_tutorial_chunks` 本身是「整份替换」，所以「0 条才灌」不会留下半份索引。
    """
    items = tutorial_seed.load_items()
    if not items:
        return None
    counts = repository.rag_chunk_counts()
    existing = counts.get("tutorial", 0)
    if existing > 0:
        return {
            "skipped": True,
            "tutorial_chunks": existing,
            "chunk_count": counts["total"],
        }
    logger.info("rag.tutorial_seed.ingest items=%d", len(items))
    summary = ingest_tutorial_chunks(items, runtime)
    summary["skipped"] = False
    return summary
