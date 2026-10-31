"""画像生成（AC-2 / anti-goal 1）：AI 读正文 → ProfileDraft → 原文溯源校验 → 落库。

契约：
- `generate_profile` 返回**已入库**的 `Profile`（含 id / resume_id / updated_at）。
- 任何一条 skills / projects 的 `source_quote` 若不能在简历正文里逐字命中，一律在
  入库前抛 `AI_SCHEMA_INVALID`（502）—— 宁可让用户重试，也不落一份「无源之词」的画像。
- 注入 `client=` 即可零网络测试（TECHNICAL §6.1）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from ..errors import AI_SCHEMA_INVALID, VALIDATION_ERROR, AppError
from ..repository import insert_profile
from ..schemas import Profile, ProfileDraft
from .ai import AIClient

#: 送进模型的简历正文上限：超出即截断（长简历既撑上下文，也会拖慢首屏）。
MAX_PROFILE_CHARS = 12000

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


async def generate_profile(
    resume_id: str, text: str, *, client: AIClient | None = None
) -> Profile:
    """读简历正文 → 模型抽 5 维度 → 校验溯源 → 入库并返回。"""
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
    draft = await ai.complete_model(PROFILE_SYSTEM, context, ProfileDraft)
    verify_quotes(draft, body)
    if not draft.skills and not draft.tech_stack and not draft.projects:
        raise AppError(
            AI_SCHEMA_INVALID,
            "AI 没能从简历里抽出任何内容，请重试一次或换一份简历",
            status=502,
            retryable=True,
        )

    profile = Profile.model_validate(
        {
            **draft.model_dump(),
            "id": uuid.uuid4().hex,
            "resume_id": resume_id,
            "updated_at": datetime.now(UTC).isoformat(),
        }
    )
    insert_profile(profile)
    return profile
