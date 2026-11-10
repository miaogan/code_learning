"""r65 教练建议编排：清洗材料 → 组提示词 → 调模型 → 白名单校验。

口径：
- 材料为空**不调用模型**（零成本、零等待），直接回中文说明；
- 前台交互调用，`retry_unavailable` 保持默认 False（避免用户等待翻倍）；
- 专用超时 `COACH_TIMEOUT_S`：建议输出短，不该跟着全局 600s 的画像档一起等。
"""

from app.schemas import CoachAdvice
from app.services.ai.ai import AIClient
from app.services.coach import policy

#: 建议输出只有几十行 JSON，给 120s 足够；与画像的 600s 档位分离（r34 之后的同类做法）。
COACH_TIMEOUT_S = 120


def empty_advice() -> CoachAdvice:
    """材料不可用时的固定出口：不花钱、不等待，只给中文指引。"""
    return CoachAdvice(notice=policy.EMPTY_MATERIALS_NOTICE)


async def build_advice(
    materials: list[dict[str, str]],
    *,
    focus: str,
    goal: str,
    client: AIClient,
) -> CoachAdvice:
    """`materials` 必须是 `policy.sanitize_materials()` 的产物（href 即白名单）。"""
    prompt = policy.build_user_prompt(materials, focus, goal)
    draft = await client.complete_model(
        policy.COACH_SYSTEM,
        prompt,
        policy.CoachDraft,
        timeout_s=COACH_TIMEOUT_S,
    )
    return CoachAdvice(**policy.sanitize_advice(draft, materials))
