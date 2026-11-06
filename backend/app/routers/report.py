"""诊断报告路由（AC-5 / AC-6 / AC-9）：生成、读取最近一份、导出 Markdown。

三条语义分开：`generate` 造新报告（可能调 AI），`latest` 只读旧报告（刷新页面不得重跑 AI），
`markdown` 是同一份报告的文本投影（AC-9「导出与页面一致」靠它同源）。
"""

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from app.core import repository
from app.core.errors import NOT_FOUND, AppError
from app.deps import CurrentUser, current_user
from app.schemas import Report, ReportGenerateRequest
from app.services.ai import user_ai
from app.services.report.diagnosis import build_report
from app.services.report.markdown import to_markdown

router = APIRouter(prefix="/api/reports", tags=["report"], dependencies=[Depends(current_user)])


@router.post("/generate", response_model=Report, summary="合并测评结果生成短板报告")
async def generate_report(
    user: CurrentUser,
    payload: ReportGenerateRequest | None = None,
) -> Report:
    body = payload or ReportGenerateRequest()
    client = user_ai.client_for(user, "heavy")
    return await build_report(body.run_ids, client=client)


@router.get("/latest", response_model=Report, summary="读取最近一份诊断报告")
def read_latest_report() -> Report:
    report = repository.latest_report()
    if report is None:
        raise AppError(NOT_FOUND, "还没有诊断报告，请先生成一份", status=404)
    return report


@router.get("/{report_id}/markdown", response_class=PlainTextResponse, summary="导出 .md")
def export_markdown(report_id: str) -> PlainTextResponse:
    report = repository.get_report(report_id)
    if report is None:
        raise AppError(NOT_FOUND, "这份报告不存在或已被清理，请重新生成", status=404)
    return PlainTextResponse(to_markdown(report), media_type="text/markdown")
