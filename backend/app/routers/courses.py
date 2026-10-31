"""精选课程清单路由（AC-6）：服务端单一 JSON 清单。"""

from fastapi import APIRouter

from ..schemas import Course
from ..services import courses

router = APIRouter(prefix="/api/courses", tags=["courses"])


@router.get("", response_model=list[Course], summary="读取精选基础课程清单")
def list_courses() -> list[Course]:
    return courses.list_courses()
