"""r100 工程证据中心（只读聚合）：把「看不见的工程深度」摆上界面。

- `data_scale`：真实落库的行数（用户维度业务表按当前账号统计；题库 / chunk 是
  共享语料，全量计数）——零 AI、零 Key、零评分，只报事实；
- `tables`：public schema 下的表数（DDL 演进的直接证据）；
- `rag`：RAG 索引状态（embedder / 引擎形态 / 是否需要重建）。

静态工程档案（架构数字 / 门禁清单 / 幂等三件套说明）在前端
`content/engineeringArchive.ts` 单点维护——那部分随代码评审更新，不进数据库。
"""

from fastapi import APIRouter, Depends

from app.core import repository
from app.core.db import connection
from app.deps import current_user
from app.schemas import EvidenceSummary, RagStatus
from app.services.retrieval import indexer

router = APIRouter(
    prefix="/api/evidence", tags=["evidence"], dependencies=[Depends(current_user)]
)


@router.get("/summary", response_model=EvidenceSummary, summary="工程证据摘要（行数事实 + RAG 索引状态）")
def evidence_summary() -> EvidenceSummary:
    scale = repository.evidence_data_scale()
    with connection() as conn:
        tables = int(
            conn.execute(
                "SELECT count(*) AS n FROM pg_tables WHERE schemaname = 'public'"
            ).fetchone()["n"]
        )
    return EvidenceSummary(
        data_scale=scale,
        tables=tables,
        rag=RagStatus(**indexer.index_status()),
    )
