"""r100 B4 教练 Agent 编排：planner → executor → reflector → finalizer（LangGraph）。

与太傅（对话式 `agent ⇄ tools` 循环）刻意不同：这里演示的是**显式编排**——
先把问题规划成一条可审计的工具计划，执行后反思「材料够不够、缺什么」，
不够就补一轮执行，最后只基于工具结果写结论。每个节点的产出都进 `steps` 轨迹落库，
`GET /api/coach/agent/runs/{id}` 可回放「它为什么这么答」。

四道边界（与 r83 同一纪律）：
1. 出网只经 `AIClient`（结构化补全），图里没有 langchain 模型抽象；
2. 取料只经 `TOOLS` 白名单，模型不能越过工具看别的东西；
3. 引用只由工具结果产生（ref 令牌 t1/q1/w1/p1/l1 白名单），越界引用丢弃并计数；
4. 工具全部只读、有界（条数与字符数都封顶），一次编排最多 2 轮执行、3 条计划。
"""

from __future__ import annotations

import json
import logging
from functools import partial
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.core import repository
from app.schemas import (
    CoachAgentRun,
    CoachBriefDraft,
    CoachCitation,
    CoachPlanDraft,
    CoachReflectDraft,
)
from app.services.ai.ai import AIClient
from app.services.retrieval.hybrid import search_chunks

logger = logging.getLogger("app.coach.agent")

#: 一次编排最多几轮执行（首轮 + 补一轮）；反思说「还不够」也不无限补。
MAX_ACT_ROUNDS = 2
#: 单轮最多执行几步（规划器已限 3，补跑限 2，这里再兜一层）。
MAX_STEPS_PER_ROUND = 3
#: 结论 / 规划 / 反思都是短 JSON，用专用超时，不跟 600s 的画像档一起等。
AGENT_TIMEOUT_S = 120
#: 回灌给模型的每个工具结果最多几行；超出截断（轨迹里仍记条数）。
MAX_RESULT_LINES = 6
#: 工具返回的条目上限（检索类工具）。
MAX_ITEMS = 3

#: 工具闭集 + 中文说明（规划器提示词与执行器共用同一份，新增工具只改这里）。
TOOL_CATALOG: dict[str, str] = {
    "read_shortfalls": "读取最近一次诊断报告的薄弱点（分组名 + 诊断），了解用户当前短板。参数：无。",
    "search_tutorials": (
        "站内教程语义检索（RAG 混合检索），返回相关教程小节的标题与摘要。"
        "参数：query（中文关键词，如「事务隔离级别」）。"
    ),
    "search_questions": (
        "题库检索，返回相关题目题面（不含答案），用于安排练习。"
        "参数：query（中文关键词）；direction 可选（前端/后端/SQL 与数据库/中间件与运维/"
        "算法与数据结构/计算机基础/AI 工程/研发工程实践）。"
    ),
    "read_plan": "读取最近一份报告的 7 天学习计划打卡进度（做到第几天、完成了哪些）。参数：无。",
    "read_leap_archive": (
        "读取跃迁档案汇总：目标岗位差距、画像里逐条溯源的项目证据与已作答的面试表达。"
        "用于回答「我现在离目标岗位差什么 / 有哪些项目可讲 / 表达缺什么」这类问题。参数：无。"
    ),
}

#: 无报告 / 无画像时也要能跑：工具逐个给中文说明，不整体拒绝。
_NOTICE_NO_REPORT = "还没有诊断报告：薄弱点与计划工具会返回空，结论只能基于教程与题库检索。"


class ToolOutcome(TypedDict):
    """工具统一返回形状：执行器不必区分具体工具。"""

    ok: bool
    label: str
    summary: str
    items: list[dict[str, str]]
    lines: list[str]


def _empty(label: str, summary: str) -> ToolOutcome:
    return {"ok": False, "label": label, "summary": summary, "items": [], "lines": []}


