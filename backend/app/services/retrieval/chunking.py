"""r103 分块层：按**内容类型**选切分策略（llama-index 可用时走它的 SentenceSplitter）。

为什么不是「一把 SentenceSplitter 切所有东西」：站内语料是混合体——
题目（短，整段最好）、教程正文（段落/句子）、代码（按行，切在语句中间就是垃圾）、
表格（行组必须连同表头）。同一套滑窗参数切这四类，代码块会被切碎、表格会丢表头，
召回质量反而下降。

分工：
- **prose**（正文/列表）：优先用 llama-index 的 `SentenceSplitter`（按 token 计数、
  带重叠，业界标准实现）；未装 llama-index 或显式 `RAG_CHUNKER=native` 时用等价的
  自研句子累加器——两条路都保证「不切碎句子」。
- **code**：自研按行累加、绝不切在行中间；llama 的 `CodeSplitter` 需要 tree-sitter
  语言包（多一套二进制依赖），收益不抵成本，刻意不用。
- **table**：自研按行批切、每批重复表头（llama 的 MarkdownNodeParser 只认 markdown
  文本表格，我们的表格是结构化 block，交给它反而要先拼再拆）。
- **question**：整段不切（题干 + 解析是一个语义单元，切开只会丢上下文）。

`RAG_CHUNKER=auto`（默认）在装有 llama-index 时用它切 prose，否则全程自研；
两条路径的输出都受 `MAX_CHUNK_CHARS` 上限约束，落库口径一致。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger("app.rag.chunking")

#: 单块正文上限（字符）：与 indexer 的落库上限同源，避免「切完又截断」。
MAX_CHUNK_CHARS = 1200
#: 句子切分：中英文句末标点后断开（保留标点）。
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；!?;])\s*")

_llama_splitter: Any = None
_llama_checked = False


def _settings():
    return get_settings()


def llama_available() -> bool:
    """探测 llama-index 是否可用（导入失败只记一次日志，不反复抛）。"""
    global _llama_checked, _llama_splitter
    if _llama_checked:
        return _llama_splitter is not None
    _llama_checked = True
    try:
        from llama_index.core.node_parser import SentenceSplitter

        _llama_splitter = SentenceSplitter(
            chunk_size=_settings().rag_chunk_tokens,
            chunk_overlap=_settings().rag_chunk_overlap,
        )
    except Exception as exc:  # 未安装 / 版本不兼容：退回自研实现，不影响主链路
        logger.info("rag.chunking.llama_unavailable error=%s", type(exc).__name__)
        _llama_splitter = None
    return _llama_splitter is not None


def chunker_engine() -> str:
    """当前实际生效的 prose 切分引擎（status / 日志用，如实报告）。"""
    mode = _settings().rag_chunker.strip().lower()
    if mode == "native":
        return "native"
    if mode == "llama":
        return "llama" if llama_available() else "native"
    return "llama" if llama_available() else "native"


def _split_prose_native(text: str) -> list[str]:
    """自研句子累加器：按句末标点断句，累加到接近上限，段落边界优先断开。"""
    limit = MAX_CHUNK_CHARS
    pieces: list[str] = []
    for paragraph in re.split(r"\n{2,}", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        sentences = [item for item in _SENTENCE_SPLIT.split(paragraph) if item.strip()]
        buffer = ""
        for sentence in sentences:
            if buffer and len(buffer) + len(sentence) > limit:
                pieces.append(buffer.strip())
                buffer = ""
            buffer += sentence
        if buffer.strip():
            pieces.append(buffer.strip())
    return [piece for piece in pieces if piece]


def _split_prose_llama(text: str) -> list[str]:
    """llama-index 的 SentenceSplitter（按 token 计数 + 重叠，业界标准实现）。"""
    splitter = _llama_splitter
    if splitter is None:
        return _split_prose_native(text)
    chunks = splitter.split_text(text)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _split_code(text: str) -> list[str]:
    """代码按行累加：**绝不切在行中间**；优先在空行（逻辑块边界）断开。"""
    lines = text.splitlines()
    pieces: list[str] = []
    buffer: list[str] = []
    length = 0
    for line in lines:
        if buffer and length + len(line) + 1 > MAX_CHUNK_CHARS:
            pieces.append("\n".join(buffer).strip())
            buffer, length = [], 0
        buffer.append(line)
        length += len(line) + 1
    if buffer:
        pieces.append("\n".join(buffer).strip())
    return [piece for piece in pieces if piece]


def _split_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    """表格按行批切，每批都带表头——丢了表头的数据行对检索毫无意义。"""
    header_line = " | ".join(str(cell) for cell in headers)
    pieces: list[str] = []
    buffer = [header_line]
    length = len(header_line)
    for row in rows:
        line = " | ".join(str(cell) for cell in row)
        if len(buffer) > 1 and length + len(line) + 1 > MAX_CHUNK_CHARS:
            pieces.append("\n".join(buffer))
            buffer = [header_line]
            length = len(header_line)
        buffer.append(line)
        length += len(line) + 1
    if len(buffer) > 1:
        pieces.append("\n".join(buffer))
    return pieces


def split_by_type(content_type: str, text: str) -> list[str]:
    """单段文本按类型切分（question 整段、prose 句子累加、code 按行）。"""
    body = str(text or "").strip()
    if not body:
        return []
    if content_type == "question":
        return [body]
    if content_type == "code":
        return _split_code(body)
    if chunker_engine() == "llama":
        return _split_prose_llama(body)
    return _split_prose_native(body)


def _serialize_block(block: dict[str, Any]) -> tuple[str, str]:
    """教程 block → (内容类型, 文本)。与前端 `TutorialBlock` 的 kind 一一对应。

    表格走 `split_tutorial_blocks` 的结构化分支（要保留表头），这里只做兜底序列化。
    """
    kind = str(block.get("kind") or "text")
    if kind in ("text", "note"):
        title = str(block.get("title") or "").strip()
        text = str(block.get("text") or "").strip()
        return "prose", (title + "：" + text if title else text)
    if kind == "list":
        items = [str(item).strip() for item in (block.get("items") or []) if str(item).strip()]
        return "prose", "；".join(items)
    if kind == "table":
        headers = [str(cell) for cell in (block.get("headers") or [])]
        rows = [[str(cell) for cell in row] for row in (block.get("rows") or [])]
        text = "\n".join([" | ".join(headers), *(" | ".join(row) for row in rows)])
        return "prose", text
    if kind == "code":
        caption = str(block.get("caption") or "").strip()
        code = str(block.get("code") or "").strip()
        return "code", (caption + "\n" + code if caption else code)
    return "prose", str(block.get("text") or "")


def split_tutorial_blocks(blocks: Sequence[dict[str, Any]]) -> list[str]:
    """教程小节：逐 block 按其类型切分，产出一组子片（顺序与原文一致）。

    表格 block 特殊处理（结构化行 + 表头重复），其余走 `split_by_type`。
    """
    pieces: list[str] = []
    for block in blocks:
        kind = str(block.get("kind") or "text")
        if kind == "table":
            headers = [str(cell) for cell in (block.get("headers") or [])]
            rows = [[str(cell) for cell in row] for row in (block.get("rows") or [])]
            if headers and rows:
                pieces.extend(_split_table(headers, rows))
            continue
        content_type, text = _serialize_block(block)
        if text:
            pieces.extend(split_by_type(content_type, text))
    return [piece for piece in pieces if piece.strip()]
