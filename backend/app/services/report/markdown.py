"""`Report` → Markdown 纯函数（r1 AC-9 / r7 AC-12）：页面预览、复制与 `.md` 导出同源。

只有这一个渲染源：前端只展示后端返回的文本，不二次拼串，因此「分数不带多余的 `.0`、
非整数保留 1 位小数」的展示口径在这里一次定死（与 `frontend/src/lib/format.ts` 同规则）。

r7 起在既有「短板总览表 + 每条短板块」**之后**追加三块（薄弱地图 / 简历要点 / 竞争力对标），
顺序与 `Report` 字段一致：`weakness_map` → `resume_pointers` → `role_fit`。
`None`（旧报告，字段从未落库）与 `[]`（新报告但本块无内容）在文本上是**两套不同文案**，
全部取自 `services/coach_copy.py`（与前端 `lib/coach.ts` 是同一批字，禁止在这里另写中文）。
"""

from __future__ import annotations

from urllib.parse import quote

from app.schemas import Course, Report, ResumePointer, RoleFit, Shortfall
from app.services.resume import coach_copy

SEVERITY_LABEL: dict[str, str] = {"high": "高", "medium": "中", "low": "低"}

#: 简历要点跳转的前端路由：只带 `focus` / `section` / `anchor` 三个短参数（AC-5）。
POLISH_PATH = "/polish"

#: 与前端 `coach.ANCHOR_MAX_CHARS` 同值：超长原句只带 `focus`（逐字键）不带 `anchor`，
#: 保持与 `polishHref` 逐字同形，也避免把整段正文塞进 URL。
ANCHOR_MAX_CHARS = 40

#: 表格里表示「没有标签」的占位符，与 `format_score(None)` 同一枚字符。
EMPTY_CELL = "—"


def format_score(value: float | None) -> str:
    """分数展示口径：整数不带 `.0`（`2.0` → `2`），否则保留 1 位小数（`6.75` → `6.8`）。"""
    if value is None:
        return "—"
    rounded = round(float(value), 1)
    return str(int(rounded)) if rounded == int(rounded) else f"{rounded:.1f}"


def format_percent(rate: float) -> str:
    """错误率展示：整数百分比，与前端 `weaknessRateLabel`（`Math.round(rate * 100)`）同口径。

    用 `int(x + 0.5)` 而不是内置 `round()`：Python 的 `round` 是银行家舍入
    （`round(62.5) == 62`），与 JS 的 `Math.round`（→ 63）不一致，会出现
    「页面 63% / `.md` 62%」的同源漂移——正是反面目标 2（与页面口径对不上）要防的。
    """
    return f"{int(float(rate) * 100 + 0.5)}%"