def _clip(text: Any, limit: int = 160) -> str:
    value = str(text or "").replace("\n", " ").strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _read_shortfalls(_args: dict[str, str]) -> ToolOutcome:
    """薄弱点：只读最近一份报告，取前 3 条（报告 payload 结构见 Report.shortfalls）。"""
    report = repository.latest_report()
    if report is None:
        return _empty("薄弱点", "还没有诊断报告")
    items: list[dict[str, str]] = []
    tops = list(report.shortfalls or [])[:MAX_ITEMS]
    for index, shortfall in enumerate(tops, start=1):
        detail = str(shortfall.diagnosis or "")
        if shortfall.actions:
            detail += "｜建议：" + "；".join(str(action) for action in shortfall.actions[:2])
        if shortfall.evidence:
            detail += "｜证据：" + str(shortfall.evidence)
        items.append(
            {
                "ref": f"w{index}",
                "title": _clip(shortfall.name, 40),
                "snippet": _clip(detail, 160),
                "href": "/report",
                "kind": "shortfall",
            }
        )
    if not items:
        return _empty("薄弱点", "报告里没有薄弱点记录")
    return {
        "ok": True,
        "label": "薄弱点",
        "summary": f"{len(items)} 个薄弱点",
        "items": items,
        "lines": [item["title"] + "：" + item["snippet"] for item in items],
    }


def _search_tutorials(args: dict[str, str]) -> ToolOutcome:
    """教程语义检索：直连 r100 的 RAG 混合检索（教程 chunk 闭集）。"""
    query = _clip(args.get("query") or "", 80)
    if not query:
        return _empty("教程检索", "缺少 query 参数")
    payload = search_chunks(query, mode="hybrid", top_k=MAX_ITEMS, kinds=["tutorial"])
    hits = list(payload["items"])[:MAX_ITEMS]
    if not hits:
        return _empty("教程检索", payload.get("notice") or "没有命中教程小节")
    items: list[dict[str, str]] = []
    lines: list[str] = []
    for index, hit in enumerate(hits, start=1):
        href = "/learn/" + str(hit["ref_id"])
        # r103：小节被切分时 section_id 带 `#n` 后缀，锚点只取前半段。
        anchor = str(hit.get("section_id") or "").split("#")[0]
        if anchor:
            href += "#tutorial-" + anchor
        items.append(
            {
                "ref": f"t{index}",
                "title": _clip(hit["title"] or hit["snippet"], 48),
                "snippet": _clip(hit["snippet"], 160),
                "href": href,
                "kind": "tutorial",
            }
        )
        lines.append(f"{items[-1]['title']}：{items[-1]['snippet']}")
    return {
        "ok": True,
        "label": "教程检索",
        "summary": f"{len(items)} 条教程小节（{payload.get('engine') or 'hybrid'}）",
        "items": items,
        "lines": lines[:MAX_RESULT_LINES],
    }


def _search_questions(args: dict[str, str]) -> ToolOutcome:
    """题库检索：复用既有 `repository.search_questions`（答案永不入响应）。"""
    query = _clip(args.get("query") or "", 80)
    if not query:
        return _empty("题库检索", "缺少 query 参数")
    direction = _clip(args.get("direction") or "", 20)
    directions = [direction] if direction else None
    result = repository.search_questions(query, directions, limit=MAX_ITEMS)
    rows = list(result["items"])[:MAX_ITEMS]
    if not rows:
        return _empty("题库检索", "没有命中题目")
    items = [
        {
            "ref": f"q{index}",
            "title": _clip(row["prompt"], 60),
            "snippet": _clip(
                (row["direction"] or "") + (" / " + row["sub_direction"]
                                            if row.get("sub_direction") else ""),
                60,
            ),
            "href": "/practice?direction=" + str(row["direction"] or ""),
            "kind": "question",
        }
        for index, row in enumerate(rows, start=1)
    ]
    return {
        "ok": True,
        "label": "题库检索",
        "summary": f"{len(items)} 道相关题",
        "items": items,
        "lines": [item["title"] for item in items],
    }


