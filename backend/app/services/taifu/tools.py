"""r83 太傅工具层：让模型自己决定读哪一条，而不是靠服务端的 `if kind` 分支。

边界（与 PRD「明确不做」对齐）：
- 四个只读工具，全部经 `deep_read.build_detail()` 取料 —— 与 r82 的页面深读同一份实现，
  「题目被删」「原句找不到」这些边界不需要再写第二遍；
- 唯一的写操作是 `remember`，只写 `taifu_memories`，且沿用 `policy.sanitize_memories`
  的长度闭区间与去重口径；
- **读不到就返回 `ok=False`**：不拿相似数据凑数，界面据此显示「没读到」。

本模块不碰流、不碰提示词、不碰图：入参是 (工具名, JSON 参数字符串, 上下文)，出参是统一的 ToolResult。
"""

from __future__ import annotations

import json
from typing import Any, TypedDict

from app.core import repository
from app.schemas import Profile, Report
from app.services.taifu import policy
from app.services.taifu.brief import clip
from app.services.taifu.deep_read import (
    DETAIL_LINE_MAX,
    KIND_ATTEMPT,
    KIND_RESUME,
    KIND_WEAKNESS,
    MAX_DETAIL_LINES,
    MAX_SAMPLES,
    build_detail,
)

#: 回灌给模型的行数上限：与明细段同源（≤8 行 × 160 字），一次工具调用不至于吃掉半窗上下文。
MAX_RESULT_LINES = MAX_DETAIL_LINES
#: 界面卡片的摘要长度：一行能显示完，超出部分点开引用去看。
SUMMARY_MAX = 60
#: 按关键词找错题时最多扫多少条：作答记录可能有上千条，全扫会让一次工具调用变成慢查询。
KEYWORD_SCAN_LIMIT = 200

#: 工具名 → 界面短标签（`ok=False` 时也用它，避免卡片没有标题）。
TOOL_LABELS: dict[str, str] = {
    "read_weakness_detail": "薄弱明细",
    "read_question_detail": "错题明细",
    "read_resume_anchor": "简历原句",
    "compare_reports": "报告对比",
    "remember": "长期记忆",
}


class ToolResult(TypedDict):
    """统一返回形状：图节点不必区分具体工具。"""

    ok: bool
    #: 界面卡片标题，如「错题明细 · 事件循环与微任务」。
    label: str
    #: 一行结果摘要。
    summary: str
    #: 有具体指向时给引用 href；`None` 表示不进引用（如 `remember`）。
    href: str | None
    #: 回灌给模型的行。
    content: list[str]


TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_weakness_detail",
            "description": (
                "读取某个知识薄弱分组的明细：分组诊断，以及组内样例题的题面、正确答案、"
                "你的作答结果与解析。用户问「这一组我到底缺什么」「为什么总在这一点上错」时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "point": {
                        "type": "string",
                        "description": "分组名，逐字抄【薄弱地图】里的写法即可，允许只写关键词",
                    }
                },
                "required": ["point"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_question_detail",
            "description": (
                "读取一道错题的明细：题面、选项、正确答案、你的结果、解析。"
                "用户问「这题为什么错」「这题考什么」时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question_id": {
                        "type": "string",
                        "description": "题号；档案里没给题号时留空，改传 keyword",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "题号不确定时传题面关键词，服务端在你的错题里按题面匹配",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_resume_anchor",
            "description": (
                "读取简历某一条的原文与上下文：原句、所在段落与行号、前后各 120 字。"
                "用户问「这句该怎么改」「这条要不要删」时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "anchor_text": {
                        "type": "string",
                        "description": "简历里的原句，逐字抄，不要改写；来源是【简历改进要点】里的「原句：」",
                    }
                },
                "required": ["anchor_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_reports",
            "description": (
                "对比最近两份诊断报告：笔试总分、面试均分、薄弱项错误率的升降。"
                "用户问「比上次好在哪」「有没有进步」时调用。无参数。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": (
                "把用户明确说过的、档案里没有的背景或偏好记成长期记忆，供以后每轮参考。"
                "只记事实与偏好，不记你自己的推测；档案里已有的不要记。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "不超过 80 字的一条事实，用第三人称写，如「他每天只有 1 小时学习时间」",
                    }
                },
                "required": ["content"],
            },
        },
    },
]

