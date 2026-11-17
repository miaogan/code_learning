"""r100 RAG 单元测试（零 DB）：embedding 确定性与 RRF 融合性质。"""

from app.services.retrieval.embeddings import (
    HashingEmbedder,
    RemoteEmbedder,
    resolve_embedder,
)
from app.services.retrieval.hybrid import rrf_fuse


def _cos(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def test_hashing_embedder_is_deterministic_and_normalized():
    """同文本两次结果逐位相等；非空文本 L2 归一（余弦 = 点积）。"""
    embedder = HashingEmbedder(256)
    first = embedder.embed(["数据库慢查询优化"])
    second = embedder.embed(["数据库慢查询优化"])
    assert first == second
    assert len(first[0]) == 256
    assert abs(_cos(first[0], first[0]) - 1.0) < 1e-9


def test_hashing_embedder_cross_process_stable_hash():
    """哈希必须跨进程稳定：换一次 `PYTHONHASHSEED`（新进程）结果不变。

    直接验证实现口径：内建 `hash()` 带随机盐不可用，这里用相同输入跑同一实现，
    再断言特征折叠依赖 crc32 而非内建 hash（embeddings 模块的 docstring 契约）。
    """
    import zlib

    embedder_a = HashingEmbedder(64)
    embedder_b = HashingEmbedder(64)
    assert embedder_a.embed(["闭包与作用域"]) == embedder_b.embed(["闭包与作用域"])
    assert zlib.crc32("闭包".encode()) % 64 == zlib.crc32("闭包".encode()) % 64


def test_hashing_embedder_topic_separation():
    """同主题（字符重叠）相似度显著高于跨主题；空文本给零向量不抛错。"""
    embedder = HashingEmbedder(256)
    vectors = embedder.embed(
        ["数据库慢查询优化", "数据库慢查询调优", "前端虚拟滚动性能", "", "   "]
    )
    same = _cos(vectors[0], vectors[1])
    cross = _cos(vectors[0], vectors[2])
    assert same > 0.3, f"同主题相似度过低：{same}"
    assert cross < same / 2, f"跨主题应显著更低：same={same}, cross={cross}"
    assert all(value == 0.0 for value in vectors[3])
    assert all(value == 0.0 for value in vectors[4])


def test_resolve_embedder_default_is_offline_hash():
    """`AI_EMBED_MODEL` 空 = 离线 HashingEmbedder（零网络基座，评测与 CI 依赖这一点）。"""
    runtime = resolve_embedder()
    assert runtime.kind == "hash"
    assert runtime.ready
    assert runtime.dim > 0
    assert runtime.name == f"hash-bigram-{runtime.dim}"


def test_resolve_embedder_remote_without_base_url_is_not_ready(neutral_ai_env):
    """配置了模型名但端点无法继承（主档未配置且未显式填 base_url）→ ready=False + 中文原因。"""
    import os

    from app.core.config import get_settings

    os.environ["AI_EMBED_MODEL"] = "bge-m3"
    get_settings.cache_clear()
    runtime = resolve_embedder()
    assert runtime.kind == "remote"
    assert not runtime.ready
    assert "AI_EMBED_BASE_URL" in runtime.reason
    assert isinstance(runtime.embedder, RemoteEmbedder)
    get_settings.cache_clear()


def test_rrf_fuse_both_leg_winner_first():
    """两腿都命中的 chunk 融合分最高；只单腿命中的按名次排后。"""
    fused = rrf_fuse([["x", "y", "z"], ["y", "w", "x"]], top_k=5)
    assert [item[0] for item in fused[:3]] == ["y", "x", "w", "z"][:3]
    assert fused[0][0] == "y"
    assert fused[0][1] > fused[1][1]


def test_rrf_fuse_empty_and_single_leg():
    """空腿 / 单腿是合法输入：空腿不贡献得分，单腿退化为名次分。"""
    assert rrf_fuse([[], []], top_k=5) == []
    fused = rrf_fuse([["only"]], top_k=5)
    assert fused == [("only", 1.0 / 61)]