def _read_plan(_args: dict[str, str]) -> ToolOutcome:
    """7 天计划进度：只读打卡状态（`done` 里的任务 id 数 = 已完成数）。"""
    report = repository.latest_report()
    if report is None:
        return _empty("计划进度", "还没有诊断报告")
    state = repository.get_plan_state(report.id)
    done = [key for key, flag in (state.get("done") or {}).items() if flag]
    if not state.get("updated_at"):
        return _empty("计划进度", "这份报告还没有开始打卡")
    minutes = int(state.get("daily_minutes") or 0)
    text = f"已完成 {len(done)} 项任务"
    if minutes:
        text = "每日 " + str(minutes) + " 分钟，" + text
    if state.get("started_on"):
        text += "，起始日 " + str(state["started_on"])
    return {
        "ok": True,
        "label": "计划进度",
        "summary": text,
        "items": [
            {
                "ref": "p1",
                "title": "7 天计划进度",
                "snippet": _clip(text, 120),
                "href": "/report",
                "kind": "plan",
            }
        ],
        "lines": [text],
    }


def _read_leap_archive(_args: dict[str, str]) -> ToolOutcome:
    """跃迁档案：复用服务端聚合（零 AI、零重算），只产出有事实支撑的条目。

    `href` 统一指向 `/leap`（太傅 / 教练的页面白名单里已登记）；没有报告 / 没有项目
    时给中文空结果，绝不编造岗位差距或项目证据。
    """
    from app.services.leap import build_leap_archive

    snapshot = build_leap_archive()
    items: list[dict[str, str]] = []
    fit = snapshot.role_gap.role_fit
    if fit is not None:
        for index, name in enumerate(fit.first_fix[:MAX_ITEMS], start=1):
            items.append(
                {
                    "ref": f"l{index}",
                    "title": _clip(f"先补：{name}", 40),
                    "snippet": _clip(f"{fit.target_role or '目标岗位'} · {fit.notice or '差距见跃迁档案'}", 160),
                    "href": "/leap",
                    "kind": "leap_role",
                }
            )
    for index, project in enumerate(snapshot.engineering.projects[:MAX_ITEMS], start=1):
        items.append(
            {
                "ref": f"l{MAX_ITEMS + index}",
                "title": _clip(project.name, 40),
                "snippet": _clip(
                    f"{project.role or '项目'} · 原文溯源 {project.evidence_count} 条"
                    + ("｜" + "；".join(project.bullets[:2]) if project.bullets else ""),
                    160,
                ),
                "href": "/leap",
                "kind": "leap_project",
            }
        )
    if not items:
        return _empty("跃迁档案", snapshot.role_gap.notice or "跃迁档案还没有可引用的证据")
    return {
        "ok": True,
        "label": "跃迁档案",
        "summary": f"岗位差距 {len(fit.first_fix) if fit else 0} 项、项目 {len(snapshot.engineering.projects)} 条",
        "items": items,
        "lines": [item["title"] + "：" + item["snippet"] for item in items],
    }


#: 工具名 → 执行函数（闭集；规划器给出的闭集外工具一律不执行）。
TOOLS: dict[str, Any] = {
    "read_shortfalls": _read_shortfalls,
    "search_tutorials": _search_tutorials,
    "search_questions": _search_questions,
    "read_plan": _read_plan,
    "read_leap_archive": _read_leap_archive,
}

_PLANNER_SYSTEM = (
    "你是学习教练的规划器。用户会给你一个问题、目标与可用工具清单。"
    "请规划最多 3 步工具调用，选择最有信息量的组合（通常先读现状，再检索教程/题库）。"
    "只输出一个 JSON 对象：{\"goal\": \"一句话目标\", \"steps\": "
    "[{\"tool\": \"工具名\", \"reason\": \"中文理由\", \"args\": {\"query\": \"中文关键词\"}}]}。"
    "工具名必须来自清单，不要编造；参数值用中文短词。"
)

