"""r77 太傅问答的纯函数层：问句清洗、提示词拼装、回答净化与**引用白名单**。

与 r65 教练同一条思路、不同一条边界：
- 教练的材料由前端上传，服务端只能做形状校验；
- 太傅的材料由服务端自己查（`brief.build_sections`），客户端无法注入，
  因此白名单是「这次真的读到了哪几段」的投影 —— 模型引用一段没读到的页面即视为幻觉。

本模块零 IO、零配置，所有规则可单测。
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

#: 问句上限：太傅要回答的是「我这情况怎么办」，不是写作文；200 字足够说清背景。
QUESTION_MAX = 200
#: 回答上限：面板宽度有限，超长回答在浮窗里读不完，也容易变成注水。
REPLY_MAX = 1200
#: 单次回答最多 4 条出处：再多用户也不会点，反而稀释「这条引用支撑哪句话」。
CITATION_LIMIT = 4
#: 进提示词的最近消息条数（3 轮问答）。
HISTORY_LIMIT = 6
HISTORY_ITEM_MAX = 300
#: 线程摘要上限：只写结论与已确认背景，长过这个数就不是「摘要」而是又一段对话。
#: （r81 起统一叫 summary：r80 的 `memory` 与长期记忆的 `memories` 只差一个字母，模型极易搞混形状。）
SUMMARY_MAX = 240
#: 摘要有效下限：模型常回「无」「（无）」「N/A」这类占位，短于 4 字一律当作没给（不清空旧摘要）。
#: 别再调高：中文摘要一行十几个字就够用，阈值定高了会把合法短摘要一起丢掉。
SUMMARY_MIN = 4
#: 单条长期记忆上限：一句话说得清的事实，不是一段自述。
MEMORY_ITEM_MAX = 80
#: 单条长期记忆下限：太短的（「好的」「是的」）没有信息量，不记。
MEMORY_ITEM_MIN = 6
#: 每轮最多新增长期记忆条数：一次说十件事是自述，不是对话。
MEMORY_ITEMS_PER_TURN = 2

EMPTY_QUESTION_NOTICE = "先写下你想问的问题，比如「我最近一次测评为什么掉分」。"
EMPTY_BRIEF_NOTICE = (
    "你的站内记录还是空的：先上传简历并生成技术画像，或先做一次计分测评 / 练习，"
    "我才有东西可以分析。"
)
EMPTY_REPLY_NOTICE = "这次没有生成可用回答，可以再问一次，或先去诊断报告里看具体短板。"

#: 当前页面白名单：**闭集**，只认这些路径。前端传什么路由都只能命中这里，
#: 因此「页面上下文」不会变成任意文本注入提示词的入口。
#: 页面只进提示词、**不进引用白名单** —— 你正在看的页面不是「依据」。
PAGES: dict[str, tuple[str, str]] = {
    "/": ("投卷（上传简历）", "上传简历、查看解析与画像生成进度"),
    "/profile": ("立传（技术画像）", "技能 / 技术栈 / 项目 / 目标岗位，可逐条编辑"),
    "/interview": ("召对（模拟面试）", "多轮追问与逐题评分，可回放在途场次"),
    "/exam": ("科考（笔试）", "10–12 道客观题、本地判分与熟练度过滤"),
    "/report": ("医案（诊断报告）", "短板、薄弱分组、简历改进要点与 7 天计划"),
    "/history": ("战绩（测评历史）", "历次面试均分 / 笔试总分与趋势"),
    "/practice": ("演武（专项练习）", "按方向的练习题单与错题本"),
    "/learn": ("学堂（站内教程）", "8 个方向的章节与阅读进度"),
    "/polish": ("修文（简历润色）", "逐句润色建议与原文对照"),
    "/versions": ("校勘（简历版本）", "多个简历版本的差异对比"),
    "/archive": ("卷宗（学习档案）", "跨模块汇总与 Markdown 导出"),
    "/pioneer": ("先锋（技术雷达）", "新技术清单与评估分档"),
    "/guozijian": ("国子监（生成进度）", "雷达样例的章节 / 题目 / 自检进度"),
    "/search": ("检索（全站搜索）", "教程与题库的全文检索"),
    "/settings": ("典制（设置）", "账号、AI Key 与每日配额"),
}

PAGE_UNKNOWN = "（未识别当前页面，按问题本身回答）"

TAIFU_SYSTEM = """你是「太傅」，逃跑计划的跃迁参谋，服务对象是想转向 AI 应用 / Agent 后端的外包工程师。

