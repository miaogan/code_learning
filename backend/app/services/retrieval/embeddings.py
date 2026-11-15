"""r100 embedding provider 层：离线确定性 Hashing 与 OpenAI 兼容远端两条路。

设计口径（与 `config.resolve_ai()` 的三不变量同构，写死后别漂）：

1. **确定性是硬约束**：`HashingEmbedder` 用 `zlib.crc32`（跨进程稳定）做特征哈希，
   绝不用内建 `hash()`（PYTHONHASHSEED 每次启动都会变，CI 里「同一文本两次运行
   得到不同向量」是最难排查的 flaky）。它是默认档：`AI_EMBED_MODEL` 留空即启用，
   评测门禁因此可以零网络、零 Key、逐字节复跑。
2. **远端档不回落主档 Key 的规则与视觉档相同**：`AI_EMBED_BASE_URL` / `AI_EMBED_API_KEY`
   留空 = 继承主档（同一账号换个模型名的默认用法）；显式填写则只认该档。
3. **维度是索引的一部分**：`dim` 进 DDL（`vector(dim)` 列），换 embedder / 换维度
   必须重建索引；插入前逐条校验 `len(vec) == dim`，不匹配即抛中文错误，
   不让错维向量静默落库（那会让余弦相似度变成噪声）。

`HashingEmbedder` 是 char-bigram + 特征哈希（hashing trick）：中文按字、英文按词内
字符对折叠，无需分词器与模型文件；它给出的「语义」本质是**字符重叠度**，
检索评测里它的角色是**可复跑的基座**——真实语义换 `AI_EMBED_MODEL` 指向任意
OpenAI 兼容 `/embeddings` 端点（LM Studio 本地模型或云端 embedding 服务）即可，
管线代码零改动。
"""

from __future__ import annotations

import logging
import math
import re
import time
import unicodedata
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import AiRuntime, Settings, get_settings
from app.core.errors import AI_UNAVAILABLE, AppError

logger = logging.getLogger("app.rag.embeddings")

#: 归一化时去掉的字符类：控制符 / 空白 / 标点。中文标点（，。、；：）也在其中。
_STRIP_RE = re.compile(r"[\s\W_]+", re.UNICODE)

EmbeddingVector = list[float]