_REFLECT_SYSTEM = (
    "你是学习教练的反思器。判断已收集的材料是否足以回答用户的问题。"
    "只输出一个 JSON 对象：{\"sufficient\": true/false, \"missing\": [\"缺什么（中文短句）\"], "
    "\"extra_steps\": [{\"tool\": \"工具名\", \"reason\": \"中文理由\", \"args\": {}}]}。"
    "sufficient=true 时 extra_steps 给空数组；不足时最多补 2 步，且只补真正缺的那部分。"
)

_BRIEF_SYSTEM = (
    "你是学习教练。基于【工具结果】回答用户问题，并给出可执行建议。"
    "硬性规则：只使用工具结果里的信息，没有的不要编造；引用必须用结果里的 ref 令牌"
    "（如 t1、q2、w1、l1），每一条引用都要真实对应结果中的条目；回答末尾的 actions 给 1-3 条"
    "具体行动（做到什么、用什么材料）。只输出一个 JSON 对象："
    "{\"answer\": \"中文回答\", \"citations\": [\"t1\"], \"actions\": [\"...\"]}。"
)


class AgentState(TypedDict, total=False):
    """图状态：`steps` 是完整审计轨迹，`catalog` 是引用白名单（ref → 条目）。"""

    run_id: str
    question: str
    goal: str
    rounds: int
    pending: list[dict[str, Any]]
    executed: list[dict[str, Any]]
    catalog: dict[str, dict[str, str]]
    steps: list[dict[str, Any]]
    missing: list[str]
    answer: str
    citations: list[dict[str, str]]
    dropped: int
    notice: str
    started_at: str


def _tool_brief() -> str:
    return "\n".join("- " + name + "：" + desc for name, desc in TOOL_CATALOG.items())


