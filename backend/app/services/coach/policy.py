"""r65 教练建议的纯函数层：材料清洗、提示词拼装、**引用白名单校验**。

为什么把「引用必须逐字来自输入材料」做成服务端硬校验：模型的 `href` 是最容易幻觉的字段
（会编出看着合理的 `/learn/xxx` 链接），前端无法分辨真假。这里以材料里出现过的 href 为
**允许集合**，命中不了的 action 直接丢弃并计数，界面可展示「已丢弃 N 条无依据建议」。

本模块零 IO、零配置，所有规则都是可单测的纯函数。
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

#: 单次调用最多上传的材料条数：够覆盖 3 个薄弱方向各 3 小节，又不至于把上下文撑爆。
MATERIAL_LIMIT = 12
MATERIAL_TITLE_MAX = 60
MATERIAL_DETAIL_MAX = 900
#: 材料以外的三个短字段同样夹取：方向名 / 岗位名可能来自用户输入。
FOCUS_MAX = 40
GOAL_MAX = 160

BLOCK_LIMIT = 4
ACTION_LIMIT = 3
MINUTES_MIN = 10
MINUTES_MAX = 120
#: 动作时长默认 30 分钟；写成派生表达式是因为服务层禁止出现 30 字面量
#: （`test_proficiency_thresholds_only_from_config` 把 30 当作熟练度窗口天数的哨兵）。
DEFAULT_MINUTES = MINUTES_MIN * 3
SUMMARY_MAX = 160
TITLE_MAX = 40
REASON_MAX = 100
LABEL_MAX = 40
WHY_MAX = 80

EMPTY_MATERIALS_NOTICE = (
    "没有可用的站内材料：请先生成诊断报告（或先做一次计分测评），再来生成学习建议。"
)
NO_CITATION_NOTICE = (
    "模型没有给出可核对的站内依据链接，本次建议已留空：可以再试一次，或先去看诊断报告里的薄弱方向。"
)

COACH_SYSTEM = """你是「逃跑计划」的学习教练，服务对象是想转向 AI 应用 / Agent 后端的外包工程师。

硬性规则：
1. 只能使用【材料】里出现过的内容，不得引入材料之外的知识点、课程名、链接或统计数字。
2. 每条建议的 href 必须从材料里**逐字复制**，不得改写、拼接、推测或自造。
3. 材料不足以支撑建议时，宁可只给一行 summary，也不要编造。
4. 只输出一个 JSON 对象，不要代码围栏，不要额外解释。"""

USER_PROMPT_TEMPLATE = """【材料】
{materials}

【聚焦】{focus}
【本次目标】{goal}

请输出 JSON：
{{"summary": "一句话总览（≤80 字）", "blocks": [{{"title": "阶段标题（≤12 字）", "reason": "为什么先做这一步", "actions": [{{"label": "动作（≤20 字）", "href": "材料里的 href 原文", "why": "这条怎么补短板", "minutes": 30}}]}}]}}