class Embedder(Protocol):
    """同步协议：检索路由本身是同步的（FastAPI 同步路由跑线程池），不掺 async。"""

    @property
    def name(self) -> str: ...

    @property
    def dim(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> list[EmbeddingVector]: ...


@dataclass(frozen=True)
class EmbedderRuntime:
    """一次解析出的 embedding 运行期口径（`resolve_embedder` 的返回值）。

    `kind ∈ {"hash", "remote"}`：`hash` = 离线确定性（零网络、CI 可复跑）；
    `remote` = OpenAI 兼容 `/embeddings` 端点。`name` 是索引的组成成分
    （进 `rag_chunks.embedder` 列与 content_sha），换 name 即换索引。
    """

    kind: str
    name: str
    dim: int
    embedder: Embedder
    ready: bool = True
    reason: str = ""


def normalize_text(text: str) -> str:
    """小写 + NFKC + 去空白与标点。中文标点全角形式经 NFKC 后仍在 `\\W` 集内，一并去掉。"""
    lowered = unicodedata.normalize("NFKC", str(text or "")).lower()
    return _STRIP_RE.sub("", lowered)


def _stable_hash(feature: str, dim: int) -> int:
    """crc32 特征哈希：跨进程 / 跨机器确定（内建 `hash()` 受 PYTHONHASHSEED 影响不可用）。"""
    return zlib.crc32(feature.encode("utf-8")) % dim


class HashingEmbedder:
    """char-bigram 特征哈希向量：确定性、零依赖、零网络。

    - 特征 = 归一化文本的相邻字符对（保留一个单字特征兜底，短词如「锁」也能命中）；
    - 每个 bigram 命中一次 +1（bag-of-bigrams），最后 L2 归一（空文本给零向量）；
    - 相似度语义 = 字符 bigram 的 Jaccard 重叠近似 —— 是**模糊关键词**基座，
      不是语义模型；接入真实语义模型见 `RemoteEmbedder`。
    """

    def __init__(self, dim: int = 256) -> None:
        self._dim = int(dim)

    @property
    def name(self) -> str:
        return f"hash-bigram-{self._dim}"

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        vectors: list[EmbeddingVector] = []
        for raw in texts:
            text = normalize_text(raw)
            vec: EmbeddingVector = [0.0] * self._dim
            if text:
                features = [text[i : i + 2] for i in range(len(text) - 1)] or [text]
                for feature in features:
                    vec[_stable_hash(feature, self._dim)] += 1.0
                norm = math.sqrt(sum(value * value for value in vec))
                if norm > 0:
                    vec = [value / norm for value in vec]
            vectors.append(vec)
        return vectors


class RemoteEmbedder:
    """OpenAI 兼容 `/embeddings` 端点：显式档位（不悄悄回落别的服务）。

    端点 / Key 缺省继承主档（`resolve_ai()` 的快照），批量按 `ai_embed_batch` 切分；
    任何失败抛 `AI_UNAVAILABLE`（中文 message、`retryable=True`），不静默降级成零向量
    ——零向量会让余弦排序变成随机排序，比报错更糟。
    """

    def __init__(self, base_url: str, model: str, api_key: str, dim: int,
                 timeout_s: float, batch_size: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._dim = int(dim)
        self._timeout_s = float(timeout_s)
        self._batch = max(1, int(batch_size))

    @property
    def name(self) -> str:
        return f"remote:{self._model}"

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        vectors: list[EmbeddingVector] = []
        for start in range(0, len(texts), self._batch):
            vectors.extend(self._embed_batch(list(texts[start : start + self._batch])))
        return vectors

    def _embed_batch(self, batch: list[str]) -> list[EmbeddingVector]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {"model": self._model, "input": batch}
        try:
            with httpx.Client(timeout=self._timeout_s) as client:
                response = client.post(
                    self._base_url + "/embeddings", json=payload, headers=headers
                )
        except httpx.HTTPError as exc:
            raise AppError(
                AI_UNAVAILABLE,
                "embedding 服务连接失败，请检查 AI_EMBED_BASE_URL / AI_EMBED_MODEL",
                retryable=True,
            ) from exc
        if response.status_code != 200:
            raise AppError(
                AI_UNAVAILABLE,
                "embedding 服务返回 "
                + str(response.status_code)
                + "，请检查模型名与 Key（AI_EMBED_MODEL / AI_EMBED_API_KEY）",
                retryable=True,
            )
        data: dict[str, Any] = response.json()
        rows = sorted(data.get("data") or [], key=lambda item: int(item.get("index", 0)))
        vectors = [[float(value) for value in row["embedding"]] for row in rows]
        if len(vectors) != len(batch):
            raise AppError(
                AI_UNAVAILABLE, "embedding 服务返回条数与请求不一致", retryable=True
            )
        return vectors


#: 与 `AiRuntime` 同款的「解析永不 raise」：配置错只置 ready=False + 中文 reason，
#: 调用方（索引重建 / 检索入口）据此走「RAG 未就绪」提示，而不是 500。
def resolve_embedder(settings: Settings | None = None) -> EmbedderRuntime:
    """唯一解析出口：`AI_EMBED_MODEL` 空 → 离线 Hashing；非空 → OpenAI 兼容远端。"""
    current = settings or get_settings()
    dim = int(current.ai_embed_dim)
    model = current.ai_embed_model.strip()
    if not model:
        return EmbedderRuntime(
            kind="hash",
            name=HashingEmbedder(dim).name,
            dim=dim,
            embedder=HashingEmbedder(dim),
        )
    main: AiRuntime = current.resolve_ai()
    base_url = current.ai_embed_base_url.strip() or main.base_url
    api_key = current.ai_embed_api_key.strip() or main.api_key
    runtime = EmbedderRuntime(
        kind="remote",
        name=f"remote:{model}",
        dim=dim,
        embedder=RemoteEmbedder(
            base_url, model, api_key, dim,
            timeout_s=current.ai_embed_timeout_s, batch_size=current.ai_embed_batch,
        ),
    )
    if not base_url:
        return EmbedderRuntime(
            kind="remote", name=runtime.name, dim=dim, embedder=runtime.embedder,
            ready=False, reason="AI_EMBED_MODEL 已设置但 AI_EMBED_BASE_URL 为空，请检查 backend/.env",
        )
    if not main.ready and not current.ai_embed_base_url.strip():
        return EmbedderRuntime(
            kind="remote", name=runtime.name, dim=dim, embedder=runtime.embedder,
            ready=False, reason="主档 AI 未配置，embedding 无法继承端点：请配置主档或显式填 AI_EMBED_BASE_URL",
        )
    return runtime


def now_ms() -> int:
    return int(time.time() * 1000)
