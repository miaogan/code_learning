"""r117 向量检索后端：与 `DB_MODE` 同构的四档 + 自动档，检索层唯一分派点。

四档语义（`VECTOR_MODE`）：

| 档位 | 向量存哪 | 相似度在哪算 | `engine` 字段 | 适用 |
|---|---|---|---|---|
| `pgvector` | `rag_chunks.embedding`（`vector(dim)` 或 `double precision[]`） | SQL `<=>` 或取回后 Python | `pgvector` / `python-cosine` | 有 PG 的部署（现状不变） |
| `sqlite` | `rag_chunks.embedding`（JSON 文本） | 取回后 Python 余弦 | `python-cosine` | 内网单机、连 faiss 都不想装 |
| `faiss` | **本地单文件索引**（每 kind 一个 `.faiss` + sidecar JSON） | faiss `IndexFlatIP`（C++ SIMD） | `faiss` | 内网 / 气隙，单文件可随库一起备份 |
| `milvus` | 远端 Milvus collection | Milvus HNSW `COSINE` | `milvus` | 有向量库服务的企业内网 |

设计约束（与 `resolve_ai` / `resolve_embedder` 同款三条不变量）：

1. **解析永不 raise**：配置错 / 依赖缺失 / 服务不可达都折成 `ready=False` + 中文 reason，
   由调用方（检索入口 / 索引状态）给「为什么没有结果」，绝不 500。
2. **元数据的唯一事实源仍是 `rag_chunks`**：faiss / Milvus 只是派生索引，`write()` 先把
   元数据行写进业务库（事务化、可回滚、幂等），再把向量写进派生索引。索引坏了 = 重建，
   不丢数据；索引和库的一致性由 sidecar 的 `(embedder, dim, count)` 对账（见 `_stale_reason`）。
3. **可选依赖缺了不崩**：faiss / pymilvus 都是**可选**依赖（requirements 里注释说明），
   没装则该档 `ready=False` + 中文提示，`auto` 会跳过它继续探测下一档 —— 与 r103
   「未装 llama-index 就自研切分兜底」同一风格。

faiss 选 `IndexIDMap2(IndexFlatIP)` 而不是 IVF / HNSW：向量先 L2 归一化，IP 即精确余弦，
**无调参、确定性、可复跑**（评测门禁要求逐字节复现），1.5k 条 × 256 维毫秒级。
题库涨到十万级再换 `IndexIVFFlat`，是 `write()` 里的一行改动，检索层无感。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.core import repository
from app.core.config import Settings, get_settings
from app.core.db import active_backend, rag_embedding_mode
from app.core.errors import AI_UNAVAILABLE, AppError

logger = logging.getLogger("app.rag.vectors")

#: `VECTOR_MODE` 闭集（config 的 Literal 与这里必须同步改，测试钉住）。
VECTOR_MODES: tuple[str, ...] = ("auto", "pgvector", "sqlite", "faiss", "milvus")

#: 派生索引里的 kind 闭集（与 `rag_chunks.kind` 的取值一致：题库 / 教程）。
VECTOR_KINDS: tuple[str, ...] = ("question", "tutorial")

#: Milvus collection 名的合法性：只允许标识符字符，防注入进 filter 表达式。
_MILVUS_COLLECTION_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,255}$")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _load_faiss() -> tuple[Any, Any] | None:
    """faiss 是可选依赖：`faiss-cpu`（自带 numpy 依赖）。没装返回 None，不打断进程。"""
    try:
        import faiss  # noqa: PLC0415 - 可选依赖，延迟导入
        import numpy  # noqa: PLC0415
    except ImportError:
        return None
    return faiss, numpy


def _load_milvus() -> Any | None:
    """pymilvus 是可选依赖（纯 Python）。没装返回 None。"""
    try:
        from pymilvus import MilvusClient  # noqa: PLC0415
    except ImportError:
        return None
    return MilvusClient


# --- 后端协议 ----------------------------------------------------------------


class VectorStore(Protocol):
    """向量后端的最小协议：写（元数据 + 派生索引）与查（向量 top-K）。

    元数据**总是**先落 `rag_chunks`（`repository.rag_write_chunks`，事务化），派生索引
    只存「chunk_id + 向量」——检索命中后再按 id 回业务库取 title / content，
    保证「改了题库解释文案、重建索引前后」不存在两份会漂移的正文。
    """

    engine: str

    def write(
        self, rows: list[dict[str, Any]], *, kind: str, embedder: str, dim: int
    ) -> int: ...

    def search(
        self,
        query_vec: list[float],
        *,
        embedder: str,
        dim: int,
        top_k: int,
        kinds: list[str] | None,
    ) -> list[dict[str, Any]]: ...

    def notice(self, *, embedder: str, dim: int) -> str:
        """派生索引与业务库的对账结论：空串 = 一致；非空 = 可直接展示的中文提示。"""


@dataclass(frozen=True)
class VectorHandle:
    """`resolve_vector_store` 的返回：**永不 raise**，未就绪时只带中文 reason。"""

    mode: str  # 实际生效的档位（auto 展开后的结果）
    engine: str  # 相似度在哪里算（进 HTTP 响应，如实报告，不伪装降级）
    store: VectorStore | None
    ready: bool
    reason: str


def _finalize(
    ids: list[tuple[str, float]], *, top_k: int
) -> list[dict[str, Any]]:
    """`(chunk_id, score)` → 检索行：按分排序、截 top_k、回业务库取元数据。

    元数据缺失（索引与库不同步）的 chunk 直接丢弃 —— 宁可少一条，不给「空标题」。
    """
    ordered = sorted(ids, key=lambda pair: (-pair[1], pair[0]))[:top_k]
    if not ordered:
        return []
    chunks = repository.rag_fetch_chunks([chunk_id for chunk_id, _ in ordered])
    rows: list[dict[str, Any]] = []
    for chunk_id, score in ordered:
        chunk = chunks.get(chunk_id)
        if chunk is None:
            logger.warning("rag.vector.orphan_chunk id=%s skipped", chunk_id)
            continue
        rows.append({**chunk, "score": round(float(score), 6)})
    return rows


# --- pgvector / sqlite：向量仍在业务库里（现状路径，行为不变） ----------------


class _DbStore:
    """向量存 `rag_chunks.embedding` 的两档：pgvector 形态走 SQL，其余取回后 Python 余弦。

    这是 r100/r114 的既有路径原样搬进来 —— 行为一个字不改，只是分派点收拢到这里。
    `engine` 如实区分：`pgvector`（索引内算）/ `python-cosine`（取回后算）。
    """

    def __init__(self, *, mode: str) -> None:
        self._mode = mode  # rag_embedding_mode() 的结果：pgvector / array / missing

    @property
    def engine(self) -> str:
        return "pgvector" if self._mode == "pgvector" else "python-cosine"

    def write(
        self, rows: list[dict[str, Any]], *, kind: str, embedder: str, dim: int
    ) -> int:
        return repository.rag_write_chunks(rows, mode=self._mode, replace_kind=kind)

    def search(
        self,
        query_vec: list[float],
        *,
        embedder: str,
        dim: int,
        top_k: int,
        kinds: list[str] | None,
    ) -> list[dict[str, Any]]:
        if self._mode == "pgvector":
            return repository.rag_vector_search(
                query_vec, embedder=embedder, top_k=top_k, mode=self._mode, kinds=kinds
            )
        scanned = repository.rag_array_scan(embedder=embedder, kinds=kinds)

        def _parse(value: Any) -> list[float]:
            if isinstance(value, str):
                parsed = json.loads(value)
                return [float(item) for item in parsed] if isinstance(parsed, list) else []
            return [float(item) for item in value]

        scored = [
            (repository.rag_cosine(query_vec, _parse(row["embedding"])), row)
            for row in scanned
        ]
        scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
        return [
            {key: value for key, value in row.items() if key != "embedding"} | {"score": score}
            for score, row in scored[:top_k]
        ]

    def notice(self, *, embedder: str, dim: int) -> str:
        return ""


# --- faiss：本地单文件派生索引 ------------------------------------------------


class FaissStore:
    """每个 kind 两个文件：`<kind>.faiss`（向量索引）+ `<kind>.json`（对账 sidecar）。

    为什么按 kind 拆文件而不是一个大索引：`kinds` 过滤必须**精确**——先取全局 top-K
    再按 kind 筛会把「只搜教程」变成「教程得先挤进全局前 K」（`rag_vector_search`
    的注释里有同样的教训），faiss 没法在索引内按元数据过滤，按 kind 分文件是零损失的解。

    原子写：两个临时文件先落盘、`fsync` 后分别 `os.replace`。faiss 与 sidecar 不是
    原子对（跨两个文件做不到），所以 sidecar 里存 `index_sha256` + `count`，加载时
    对账，对不上就当索引坏了（见 `notice`），提示重建而不是返回错的检索结果。
    """

    engine = "faiss"

    def __init__(self, directory: str) -> None:
        self._dir = Path(directory)
        #: 进程内索引缓存：key = (路径, mtime_ns, size)。重建索引后 mtime 变化即失效。
        self._cache: dict[tuple[str, int, int], tuple[Any, list[str]]] = {}

    def _index_path(self, kind: str) -> Path:
        return self._dir / f"{kind}.faiss"

    def _sidecar_path(self, kind: str) -> Path:
        return self._dir / f"{kind}.json"

    def _kinds_on_disk(self) -> list[str]:
        if not self._dir.exists():
            return []
        return [
            path.name.removesuffix(".faiss")
            for path in sorted(self._dir.glob("*.faiss"))
            if path.name.removesuffix(".faiss") in VECTOR_KINDS
        ]

    def _atomic_write(self, path: Path, payload: bytes) -> None:
        """临时文件 + fsync + `os.replace`：写一半崩溃不会留下半个索引。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

    def write(
        self, rows: list[dict[str, Any]], *, kind: str, embedder: str, dim: int
    ) -> int:
        loaded = _load_faiss()
        if loaded is None:
            raise AppError(
                AI_UNAVAILABLE,
                "faiss 未安装：内网机器请 pip install faiss-cpu（或设 VECTOR_MODE=sqlite 用业务库存向量）",
                retryable=False,
            )
        faiss, numpy = loaded
        # 1. 元数据先落业务库（事务化、幂等）—— 派生索引坏了可以随时重建。
        repository.rag_write_chunks(
            rows, mode=rag_embedding_mode(), replace_kind=kind
        )
        self._cache.clear()

        # 2. 派生索引：L2 归一化后 IndexFlatIP = 精确余弦，无调参、确定性可复跑。
        self._dir.mkdir(parents=True, exist_ok=True)
        index_path = self._index_path(kind)
        sidecar_path = self._sidecar_path(kind)
        if not rows:
            # 全量替换成空集：删掉派生文件，别留一个「0 向量的空索引」骗人。
            for path in (index_path, sidecar_path):
                path.unlink(missing_ok=True)
            return 0
        ordered = sorted(rows, key=lambda row: str(row["id"]))
        vectors = numpy.array([row["embedding"] for row in ordered], dtype="float32")
        if vectors.shape[1] != dim:
            raise AppError(
                AI_UNAVAILABLE,
                f"embedding 维度 {vectors.shape[1]} 与配置 AI_EMBED_DIM={dim} 不一致，请对齐后重建索引",
                retryable=False,
            )
        faiss.normalize_L2(vectors)
        index = faiss.IndexIDMap2(faiss.IndexFlatIP(dim))
        index.add_with_ids(
            vectors, numpy.arange(len(ordered), dtype="int64")
        )
        # `write_index` 直接写文件最稳（序列化 API 在不同 faiss 版本签名有差异）。
        tmp = index_path.with_suffix(".faiss.tmp")
        faiss.write_index(index, str(tmp))
        tmp.replace(index_path)
        ids = [str(row["id"]) for row in ordered]
        sidecar = {
            "embedder": embedder,
            "dim": dim,
            "count": len(ids),
            "ids": ids,
            "built_at": _now_iso(),
            "index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        }
        self._atomic_write(
            sidecar_path, (json.dumps(sidecar, ensure_ascii=False) + "\n").encode("utf-8")
        )
        return len(rows)

    def _load(self, kind: str, *, embedder: str, dim: int) -> tuple[Any, list[str]] | None:
        """带缓存的索引加载；sidecar 对账不过 = 返回 None（调用方当它不存在）。"""
        loaded = _load_faiss()
        if loaded is None:
            return None
        faiss, _numpy = loaded
        index_path = self._index_path(kind)
        sidecar_path = self._sidecar_path(kind)
        if not index_path.exists() or not sidecar_path.exists():
            return None
        stat = index_path.stat()
        key = (str(index_path), stat.st_mtime_ns, stat.st_size)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        meta = json.loads(sidecar_path.read_text(encoding="utf-8"))
        if (
            str(meta.get("embedder")) != embedder
            or int(meta.get("dim") or 0) != dim
            or str(meta.get("index_sha256"))
            != hashlib.sha256(index_path.read_bytes()).hexdigest()
        ):
            return None  # 换了 embedding / 维度 / 文件与 sidecar 不配对：宁可空结果不给错的
        index = faiss.read_index(str(index_path))
        ids = [str(item) for item in meta.get("ids") or []]
        if index.ntotal != len(ids):
            return None
        self._cache[key] = (index, ids)
        return index, ids

    def search(
        self,
        query_vec: list[float],
        *,
        embedder: str,
        dim: int,
        top_k: int,
        kinds: list[str] | None,
    ) -> list[dict[str, Any]]:
        loaded = _load_faiss()
        if loaded is None:
            raise AppError(
                AI_UNAVAILABLE,
                "faiss 未安装：请 pip install faiss-cpu 或改用 VECTOR_MODE=sqlite",
                retryable=False,
            )
        faiss, numpy = loaded
        query = numpy.array([query_vec], dtype="float32")
        if query.shape[1] != dim:
            return []
        faiss.normalize_L2(query)
        candidates: list[tuple[str, float]] = []
        for kind in kinds or self._kinds_on_disk():
            indexed = self._load(kind, embedder=embedder, dim=dim)
            if indexed is None:
                continue
            index, ids = indexed
            scores, ordinals = index.search(query, min(max(1, top_k), len(ids)))
            for score, ordinal in zip(scores[0].tolist(), ordinals[0].tolist(), strict=False):
                if ordinal < 0 or ordinal >= len(ids):
                    continue
                candidates.append((ids[ordinal], float(score)))
        return _finalize(candidates, top_k=top_k)

    def notice(self, *, embedder: str, dim: int) -> str:
        """对账：文件缺失 / sidecar 不配对 / 与业务库行数不一致，都给可操作的中文提示。"""
        kinds = self._kinds_on_disk()
        if not kinds:
            return "faiss 索引尚未构建：先重建题库索引，再从学堂页推送教程正文"
        counts = repository.rag_chunk_counts()
        for kind in kinds:
            sidecar_path = self._sidecar_path(kind)
            if not sidecar_path.exists():
                return f"{kind} 的 faiss 索引文件与对账文件不配对，请重建索引"
            meta = json.loads(sidecar_path.read_text(encoding="utf-8"))
            if str(meta.get("embedder")) != embedder or int(meta.get("dim") or 0) != dim:
                return "faiss 索引是按其它 embedding 配置构建的，请重建索引"
            if int(meta.get("count") or 0) != counts.get(kind, 0):
                return f"{kind} 的 faiss 索引与题库行数不一致（可能上次写入中断），请重建索引"
        return ""


# --- milvus：远端向量库（企业内网） -------------------------------------------


class MilvusStore:
    """pymilvus `MilvusClient` 连远端；collection 只存「chunk_id + 向量 + 检索要用过的过滤列」。

    元数据（title / content）仍以 `rag_chunks` 为唯一事实源，命中后回业务库取——
    不在向量库里存正文，意味着「改了题库文案」不会出现两份漂移的正文，
    也意味着换向量库（faiss ↔ milvus ↔ pgvector）不影响任何展示数据。
    """

    engine = "milvus"

    def __init__(self, *, uri: str, collection: str, token: str = "") -> None:
        self._uri = uri.strip()
        self._collection = collection.strip() or "rag_chunks"
        self._token = token.strip()

    def _client(self) -> Any:
        client_cls = _load_milvus()
        if client_cls is None:
            raise AppError(
                AI_UNAVAILABLE,
                "pymilvus 未安装：请 pip install pymilvus（或改用 VECTOR_MODE=faiss）",
                retryable=False,
            )
        return client_cls(uri=self._uri, token=self._token) if self._token else client_cls(
            uri=self._uri
        )

    def _ensure_collection(self, client: Any, *, dim: int) -> None:
        if client.has_collection(self._collection):
            return
        from pymilvus import DataType  # noqa: PLC0415 - 可选依赖，延迟导入

        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=512)
        schema.add_field("kind", DataType.VARCHAR, max_length=64)
        schema.add_field("embedder", DataType.VARCHAR, max_length=128)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dim)
        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": 16, "efConstruction": 200},
        )
        client.create_collection(
            self._collection, schema=schema, index_params=index_params
        )
        logger.info(
            "rag.milvus.collection_created name=%s dim=%s", self._collection, dim
        )

    def write(
        self, rows: list[dict[str, Any]], *, kind: str, embedder: str, dim: int
    ) -> int:
        # 1. 元数据先落业务库（与其它档一致：向量库只是派生索引）。
        repository.rag_write_chunks(
            rows, mode=rag_embedding_mode(), replace_kind=kind
        )
        client = self._client()
        self._ensure_collection(client, dim=dim)
        # 2. 全量替换该 kind：先按 kind 删（Milvus 的布尔表达式删除），再插。
        client.delete(self._collection, filter=f'kind == "{kind}"')
        if rows:
            client.insert(
                self._collection,
                data=[
                    {
                        "id": str(row["id"]),
                        "kind": str(row["kind"]),
                        "embedder": embedder,
                        "vector": [float(value) for value in row["embedding"]],
                    }
                    for row in rows
                ],
            )
        return len(rows)

    def search(
        self,
        query_vec: list[float],
        *,
        embedder: str,
        dim: int,
        top_k: int,
        kinds: list[str] | None,
    ) -> list[dict[str, Any]]:
        client = self._client()
        if not client.has_collection(self._collection):
            return []
        flt = f'embedder == "{embedder}"'
        if kinds:
            flt += " and kind in " + json.dumps(list(kinds))
        results = client.search(
            self._collection,
            data=[query_vec],
            limit=max(1, top_k),
            filter=flt,
            output_fields=["id"],
        )
        candidates: list[tuple[str, float]] = []
        for hits in results or []:
            for hit in hits or []:
                candidates.append((str(hit["id"]), float(hit.get("distance") or 0.0)))
        return _finalize(candidates, top_k=top_k)

    def notice(self, *, embedder: str, dim: int) -> str:
        return ""