硬性规则：
1. 只能使用【档案】里出现过的内容；档案里没有的数字、项目、结论一律不写。
2. 引用只能从【档案】里逐字抄写出现过的 href：段标题后的页面（如 /report），或行内标注的具体位置（如 /report#weakness-2）。不得自造链接、锚点或页面。
3. 信息不足时直接说明「你的记录里还没有 X」，并指出补哪一步能让这个问题变得可答。
4. 不承诺求职结果，不把模拟测评说成工作经历，不编造项目指标。
5. 【当前页面】只用于理解「这里 / 这条」这类指代；不要因为用户在这一页就编造该页没有的数据。
6. 【早期对话摘要】是你自己在前几轮写下的记忆：只用来理解「上次说的那个」，**不是依据**，也不能从里面挑引用。
7. 【长期记忆】是用户此前明确说过的背景与偏好：用来知道「他是谁」，同样**不是依据**；与【档案】冲突时以【档案】为准。
8. 只输出一个 JSON 对象：{"reply": "回答正文", "citations": ["/report"], "summary": "早期对话摘要", "memories": ["值得长期记住的新事实"]}，不要代码围栏，不要额外解释。"""

SUMMARY_NONE = "（无：这是本次线程的开头，或对话还短到不需要压缩）"
SUMMARY_TASK = {
    True: (
        "另外：把【早期对话摘要】与【最近对话】里这一轮的内容合并，用 summary 字段输出更新后的摘要"
        f"（不超过 {SUMMARY_MAX} 字，只保留用户已确认的背景与已经给过的结论，不写链接、不写客套话）。"
    ),
    False: "本轮不需要压缩摘要：summary 字段给空字符串。",
}

MEMORIES_NONE = "（无）"
MEMORY_TASK = (
    "长期记忆：只有当用户这一轮**明确说出一条跨对话仍然成立、且【档案】与【长期记忆】里都没有的**事实或偏好时"
    f"（例如「只能周末学习」「已排除算法岗」「更想留在杭州」），才用 memories 字段输出，每条不超过 {MEMORY_ITEM_MAX} 字，"
    f"最多 {MEMORY_ITEMS_PER_TURN} 条；这一轮问了什么、你的建议都不算长期记忆。没有就给空数组。"
)

USER_PROMPT_TEMPLATE = """【档案】
{materials}

【长期记忆】（用户口头说过、档案里没有的背景与偏好；不是依据，不能当引用出处）
{memories}
【早期对话摘要】{summary}
【当前页面】{page}

【最近对话】
{history}

【问题】{question}

