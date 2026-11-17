"""JD 岗位对位（r110）：把一段招聘文本对照画像证据，产出可追溯的缺口清单。

三条硬边界：

- **零 AI / 零新表**：只用内置岗位模型、画像证据与 JD 文本；不调模型、不写库；
- **不产出能力分**：没有「匹配度 87%」这类数字。`missing` 只表示「这段 JD 里出现的
  技术词，在画像里没找到可复算的证据」，不能推出能力不足，也不能把模拟经历写成生产经验；
- **诉求与事实分开**：JD 直接写到的词标 `origin=jd`；目标岗位模型要求但 JD 未提到的
  标 `origin=role_model`，两者绝不混成一句「JD 要求」。

匹配是确定性关键词层：别名表只做召回，命中位置与画像证据都在响应里回传供用户复核。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from app.core import repository
from app.core.errors import VALIDATION_ERROR, AppError
from app.schemas import (
    JdGapItem,
    JdInterviewPreset,
    JdKeywordItem,
    JdMatchRequest,
    JdMatchResult,
    Profile,
)
from app.services.report import role_fit as role_fit_service, rules

#: 响应规模上限：避免长 JD 把看板刷成一面墙；顺序按 JD 里出现的位置（先到先得）。
MAX_KEYWORDS = 24
MAX_GAPS = 12
MAX_EVIDENCE_PER_KEYWORD = 3
MAX_SOURCE_QUOTE = 90

# 岗位名识别：内置模型名先按包含命中；这里只收常见简称，避免「工程师」三字乱命中。
_ROLE_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("后端开发", "后端工程师", "服务端开发", "后端"), "后端工程师"),
    (("前端开发", "前端工程师", "web前端", "前端"), "前端工程师"),
    (("算法工程师", "算法开发", "机器学习算法"), "算法工程师"),
    (("ai工程师", "大模型应用", "大模型开发", "llm应用"), "AI 工程师"),
    (("数据库工程师", "dba", "数据库开发"), "数据库工程师"),
    (("运维工程师", "sre", "devops", "中间件运维"), "中间件与运维工程师"),
    (("研发效能", "工程效能", "平台工程"), "研发效能工程师"),
    (("通用软件工程师", "软件开发工程师"), "通用软件工程师"),
)

# 别名提示里的方向/子方向必须落在 rules 闭集内（启动时自检一次，写错就早失败）。
_SUB_HINTS: tuple[tuple[str, str, str], ...] = (
    ("react", "前端", "react"),
    ("vue", "前端", "vue3"),
    ("typescript", "前端", "ts"),
    ("javascript", "前端", "js"),
    ("css", "前端", "css"),
    ("html", "前端", "html"),
    ("python", "后端", "python"),
    ("java", "后端", "java"),
    ("go语言", "后端", "go"),
    ("redis", "中间件与运维", "Redis"),
    ("docker", "中间件与运维", "Docker 与容器"),
    ("kubernetes", "中间件与运维", "Docker 与容器"),
    ("k8s", "中间件与运维", "Docker 与容器"),
    ("nginx", "中间件与运维", "Nginx"),
    ("消息队列", "中间件与运维", "消息队列"),
    ("kafka", "中间件与运维", "消息队列"),
    ("rabbitmq", "中间件与运维", "消息队列"),
    ("ci/cd", "研发工程实践", "CI-CD"),
    ("ci流水线", "研发工程实践", "CI-CD"),
    ("监控", "中间件与运维", "监控与日志"),
    ("可观测", "中间件与运维", "监控与日志"),
    ("mysql", "SQL 与数据库", "SQL 基础"),
    ("postgresql", "SQL 与数据库", "SQL 基础"),
    ("postgres", "SQL 与数据库", "SQL 基础"),
    ("sql", "SQL 与数据库", "SQL 基础"),
    ("索引", "SQL 与数据库", "索引"),
    ("事务", "SQL 与数据库", "事务与 ACID"),
    ("rag", "AI 工程", "LLM 与 RAG"),
    ("llm", "AI 工程", "LLM 与 RAG"),
    ("大模型", "AI 工程", "LLM 与 RAG"),
    ("agent", "AI 工程", "Agent"),
    ("prompt", "AI 工程", "Prompt 工程"),
    ("embedding", "AI 工程", "LLM 与 RAG"),
    ("向量", "AI 工程", "LLM 与 RAG"),
    ("git", "研发工程实践", "Git 与版本控制"),
    ("测试", "研发工程实践", "测试"),
    ("pytest", "研发工程实践", "测试"),
    ("vitest", "研发工程实践", "测试"),
    ("架构设计", "研发工程实践", "架构设计"),
    ("系统设计", "研发工程实践", "架构设计"),
    ("动态规划", "算法与数据结构", "动态规划"),
    ("二叉树", "算法与数据结构", "二叉树与递归"),
    ("链表", "算法与数据结构", "链表"),
    ("排序", "算法与数据结构", "排序"),
    ("图算法", "算法与数据结构", "图"),
    ("复杂度", "算法与数据结构", "复杂度"),
    ("哈希", "算法与数据结构", "哈希"),
    ("操作系统", "计算机基础", "操作系统"),
    ("计算机网络", "计算机基础", "网络"),
    ("网络基础", "计算机基础", "网络"),
)

# 常见缩写：内置模型里的正式名较长，招聘文本往往只写简称。
_ALIAS_OVERRIDES: dict[str, tuple[str, ...]] = {
    "React": ("react",),
    "JavaScript": ("javascript", "js"),
    "TypeScript": ("typescript", "ts"),
    "HTML/CSS": ("html", "css"),
    "CSS 布局": ("css",),
    "Python": ("python",),
    "Python 后端服务": ("python",),
    "Python 数据处理": ("python",),
    "SQL": ("sql",),
    "SQL 基础": ("sql",),
    "复杂 SQL": ("sql",),
    "SQL 调优": ("sql",),
    "MySQL/PostgreSQL": ("mysql", "postgresql", "postgres"),
    "PostgreSQL 运维": ("postgresql", "postgres"),
    "Redis 缓存": ("redis",),
    "Redis 与缓存": ("redis",),
    "Docker 基础": ("docker",),
    "Docker 与容器编排": ("docker",),
    "Kubernetes 运维": ("kubernetes", "k8s"),
    "Kubernetes 架构": ("kubernetes", "k8s"),
    "Nginx 反向代理": ("nginx",),
    "消息队列": ("kafka", "rabbitmq", "消息队列"),
    "CI 基础": ("ci/cd", "ci流水线"),
    "CI 流水线": ("ci/cd", "ci流水线"),
    "CI/CD 流水线": ("ci/cd", "ci流水线"),
    "Git 基础": ("git",),
    "Git 与工程化": ("git",),
    "Git": ("git",),
    "HTTP": ("http",),
    "HTTP 与 REST": ("http", "rest"),
    "LLM 应用开发": ("llm", "大模型"),
    "RAG 检索增强": ("rag",),
    "RAG 架构": ("rag",),
    "Prompt 工程": ("prompt",),
    "Agent 设计": ("agent",),
    "Agent 编排与可靠性": ("agent",),
    "单元测试基础": ("pytest", "单元测试"),
    "自动化测试": ("自动化测试", "pytest", "vitest"),
    "可观测性体系": ("可观测", "监控"),
    "监控告警入门": ("监控",),
    "事务基础": ("事务",),
    "事务与锁": ("事务", "锁"),
}


def _compact(value: str) -> str:
    return "".join(value.split()).lower()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _aliases_of(name: str) -> tuple[str, ...]:
    candidates = {name, _compact(name)}
    candidates.update(_ALIAS_OVERRIDES.get(name, ()))
    normalized = _compact(name).replace("/", "").replace("与", "").replace("和", "")
    if normalized:
        candidates.add(normalized)
    return tuple(sorted((item.strip().lower() for item in candidates if item.strip()), key=len, reverse=True))


def _alias_pattern(alias: str) -> str:
    """短 ASCII 别名加单词边界：避免 `go` 命中 `golang`、`js` 命中 `json`。"""
    escaped = re.escape(alias)
    if alias.isascii() and alias.replace(".", "").isalnum() and len(alias) <= 4:
        return rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"
    return escaped


def term_in_text(text: str, term: str) -> bool:
    """r111 复用同一套别名与词边界做「回答里是否提到这个缺口词」对照。

    这是关键词命中，不是语义理解或能力判定；调用方必须在 UI 上写明这一点。
    """
    cleaned = term.strip()
    if not cleaned:
        return False
    return any(
        re.search(_alias_pattern(alias), text, flags=re.IGNORECASE) is not None
        for alias in _aliases_of(cleaned)
    )


def _all_terms() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """岗位模型里的全部能力名 + 它们的别名（只读内存表，进程内可重复调用）。"""
    terms: dict[str, tuple[str, ...]] = {}
    for levels in role_fit_service.load_role_models().values():
        for level in levels:
            for skill in level.skills:
                terms.setdefault(skill.name, _aliases_of(skill.name))
    return tuple(terms.items())


def _snippet(text: str, start: int, end: int) -> str:
    left = max(0, start - 28)
    right = min(len(text), end + 52)
    piece = text[left:right].strip()
    return f"{'…' if left > 0 else ''}{piece}{'…' if right < len(text) else ''}"


def _skill_hits(name: str, aliases: tuple[str, ...], skill_name: str) -> bool:
    haystack = _compact(skill_name)
    candidate = _compact(name)
    return any(alias in haystack or haystack in alias for alias in (*aliases, candidate) if alias)


def _profile_evidence(
    profile: Profile | None, name: str, aliases: tuple[str, ...]
) -> tuple[int, int, list[str], bool]:
    """只看当前画像里的非历史技能：`user_level` 由既有纯函数给出，证据原文逐条回传。"""
    level = role_fit_service.user_level_of(name, profile)
    if profile is None:
        return level, 0, [], False
    quotes: list[str] = []
    hit = False
    for skill in profile.skills:
        if skill.status == "historical" or not _skill_hits(name, aliases, skill.name):
            continue
        hit = True
        for evidence in skill.source_quotes:
            text = str(evidence.quote or "").strip()
            if text and text not in quotes:
                quotes.append(text)
        legacy = str(skill.source_quote or "").strip()
        if legacy and legacy not in quotes:
            quotes.append(legacy)
    return level, len(quotes), quotes[:MAX_EVIDENCE_PER_KEYWORD], hit


def _detect_role(text: str, profile: Profile | None) -> str | None:
    compact = _compact(text)
    for role in role_fit_service.load_role_models():
        if _compact(role) in compact:
            return role
    for aliases, role in _ROLE_HINTS:
        if any(_compact(alias) in compact for alias in aliases):
            return role
    if profile is not None and (profile.target_role or "").strip():
        return profile.target_role.strip()
    report = repository.latest_report()
    if report is not None and report.role_fit is not None and report.role_fit.target_role:
        return report.role_fit.target_role
    return None


def _topic_hint(name: str, aliases: tuple[str, ...], direction: str) -> str:
    """二级方向提示：别名命中即计数；必须属于该方向闭集，否则给空串（不编造）。"""
    haystack = " ".join((name, *aliases)).lower()
    sub_directions = rules.SUBDIRECTIONS.get(direction, ())
    for needle, hint_direction, sub in _SUB_HINTS:
        if needle in haystack and hint_direction == direction and sub in sub_directions:
            return sub
    return ""


def _preset(
    role: str | None,
    fit: Any,
    keywords: list[JdKeywordItem],
    gaps: list[JdGapItem],
) -> JdInterviewPreset | None:
    if not role:
        return None
    direction = fit.model.direction if fit is not None and fit.model is not None else None
    if direction not in rules.DIRECTIONS:
        tally: dict[str, int] = {}
        for item in keywords:
            haystack = f"{item.name} {item.matched_alias}".lower()
            for needle, hint_direction, _sub in _SUB_HINTS:
                if needle in haystack and hint_direction in rules.DIRECTIONS:
                    tally[hint_direction] = tally.get(hint_direction, 0) + 1
        direction = max(tally, key=tally.get) if tally else ""
    direction = direction if direction in rules.DIRECTIONS else ""
    sub = ""
    for item in keywords:
        hinted = _topic_hint(f"{item.name} {item.matched_alias}", (), direction)
        if hinted:
            sub = hinted
            break
    if direction and sub and not rules.is_valid_sub_direction(direction, sub):
        sub = ""
    # r111：JD 缺口优先；没有「JD 写到但无证据」时才回退岗位模型的先补项。
    focus: list[str] = []
    for name in [*(item.name for item in gaps if item.origin == "jd"), *(fit.first_fix if fit is not None else [])]:
        cleaned = name.strip()[:40]
        if cleaned and cleaned not in focus:
            focus.append(cleaned)
        if len(focus) == 3:
            break
    reason = (
        "按本次 JD 识别的岗位、命中技术词与前 3 个缺口预填；"
        "经验 / 市场 / 公司规模仍在召对页自行选择。"
    )
    return JdInterviewPreset(
        target_role=role,
        direction=direction,
        sub_direction=sub,
        focus_gaps=focus,
        reason=reason,
    )


def match_jd(payload: JdMatchRequest) -> JdMatchResult:
    """一次纯函数式对位：识别岗位 → 检词 → 查画像证据 → 组缺口与面试预设。"""
    text = payload.jd_text.strip()
    if not text:
        raise AppError(VALIDATION_ERROR, "请粘贴岗位 JD 后再对位", status=400, retryable=False)

    profile = repository.latest_profile()
    explicit = (payload.target_role or "").strip()
    role = explicit or _detect_role(text, profile)
    fit = role_fit_service.build_role_fit(profile, role) if role else None
    required = {
        item.name
        for item in (fit.items if fit is not None else [])
    }

    # 先全量召回再统一挑：同一段文字可能被「Python」和「Python 后端服务」同时命中，
    # 必须保留覆盖更长的那一项，不能让先遍历到的短名把证据抢走。
    candidates: list[tuple[int, int, str, str, tuple[str, ...]]] = []
    for name, aliases in _all_terms():
        best: tuple[int, int, str] | None = None
        for alias in aliases:
            for match in re.finditer(_alias_pattern(alias), text, flags=re.IGNORECASE):
                candidate = (match.start(), -len(match.group(0)), alias)
                if best is None or candidate < best:
                    best = candidate
                break
        if best is not None:
            start, negative_len, _alias = best
            candidates.append((start, start - negative_len, name, _alias, aliases))

    candidates.sort(key=lambda row: (row[0], -(row[1] - row[0]), row[2]))
    occupied: list[tuple[int, int]] = []
    keywords: list[JdKeywordItem] = []
    for start, end, name, _alias, aliases in candidates:
        if len(keywords) >= MAX_KEYWORDS:
            break
        if any(start < taken_end and taken_start < end for taken_start, taken_end in occupied):
            continue
        occupied.append((start, end))
        matched_alias = text[start:end]
        level, evidence_count, evidence, hit = _profile_evidence(profile, name, aliases)
        # 有画像技能且 level≥2 才算「有证据」；只在 tech_stack 出现算「提到但证据弱」。
        status = "evidence" if hit and level >= 2 else "mentioned" if hit else "missing"
        keywords.append(
            JdKeywordItem(
                name=name,
                matched_alias=matched_alias,
                source_quote=_snippet(text, start, end),
                user_level=level,
                evidence_count=evidence_count,
                evidence=evidence,
                status=status,
                role_required=name in required,
            )
        )
    gaps: list[JdGapItem] = []
    seen: set[str] = set()
    for item in keywords:
        if item.status == "evidence":
            continue
        gaps.append(
            JdGapItem(
                name=item.name,
                origin="jd",
                reason=f"JD 写到「{item.matched_alias}」，画像里没有可复算的证据。",
                source_quote=item.source_quote,
            )
        )
        seen.add(_compact(item.name))
    if fit is not None:
        for name in fit.first_fix:
            if len(gaps) >= MAX_GAPS:
                break
            if _compact(name) in seen:
                continue
            gaps.append(
                JdGapItem(
                    name=name,
                    origin="role_model",
                    reason=f"目标岗位模型要求「{name}」，这段 JD 未直接提到；不据此判定 JD 硬性要求。",
                )
            )

    notices = [
        "这只是 JD 文本与画像证据的字面对照，不是能力评分；未命中只表示这段文本里没找到证据。"
    ]
    if profile is None:
        notices.append("还没有画像：先上传简历完成画像，证据列才会引用你的真实记录。")
    if not keywords:
        notices.append("这段话里没检出可匹配的技术词，可以补上「技能要求 / 岗位职责」再试。")
    if not role:
        notices.append("未识别到目标岗位；在上方指定岗位后，会补出岗位模型的缺口。")

    return JdMatchResult(
        target_role=role,
        role_fit=fit,
        keywords=keywords,
        gaps=gaps,
        preset=_preset(role, fit, keywords, gaps),
        notice="".join(notices),
        source_chars=len(text),
        matched_count=sum(1 for item in keywords if item.status != "missing"),
        missing_count=sum(1 for item in keywords if item.status == "missing"),
        generated_at=_now_iso(),
    )