#: 工具名闭集：路由层与图节点据此判断「模型给了个不存在的工具」。
TOOL_NAMES = frozenset(TOOL_LABELS)


class ToolContext:
    """一次问答内的取料上下文：懒加载简历正文、累计已写入的记忆。

    简历正文只在真的调了 `read_resume_anchor` 时才读 —— 它可能有几十 KB，
    为一次「我弱在哪」的问题读一遍正文是纯浪费。
    """

    def __init__(
        self,
        *,
        profile: Profile | None,
        report: Report | None,
        attempts: list[dict[str, Any]],
        memories: list[str],
    ) -> None:
        self.profile = profile
        self.report = report
        self.attempts = attempts
        self._memories = list(memories)
        self._document_loaded = False
        self._document_text: str | None = None
        self.memories_added = 0
        self.new_memories: list[str] = []

    def document(self) -> str | None:
        if not self._document_loaded:
            self._document_loaded = True
            if self.profile is not None:
                self._document_text = repository.get_document_text(self.profile.resume_id)
        return self._document_text

    def remember(self, content: str) -> str:
        """写入一条记忆；返回空串表示没写成（长度不合规 / 重复 / 本轮已满）。"""
        if self.memories_added >= policy.MEMORY_ITEMS_PER_TURN:
            return ""
        kept = policy.sanitize_memories([content], self._memories)
        if not kept:
            return ""
        written = kept[0]
        repository.insert_taifu_memory(written)
        self._memories.append(written)
        self.new_memories.append(written)
        self.memories_added += 1
        return written


async def run(name: str, arguments: str, context: ToolContext) -> ToolResult:
    """执行一个工具调用。未知工具与非法参数都返回 `ok=False`，不抛异常。"""
    args = _parse_arguments(arguments)
    if name == "read_weakness_detail":
        return _weakness(context, str(args.get("point") or ""))
    if name == "read_question_detail":
        return _question(context, str(args.get("question_id") or ""), str(args.get("keyword") or ""))
    if name == "read_resume_anchor":
        return _resume(context, str(args.get("anchor_text") or ""))
    if name == "compare_reports":
        return _compare()
    if name == "remember":
        return _remember(context, str(args.get("content") or ""))
    return _fail(f"没有这个工具：{clip(name, 20)}")


def _parse_arguments(raw: str) -> dict[str, Any]:
    """模型给的参数是字符串：空串按空对象处理，解析失败也按空对象（由工具自己判缺参）。"""
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _ok(detail: dict[str, Any]) -> ToolResult:
    lines = [str(line) for line in (detail.get("lines") or [])][:MAX_RESULT_LINES]
    summary = lines[0] if lines else str(detail.get("label") or "")
    return {
        "ok": True,
        "label": str(detail.get("label") or ""),
        "summary": clip(summary, SUMMARY_MAX),
        "href": str(detail.get("href") or "") or None,
        "content": lines,
    }


def _fail(message: str) -> ToolResult:
    return {
        "ok": False,
        "label": "",
        "summary": clip(message, SUMMARY_MAX),
        "href": None,
        "content": [f"未读到：{clip(message, DETAIL_LINE_MAX)}"],
    }


def _match_weakness(items: list[Any], point: str) -> int | None:
    """分组名匹配：先逐字，再互相包含。返回 1-based 序号（`/report#weakness-N` 的 N）。"""
    needle = point.strip()
    if not needle:
        return None
    for index, item in enumerate(items, start=1):
        if str(item.point).strip() == needle:
            return index
    for index, item in enumerate(items, start=1):
        name = str(item.point).strip()
        if name and (needle in name or name in needle):
            return index
    return None


def _weakness(context: ToolContext, point: str) -> ToolResult:
    report = context.report
    if report is None or not report.weakness_map:
        return _fail("还没有诊断报告，读不到薄弱分组")
    index = _match_weakness(list(report.weakness_map), point)
    if index is None:
        return _fail(f"报告里没有「{clip(point, 20)}」这个分组")
    detail = build_detail(
        {"kind": KIND_WEAKNESS, "index": index},
        profile=context.profile,
        report=report,
        attempts=context.attempts,
        document_text=None,
        load_question=repository.get_question,
    )
    if detail is None:
        return _fail("这一组没有可用的样例题")
    return _ok(detail)


