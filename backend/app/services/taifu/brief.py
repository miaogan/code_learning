"""r77 太傅档案摘要：把服务端真值投影成「段 + 行」，**段的 href 即引用白名单**。

为什么是服务端拼而不是前端传（与 r65 教练相反）：教练的材料是前端才有的教程语料；
太傅要读的是画像 / 报告 / 测评 / 练习 / 学习，这些都在服务端库里 —— 让客户端上传等于
把「我能引用什么」的决定权交给客户端，引用白名单就失去意义。

三条硬规则：
1. **没有数据的段不出现**：白名单只允许引用真实存在的页面，不出现「引用一个空报告」；
2. **不二次统计**：分数取 `history.score_of`、错误率取报告里已算好的 `rate`，本模块只做投影；
3. **行数有上限**：单段最多 6 行、每行 120 字，摘要整体控制在 2–3KB，避免烧上下文。
"""

from __future__ import annotations

from typing import Any

from app.schemas import Profile, Report
from app.services.interview.history import score_of

#: 各维度的投影上限：够模型判断「强/弱/有没有」，又不会把整份档案塞进提示词。
MAX_TECH = 8
MAX_SKILLS = 6
MAX_PROJECTS = 3
MAX_WEAK = 5
MAX_RUNS = 5
LINE_MAX = 120
#: 锚点标签长度：引用 chip 只有一行位置，太长会把「依据」行挤成两行。
ANCHOR_LABEL_MAX = 40
SECTION_LINE_LIMIT = 6

KIND_LABEL: dict[str, str] = {"exam": "笔试", "interview": "面试"}
SCORE_UNIT: dict[str, str] = {"exam": "/100", "interview": "/10"}


def clip(text: Any, limit: int = LINE_MAX) -> str:
    """压平空白 + 截断：摘要行必须是单行，否则提示词里的编号结构会被换行打散。"""
    flat = " ".join(str(text or "").split())
    if limit <= 0:
        return ""
    return flat if len(flat) <= limit else flat[:limit].rstrip() + "…"


