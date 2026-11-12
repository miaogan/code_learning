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

#: r82 焦点闭集：页面只能把「用户点了哪一条」说成这三种，其余一律当没传。
FOCUS_KINDS: frozenset[str] = frozenset({"weakness", "attempt", "resume"})
#: 题号上限：题库 id 都是短 slug；超长（或带奇怪字符）一律当非法，不往 SQL 送。
FOCUS_QUESTION_ID_MAX = 64
#: 简历原句上限：`ResumePointer.anchor_text` ≤40 字，这里留一倍余量给正文里更长的句子。
FOCUS_ANCHOR_MAX = 80

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
8. 【重点明细】是用户刚从页面上点开的那一条的原始记录（题面、解析、正文原句），比【档案】更细，**同样是依据**：
   回答「这条 / 这题 / 这段」时优先用它，可以引用它的 href；明细里没有的内容不要补。
9. 只输出一个 JSON 对象：{"reply": "回答正文", "citations": ["/report"], "summary": "早期对话摘要", "memories": ["值得长期记住的新事实"]}，不要代码围栏，不要额外解释。"""

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

【重点明细】（用户刚从页面上点开的那一条，比【档案】更细；同样是依据，优先用它回答「这条 / 这题 / 这段」）
{detail}

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
#: 没有明细时的占位：必须明确说「不要猜『这条』指什么」，否则模型会把摘要里最近的一组当成本条。
DETAIL_NONE = "（本轮没有额外明细：直接按【档案】回答；不要猜「这条 / 这题 / 这段」指的是哪一条。）"


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


def sanitize_focus(raw: Any) -> dict[str, Any] | None:
    """把页面带来的焦点归一成闭集里的三种之一；不合法一律 `None`（== 没传）。

    **不做库内校验**（这一组报告里有没有、这道题有没有作答、这句在不在正文里）——
    那是 `deep_read.build_detail()` 的事。这里只保证「形状可信」：
    未知 kind、0 或负数序号、空题号、空原句、超长字段都进不了下游。

    `bool` 要单独排除：Python 里 `True` 是 `int` 的实例，`index=True` 会变成第 1 组，
    把「脏数据」静默解释成「第一条」是最不该发生的一类猜测。
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        data: dict[str, Any] = raw
    else:
        data = {
            name: getattr(raw, name, "")
            for name in ("kind", "index", "question_id", "anchor")
        }
    kind = flatten(data.get("kind"))
    if kind not in FOCUS_KINDS:
        return None
    if kind == "weakness":
        index = data.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 1:
            return None
        return {"kind": kind, "index": index}
    if kind == "attempt":
        question_id = flatten(data.get("question_id"))
        if not question_id or len(question_id) > FOCUS_QUESTION_ID_MAX:
            return None
        if not re.fullmatch(r"[0-9A-Za-z_-]+", question_id):
            return None
        return {"kind": kind, "question_id": question_id}
    anchor = flatten(data.get("anchor"))
    if not anchor or len(anchor) > FOCUS_ANCHOR_MAX:
        return None
    return {"kind": kind, "anchor": anchor}


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


def render_detail(detail: dict[str, Any] | None) -> str:
    """把「重点明细」渲染成提示词里的独立一块（编号固定 `[1]`，不与档案段混排）。

    明细是**单条**，所以不参与档案的 `[1]..[n]` 编号：混在一起模型会以为它是第 n 段摘要，
    回答时就会把摘要里的其它组也当成本条的依据。
    """
    if not detail:
        return DETAIL_NONE
    head = f"[1] {detail.get('label') or '重点明细'}（href: {detail.get('href') or ''}）"
    body = "\n".join(f"- {line}" for line in detail.get("lines") or [])
    return f"{head}\n{body}" if body else head


def build_user_prompt(
    sections: list[dict[str, Any]],
    history: list[dict[str, Any]],
    question: str,
    page: dict[str, str] | None = None,
    *,
    summary: str = "",
    memories: list[str] | None = None,
    compact: bool = False,
    detail: dict[str, Any] | None = None,
) -> str:
    """拼用户消息：档案逐段编号 + 段 href + 行，后接**重点明细**、长期记忆、线程摘要、当前页面与本次问题。

    `page` / `summary` / `memories` 都只用于**理解**，**不是**依据：三者都不进引用白名单。
    `detail` 相反 —— 它是服务端从库里重新取的一条真值，**进**白名单（由调用方合进 `sanitize_reply`）。
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
        detail=render_detail(detail),
        memories=render_memories(list(memories or [])),
        summary=flatten(summary) or SUMMARY_NONE,
        page=page_line,
        history=rendered_history,
        question=flatten(question),
        memory_task=MEMORY_TASK,
        summary_task=SUMMARY_TASK[compact],
    )


TAIFU_AGENT_SYSTEM = """你是「太傅」，逃跑计划的跃迁参谋，服务对象是想转向 AI 应用 / Agent 后端的外包工程师。