def _collect_lines(executed: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for record in executed:
        if not record.get("ok"):
            continue
        lines = record.get("lines") or []
        if not lines:
            continue
        blocks.append("【" + str(record.get("label")) + "】\n" + "\n".join(lines[:MAX_RESULT_LINES]))
    return "\n\n".join(blocks)


def _sanitize_steps(raw: list[Any]) -> list[dict[str, Any]]:
    """规划器 / 反思器的步：闭集外工具丢弃，参数截短，总数截断。"""
    steps: list[dict[str, Any]] = []
    for item in raw:
        name = str(getattr(item, "tool", "") or "").strip()
        if name not in TOOLS:
            continue
        args = {
            str(key)[:20]: _clip(value, 80)
            for key, value in (getattr(item, "args", {}) or {}).items()
            if str(key) in ("query", "direction", "point")
        }
        steps.append({"tool": name, "reason": _clip(getattr(item, "reason", ""), 120), "args": args})
        if len(steps) >= MAX_STEPS_PER_ROUND:
            break
    return steps


def _default_plan(question: str) -> list[dict[str, Any]]:
    """规划器失效时的确定性兜底：读现状 + 按问句检索教程与题库。"""
    return [
        {"tool": "read_shortfalls", "reason": "先看当前短板（兜底计划）", "args": {}},
        {"tool": "search_tutorials", "reason": "按问句找教程小节（兜底计划）", "args": {"query": question}},
        {"tool": "search_questions", "reason": "按问句找相关题（兜底计划）",
         "args": {"query": question, "direction": ""}},
    ][:MAX_STEPS_PER_ROUND]


async def _plan_node(state: AgentState, client: AIClient) -> dict[str, Any]:
    """规划：一次结构化补全产出计划；失败/空计划时走确定性兜底并如实记账。"""
    user = (
        "【问题】\n" + state["question"]
        + "\n\n【目标】\n" + (state.get("goal") or "未指定")
        + "\n\n【可用工具】\n" + _tool_brief()
    )
    fallback = False
    try:
        draft: CoachPlanDraft = await client.complete_model(
            _PLANNER_SYSTEM, user, CoachPlanDraft, timeout_s=AGENT_TIMEOUT_S
        )
        steps = _sanitize_steps(list(draft.steps))
        goal = draft.goal.strip()[:200]
    except Exception as exc:  # 规划失败不阻断：兜底计划 + 如实记账
        logger.warning("coach.plan_failed error=%s", type(exc).__name__)
        steps, goal = [], ""
    if not steps:
        steps, fallback = _default_plan(state["question"]), True
    trace_step = {
        "kind": "plan",
        "goal": goal or state.get("goal") or "",
        "steps": steps,
        "fallback": fallback,
    }
    return {
        "pending": steps,
        "goal": goal or state.get("goal") or "",
        "steps": [*state.get("steps", []), trace_step],
    }


async def _act_node(state: AgentState, client: AIClient) -> dict[str, Any]:
    """执行：按计划顺序跑工具，结果进 `executed` 与引用白名单，逐条进轨迹。"""
    executed = list(state.get("executed", []))
    catalog = dict(state.get("catalog", {}))
    trace = list(state.get("steps", []))
    seen = {(record["tool"], json.dumps(record["args"], ensure_ascii=False)) for record in executed}
    for step in state.get("pending", [])[:MAX_STEPS_PER_ROUND]:
        key = (step["tool"], json.dumps(step.get("args") or {}, ensure_ascii=False))
        if key in seen:
            trace.append({"kind": "tool_skip", "tool": step["tool"], "reason": "重复调用已跳过"})
            continue
        fn = TOOLS[step["tool"]]
        try:
            outcome: ToolOutcome = fn(step.get("args") or {})
        except Exception as exc:  # 单个工具失败不连坐整场编排
            logger.warning("coach.tool_failed tool=%s error=%s", step["tool"], type(exc).__name__)
            outcome = _empty(step["tool"], "工具执行失败，已跳过")
        record = {"tool": step["tool"], "args": step.get("args") or {}, **outcome}
        executed.append(record)
        for item in outcome["items"]:
            catalog.setdefault(item["ref"], item)
        trace.append(
            {
                "kind": "tool",
                "tool": step["tool"],
                "reason": step.get("reason", ""),
                "args": step.get("args") or {},
                "ok": outcome["ok"],
                "label": outcome["label"],
                "summary": outcome["summary"],
                "items": outcome["items"],
            }
        )
        seen.add(key)
    return {
        "executed": executed,
        "catalog": catalog,
        "steps": trace,
        "pending": [],
        "rounds": int(state.get("rounds", 0)) + 1,
    }


async def _reflect_node(state: AgentState, client: AIClient) -> dict[str, Any]:
    """反思：材料够不够？不够且还有轮次额度就补执行，否则收敛到结论。"""
    material = _collect_lines(state.get("executed", [])) or "（工具没有返回可用材料）"
    user = (
        "【问题】\n" + state["question"]
        + "\n\n【工具结果】\n" + material
        + "\n\n【可用工具】\n" + _tool_brief()
    )
    try:
        draft: CoachReflectDraft = await client.complete_model(
            _REFLECT_SYSTEM, user, CoachReflectDraft, timeout_s=AGENT_TIMEOUT_S
        )
        sufficient = bool(draft.sufficient)
        missing = [str(item)[:80] for item in draft.missing[:5]]
        extra = [] if sufficient else _sanitize_steps(list(draft.extra_steps))
    except Exception as exc:
        logger.warning("coach.reflect_failed error=%s", type(exc).__name__)
        sufficient, missing, extra = True, [], []
    exhausted = int(state.get("rounds", 0)) >= MAX_ACT_ROUNDS
    pending = [] if exhausted else extra
    trace = {
        "kind": "reflect",
        "sufficient": sufficient,
        "missing": missing,
        "extra_steps": extra,
        "rounds": int(state.get("rounds", 0)),
        "exhausted": exhausted,
    }
    return {"missing": missing, "pending": pending, "steps": [*state.get("steps", []), trace]}


async def _final_node(state: AgentState, client: AIClient) -> dict[str, Any]:
    """结论：只基于工具结果写回答；引用按白名单解析，越界丢弃并计数。"""
    catalog = state.get("catalog", {})
    material = _collect_lines(state.get("executed", [])) or "（没有可用材料）"
    refs = "\n".join(f"- {ref}：{item['title']}" for ref, item in sorted(catalog.items()))
    user = (
        "【问题】\n" + state["question"]
        + "\n\n【目标】\n" + (state.get("goal") or "未指定")
        + "\n\n【工具结果】\n" + material
        + "\n\n【可引用条目】\n" + (refs or "（无可引用条目）")
    )
    try:
        draft: CoachBriefDraft = await client.complete_model(
            _BRIEF_SYSTEM, user, CoachBriefDraft, timeout_s=AGENT_TIMEOUT_S
        )
        answer = draft.answer.strip()[:4000]
        cited = [str(item).strip() for item in draft.citations]
        actions = [str(item)[:120] for item in draft.actions[:5]]
    except Exception as exc:
        logger.warning("coach.brief_failed error=%s", type(exc).__name__)
        answer, cited, actions = "编排已完成，但结论生成失败，请稍后在「讲席」重试。", [], []
    valid: list[dict[str, str]] = []
    for ref in cited:
        if ref in catalog and ref not in {item["ref"] for item in valid}:
            valid.append(dict(catalog[ref]))
    dropped = max(0, len(cited) - len(valid))
    trace = {"kind": "final", "actions": actions, "dropped_citations": dropped}
    return {
        "answer": answer,
        "citations": valid,
        "dropped": dropped,
        "steps": [*state.get("steps", []), trace],
    }


def _route_after_reflect(state: AgentState) -> str:
    return "act" if state.get("pending") else "final"


def _build_graph(client: AIClient):
    """编译图：节点用 `functools.partial` 注入 client。

    为什么不用 lambda：LangGraph 靠 `iscoroutinefunction` 判定节点是否 async，
    `lambda state: _plan_node(state, client)` 返回的是「一个协程对象」而不是协程函数，
    会被当成同步更新、把协程当 state 写回去。partial 的 async 判定在 CPython 里成立。
    """
    graph = StateGraph(AgentState)
    graph.add_node("plan", partial(_plan_node, client=client))
    graph.add_node("act", partial(_act_node, client=client))
    graph.add_node("reflect", partial(_reflect_node, client=client))
    graph.add_node("final", partial(_final_node, client=client))
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "act")
    graph.add_edge("act", "reflect")
    graph.add_conditional_edges("reflect", _route_after_reflect, {"act": "act", "final": "final"})
    graph.add_edge("final", END)
    return graph.compile()


