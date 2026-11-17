"""画像生成（AC-2 / anti-goal 1）：AI 读正文 → ProfileDraft → 原文溯源校验 → 增量合并 → 落库。

契约（r3 起）：
- `generate_profile` 返回**已入库**的 `ProfileWithMerge`：`Profile` 部分是合并后的
  唯一画像（**同一个 `profile_id`**，多次上传只累积不新增行），`merge_summary` 是
  本次合并的一次性事件摘要（不写库，不进 `GET /api/profiles/latest` 的持久契约）。
- 合并语义全部在 `services/profile_merge.py`：本文件只负责 AI 编排与「写一次」，
  不重复任何判同 / 历史项 / 证据累积规则。
- 溯源口径（r116 校准）：`source_quote` 先归一化（NFKC + 去不可见格式字符 + 去空白）再在正文里
  定位。没命中的处理顺序是**补抽一次 → 逐条剔除 → 一条都不剩才报错**。
  被剔除的条目不会入库，所以 anti-goal 1「画像里不出现无源之词」依然成立；而 r3 的
  「任一条不合格就整份 502」会让失败率随条目数指数放大（15 条 × 单条 5% ⇒ 只剩 46% 成功率），
  表现为「同一份简历上传有时成功有时失败」，是可用性缺陷而非安全约束。
- 时间线事件写在落库成功之后，且**写入失败不阻断主流程**（AC-3）。
- 注入 `client=` 即可零网络测试（TECHNICAL §6.1）。
"""

from __future__ import annotations

import logging
import unicodedata
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from app.core import repository
from app.core.errors import AI_SCHEMA_INVALID, VALIDATION_ERROR, AppError
from app.schemas import Profile, ProfileDraft
from app.services.ai.ai import AIClient
from app.services.profile.profile_merge import (
    STATUS_HISTORICAL,
    ProfileMergeSummary,
    ProfileWithMerge,
    merge_profile,
    normalize_name,
)

#: 送进模型的简历正文上限：超出即截断（长简历既撑上下文，也会拖慢首屏）。
MAX_PROFILE_CHARS = 12000

logger = logging.getLogger("app.profile")

#: 单条 `source_quote` 的合理上限（DESIGN §2.2 溯源引用块按一行展示）。
MAX_QUOTE_CHARS = 200

#: Unicode「格式类」字符（Cf）：零宽空格 / 零宽连接符 / BOM / 软连字符 / word joiner 全在这一类。
#: PDF 抽取的产物里很常见，且 `str.split()` 吃不掉它们 —— 溯源比对必须整类丢掉（见 `_squash`）。
_IGNORABLE_CATEGORY = "Cf"

#: 模型抄到一半用省略号收尾时的收尾符；判定命中时只去尾部，不接受中间出现。
_TRAILING_ELLIPSES = ("…", "⋯", "...")

#: 溯源没命中时的补抽提示：把「哪几条没命中」直接回灌，比笼统说一句「重试」有效得多。
QUOTE_REPAIR_HINT = """上一次回答里，以下条目的 source_quote 在简历正文中找不到逐字出处：{labels}
请重新输出完整 JSON。这次 source_quote 必须从简历正文里**原样复制一段连续文字**（含原有标点），
不要改写、不要概括、不要用省略号收尾；确实找不到出处的条目请直接删掉，不要为了凑数保留。"""

#: 正文被截断后追加在模型输入末尾的说明（TECHNICAL §4.2；前端 `ProfileDimension` 顶部同文案）。
#: 只进模型输入，不进溯源校验文本 —— 后缀不是简历原文，不能被当成出处。
TRUNCATION_NOTE = f"（已截取前 {MAX_PROFILE_CHARS} 字）"

#: 截断时保留完整末行的下限比例：低于该比例就不动，免得多送少送都别扭。
_TRUNCATE_KEEP_RATIO = 0.8

PROFILE_SYSTEM = """你是简历画像抽取器。只依据用户给出的简历正文，输出一个 JSON 对象，不要任何解释。

字段：
- skills: [{"name": 技能名（≤12 字）, "source_quote": 简历原文片段}]
- tech_stack: [技术名词，逐项短词]
- years_experience: 数字（年，可小数；无法判断填 null）
- projects: [{"name", "role", "period", "bullets": [成果短句], "source_quote": 简历原文片段}]
- target_role: 目标岗位（≤20 字；无法判断填 null）

硬性规则：
1. 只写简历里明确写出的内容，禁止推断、禁止补充行业常识、禁止编造项目与技能。
2. source_quote 必须是简历正文中**连续、逐字**的片段（≤200 字），不得改写、不得拼接多段。
3. 若某个维度无信息，给空数组（或 null）；宁缺毋滥，不要为了凑满而编造。
4. 只输出 JSON 对象本身：不要代码围栏，不要注释，不要额外说明文字。"""