硬性规则：
1. 只能使用【档案】里出现过的内容，以及你**实际调用工具读到**的内容；没有的数字、项目、结论一律不写。
2. 不要写链接、锚点或页面路径 —— 引用由系统根据你读了什么自动附上，你写了也不会显示。
3. 信息不足时，先调工具去读，别猜。可用的工具：
   - `read_weakness_detail`：读某个薄弱分组的诊断与样例题（用户问「这一组怎么补」「为什么总错」）；
   - `read_question_detail`：读某道错题的题面 / 答案 / 解析（用户问「这题为什么错」）；
   - `read_resume_anchor`：读简历某一条的原句与前后文（用户问「这句怎么改」）；
   - `compare_reports`：对比最近两份报告（用户问「有没有进步」「比上次好在哪」）；
   - `remember`：把用户明确说过的、档案里没有的事实或偏好记成长期记忆。
4. 工具说「未读到」时，就照实说没读到，不要用相似内容替代，也不要假装读过。
5. 不需要细节就直接回答 —— 为了「更完整」而反复调工具是浪费，用户等的是结论。
6. 【当前页面】只用于理解「这里 / 这条」这类指代；不要因为用户在这一页就编造该页没有的数据。
7. 【早期对话摘要】与【长期记忆】只用来理解背景，**不是依据**；与【档案】冲突时以【档案】为准。
8. 不承诺求职结果，不把模拟测评说成工作经历，不编造项目指标。
9. 直接输出中文正文（可以分段、可以用 `-` 列表、可以用 `**加粗**`），不要输出 JSON，不要代码围栏。"""

AGENT_PROMPT_TEMPLATE = """【档案】
{materials}

【长期记忆】（用户口头说过、档案里没有的背景与偏好；不是依据）
{memories}
【早期对话摘要】{summary}
【当前页面】{page}
【页面焦点】{focus}

【最近对话】
{history}

【问题】{question}

请直接回答。需要明细时先调工具；不需要就直接给结论。"""

NO_FOCUS = "（本轮没有页面焦点：不要猜「这条 / 这题 / 这段」指的是哪一条。）"

#: 焦点 → 提示模型该调哪个工具。只给方向，不给明细 —— 明细必须经工具才算「读到」。
_FOCUS_HINTS: dict[str, str] = {
    "weakness": (
        "薄弱明细 · 报告第 {index} 组。需要细节时调 read_weakness_detail，"
        "point 传【薄弱地图】里对应的分组名。"
    ),
    "attempt": (
        "错题明细 · 题号 {question_id}。需要细节时调 read_question_detail，"
        "question_id 传这个题号。"
    ),
    "resume": (
        "简历原句「{anchor}」。需要细节时调 read_resume_anchor，anchor_text 逐字传这句话。"
    ),
}


def render_focus(focus: dict[str, Any] | None) -> str:
    """把闭集校验过的焦点渲染成一句提示；不认识的一律按「没有焦点」。"""
    if not focus:
        return NO_FOCUS
    template = _FOCUS_HINTS.get(str(focus.get("kind") or ""))
    if template is None:
        return NO_FOCUS
    try:
        return template.format(**focus)
    except (KeyError, IndexError):
        return NO_FOCUS


def build_agent_prompt(
    sections: list[dict[str, Any]],
    history: list[dict[str, Any]],
    question: str,
    page: dict[str, str] | None = None,
    *,
    summary: str = "",
    memories: list[str] | None = None,
    focus: dict[str, Any] | None = None,
) -> str:
    """r83 的首轮用户消息：与 `build_user_prompt` 同源，但**不再注入明细**。

    明细改由工具取 —— 这样「模型读到了」与「模型没读」在事件流里是可区分的，
    也是这一轮把「深读」从 if 分支换成工具调用的关键。
    也不再要求模型回写 summary / memories：前者由 finalize 的后置小调用负责，
    后者走 `remember` 工具（用户能在界面上看见它记了什么）。
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
    return AGENT_PROMPT_TEMPLATE.format(
        materials=rendered_materials,
        memories=render_memories(list(memories or [])),
        summary=flatten(summary) or SUMMARY_NONE,
        page=page_line,
        focus=render_focus(focus),
        history=rendered_history,
        question=flatten(question),
    )


class TaifuSummary(BaseModel):
    """finalize 后置调用的输出：只有摘要，不掺别的字段。"""

    summary: str = ""


SUMMARY_SYSTEM = """你在压缩一段对话的早期部分，供后续轮次当作背景。

只保留：用户已确认的身份 / 目标 / 约束，以及你已经给过的结论与建议要点。
不写链接、不写客套话、不写下一步提问。输出一个 JSON 对象：{"summary": "..."}"""

SUMMARY_PROMPT = """【已有摘要】
{summary}

【需要并入的对话】
{history}

请合并成一段不超过 {limit} 字的摘要：只保留仍然成立的内容，已有摘要里过时的说法可以丢掉。
如果这些对话没有产生值得长期保留的信息，summary 给空字符串。"""


def build_summary_prompt(existing: str, history: list[dict[str, Any]]) -> str:
    """线程摘要的独立提示词。摘要从主调用里拆出来，是因为流式正文没法再塞一个 JSON 字段。"""
    return SUMMARY_PROMPT.format(
        summary=flatten(existing) or SUMMARY_NONE,
        history="\n".join(_history_line(item) for item in history) or NO_HISTORY,
        limit=SUMMARY_MAX,
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
