"""`Report` → Markdown 纯函数（AC-9）：页面预览与 `.md` 导出同源。

只有这一个渲染源：前端只展示后端返回的文本，不二次拼串，因此「分数不带多余的 `.0`、
非整数保留 1 位小数」的展示口径在这里一次定死（与 `frontend/src/lib/format.ts` 同规则）。
"""

from ..schemas import Course, Report, Shortfall

SEVERITY_LABEL: dict[str, str] = {"high": "高", "medium": "中", "low": "低"}


def format_score(value: float | None) -> str:
    """分数展示口径：整数不带 `.0`（`2.0` → `2`），否则保留 1 位小数（`6.75` → `6.8`）。"""
    if value is None:
        return "—"
    rounded = round(float(value), 1)
    return str(int(rounded)) if rounded == int(rounded) else f"{rounded:.1f}"


def to_markdown(report: Report) -> str:
    """把报告渲染成 Markdown：概览表 + 每条短板的诊断/动作/证据/课程。"""
    lines: list[str] = [
        "# 能力诊断报告",
        "",
        f"- 报告编号：`{report.id}`",
        f"- 生成时间：{report.generated_at}",
        f"- 面试均分：{format_score(report.interview_avg)}/10",
        f"- 笔试总分：{format_score(report.exam_total)}/100",
        f"- 关联测评：{'、'.join(report.run_ids) if report.run_ids else '—'}",
        "",
        "## 短板总览",
        "",
        "| # | 短板 | 严重度 | 证据 |",
        "|---|---|---|---|",
    ]
    for order, item in enumerate(report.shortfalls, start=1):
        label = SEVERITY_LABEL.get(item.severity, item.severity)
        lines.append(f"| {order} | {item.name} | {label} | {item.evidence} |")

    for order, item in enumerate(report.shortfalls, start=1):
        lines.append("")
        lines.extend(_shortfall_block(item, order))

    return "\n".join(lines).rstrip() + "\n"


def _shortfall_block(item: Shortfall, order: int) -> list[str]:
    label = SEVERITY_LABEL.get(item.severity, item.severity)
    evidence = item.evidence
    if item.question_ref:
        evidence = f"{evidence}（题目 {item.question_ref}）"
    lines: list[str] = [
        f"## {order}. {item.name}（严重度：{label}）",
        "",
        f"- 证据：{evidence}",
        f"- 诊断：{item.diagnosis}",
        "- 建议动作：",
    ]
    lines.extend([f"  {index}. {action}" for index, action in enumerate(item.actions, start=1)])
    if not item.actions:
        lines.append("  1. 暂无")
    lines.append("- 推荐课程：")
    lines.extend([f"  - {_course_line(course)}" for course in item.courses])
    if not item.courses:
        lines.append("  - 暂无课程")
    return lines


def _course_line(course: Course) -> str:
    head = f"{course.title}（{course.level}）"
    if course.url:
        return f"[{head}]({course.url}) — {course.why}"
    return f"{head} — {course.why}（暂无官方链接，暂不可点）"