def _clip(text: str) -> str:
    """截断到 `MAX_PROFILE_CHARS` 内，并尽量不把最后一行切成半句（半句会污染溯源校验）。"""
    body = text.strip()
    if len(body) <= MAX_PROFILE_CHARS:
        return body
    head = body[:MAX_PROFILE_CHARS]
    cut = head.rfind("\n")
    if cut >= int(MAX_PROFILE_CHARS * _TRUNCATE_KEEP_RATIO):
        head = head[:cut]
    return head.rstrip()


def _squash(text: str) -> str:
    """归一化后去掉全部空白：模型抄写时常常丢掉换行或多余空格，这不算编造。

    r116 起不再「只去空白」—— 只去空白会把两类**假失配**当成编造：

    - **全半角差异**：模型很爱把 `（）` 写成 `()`、把 `：` 写成 `:`，内容一个字没改；
    - **不可见格式字符**：PDF 抽取常在行尾断词处留软连字符 `U+00AD`，跨页拼接处留零宽空格
      `U+200B`、BOM `U+FEFF`、word joiner `U+2060`。这些字符模型「看不见」也就不会复制，
      而 `str.split()` 并不把它们当空白（只有 `isspace()` 为真的才被去掉），于是正文里带着、
      引用里没有 —— 引用跨过这些位置就失败、没跨过就成功，正是「同一份简历时好时坏」的来源。

    `NFKC` 抹平字形与全半角差异，`Cf`（Unicode 格式类）一次性覆盖上述全部不可见字符。
    """
    return "".join(
        char
        for char in unicodedata.normalize("NFKC", text)
        if not char.isspace() and unicodedata.category(char) != _IGNORABLE_CATEGORY
    )


def _without_trailing_ellipsis(text: str) -> str:
    """去掉尾部的省略号：模型抄到一半就用「…」收尾很常见，那是截断而不是编造。

    只放宽末尾 —— 去掉省略号之后剩下的部分仍必须逐字命中，改写与拼接照样过不了。
    """
    cleaned = text.rstrip()
    for mark in _TRAILING_ELLIPSES:
        while cleaned.endswith(mark):
            cleaned = cleaned[: -len(mark)].rstrip()
    return cleaned


def _quote_hits(quote: str, haystack: str) -> bool:
    """`quote` 是否是 `haystack`（已归一化的正文）里的连续片段；空引用一律算没命中。"""
    normalized = _squash(_without_trailing_ellipsis(quote))
    return bool(normalized) and normalized in haystack


def _clip_quote(entry: Any) -> None:
    """模型偶尔会贴一长段原文：截到 `MAX_QUOTE_CHARS` 后仍是从简历起点连续逐字的片段，
    既守住 DESIGN §2.2「溯源块按一行展示」的宽度，也不改变命中的判定口径。"""
    if len(entry.source_quote) > MAX_QUOTE_CHARS:
        entry.source_quote = entry.source_quote[:MAX_QUOTE_CHARS].rstrip()


def verify_quotes(draft: ProfileDraft, text: str) -> None:
    """溯源校验（最终闸门）：任一条 skill / project 的 `source_quote` 不能在正文命中就抛。

    这是 anti-goal 1「无源之词」的最后一道防线，**故意保持**「一条不合格 → 整份拒绝」的语义。
    `generate_profile` 在调它之前已经走完「补抽 → 剔除」，正常路径到这里不会再抛；
    独立成函数以便被单测直接钉住（文件头契约见 r116 说明）。
    """
    haystack = _squash(text)
    for entry in (*draft.skills, *draft.projects):
        _clip_quote(entry)
        label = entry.name[:40]
        if not _squash(entry.source_quote):
            raise AppError(
                AI_SCHEMA_INVALID,
                f"「{label}」缺少简历原文出处，请重试一次",
                status=502,
                retryable=True,
            )
        if not _quote_hits(entry.source_quote, haystack):
            raise AppError(
                AI_SCHEMA_INVALID,
                f"「{label}」在简历原文中找不到出处，请重试一次",
                status=502,
                retryable=True,
            )