{memory_task}
{summary_task}
请输出 JSON：{{"reply": "中文回答，允许换行分段", "citations": ["档案里出现过的 href"], "summary": "", "memories": []}}。
约束：citations 最多 4 条且必须逐字来自【档案】；没有可引用的内容时给空数组。"""

NO_HISTORY = "（这是本轮对话的第一句）"


class TaifuDraftReply(BaseModel):
    """模型输出（**未校验**）：`citations` 必须再过白名单才允许进响应。

    - `summary`：r80 的线程摘要（早期对话压缩，滚动重写）；
    - `memories`：r81 的长期记忆候选（跨对话的事实与偏好，去重后才可能落库）。
    两者都**永不进引用白名单** —— 它们都是模型自己写的话，不是站内记录。
    """

    reply: str = ""
    citations: list[Any] = Field(default_factory=list)
    summary: str = ""
    memories: list[Any] = Field(default_factory=list)


def flatten(text: Any) -> str:
    """压平空白：问句与摘要行都必须是单行。"""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def sanitize_page(raw: Any) -> dict[str, str] | None:
    """把前端传来的 pathname 归一成闭集里的一页；未识别一律返回 `None`（不猜、不截断成前缀）。

    `/learn/<slug>` 是唯一的子路径：教程详情归到学堂，否则每章都要在闭集里开一条。
    查询串与 hash 在归一前去掉（`?run_id=` / `#tutorial-s1` 不参与判定）。
    """
    path = flatten(raw).split("?")[0].split("#")[0]
    if not path:
        # 空串 = 前端没传（或旧版本客户端）：不猜页面，也不要默认成首页。
        return None
    path = path.rstrip("/") or "/"
    if path.startswith("/learn/"):
        path = "/learn"
    entry = PAGES.get(path)
    if entry is None:
        return None
    return {"path": path, "label": entry[0], "hint": entry[1]}


def sanitize_question(raw: Any) -> str:
    """问句清洗：压平 + 截断。空串表示「不该进模型」，由路由层给中文提示。"""
    flat = flatten(raw)
    if len(flat) <= QUESTION_MAX:
        return flat
    return flat[:QUESTION_MAX].rstrip() + "…"


def normalize_reply(raw: Any) -> str:
    """回答正文：保留换行（前端按段落渲染），压掉 3+ 连续空行，超长截断。"""
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= REPLY_MAX:
        return text
    return text[:REPLY_MAX].rstrip() + "…"


def _history_line(message: dict[str, Any]) -> str:
    speaker = "太傅" if message.get("role") == "assistant" else "用户"
    return f"{speaker}：{flatten(message.get('content'))[:HISTORY_ITEM_MAX]}"


def sanitize_summary(raw: Any) -> str:
    """线程摘要净化：压成**单行**、截到 `SUMMARY_MAX`；短于 `SUMMARY_MIN` 视为没给。

    单行是硬要求：摘要会作为提示词里的一个 `【段】` 出现，多行会把后面的段头挤散。
    返回空串表示「本轮不更新摘要」，调用方据此**保留旧摘要**（不能拿空串覆盖）。
    """
    flat = flatten(raw)
    if len(flat) < SUMMARY_MIN:
        return ""
    if len(flat) <= SUMMARY_MAX:
        return flat
    return flat[:SUMMARY_MAX].rstrip() + "…"


def _memory_key(text: str) -> str:
    """长期记忆的比较键：只留中文与字母数字，去空格与标点，ASCII 不区分大小写。

    只用来判「是不是同一件事」，不追求语义相似（没有 embedding，也不想为此引依赖）。
    """
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]", "", text).lower()


def sanitize_memories(raw: list[Any], existing: list[str]) -> list[str]:
    """长期记忆候选净化：压单行 → 长度夹取 → 与已有/同批去重 → 每轮最多 `MEMORY_ITEMS_PER_TURN` 条。

    去重口径是「**互相包含即同一件事**」：「只能周末学习」与「用户只能周末学习，工作日要上班」
    记一条就够，再记一条只会让后面的条目挤掉别的。宁可少记，不要记重。
    """
    keys = [key for key in (_memory_key(item) for item in existing) if key]
    kept: list[str] = []
    kept_keys: list[str] = []
    for value in raw:
        text = flatten(value)
        if len(text) < MEMORY_ITEM_MIN:
            continue
        if len(text) > MEMORY_ITEM_MAX:
            text = text[:MEMORY_ITEM_MAX].rstrip() + "…"
        key = _memory_key(text)
        if not key:
            continue
        if any(key == old or key in old or old in key for old in keys):
            continue
        if any(key == new or key in new or new in key for new in kept_keys):
            continue
        kept.append(text)
        kept_keys.append(key)
        if len(kept) >= MEMORY_ITEMS_PER_TURN:
            break
    return kept


def render_memories(contents: list[str]) -> str:
    """把长期记忆渲染成提示词里的编号清单；空列表给固定占位（不留空段头）。"""
    lines = [f"{index}. {flatten(text)}" for index, text in enumerate(contents, start=1)]
    return "\n".join(lines) or MEMORIES_NONE


def build_user_prompt(
    sections: list[dict[str, Any]],
    history: list[dict[str, Any]],
    question: str,
    page: dict[str, str] | None = None,
    *,
    summary: str = "",
    memories: list[str] | None = None,
    compact: bool = False,
) -> str:
    """拼用户消息：档案逐段编号 + 段 href + 行，后接长期记忆、线程摘要、当前页面与本次问题。

    `page` / `summary` / `memories` 都只用于**理解**，**不是**依据：三者都不进引用白名单。
    `compact=True` 时才要求模型回写摘要：窗口还没溢出时压摘要既无信息量、又白占篇幅。
    """
    blocks: list[str] = []
    for index, section in enumerate(sections, start=1):
        head = f"[{index}] {section['label']}（href: {section['href']}）"
        body = "\n".join(f"- {line}" for line in section["lines"])
        blocks.append(f"{head}\n{body}")
    rendered_materials = "\n\n".join(blocks) or "（无）"
    rendered_history = (
        "\n".join(_history_line(item) for item in history[-HISTORY_LIMIT:]) or NO_HISTORY
    )
    page_line = (
        f"{page['label']}（{page['path']}）—— {page['hint']}" if page is not None else PAGE_UNKNOWN
    )
    return USER_PROMPT_TEMPLATE.format(
        materials=rendered_materials,
        memories=render_memories(list(memories or [])),
        summary=flatten(summary) or SUMMARY_NONE,
        page=page_line,
        history=rendered_history,
        question=flatten(question),
        memory_task=MEMORY_TASK,
        summary_task=SUMMARY_TASK[compact],
    )


def sanitize_reply(draft: TaifuDraftReply, sections: list[dict[str, Any]]) -> dict[str, Any]:
    """校验 + 净化模型输出，返回 `TaifuReply` 的字段字典。

    - `citations` 里不在本次档案白名单的 href → 丢弃并计数（幻觉引用）；
    - 白名单 = 各段 href + 段内锚点（`/report#weakness-N`），锚点标签更具体；
    - 重复 href 去重保序（不算幻觉）；空串直接跳过；
    - 正文为空 → 给中文 notice，**不抛异常**（模型退化不该变成 500）；
    - `materials_used` 恒等于本次读到的段数，让界面能如实展示「读了几段记录」。
    """
    allowed = {section["href"]: section["label"] for section in sections}
    for section in sections:
        for anchor in section.get("anchors") or []:
            href = str(anchor.get("href") or "")
            if href:
                # 段级 href 优先：同一 URL 若两者都有，保留段标签（更短、更稳）。
                allowed.setdefault(href, str(anchor.get("label") or href))
    citations: list[dict[str, str]] = []
    seen: set[str] = set()
    dropped = 0
    for raw in draft.citations:
        href = flatten(raw)
        if not href:
            continue
        if href not in allowed:
            dropped += 1
            continue
        if href in seen:
            continue
        seen.add(href)
        citations.append({"label": allowed[href], "href": href})
        if len(citations) >= CITATION_LIMIT:
            break

    reply = normalize_reply(draft.reply)
    return {
        "reply": reply,
        "citations": citations,
        "materials_used": len(sections),
        "dropped_citations": dropped,
        "notice": "" if reply else EMPTY_REPLY_NOTICE,
        "created_at": "",
    }