def to_markdown(report: Report) -> str:
    """把报告渲染成 Markdown：概览表 + 每条短板 + r7 三块（薄弱地图/简历要点/竞争力对标）。"""
    lines: list[str] = [
        "# 能力诊断报告",
        "",
        f"- 报告编号：`{report.id}`",
        f"- 生成时间：{report.generated_at}",
        f"- 面试均分：{format_score(report.interview_avg)}/10",
        f"- 笔试总分：{format_score(report.exam_total)}/100",
        f"- 关联测评：{'、'.join(report.run_ids) if report.run_ids else EMPTY_CELL}",
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

    lines.extend(_weakness_block(report))
    lines.extend(_resume_block(report))
    lines.extend(_role_block(report))

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


# --- r7 三块：薄弱地图 / 简历要点 / 竞争力对标（AC-12：顺序固定、条数与字段一致）------


def _weakness_block(report: Report) -> list[str]:
    """知识薄弱地图：`None` → 旧报告提示；`[]` → 中文空态；非空 → 表格 + 逐条摘要。"""
    lines: list[str] = ["", "## 知识薄弱地图", ""]
    items = report.weakness_map
    if items is None:
        lines.append(f"> {coach_copy.LEGACY_BLOCK_NOTICE}")
        return lines
    if not items:
        lines.append(f"> {coach_copy.WEAKNESS_EMPTY}")
        return lines

    lines.append("| # | 薄弱点 | 难度 | 必备级别 | 错/共 | 错误率 | 证据 |")
    lines.append("|---|---|---|---|---|---|---|")
    for order, item in enumerate(items, start=1):
        evidence = "；".join(sample.evidence for sample in item.samples) or EMPTY_CELL
        cells = (
            str(order),
            _cell(item.point),
            _labels(item.difficulty, coach_copy.DIFFICULTY_LABEL),
            _labels(item.essentiality, coach_copy.ESSENTIALITY_LABEL),
            f"{item.wrong}/{item.total}",
            format_percent(item.rate),
            _cell(evidence),
        )
        lines.append("| " + " | ".join(cells) + " |")

    # 摘要（AI 只补这一句）单独成行：表格里塞长文本会撑坏列宽，而摘要必须与页面同源可见。
    lines.append("")
    for order, item in enumerate(items, start=1):
        lines.append(
            f"- **{order}. {item.point}**：{_one_line(item.summary)}"
            f"（组内均分 {format_score(item.avg)}/10）"
        )
    return lines


def _resume_block(report: Report) -> list[str]:
    """简历改进要点：`None` → 旧报告提示；`[]` → 服务端降级原因；非空 → 逐条 + `/polish` 跳转。"""
    lines: list[str] = ["", "## 简历改进要点", ""]
    pointers = report.resume_pointers
    if pointers is None:
        lines.append(f"> {coach_copy.LEGACY_BLOCK_NOTICE}")
        return lines
    if not pointers:
        lines.append(f"> {report.resume_pointers_notice or coach_copy.RESUME_AI_FALLBACK}")
        return lines

    for order, pointer in enumerate(pointers, start=1):
        section = coach_copy.SECTION_LABEL.get(pointer.section, pointer.section)
        location = _one_line(pointer.location).strip() or section
        lines.append(f"{order}. **{location}**")
        lines.append(f"   - 原句：「{_one_line(pointer.anchor_text)}」")
        lines.append(f"   - 问题：{_one_line(pointer.issue)}")
        lines.append(f"   - 定位：[去润色页定位]({_polish_href(pointer)})")
    return lines


def _role_block(report: Report) -> list[str]:
    """市场竞争力对标：`None` → 旧报告提示；无模型 → 两句降级文案；有模型 → 差距表 + 清单。"""
    lines: list[str] = ["", "## 市场竞争力对标", ""]
    role = report.role_fit
    if role is None:
        lines.append(f"> {coach_copy.LEGACY_BLOCK_NOTICE}")
        return lines

    if role.target_role:
        lines.append(f"- 目标岗位：{role.target_role}{_source_suffix(role)}")

    if role.model is None:
        notices = [coach_copy.ROLE_NO_MODEL, coach_copy.ROLE_NO_MODEL_HINT]
        extra = _one_line(role.notice or "").strip()
        if extra and extra not in notices:
            notices.insert(0, extra)
        if lines[-1]:
            # 引用块紧贴上一行列表项会被解析成列表续行：留一行空行，让降级提示自成一段。
            lines.append("")
        lines.extend(f"> {notice}" for notice in notices)
        return lines

    lines.append(f"- 匹配模型：{_one_line(role.model.label)}")
    if role.items:
        lines.extend(["", "| 能力项 | 要求 | 当前 | 差距 |", "|---|---|---|---|"])
        for item in role.items:
            must = "（必备）" if item.must else ""
            cells = (_cell(f"{item.name}{must}"), str(item.required), str(item.user_level))
            lines.append("| " + " | ".join(cells) + f" | {_gap_label(item.gap)} |")

    lines.append("")
    missing = "、".join(role.missing_must) if role.missing_must else "暂无"
    lines.append(f"- 缺失必备技能：{missing}")
    if role.first_fix:
        lines.append("- 先后补什么：")
        lines.extend(
            f"  {order}. {name}" for order, name in enumerate(role.first_fix, start=1)
        )
    else:
        lines.append("- 先后补什么：暂无需补的必备技能")
    if role.conclusion:
        lines.append(f"- 结论：{_one_line(role.conclusion)}")
    return lines


def _source_suffix(role: RoleFit) -> str:
    """目标岗位来源后缀：与页面同一批标签（AC-9 要求两处都显示来源）。"""
    label = role.role_source_label or coach_copy.ROLE_SOURCE_LABEL.get(role.role_source or "", "")
    return f"（来源：{label}）" if label else ""


def _polish_href(pointer: ResumePointer) -> str:
    """`/polish?focus=&section=&anchor=` —— 参数名/顺序/编码与前端 `polishHref` 逐字一致（AC-5）。"""
    params = [("focus", pointer.focus_key), ("section", pointer.section)]
    if 0 < len(pointer.anchor_text) <= ANCHOR_MAX_CHARS:
        params.append(("anchor", pointer.anchor_text))
    query = "&".join(f"{key}={_uri_component(value)}" for key, value in params)
    return f"{POLISH_PATH}?{query}"


def _uri_component(text: str) -> str:
    """`encodeURIComponent` 的 Python 等价：空格编成 `%20`（不是 `+`），保留 `!'()*-._~`。"""
    return quote(text, safe="!'()*-._~")


def _gap_label(gap: int) -> str:
    """差距列：`0` 写「达标」而不是 `0`（与前端 `roleGapLabel` 一字不差，AC-8/AC-20）。"""
    return "达标" if gap <= 0 else str(gap)


def _labels(values: list[str], label_map: dict[str, str]) -> str:
    """闭集标签 join：未知值原样透出（不吞数据、不编中文），空列表占位 `—`。"""
    if not values:
        return EMPTY_CELL
    return "、".join(label_map.get(value, value) for value in values)


def _one_line(text: str) -> str:
    """压平换行：摘要 / 原句 / 结论都是单行槽位，正文里的 `\\n` 会拆坏列表缩进。"""
    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def _cell(text: str) -> str:
    """表格单元格：先压平换行，再转义竖线，避免一条证据把整张表拆成两半。"""
    return _one_line(text).replace("|", "\\|")