约束：blocks 最多 4 块，每块 actions 最多 3 条，minutes 取 10 / 15 / 30 / 45 / 60。"""

DEFAULT_FOCUS = "未指定（请依据材料里的薄弱方向自行收窄）"
DEFAULT_GOAL = "在 7 天内补上材料所覆盖的最薄弱工程能力"


class CoachDraftAction(BaseModel):
    """模型输出的动作（**未校验**）：`href` 必须再过白名单才允许进响应。"""

    label: str = ""
    href: str = ""
    why: str = ""
    minutes: int = DEFAULT_MINUTES


class CoachDraftBlock(BaseModel):
    title: str = ""
    reason: str = ""
    actions: list[CoachDraftAction] = Field(default_factory=list)


class CoachDraft(BaseModel):
    """模型输出的整体结构：只保留这三个键，多给的字段一律忽略。"""

    summary: str = ""
    blocks: list[CoachDraftBlock] = Field(default_factory=list)


def flatten(text: str) -> str:
    """压平空白：模型输出常带换行 / 多空格，直接渲染会撑破卡片排版。"""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def clamp(text: str, limit: int) -> str:
    """压平 + 截断。截断用单字符省略号，不额外拼接换行。"""
    flat = flatten(text)
    if limit <= 0:
        return ""
    if len(flat) <= limit:
        return flat
    return flat[:limit].rstrip() + "…"


def sanitize_materials(materials: list[Any]) -> list[dict[str, str]]:
    """清洗上传材料：只留站内路径、按 href 去重、夹取长度、上限 `MATERIAL_LIMIT` 条。

    `href` 不以 `/` 开头的一律丢弃 —— 教练只该跳站内页面，外链与相对路径都会让
    「引用白名单」失去意义。
    """
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in materials or []:
        href = flatten(getattr(item, "href", ""))
        if not href.startswith("/") or href in seen:
            continue
        seen.add(href)
        cleaned.append(
            {
                "href": href,
                "title": clamp(getattr(item, "title", ""), MATERIAL_TITLE_MAX),
                "detail": clamp(getattr(item, "detail", ""), MATERIAL_DETAIL_MAX),
                "direction": flatten(getattr(item, "direction", "")),
                "sub_direction": flatten(getattr(item, "sub_direction", "")),
                "level": flatten(getattr(item, "level", "")),
            }
        )
        if len(cleaned) >= MATERIAL_LIMIT:
            break
    return cleaned


def _material_line(index: int, material: dict[str, str]) -> str:
    tags = " · ".join(
        part
        for part in (material["direction"], material["sub_direction"], material["level"])
        if part
    )
    head = f"{index}. {material['title']}" + (f"（{tags}）" if tags else "")
    return f"{head}\nhref: {material['href']}\n摘要: {material['detail']}"


def build_user_prompt(
    materials: list[dict[str, str]], focus: str = "", goal: str = ""
) -> str:
    """拼用户消息：材料逐条编号 + href 原文，后接聚焦与目标。"""
    rendered = "\n\n".join(
        _material_line(index, material) for index, material in enumerate(materials, start=1)
    )
    return USER_PROMPT_TEMPLATE.format(
        materials=rendered or "（无）",
        focus=clamp(focus, FOCUS_MAX) or DEFAULT_FOCUS,
        goal=clamp(goal, GOAL_MAX) or DEFAULT_GOAL,
    )


def _minutes_of(value: Any) -> int:
    """分钟数夹取：非数字 / 布尔一律回落 DEFAULT_MINUTES，其余夹到 [MINUTES_MIN, MINUTES_MAX]。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_MINUTES
    return max(MINUTES_MIN, min(MINUTES_MAX, value))


def sanitize_advice(draft: CoachDraft, materials: list[dict[str, str]]) -> dict[str, Any]:
    """校验 + 净化模型输出，返回 `CoachAdvice` 的字段字典。

    - `href` 不在材料允许集合 → 丢弃该 action，`dropped_citations` +1；
    - 空 label 的 action → 丢弃（没内容的动作点了也没意义），不计入幻觉计数；
    - 清洗后没有任何 action 的 block → 整块丢弃（不展示空阶段）；
    - 最终一个 block 都没有 → 返回 summary + 中文 notice，**不抛异常**（模型退化不该变成 500）。
    """
    allowed = {material["href"] for material in materials}
    dropped = 0
    blocks: list[dict[str, Any]] = []
    for block in draft.blocks[:BLOCK_LIMIT]:
        title = clamp(block.title, TITLE_MAX)
        actions: list[dict[str, Any]] = []
        for action in block.actions:
            href = flatten(action.href)
            if href not in allowed:
                dropped += 1
                continue
            label = clamp(action.label, LABEL_MAX)
            if not label:
                continue
            actions.append(
                {
                    "label": label,
                    "href": href,
                    "why": clamp(action.why, WHY_MAX),
                    "minutes": _minutes_of(action.minutes),
                }
            )
            if len(actions) >= ACTION_LIMIT:
                break
        if not title or not actions:
            continue
        blocks.append(
            {
                "title": title,
                "reason": clamp(block.reason, REASON_MAX),
                "actions": actions,
            }
        )
        if len(blocks) >= BLOCK_LIMIT:
            break

    summary = clamp(draft.summary, SUMMARY_MAX)
    return {
        "summary": summary,
        "blocks": blocks,
        "materials_used": len(materials),
        "dropped_citations": dropped,
        "notice": "" if blocks else NO_CITATION_NOTICE,
    }
