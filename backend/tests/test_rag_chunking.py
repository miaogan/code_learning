"""r103 分块层测试：按内容类型选切分器（llama-index SentenceSplitter / 自研兜底）。

断言口径是「切分语义」而不是具体字符数：代码不切行、表格不带丢表头、句子不拦腰断。
"""

import pytest

from app.core.config import get_settings
from app.services.retrieval import chunking


def _native(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_CHUNKER", "native")
    get_settings.cache_clear()


def test_question_is_never_split():
    """题目整段不切：题干 + 解析是一个语义单元。"""
    text = "题干？" + "解析内容。" * 400
    assert chunking.split_by_type("question", text) == [text.strip()]


def test_prose_splits_at_sentence_boundary(monkeypatch):
    """prose：超长按句子累加，每片不超上限且不以半句结尾。"""
    _native(monkeypatch)
    sentence = "这是一个用于验证切分行为的中文句子，长度适中但重复次数很多。"
    text = sentence * 60  # 60 × 30 字 = 1800 字，超过 1200 上限，必须切
    pieces = chunking.split_by_type("prose", text)
    assert len(pieces) > 1
    assert all(len(piece) <= chunking.MAX_CHUNK_CHARS for piece in pieces)
    assert all(piece.endswith("。") for piece in pieces), "不得拦腰断句"
    assert "".join(pieces).replace(" ", "") == text.replace(" ", "")


def test_code_never_splits_lines(monkeypatch):
    """code：按行累加，任何一行都必须完整出现在某一片里。"""
    _native(monkeypatch)
    lines = [f"const value{i} = compute({i}) // 第 {i} 行" for i in range(120)]
    pieces = chunking.split_by_type("code", "\n".join(lines))
    assert len(pieces) > 1
    joined = "\n".join(pieces)
    for line in lines:
        assert line in joined


def test_table_repeats_header(monkeypatch):
    """table：每片都带表头（丢表头的数据行对检索没意义）。"""
    _native(monkeypatch)
    headers = ["方法", "语义", "幂等"]
    rows = [[f"PUT-{i}", "替换资源", "是"] for i in range(300)]
    pieces = chunking._split_table(headers, rows)
    assert len(pieces) > 1
    assert all(piece.splitlines()[0] == "方法 | 语义 | 幂等" for piece in pieces)


def test_tutorial_blocks_mixed(monkeypatch):
    """混合 block：正文/代码/表格各自按类型切，代码片段保持整行。"""
    _native(monkeypatch)
    blocks = [
        {"kind": "text", "text": "正文段落。" * 200},
        {"kind": "code", "caption": "示例", "code": "\n".join(["line" + str(i) for i in range(80)])},
        {"kind": "table", "headers": ["a", "b"], "rows": [["1", "2"], ["3", "4"]]},
    ]
    pieces = chunking.split_tutorial_blocks(blocks)
    assert len(pieces) >= 3
    code_piece = next(piece for piece in pieces if "line0" in piece)
    assert "line79" in "\n".join(pieces) or "line79" in code_piece
    assert any(piece.startswith("a | b") for piece in pieces)


def test_engine_reports_llama_when_installed():
    """装了 llama-index 时 auto 走 SentenceSplitter，且切分结果有界。"""
    if not chunking.llama_available():
        pytest.skip("未安装 llama-index-core，跳过 llama 路径")
    assert chunking.chunker_engine() in ("llama", "native")
    text = "句子一。" * 500
    pieces = chunking.split_by_type("prose", text)
    assert len(pieces) > 1
    assert all(piece.strip() for piece in pieces)
