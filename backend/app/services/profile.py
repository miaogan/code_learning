"""画像生成（AC-2 / anti-goal 1）：AI 读正文 → ProfileDraft → 原文溯源校验 → 增量合并 → 落库。

契约（r3 起）：
- `generate_profile` 返回**已入库**的 `ProfileWithMerge`：`Profile` 部分是合并后的
  唯一画像（**同一个 `profile_id`**，多次上传只累积不新增行），`merge_summary` 是
  本次合并的一次性事件摘要（不写库，不进 `GET /api/profiles/latest` 的持久契约）。
- 合并语义全部在 `services/profile_merge.py`：本文件只负责 AI 编排与「写一次」，
  不重复任何判同 / 历史项 / 证据累积规则。
- 任何一条 skills / projects 的 `source_quote` 若不能在简历正文里逐字命中，一律在
  入库前抛 `AI_SCHEMA_INVALID`（502）—— 宁可让用户重试，也不落一份「无源之词」的画像。
- 时间线事件写在落库成功之后，且**写入失败不阻断主流程**（AC-3）。
- 注入 `client=` 即可零网络测试（TECHNICAL §6.1）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from .. import repository
from ..errors import AI_SCHEMA_INVALID, VALIDATION_ERROR, AppError
from ..schemas import Profile, ProfileDraft
from .ai import AIClient
from .profile_merge import (
    STATUS_HISTORICAL,
    ProfileMergeSummary,
    ProfileWithMerge,
    merge_profile,
    normalize_name,
)

#: 送进模型的简历正文上限：超出即截断（长简历既撑上下文，也会拖慢首屏）。
MAX_PROFILE_CHARS = 12000

#: 画像生成的专用超时（秒，r34）：该调用要输出「技能 / 项目 / 逐条证据」大 JSON，
#: 真实体量简历上远超 20s 的通用超时（用户实测报「AI 服务响应超时」）。
#: 生成已改为后台任务（r30），用户不在同步等待，拉长不改交互体验。
PROFILE_TIMEOUT_S = 120.0

#: 单条 `source_quote` 的合理上限（DESIGN §2.2 溯源引用块按一行展示）。
MAX_QUOTE_CHARS = 200

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
    """去掉全部空白后再比对：模型抄写时常常丢掉换行或多余空格，这不算编造。"""
    return "".join(text.split())


def verify_quotes(draft: ProfileDraft, text: str) -> None:
    """溯源校验：每条 skill / project 的 `source_quote` 必须能在正文里逐字命中。

    这是 anti-goal 1「无源之词」的入库闸门，独立成函数以便被单测直接钉住。
    """
    haystack = _squash(text)
    for entry in (*draft.skills, *draft.projects):
        # 模型偶尔会贴一长段原文：截到 `MAX_QUOTE_CHARS` 后仍是从简历起点连续逐字的片段，
        # 既守住 DESIGN §2.2「溯源块按一行展示」的宽度，也不改变命中的判定口径。
        if len(entry.source_quote) > MAX_QUOTE_CHARS:
            entry.source_quote = entry.source_quote[:MAX_QUOTE_CHARS].rstrip()
        quote = _squash(entry.source_quote)
        label = entry.name[:40]
        if not quote:
            raise AppError(
                AI_SCHEMA_INVALID,
                f"「{label}」缺少简历原文出处，请重试一次",
                status=502,
                retryable=True,
            )
        if quote not in haystack:
            raise AppError(
                AI_SCHEMA_INVALID,
                f"「{label}」在简历原文中找不到出处，请重试一次",
                status=502,
                retryable=True,
            )


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
        from . import timeline
    except Exception:  # noqa: BLE001 - 并行开发窗口内时间线模块可能尚未落地
        return None
    recorder = getattr(timeline, name, None)
    return recorder if callable(recorder) else None


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
    draft = await ai.complete_model(
        PROFILE_SYSTEM,
        context,
        ProfileDraft,
        timeout_s=PROFILE_TIMEOUT_S,
        # 后台任务：超时/5xx 自动重来一次，不让一次抖动直接判死（用户可重试但代价高）。
        retry_unavailable=True,
    )
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