def unsourced_labels(draft: ProfileDraft, text: str) -> list[str]:
    """列出 `source_quote` 没能在正文里命中的条目名（只读，不改 `draft`）。"""
    haystack = _squash(text)
    return [
        entry.name[:40]
        for entry in (*draft.skills, *draft.projects)
        if not _quote_hits(entry.source_quote, haystack)
    ]


def drop_unsourced(draft: ProfileDraft, text: str) -> list[str]:
    """剔掉没能在正文里命中的条目，返回被剔掉的名字（就地修改 `draft`）。

    与 `verify_quotes` 的分工：那是「宁可整份失败」的最终闸门，这是「宁缺毋滥」的降级路径。
    两条路都保证入库的画像里不含无源之词，区别只在一条不合格时抛不抛整份。
    """
    haystack = _squash(text)
    dropped: list[str] = []
    for attr in ("skills", "projects"):
        kept = []
        for entry in getattr(draft, attr):
            _clip_quote(entry)
            if _quote_hits(entry.source_quote, haystack):
                kept.append(entry)
            else:
                dropped.append(entry.name[:40])
        setattr(draft, attr, kept)
    return dropped


def _is_duplicate(old: Profile | None, body: str) -> bool:
    """同一份简历判定（Q4）：新旧正文去空白后完全一致即视为重复上传。

    正文取自**旧画像来源简历**；读不到正文时保守判「不重复」—— 误报重复比漏报更糟
    （漏报只多记一条事件，误报会让用户以为画像没更新）。
    """
    if old is None or not old.resume_id:
        return False
    previous = repository.get_document_text(old.resume_id)
    if previous is None:
        return False
    return _squash(_clip(previous)) == _squash(body)


def _merge_once(
    old: Profile | None,
    draft: ProfileDraft,
    *,
    resume_id: str,
    file_name: str,
    captured_at: str,
    duplicate: bool,
) -> tuple[Profile, ProfileMergeSummary]:
    """一次合并：判同 / 证据累积 / 历史项全部在 `profile_merge`，这里只透传 duplicate。"""
    return merge_profile(
        old,
        draft,
        resume_id=resume_id,
        file_name=file_name,
        captured_at=captured_at,
        duplicate=duplicate,
    )


def _summary_payload(summary: ProfileMergeSummary) -> dict[str, Any]:
    dumper = getattr(summary, "model_dump", None)
    return dumper() if callable(dumper) else asdict(summary)


def _with_summary(profile: Profile, summary: ProfileMergeSummary) -> ProfileWithMerge:
    """组装响应：画像本体 + 一次性 `merge_summary`（不落库、不进 GET 契约）。"""
    payload = profile.model_dump()
    payload["merge_summary"] = _summary_payload(summary)
    return ProfileWithMerge.model_validate(payload)


def _changed_skill_names(
    old: Profile | None, merged: Profile
) -> tuple[list[str], list[str]]:
    """合并前后的能力项差异（时间线 resume 事件要的是「名字」而不是计数）。

    - added：本次简历新增的 active 能力项；
    - removed：曾经存在、本次没写而转 historical 的能力项（不是删除）。
    """
    previous = {normalize_name(skill.name) for skill in (old.skills if old else [])}
    added = [
        skill.name
        for skill in merged.skills
        if normalize_name(skill.name) not in previous
    ]
    removed = [
        skill.name
        for skill in merged.skills
        if normalize_name(skill.name) in previous
        and getattr(skill, "status", "") == STATUS_HISTORICAL
    ]
    return added, removed


def _record_resume_event(
    *,
    resume_id: str,
    skill_added: list[str],
    skill_removed: list[str],
    duplicate: bool,
) -> None:
    """写简历时间线事件：时间线是**旁路**，任何失败都不阻断画像主流程（AC-3）。"""
    recorder = _timeline_recorder("record_resume_event")
    if recorder is None:
        return
    try:
        recorder(
            resume_id=resume_id,
            skill_added=skill_added,
            skill_removed=skill_removed,
            duplicate=duplicate,
        )
    except Exception:  # noqa: BLE001 - 旁路写入失败不得影响画像落库结果
        return


def _timeline_recorder(name: str) -> Callable[..., Any] | None:
    """惰性取时间线钩子（`services/timeline.py`）；未落地时返回 None（时间线非阻断）。"""
    try:
        from app.services.report import timeline
    except Exception:  # noqa: BLE001 - 并行开发窗口内时间线模块可能尚未落地
        return None
    recorder = getattr(timeline, name, None)
    return recorder if callable(recorder) else None