def _match_wrong_question(context: ToolContext, keyword: str) -> str:
    """在最近的错题里按题面关键词找一条。找不到返回空串。"""
    needle = keyword.strip()
    if not needle:
        return ""
    for row in context.attempts[:KEYWORD_SCAN_LIMIT]:
        question_id = str(row.get("question_id") or "")
        if not question_id:
            continue
        question = repository.get_question(question_id)
        if question is None:
            continue
        prompt = str(question.get("prompt") or "")
        if needle in prompt:
            return question_id
    return ""


def _question(context: ToolContext, question_id: str, keyword: str) -> ToolResult:
    target = question_id.strip() or _match_wrong_question(context, keyword)
    if not target:
        return _fail("没有匹配到你的错题，请换一个关键词")
    detail = build_detail(
        {"kind": KIND_ATTEMPT, "question_id": target},
        profile=context.profile,
        report=context.report,
        attempts=context.attempts,
        document_text=None,
        load_question=repository.get_question,
    )
    if detail is None:
        # 分两种原因：题目不在题库，或这道题你没有作答记录 —— 后者不叫「错题」。
        return _fail("这道题没有你的作答记录或已不在题库")
    return _ok(detail)


def _resume(context: ToolContext, anchor: str) -> ToolResult:
    text = anchor.strip()
    if not text:
        return _fail("没有给原句")
    detail = build_detail(
        {"kind": KIND_RESUME, "anchor": text},
        profile=context.profile,
        report=context.report,
        attempts=context.attempts,
        document_text=context.document(),
        load_question=repository.get_question,
    )
    if detail is None:
        return _fail("这句话在简历正文里找不到（可能正文已改版）")
    return _ok(detail)


def _percent(rate: float) -> str:
    return f"{round(rate * 100)}%"


def _compare() -> ToolResult:
    reports = repository.list_reports(limit=2)
    if len(reports) < 2:
        return _fail("目前只有一份报告，没有可比对象")
    latest, previous = reports[0], reports[1]
    lines = [f"对比：{str(previous.generated_at)[:10]} → {str(latest.generated_at)[:10]}"]
    for label, old, new in (
        ("笔试总分", previous.exam_total, latest.exam_total),
        ("面试均分", previous.interview_avg, latest.interview_avg),
    ):
        line = _delta(label, old, new)
        if line:
            lines.append(line)

    previous_map = {str(item.point): item for item in (previous.weakness_map or [])}
    for item in (latest.weakness_map or [])[:MAX_SAMPLES]:
        name = str(item.point)
        old = previous_map.get(name)
        if old is None:
            lines.append(f"新增薄弱：{clip(name, 24)}，错误率 {_percent(item.rate)}")
        elif abs(item.rate - old.rate) >= 0.05:
            trend = "好转" if item.rate < old.rate else "变差"
            lines.append(
                clip(
                    f"{clip(name, 24)}：{_percent(old.rate)} → {_percent(item.rate)}（{trend}）",
                    DETAIL_LINE_MAX,
                )
            )
    if len(lines) == 1:
        lines.append("两份报告的主要指标没有明显变化")
    return {
        "ok": True,
        "label": f"报告对比 · {str(latest.generated_at)[:10]}",
        "summary": clip(lines[1], SUMMARY_MAX),
        "href": "/report",
        "content": lines[:MAX_RESULT_LINES],
    }


def _delta(label: str, old: float | None, new: float | None) -> str:
    if old is None and new is None:
        return ""
    if old is None:
        return f"{label}：{round(float(new or 0))}（上次无数据）"
    if new is None:
        return f"{label}：本次无数据（上次 {round(float(old))}）"
    diff = round(float(new) - float(old))
    if diff == 0:
        return f"{label}：{round(float(new))}（持平）"
    return f"{label}：{round(float(old))} → {round(float(new))}（{diff:+d}）"


def _remember(context: ToolContext, content: str) -> ToolResult:
    written = context.remember(clip(content, policy.MEMORY_ITEM_MAX))
    if not written:
        return _fail("这条不适合记住（太短、超长，或与已有记忆重复）")
    return {
        "ok": True,
        "label": "已记住",
        "summary": clip(written, SUMMARY_MAX),
        "href": None,
        "content": [f"已记住：{written}"],
    }