# --- 分派：resolve 永不 raise，配置错折成 ready=False + 中文 reason ------------


def _resolve_auto() -> str:
    """auto 的展开顺序：有 PG 就留在 PG（向量与业务数据同源、还能进 sqlite 副本）；
    单机（内网默认形态）先试 faiss，没装 faiss 才用 sqlite 的 JSON 向量。"""
    if active_backend() == "postgresql":
        return "pgvector"
    if _load_faiss() is not None:
        return "faiss"
    return "sqlite"


def resolve_vector_store(settings: Settings | None = None) -> VectorHandle:
    """唯一的分派出口。**永不 raise**：依赖缺失 / 配置不全都折成 `ready=False` + 中文原因。"""
    current = settings or get_settings()
    mode = str(current.vector_mode)
    if mode == "auto":
        mode = _resolve_auto()

    if mode in ("pgvector", "sqlite"):
        store: VectorStore = _DbStore(mode=rag_embedding_mode())
        return VectorHandle(
            mode=mode, engine=store.engine, store=store, ready=True, reason=""
        )

    if mode == "faiss":
        if _load_faiss() is None:
            return VectorHandle(
                mode=mode,
                engine="faiss",
                store=None,
                ready=False,
                reason="faiss 未安装：pip install faiss-cpu，或改用 VECTOR_MODE=sqlite",
            )
        return VectorHandle(
            mode=mode,
            engine="faiss",
            store=FaissStore(current.vector_faiss_dir),
            ready=True,
            reason="",
        )

    # milvus
    uri = current.vector_milvus_uri.strip()
    collection = current.vector_milvus_collection.strip()
    if collection and not _MILVUS_COLLECTION_RE.match(collection):
        return VectorHandle(
            mode=mode,
            engine="milvus",
            store=None,
            ready=False,
            reason="VECTOR_MILVUS_COLLECTION 只能包含字母 / 数字 / 下划线且以字母开头",
        )
    if not uri:
        return VectorHandle(
            mode=mode,
            engine="milvus",
            store=None,
            ready=False,
            reason="VECTOR_MODE=milvus 但 VECTOR_MILVUS_URI 为空，请填写内网 Milvus 地址（如 http://milvus:19530）",
        )
    if _load_milvus() is None:
        return VectorHandle(
            mode=mode,
            engine="milvus",
            store=None,
            ready=False,
            reason="pymilvus 未安装：pip install pymilvus，或改用 VECTOR_MODE=faiss",
        )
    return VectorHandle(
        mode=mode,
        engine="milvus",
        store=MilvusStore(uri=uri, collection=collection),
        ready=True,
        reason="",
    )