def _section(
    key: str,
    label: str,
    href: str,
    lines: list[str],
    anchors: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """组装一段：丢掉空行，截到段上限。

    `anchors` 是「段内更细的出处」（当前只有薄弱分组的 `#weakness-N`）：
    它们是**额外**的合法引用目标，段本身的 href 仍然有效。
    """
    kept = [line for line in lines if line]
    return {
        "key": key,
        "label": label,
        "href": href,
        "lines": kept[:SECTION_LINE_LIMIT],
        "anchors": list(anchors or []),
    }


def _profile_lines(profile: Profile) -> list[str]:
    lines: list[str] = []
    lines.append(f"目标岗位：{clip(profile.target_role) if profile.target_role else '画像里未填写'}")
    if profile.years_experience:
        lines.append(f"经验年限：{profile.years_experience:g} 年")
    if profile.tech_stack:
        lines.append(f"技术栈：{clip('、'.join(profile.tech_stack[:MAX_TECH]))}")
    skills = [skill.name for skill in profile.skills if skill.status != "historical"]
    if skills:
        head = f"能力项：{len(skills)} 项"
        lines.append(f"{head}（{clip('、'.join(skills[:MAX_SKILLS]))}）")
    for project in profile.projects[:MAX_PROJECTS]:
        role = f" · {clip(project.role)}" if project.role else ""
        lines.append(f"项目：{clip(project.name)}{role} · {len(project.bullets)} 条要点")
    return lines


def _weakness_anchors(report: Report) -> list[dict[str, str]]:
    """薄弱分组的锚点白名单（`/report#weakness-N`，N 与报告页表格行号一致）。

    只取前 `MAX_WEAK` 组：摘要里没写出来的分组，模型也不该引用。
    """
    anchors: list[dict[str, str]] = []
    for index, item in enumerate((report.weakness_map or [])[:MAX_WEAK], start=1):
        anchors.append(
            {
                "href": f"/report#weakness-{index}",
                "label": f"最近诊断 · {clip(item.point, ANCHOR_LABEL_MAX)}",
            }
        )
    return anchors


def _report_lines(report: Report) -> list[str]:
    lines = [f"生成时间：{clip(report.generated_at)[:10]}"]
    scores: list[str] = []
    if report.interview_avg is not None:
        scores.append(f"面试均分 {report.interview_avg}/10")
    if report.exam_total is not None:
        scores.append(f"笔试总分 {report.exam_total}/100")
    if scores:
        lines.append("本次计分：" + " · ".join(scores))
    role_fit = report.role_fit
    if role_fit is not None and role_fit.target_role:
        target = f"岗位对标：{clip(role_fit.target_role)}"
        if role_fit.first_fix:
            target += f" → 先补 {clip('、'.join(role_fit.first_fix[:3]))}"
        lines.append(target)
    weak_items = report.weakness_map or []
    for index, item in enumerate(weak_items[:MAX_WEAK], start=1):
        difficulty = "/".join(item.difficulty) or "未标难度"
        percent = round(item.rate * 100)
        # 行内直接给锚点：模型要把「这条」指回报告里具体哪一行，靠的就是它。
        lines.append(
            f"薄弱：{clip(item.point)} · {difficulty} · 错误率 {percent}%"
            f"（{item.wrong}/{item.total}）→ /report#weakness-{index}"
        )
    if not weak_items:
        lines.append("薄弱分组：本次报告没有已计分的客观题")
    return lines


def _run_lines(runs: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for run in runs[:MAX_RUNS]:
        kind = str(run.get("kind") or "")
        label = KIND_LABEL.get(kind, kind or "测评")
        score = score_of(kind, run.get("payload") or {})
        unit = SCORE_UNIT.get(kind, "")
        value = "未计分" if score is None else f"{score}{unit}"
        lines.append(f"{clip(run.get('created_at'))[:10]} {label}：{value}")
    return lines


def _practice_lines(attempts: list[dict[str, Any]]) -> list[str]:
    total = len(attempts)
    if total == 0:
        return []
    correct = sum(1 for item in attempts if int(item.get("correct") or 0) == 1)
    distinct = len({str(item.get("question_id") or "") for item in attempts})
    last = clip(attempts[-1].get("answered_at"))[:10]
    return [
        f"已练题数：{distinct} 题",
        f"作答次数：{total} 次（最近一次 {last}）",
        f"正确率：{round(correct / total * 100)}%（{correct}/{total}）",
    ]


def _learn_lines(learn: dict[str, Any]) -> list[str]:
    chapters = learn.get("chapters") or {}
    read = {
        str(chapter_id): len(info.get("seen") or [])
        for chapter_id, info in chapters.items()
        if isinstance(info, dict) and info.get("seen")
    }
    if not read:
        return []
    lines = [f"已读章节：{len(read)} 章，共 {sum(read.values())} 个小节"]
    last = learn.get("last_chapter_id")
    if last:
        lines.append(f"上次读到：{clip(last)}")
    return lines


def build_sections(
    *,
    profile: Profile | None,
    report: Report | None,
    runs: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    learn: dict[str, Any],
) -> list[dict[str, Any]]:
    """组装档案段。**空档案返回 `[]`** —— 调用方据此短路（不调模型、不落库）。"""
    sections: list[dict[str, Any]] = []
    if profile is not None:
        sections.append(_section("profile", "目标与画像", "/profile", _profile_lines(profile)))
    if report is not None:
        sections.append(
            _section(
                "report",
                "最近诊断",
                "/report",
                _report_lines(report),
                _weakness_anchors(report),
            )
        )
    run_lines = _run_lines(runs)
    if run_lines:
        sections.append(_section("history", "测评记录", "/history", run_lines))
    practice_lines = _practice_lines(attempts)
    if practice_lines:
        sections.append(_section("practice", "练习记录", "/practice", practice_lines))
    learn_lines = _learn_lines(learn)
    if learn_lines:
        sections.append(_section("learn", "学习进度", "/learn", learn_lines))
    # 只有标题、没有事实的段没有意义：统一丢掉，避免白名单里出现空页面引用。
    return [section for section in sections if section["lines"]]