async def run_agent(question: str, *, goal: str, client: AIClient) -> CoachAgentRun:
    """跑一次编排并落库：返回完整轨迹（HTTP 层直接投影）。"""
    run_id = "cr-" + uuid4().hex[:16]
    state = await _build_graph(client).ainvoke(
        {
            "run_id": run_id,
            "question": question,
            "goal": goal,
            "rounds": 0,
            "pending": [],
            "executed": [],
            "catalog": {},
            "steps": [],
            "missing": [],
            "answer": "",
            "citations": [],
            "dropped": 0,
            "notice": "",
            "started_at": "",
        }
    )
    citations = [CoachCitation(**item) for item in state.get("citations", [])]
    executed = state.get("executed", [])
    notice = "" if any(record.get("ok") for record in executed) else _NOTICE_NO_REPORT
    run = CoachAgentRun(
        id=run_id,
        question=question,
        goal=state.get("goal") or goal,
        status="completed",
        steps=state.get("steps", []),
        answer=state.get("answer", ""),
        citations=citations,
        dropped_citations=int(state.get("dropped", 0)),
        notice=notice,
    )
    repository.save_coach_run(
        run_id,
        question=question,
        goal=run.goal,
        status=run.status,
        steps=run.steps,
        answer=run.answer,
        citations=[citation.model_dump() for citation in citations],
    )
    row = repository.coach_run_row(run_id) or {}
    run.created_at = str(row.get("created_at", ""))
    return run