async def _draft_with_sources(ai: AIClient, context: str, body: str) -> ProfileDraft:
    """抽草稿并兜住溯源：**成功路径只调一次模型**，不改变现有的时延与配额消耗。

    失败路径三级降级（r116）：
    1. 补抽一次，并把「哪几条没命中」写进提示 —— 模型对「你这条抄错了」的纠正能力远高于
       泛泛的「请重试」；
    2. 补抽反而更差（没命中的条数变多）就丢弃补抽结果，拿第一版走剔除；
    3. 逐条剔除，一条都不剩才报错（那不是抄写偏差，而是整份在编，重试才有意义）。
    """
    draft = await ai.complete_model(
        PROFILE_SYSTEM, context, ProfileDraft, retry_unavailable=True
    )
    missing = unsourced_labels(draft, body)
    if not missing:
        return draft

    logger.warning("profile.quote_miss attempt=1 missing=%s", len(missing))
    repaired = await ai.complete_model(
        PROFILE_SYSTEM,
        f"{context}\n\n{QUOTE_REPAIR_HINT.format(labels='、'.join(missing))}",
        ProfileDraft,
        retry_unavailable=True,
    )
    still = unsourced_labels(repaired, body)
    if len(still) > len(missing):
        logger.warning("profile.quote_miss attempt=2 worse=%s keep=1", len(still))
        repaired = draft

    dropped = drop_unsourced(repaired, body)
    if not repaired.skills and not repaired.projects:
        raise AppError(
            AI_SCHEMA_INVALID,
            "AI 抽出的能力项都没能在简历原文里找到出处，请重试一次",
            status=502,
            retryable=True,
        )
    if dropped:
        # 只记条数与被剔的名字（技能名/项目名是短标签，不含简历正文片段）。
        logger.warning("profile.quote_dropped count=%s names=%s", len(dropped), dropped)
    return repaired


async def generate_profile(
    resume_id: str,
    text: str,
    *,
    file_name: str = "",
    captured_at: str = "",
    client: AIClient | None = None,
) -> ProfileWithMerge:
    """读简历正文 → 模型抽 5 维度 → 校验溯源 → 合并进当前画像 → 落库 → 写 resume 事件。"""
    body = _clip(text)
    if not body:
        raise AppError(
            VALIDATION_ERROR,
            "这份简历没有可分析的正文，请换一份文件重新上传",
            status=400,
        )

    ai = client or AIClient()
    # 超长简历：正文截断后追加说明，模型才知道「后面还有没看到的内容」，不会断言信息完整；
    # 溯源仍对未加后缀的正文校验（后缀若是原文，会让「已截取」这类字样混进出处）。
    context = f"{body}{TRUNCATION_NOTE}" if len(text.strip()) > MAX_PROFILE_CHARS else body
    draft = await _draft_with_sources(ai, context, body)
    # 最终闸门：`_draft_with_sources` 已剔除无出处条目，这里只防「剔除逻辑被改坏」的回归。
    verify_quotes(draft, body)
    if not draft.skills and not draft.tech_stack and not draft.projects:
        raise AppError(
            AI_SCHEMA_INVALID,
            "AI 没能从简历里抽出任何内容，请重试一次或换一份简历",
            status=502,
            retryable=True,
        )

    # 读—合并—写：先取当前画像做合并基底，写入前再读一次；窗口内被别人改过就
    # 以最新基底重合并一次（PRD R7 乐观校验，单用户本地场景足够）。
    old = repository.latest_profile()
    duplicate = _is_duplicate(old, body)
    merged, summary = _merge_once(
        old,
        draft,
        resume_id=resume_id,
        file_name=file_name,
        captured_at=captured_at,
        duplicate=duplicate,
    )
    guard = repository.latest_profile()
    if guard is not None and (old is None or guard.id != old.id or guard.updated_at != old.updated_at):
        merged, summary = _merge_once(
            guard,
            draft,
            resume_id=resume_id,
            file_name=file_name,
            captured_at=captured_at,
            duplicate=_is_duplicate(guard, body),
        )
        old = guard  # 事件差异必须相对最终合并基底计算

    repository.insert_profile(merged)
    # 事件必须在落库成功之后写（画像失败时不留半条时间线，AC-3）。
    added, removed = _changed_skill_names(old, merged)
    _record_resume_event(
        resume_id=resume_id,
        skill_added=added,
        skill_removed=removed,
        duplicate=summary.duplicate,
    )
    return _with_summary(merged, summary)
