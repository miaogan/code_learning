"""跃迁档案看板路由（r108）：只读聚合，三块事实一次带回。

不接参数、不写库、不调 AI；`current_user` 依赖保证数据按账号隔离（repository 内
各读取函数已带 user_id 过滤）。读取侧零重算——报告差距 / 面试分数都是写入时的真相。
"""

from fastapi import APIRouter, Depends

from app.deps import current_user
from app.schemas import LeapArchive
from app.services.leap import build_leap_archive

router = APIRouter(prefix="/api/leap-archive", tags=["leap"], dependencies=[Depends(current_user)])


@router.get("", response_model=LeapArchive, summary="跃迁档案：岗位差距 + 工程证据 + 面试表达")
def read_leap_archive() -> LeapArchive:
    return build_leap_archive()
