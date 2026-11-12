"""r82 太傅「按需深读」：把用户点开的那一条从库里重新取一次料，投影成一段可引用的明细。

与 `brief.py` 的分工：
- `brief` 是**每轮全量重读**的摘要（2–3KB，覆盖面广、粒度粗）；
- `deep_read` 是**单条**明细（≤8 行，粒度细），只在用户从页面点过来时读一条。

三条硬规则：
1. **读不到就是 `None`**：焦点越界、题号不存在、原句不在正文里，一律当没传 —— 由调用方走原有摘要问答，
   不给用户看「读了但没读到」的假象；
2. **只投影、不改写**：题面 / 选项 / 答案 / 解析 / 正文全部原样截断，不做总结、不做二次统计；
3. **零 IO**：题库与正文由调用方传入（`load_question` / `document_text`），本模块可纯单测。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.schemas import Profile, Report

#: 明细段的行数上限：比档案段的 6 行略宽（要放题面与解析），但整体仍控制在 1.5KB 内。
MAX_DETAIL_LINES = 8
#: 单行上限：比档案段的 120 字宽 —— 题面与解析截太短就失去「读明细」的意义。
DETAIL_LINE_MAX = 160
#: 一个薄弱组最多带几道样例题：与 `WeaknessItem.samples` 的上限同源（1..3）。
MAX_SAMPLES = 3
#: 简历明细的前后文窗口：各 120 字，拆成两行，避免把 400 字窗口压成一行后只剩开头。
RESUME_CONTEXT = 120
#: 选项最多列几个：本项目的客观题最多 4 个，留 6 是防脏数据把一行撑爆。
MAX_OPTIONS = 6

KIND_WEAKNESS = "weakness"
KIND_ATTEMPT = "attempt"
KIND_RESUME = "resume"

RESULT_LABEL: dict[int, str] = {1: "答对", 0: "答错"}


def clip(text: Any, limit: int = DETAIL_LINE_MAX) -> str:
    """压平空白 + 截断，**含省略号不超过 `limit`**。

    与 `brief.clip` 的差别只在边界：那边是「截到 limit 再加…」（最长 limit+1），
    这边「单行 160」是验收项，不能因为省略号变成 161，所以预留 1 个字符给它。
    """
    flat = " ".join(str(text or "").split())
    if limit <= 0:
        return ""
    if len(flat) <= limit:
        return flat
    return flat[: max(1, limit - 1)].rstrip() + "…"


def _fit(prefix: str, text: Any, suffix: str = "") -> str:
    """按**整行**预算截断：`前缀 + 内容 + 后缀` 不超过 `DETAIL_LINE_MAX`。

    不能只截内容再拼后缀 —— 那样「题面 160 字 + · 你的结果：答错」会顶到 170，
    所谓「单行 160」就成了假约束。
    """
    budget = max(1, DETAIL_LINE_MAX - len(prefix) - len(suffix))
    return f"{prefix}{clip(text, budget)}{suffix}"



def _option_line(options: Any) -> str:
    """选项压成一行：`A. xxx · B. yyy`。兼容 `[{"key","text"}]` 与纯字符串两种脏数据。"""
    if not isinstance(options, list):
        return ""
    parts: list[str] = []
    for item in options[:MAX_OPTIONS]:
        if isinstance(item, dict):
            key = clip(item.get("key"), 8)
            text = clip(item.get("text"), 40)
            parts.append(f"{key}. {text}" if key else text)
        else:
            parts.append(clip(item, 40))
    kept = [part for part in parts if part]
    return "选项：" + " · ".join(kept) if kept else ""


def _answer_text(question: dict[str, Any]) -> str:
    """正确答案：`["B"]` → `B`；多选按顿号并列；text 型（空数组）给空串。"""
    answer = question.get("answer")
    if not isinstance(answer, list):
        return ""
    keys = [clip(item, 12) for item in answer if clip(item, 12)]
    return "、".join(keys)


def _latest_attempts(attempts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """题目 id → 最近一次作答（`list_attempts()` 是升序，后写覆盖前写）。"""
    latest: dict[str, dict[str, Any]] = {}
    for row in attempts:
        question_id = str(row.get("question_id") or "")
        if question_id:
            latest[question_id] = row
    return latest


def _result_label(attempt: dict[str, Any] | None) -> str:
    """作答结果文案：没作答就是「未作答」，不猜「大概没做过」。"""
    if attempt is None:
        return "未作答"
    return RESULT_LABEL.get(int(attempt.get("correct") or 0), "答错")


def _question_body(question: dict[str, Any], attempt: dict[str, Any] | None) -> list[str]:
    """一道题的明细行：题面 + 结果 / 选项 / 答案 / 解析（空字段整行省略，不留空标签）。"""
    lines = [_fit("题面：", question.get("prompt"), f" · 你的结果：{_result_label(attempt)}")]
    option_line = _option_line(question.get("options"))
    if option_line:
        lines.append(clip(option_line, DETAIL_LINE_MAX))
    answer = _answer_text(question)
    head = f"正确答案：{answer}" if answer else "正确答案：见解析"
    if attempt is not None:
        head += f" · 作答时间：{clip(attempt.get('answered_at'))[:10]}"
    lines.append(clip(head, DETAIL_LINE_MAX))
    explanation = clip(question.get("explanation"), DETAIL_LINE_MAX)
    if explanation:
        lines.append(_fit("解析：", explanation))
    return lines


def _weakness_detail(
    index: int,
    *,
    report: Report | None,
    attempts: dict[str, dict[str, Any]],
    load_question: Callable[[str], dict[str, Any] | None],
) -> dict[str, Any] | None:
    """薄弱组明细：分组信息 + 组内样例题的题面 / 答案 / 解析。

    样例题只取 `MAX_SAMPLES` 道：这一段的用途是「让我看懂我到底错在哪」，
    不是把整组题搬进提示词。
    """
    if report is None or not isinstance(report.weakness_map, list):
        return None
    items = report.weakness_map
    if index < 1 or index > len(items):
        return None
    item = items[index - 1]
    samples = list(item.samples or [])[:MAX_SAMPLES]
    if not samples:
        return None

    difficulty = "/".join(item.difficulty) or "未标难度"
    lines = [
        clip(
            f"分组：{clip(item.point)} · {difficulty} · 错误率 {round(item.rate * 100)}%"
            f"（{item.wrong}/{item.total}）",
            DETAIL_LINE_MAX,
        )
    ]
    if item.summary:
        lines.append(_fit("诊断：", item.summary))
    for sample in samples:
        question = load_question(sample.question_id)
        if question is None:
            # 题目被题库刷新删掉时不编造：只保留报告里的原始证据。
            lines.append(
                clip(
                    f"题面：题目 {clip(sample.question_id, 32)} 已不在题库 · {clip(sample.evidence, 40)}",
                    DETAIL_LINE_MAX,
                )
            )
            continue
        lines.extend(_question_body(question, attempts.get(sample.question_id)))

    return {
        "key": "detail",
        "kind": KIND_WEAKNESS,
        "label": clip(f"薄弱明细 · {item.point} · {difficulty}", 40),
        "href": f"/report#weakness-{index}",
        "lines": lines[:MAX_DETAIL_LINES],
        "anchors": [],
    }


def _attempt_detail(
    question_id: str,
    *,
    attempts: dict[str, dict[str, Any]],
    load_question: Callable[[str], dict[str, Any] | None],
) -> dict[str, Any] | None:
    """错题明细：题目 + 你的作答结果 + 解析。

    要求**本账号有该题的作答记录**：错题本里的题必然做过，没有记录的题号不是「错题」，
    不借此把任意题库条目当作「你错了的题」讲给用户。
    """
    attempt = attempts.get(question_id)
    if attempt is None:
        return None
    question = load_question(question_id)
    if question is None:
        return None
    lines = _question_body(question, attempt)
    return {
        "key": "detail",
        "kind": KIND_ATTEMPT,
        "label": clip(f"错题明细 · {question.get('prompt')}", 40),
        "href": "/practice",
        "lines": lines[:MAX_DETAIL_LINES],
        "anchors": [],
    }


def _resume_detail(
    anchor: str,
    *,
    profile: Profile | None,
    report: Report | None,
    document_text: str | None,
) -> dict[str, Any] | None:
    """简历明细：那一条的原句 + 位置 + 前后文窗口。

    原句必须能在正文里**逐字**找到（与 `ResumePointer.focus_key` 同一口径）；
    找不到说明正文已换代或前端传错了，宁可当没传，也不能拿相似句硬凑。
    """
    if profile is None or not document_text or not anchor:
        return None
    position = document_text.find(anchor)
    if position < 0:
        return None

    location = ""
    issue = ""
    for pointer in (report.resume_pointers if report is not None else None) or []:
        if pointer.anchor_text == anchor:
            location = pointer.location
            issue = pointer.issue
            break

    lines = []
    if location:
        lines.append(_fit("位置：", location))
    if issue:
        lines.append(_fit("报告指出的问题：", issue))
    lines.append(_fit("原句：", anchor))

    before = clip(document_text[max(0, position - RESUME_CONTEXT) : position])
    after_start = position + len(anchor)
    after = clip(document_text[after_start : after_start + RESUME_CONTEXT])
    if before:
        lines.append(_fit("前文：", before))
    if after:
        lines.append(_fit("后文：", after))

    return {
        "key": "detail",
        "kind": KIND_RESUME,
        "label": clip(f"简历明细 · {location or anchor}", 40),
        "href": "/polish",
        "lines": lines[:MAX_DETAIL_LINES],
        "anchors": [],
    }


def build_detail(
    focus: dict[str, Any] | None,
    *,
    profile: Profile | None,
    report: Report | None,
    attempts: list[dict[str, Any]],
    document_text: str | None,
    load_question: Callable[[str], dict[str, Any] | None],
) -> dict[str, Any] | None:
    """按焦点取一条明细；任何一步不成立都返回 `None`（调用方据此走原有摘要问答）。

    `focus` 必须已经过 `policy.sanitize_focus()`：本函数只做「数据在不在」的校验，
    不重复做字段闭集判断（那层在上游，且有单测钉住）。
    """
    if not focus:
        return None
    latest = _latest_attempts(attempts)
    kind = str(focus.get("kind") or "")
    if kind == KIND_WEAKNESS:
        return _weakness_detail(
            int(focus.get("index") or 0),
            report=report,
            attempts=latest,
            load_question=load_question,
        )
    if kind == KIND_ATTEMPT:
        return _attempt_detail(
            str(focus.get("question_id") or ""),
            attempts=latest,
            load_question=load_question,
        )
    if kind == KIND_RESUME:
        return _resume_detail(
            str(focus.get("anchor") or ""),
            profile=profile,
            report=report,
            document_text=document_text,
        )
    return None


def to_ref(detail: dict[str, Any] | None) -> dict[str, str] | None:
    """明细 → 响应里的 `detail`（界面显示「已读取：…」）；没读到就是 `None`。"""
    if not detail:
        return None
    return {
        "kind": str(detail.get("kind") or ""),
        "label": str(detail.get("label") or ""),
        "href": str(detail.get("href") or ""),
    }
