"""r110 岗位对位端点：粘贴 JD → 确定性证据清单 + 缺口 + 召对预设（零 AI）。

路由层只做登录门禁、请求体校验与转发；岗位识别 / 关键词匹配 / 画像取数全在
`services.jd_match`，与报告页的 `role_fit` 计算共用同一个纯函数，不另立口径。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import current_user
from app.schemas import JdMatchRequest, JdMatchResult
from app.services.jd_match import match_jd

router = APIRouter(
    prefix="/api/jd-match",
    tags=["jd"],
    dependencies=[Depends(current_user)],
)


@router.post("", response_model=JdMatchResult, summary="岗位对位：JD 证据清单与缺口（零 AI）")
def read_jd_match(payload: JdMatchRequest) -> JdMatchResult:
    return match_jd(payload)
