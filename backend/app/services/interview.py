"""模拟面试（r5）：多轮对话式会话引擎（AC-1..AC-7 / AC-10）。

契约（TECHNICAL §1.1 / §3.1–§3.7）：
- 会话唯一真相仍是 `runs.payload`，形状升级为 v2：`settings` / `calibration` / 开局 `plan` /
  `plan_index` / 递增 `questions` / `follow_up_count` / `turn` / `current_id`。零新表、零迁移。
- 开局 `create_run`：结构闸门（数量 / 配比 / 题干去重）在 `insert_run` **之前**，不合格 502 且
  不落库、不静默补题；通过后只投放第 1 条发言（AC-4 不预先铺开 8 题）。
- 每轮 `score_answer`：**一次** AI 调用同轮产出「本轮评分 + 下一条发言」，校验与计算全部在
  `save_run` 之前 —— 任何失败零副作用（AC-10）；同一 `question_id` 重复提交只覆盖分数。
- 四项设定（目标岗位 / 工作经验 / 面试市场 / 公司规模）只经 `rules.py` 的纯映射进每一轮
  提示词，**绝不写回画像**（AC-3）。
- `load_session` 是刷新 / 重进恢复的唯一读路径（AC-9），对 v1 payload 只读降级、不迁移。
- AI 一律经 `client=` 注入（TECHNICAL §6.1），测试零网络。
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .. import repository
from ..errors import AI_SCHEMA_INVALID, NOT_FOUND, VALIDATION_ERROR, AppError
from ..repository import RUN_COMPLETED, RUN_RUNNING
from ..schemas import (
    InterviewQuestion,
    InterviewRun,
    InterviewSession,
    InterviewSessionQuestion,
    InterviewSettings,
    InterviewSettingsPatch,
    InterviewTurn,
    Profile,
    QuestionKind,
)
from . import rules, timeline
from .ai import AIClient
from .history import INTERVIEW_KIND, score_of

#: 单轮「评分 + 下一条发言」预算：AC 要求 15s 内出结果，留 1s 给网络与落库。
SCORING_TIMEOUT_S = 14.0

#: 点评字数上限（DESIGN §2.3 的点评区按两行展示）；超长不报错，截断即可。
MAX_COMMENT_CHARS = 120

#: 题目 id 前缀（报告页证据 chip 与 `question_ref` 都直接引用它，不得随意更改）。
QUESTION_ID_PREFIX = "iq"

#: AC-6：最近 N 轮「题面 + 作答 + 分数」全文进提示词，更早的只送题面摘要。
HISTORY_WINDOW = 3

#: 画像岗位名的最长保留字符数（超长截断，避免把整段简历标题塞进提示词）。
TARGET_ROLE_MAX_CHARS = 40

#: 缺省作答提示：模型没给 hint 时的兜底，保证每条发言都有可读提示行。
DEFAULT_HINT = "结合具体经历，说明做法、取舍与结果"

#: 模型给了空点评时的兜底（不编造内容，只记录本次作答）。
DEFAULT_COMMENT = "已记录本次作答，建议补充量化结果"

INTERVIEW_SYSTEM = """你是程序员模拟面试官。依据本场设定与候选人的简历画像，产出整场面试计划，只输出 JSON 对象。

输出格式：
{"questions":[{"kind":"technical|project|challenge","prompt":"题面（≤120 字）","hint":"作答提示（≤40 字）"}]}

硬性规则：
1. 共 8 道题：technical ≥5、project ≥3，challenge ≤2（challenge 占总题量不超过 20%）。
2. 必须按 user JSON 的 settings 与 calibration 出题：目标岗位、工作经验、面试市场、公司规模都要改变题目口径，
   不得只做措辞替换。
3. technical 题对准画像的 tech_stack / skills；project 题必须点名画像里的具体项目；
   challenge 题给一个超出舒适区的场景题，允许没有标准答案。
4. 每题 prompt 必须互不相同，不得换句话重复同一道题；不需要输出 id（服务端按 iq-1 起编号）。
5. 本次只投放计划里的第 1 题作为开场发言，其余题目后续逐轮投放。
6. 只输出 JSON 对象本身：不要代码围栏，不要注释，不要额外解释。"""

ROUND_SYSTEM = """你是程序员模拟面试官。本轮候选人在回答当前题目：请先给出本轮评分，再决定下一条发言，只输出 JSON 对象。

输出格式：
{"score": 数字（0–10，一位小数）, "comment": "中文点评（≤120 字）",
 "next": {"mode": "follow_up|advance", "prompt": "追问的题面（≤120 字；advance 时可留空）", "hint": "作答提示（≤40 字）"}}

评分口径（与历史评分同源）：
- 0–3：答非所问、空泛套话或与题目无关；
- 4–6：有基本思路，但缺具体做法、缺量化结果；
- 7–8：结构清楚，讲出具体做法与结果；
- 9–10：有取舍权衡，且有可验证的效果。

点评要求：先一句说明得分理由，再给一条具体可改的改进点；不要复述题目，不要编造候选人没说的经历。

下一条发言规则：
- allow_follow_up 为 true 且上一答有可深挖之处 → mode=follow_up，题面必须接住上一答（追问细节 / 澄清 / 施压），
  不要换题；题面要具体、可回答，≤120 字。
- 否则 mode=advance，按 next_plan 的下一题推进（prompt 可留空，服务端用计划原文投放）。
- settings 与 calibration 在每一轮都必须继续影响出题口径。"""


class PlanItem(BaseModel):
    """计划条目（内部模型）：只有 kind/prompt/hint，id 一律由服务端重编号。"""

    model_config = ConfigDict(extra="ignore")

    kind: QuestionKind
    prompt: str
    hint: str = ""


class InterviewDraft(BaseModel):
    """开局响应模型（内部模型，不进 HTTP 契约；`run_id` 之类多余字段忽略）。"""

    model_config = ConfigDict(extra="ignore")

    questions: list[PlanItem]


class NextDraft(BaseModel):
    """下一条发言草稿：`mode` 用字符串宽松解析，非法取值在 `_next_question` 里降级为 advance。"""

    model_config = ConfigDict(extra="ignore")

    mode: str = "advance"
    prompt: str = ""
    hint: str = ""


class RoundDraft(BaseModel):
    """单轮响应模型（内部模型）：本轮评分 + 下一条发言，一次调用同时产出（AC-4/AC-6）。"""

    model_config = ConfigDict(extra="ignore")

    score: float = Field(ge=0, le=10)
    comment: str = ""
    next: NextDraft | None = None


# --- 配置补全与口径映射（AC-1 / AC-2④ / AC-3） ------------------------------

#: 经验档 → 口径要点。五档文案**逐档不同**：档间集合互不相同是 AC-2④ 的可判定口径。
_EXPERIENCE_CALIBRATION: dict[str, str] = {
    "应届": "基础概念、课程与个人项目、学习潜力；不考大规模架构取舍与线上故障处置",
    "1-3年": "基础概念与工程习惯、能独立完成模块；不考大规模架构取舍与线上事故主导",
    "3-5年": "独立负责模块，重点考有依据的技术取舍、问题定位与结果量化",
    "5-10年": "架构设计、跨团队协作与长线风险，要求给出方案、代价与回滚思路",
    "10年以上": "技术判断与选型、组织级影响，要求权衡历史包袱与分阶段落地路径",
}

#: 面试市场 → 口径要点（四档互不相同：本地业务深度 / 系统设计 / 工程规范 / 通用口径）。
_MARKET_CALIBRATION: dict[str, str] = {
    "国内": "业务落地与基础原理深度（并发、内存、框架原理），题面中文、术语按中文习惯",
    "北美": "系统设计与技术表达（规模、边界、trade-off），术语可保留英文并追问设计取舍",
    "欧洲": "工程规范、可维护性与协作流程，重视测试、文档与跨职能沟通",
    "其他": "通用口径：技术深度与项目结果并重，按国际通行术语表述",
}

#: 公司规模 → 口径要点（三档互不相同：大规模系统 / 端到端负责 / 资源受限全栈）。
_COMPANY_CALIBRATION: dict[str, str] = {
    "大厂": "大规模系统、流程协作与深度原理，要求讲清指标与容量估算",
    "中型": "端到端负责、性能与成本，要求讲清交付节奏与取舍依据",
    "初创": "全栈落地、资源受限取舍与快速交付，要求讲清最小可行路径与验证方式",
}


def _role_text(value: str | None) -> str:
    """岗位名归一：去空白 → 截断 → 空串回落默认（空岗位会让提示词失去锚点）。"""
    text = (value or "").strip()
    return text[:TARGET_ROLE_MAX_CHARS] or rules.DEFAULT_TARGET_ROLE


def _band_text(value: str | None) -> str:
    """经验档归一：不在闭集的一律回落默认档（防止旧数据 / 脏请求带进非法档位）。"""
    return value if value in rules.EXPERIENCE_BANDS else rules.DEFAULT_EXPERIENCE_BAND


def _market_text(value: str | None) -> str:
    return value if value in rules.MARKETS else rules.DEFAULT_MARKET


def _company_text(value: str | None) -> str:
    return value if value in rules.COMPANY_SIZES else rules.DEFAULT_COMPANY_SIZE


def fill_settings(
    patch: InterviewSettingsPatch | None, profile: Profile | None
) -> InterviewSettings:
    """补全本场四项设定：请求补丁 → 画像（岗位 / 经验档）→ 默认值。

    优先级与前端预填**逐条对称**（前端只是显示层预填，这里的结果才是权威）。
    全程只读画像对象，**不写回** `profiles`（AC-3：临时岗位不得污染长期资产）。
    """
    patch = patch or InterviewSettingsPatch()
    role = _role_text(patch.target_role or (profile.target_role if profile is not None else None))
    if patch.years_experience is not None:
        band = _band_text(patch.years_experience)
    elif profile is not None:
        band = _band_text(rules.experience_band_of(profile.years_experience))
    else:
        band = rules.DEFAULT_EXPERIENCE_BAND
    market = _market_text(patch.market)
    size = _company_text(patch.company_size)
    return InterviewSettings.model_validate(
        {
            "target_role": role,
            "years_experience": band,
            "market": market,
            "company_size": size,
        }
    )


def calibration_of(settings: InterviewSettings) -> dict[str, str]:
    """四项设定 → 提示词口径要点（纯函数，无 IO；AC-2④ 逐档可单测）。

    每档至少一条要点、档间集合互不相同：这样「改了配置但题目没变」在单测里立刻暴露。
    """
    return {
        "role": (
            f"按「{settings.target_role}」的职责与技术栈出题；"
            "与画像岗位冲突时以本项为准，项目素材尽量复用"
        ),
        "experience": _EXPERIENCE_CALIBRATION[settings.years_experience],
        "market": _MARKET_CALIBRATION[settings.market],
        "company": _COMPANY_CALIBRATION[settings.company_size],
    }


# --- 结构闸门（AC-7 双校验：开局 + 结束，同一口径） --------------------------


def _squash(text: str) -> str:
    """去掉全部空白后比对：模型改换行 / 多空格不算新题，但同一题换个说法必须能判出重复。"""
    return "".join(text.split())


def _bad_paper(reason: str) -> AppError:
    """统一的结构不合格错误：502 + 可重试，message 中文且不回显模型原文。"""
    return AppError(
        AI_SCHEMA_INVALID,
        f"本次出题不合格（{reason}），请重试一次",
        status=502,
        retryable=True,
    )


def _check_structure(kinds: list[str], prompts: list[str]) -> None:
    """数量 / 技术 / 项目 / 挑战占比 / 题干去重 —— 开局与结束共用同一份判据。"""
    total = len(kinds)
    technical = kinds.count("technical")
    project = kinds.count("project")
    challenge = sum(1 for kind in kinds if rules.is_challenge_kind(kind))
    squashed = [_squash(prompt) for prompt in prompts]

    if total < rules.MIN_INTERVIEW_QUESTIONS:
        raise _bad_paper(f"题目数量不足 {rules.MIN_INTERVIEW_QUESTIONS} 道")
    if technical < rules.MIN_TECHNICAL_QUESTIONS:
        raise _bad_paper(f"技术题不足 {rules.MIN_TECHNICAL_QUESTIONS} 道")
    if project < rules.MIN_PROJECT_QUESTIONS:
        raise _bad_paper(f"项目题不足 {rules.MIN_PROJECT_QUESTIONS} 道")
    if challenge > rules.max_challenge_count(total):
        raise _bad_paper("挑战题超过总题量的 20%")
    if len(set(squashed)) != len(squashed):
        raise _bad_paper("出现了重复的题干")


def validate_questions(questions: list[InterviewQuestion]) -> None:
    """开局闸门：计划不合格即 502，**不做静默补题**（补题等于题目与简历脱节）。"""
    _check_structure(
        [str(question.kind) for question in questions],
        [question.prompt for question in questions],
    )


def validate_session(entries: list[dict[str, Any]]) -> None:
    """结束闸门（防御性断言）：本场实际提出的发言仍满足同一份结构判据。

    名义上「开局通过 ⇒ 结束通过」由 `rules.is_follow_up_allowed` 保证（challenge 不追问、
    追问只抬高 technical/project）；这里再校验一次，被构造过的 payload 会在此拦下。
    """
    _check_structure(
        [str(entry.get("kind") or "") for entry in entries],
        [str(entry.get("prompt") or "") for entry in entries],
    )


# --- 提示词输入（结构化 JSON 投喂，不拼散文） --------------------------------


def _profile_brief(profile: Profile) -> dict[str, Any]:
    """画像 → 计划输入（只送结构化维度，不送整份简历正文，避免题目漂到无关段落）。"""
    return {
        "target_role": profile.target_role,
        "years_experience": profile.years_experience,
        "tech_stack": profile.tech_stack,
        "skills": [skill.name for skill in profile.skills],
        "projects": [
            {
                "name": project.name,
                "role": project.role,
                "period": project.period,
                "bullets": project.bullets,
            }
            for project in profile.projects
        ],
    }


def _plan_input(
    settings: InterviewSettings, calibration: dict[str, str], profile: Profile
) -> str:
    """开局输入：本场设定 + 口径要点 + 画像。AC-2③ 的可断言点就在这里（settings 逐字在 user 里）。"""
    return json.dumps(
        {
            "settings": settings.model_dump(),
            "calibration": calibration,
            "profile": _profile_brief(profile),
        },
        ensure_ascii=False,
    )


def _entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """payload 里已提出的发言（就地返回，供回写时直接更新同一份列表）。"""
    questions = payload.get("questions")
    if not isinstance(questions, list):
        return []
    return [item for item in questions if isinstance(item, dict)]


def _score_of(entry: dict[str, Any]) -> float | None:
    """已答判定：`score` 是数字才算答过（未答恒为 None，bool 不算分数）。"""
    score = entry.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    return float(score)


def _entry_of(question: InterviewQuestion) -> dict[str, Any]:
    """新发言入库形状：答案位留空，等待本轮评分回填。"""
    return {
        **question.model_dump(),
        "answer": None,
        "score": None,
        "comment": None,
        "answered_at": None,
        "elapsed_s": None,
    }


def _round_input(
    payload: dict[str, Any],
    target: dict[str, Any],
    entries: list[dict[str, Any]],
    text: str,
    settings: InterviewSettings,
    calibration: dict[str, str],
) -> str:
    """单轮输入：设定 / 口径 / 最近 3 轮全文 + 更早题面摘要 + 当前题 + 作答 + 下一步与配额。

    AC-6 的可断言点：`history` 里逐字带上一答原文；AC-2③：settings 四键每轮都在。
    """
    target_id = str(target.get("id") or "")
    answered = [
        entry
        for entry in entries
        if _score_of(entry) is not None and str(entry.get("id") or "") != target_id
    ]
    recent = answered[-HISTORY_WINDOW:]
    earlier = answered[:-HISTORY_WINDOW]
    plan = payload.get("plan")
    plan_index = payload.get("plan_index")
    plan_item: dict[str, Any] | None = None
    if isinstance(plan, list) and isinstance(plan_index, int) and plan_index + 1 < len(plan):
        candidate = plan[plan_index + 1]
        if isinstance(candidate, dict):
            plan_item = {
                "kind": candidate.get("kind"),
                "prompt": candidate.get("prompt"),
                "hint": candidate.get("hint"),
            }
    follow_up_count = int(payload.get("follow_up_count") or 0)
    return json.dumps(
        {
            "settings": settings.model_dump(),
            "calibration": calibration,
            "history": [
                {
                    "id": entry.get("id"),
                    "kind": entry.get("kind"),
                    "prompt": entry.get("prompt"),
                    "answer": entry.get("answer"),
                    "score": _score_of(entry),
                }
                for entry in recent
            ],
            "earlier": [{"id": entry.get("id"), "prompt": entry.get("prompt")} for entry in earlier],
            "current": {
                "id": target.get("id"),
                "kind": target.get("kind"),
                "prompt": target.get("prompt"),
                "hint": target.get("hint"),
            },
            "answer": text,
            "next_plan": plan_item,
            "quota": {
                "follow_ups_left": max(0, rules.MAX_FOLLOW_UPS - follow_up_count),
                "turns_left": max(0, rules.MAX_INTERVIEW_TURNS - len(entries)),
            },
            "allow_follow_up": rules.is_follow_up_allowed(
                str(target.get("kind") or ""), follow_up_count, len(entries)
            ),
        },
        ensure_ascii=False,
    )


# --- 下一条发言（AC-4 / AC-6 / AC-7 共同落点） ------------------------------


def _next_id(entries: list[dict[str, Any]]) -> str:
    """发言 id 单调：`id = iq-{已提出条数 + 1}`，刷新与重试都不会跳号。"""
    return f"{QUESTION_ID_PREFIX}-{len(entries) + 1}"


def _next_question(
    payload: dict[str, Any],
    target: dict[str, Any],
    draft: NextDraft | None,
    entries: list[dict[str, Any]],
) -> InterviewQuestion | None:
    """决定下一条发言：① 追问（受守门约束）→ ② 计划下一正题 → ③ 存量 v1 卷未答条目 → None。

    追问被守门拦下（challenge 父题 / 配额用尽 / 题面空或重复）时**静默降级**为第 ② 步：
    提问不受影响，整轮绝不因文案问题 502。计划正题一律取计划原文，不让模型改写（避免配比漂移）。
    """
    prompt = (draft.prompt or "").strip() if draft is not None else ""
    known = {_squash(str(entry.get("prompt") or "")) for entry in entries}
    if (
        draft is not None
        and str(draft.mode or "").strip() == "follow_up"
        and prompt
        and rules.is_follow_up_allowed(
            str(target.get("kind") or ""),
            int(payload.get("follow_up_count") or 0),
            len(entries),
        )
        and _squash(prompt) not in known
    ):
        hint = (draft.hint or "").strip() or DEFAULT_HINT
        return InterviewQuestion(
            id=_next_id(entries),
            kind=target.get("kind"),
            prompt=prompt,
            hint=hint,
            parent_id=str(target.get("id") or ""),
        )

    plan = payload.get("plan")
    if isinstance(plan, list) and plan:
        plan_index = payload.get("plan_index")
        index = plan_index if isinstance(plan_index, int) else 0
        if index + 1 < len(plan) and isinstance(plan[index + 1], dict):
            item = plan[index + 1]
            text = str(item.get("prompt") or "").strip()
            if text:
                payload["plan_index"] = index + 1
                return InterviewQuestion(
                    id=_next_id(entries),
                    kind=item.get("kind") or "technical",
                    prompt=text,
                    hint=str(item.get("hint") or "").strip() or DEFAULT_HINT,
                )
        return None

    # ③ 存量 v1 成品试卷（无 `plan`，§1.2「历史残留 running 可续答」）：按原卷顺序投放
    # 下一条未答条目。全部答完才返回 None，交棒给结束闸门（与 v2 同一判据）。
    for entry in entries:
        if str(entry.get("id") or "") == str(target.get("id") or ""):
            continue
        if _score_of(entry) is None:
            prompt_text = str(entry.get("prompt") or "").strip()
            if not prompt_text:
                continue
            return InterviewQuestion(
                id=str(entry.get("id") or _next_id(entries)),
                kind=entry.get("kind") or "technical",
                prompt=prompt_text,
                hint=str(entry.get("hint") or "").strip() or DEFAULT_HINT,
                parent_id=entry.get("parent_id"),
            )
    return None


# --- 开局（AC-4：只投放第 1 条发言） -----------------------------------------


async def create_run(
    profile_id: str,
    settings: InterviewSettingsPatch | None = None,
    *,
    client: AIClient | None = None,
) -> InterviewRun:
    """读画像 → 补全设定 → 生成计划 → 结构闸门 → 落库 → 只返回第 1 条发言。"""
    profile = repository.get_profile(profile_id)
    if profile is None:
        raise AppError(NOT_FOUND, "没有找到这份画像，请先生成画像再来面试", status=404)

    resolved = fill_settings(settings, profile)
    calibration = calibration_of(resolved)

    ai = client or AIClient()
    draft = await ai.complete_model(
        INTERVIEW_SYSTEM, _plan_input(resolved, calibration, profile), InterviewDraft
    )
    questions = [
        InterviewQuestion(
            id=f"{QUESTION_ID_PREFIX}-{index + 1}",
            kind=item.kind,
            prompt=item.prompt.strip(),
            hint=item.hint.strip() or DEFAULT_HINT,
        )
        for index, item in enumerate(draft.questions)
    ]
    validate_questions(questions)

    plan = [
        {"kind": str(question.kind), "prompt": question.prompt, "hint": question.hint}
        for question in questions
    ]
    first = questions[0]
    payload: dict[str, Any] = {
        "version": 2,
        "settings": resolved.model_dump(),
        "calibration": calibration,
        "plan": plan,
        "plan_index": 0,
        "questions": [_entry_of(first)],
        "answered_count": 0,
        "total": len(plan),
        "follow_up_count": 0,
        "turn": 0,
        "current_id": first.id,
    }
    run_id = uuid.uuid4().hex
    repository.insert_run(run_id, INTERVIEW_KIND, profile_id, payload)
    return InterviewRun(run_id=run_id, settings=resolved, question=first, total=len(plan))


# --- 逐轮评分 + 下一条发言（先算后写，AC-10） --------------------------------


def _total_of(payload: dict[str, Any], entries: list[dict[str, Any]]) -> int:
    """结构分母：优先 = 计划长度（追问不放大本题数）；v1 payload 回落到它自己的 `total`。"""
    plan = payload.get("plan")
    if isinstance(plan, list) and plan:
        return len(plan)
    total = payload.get("total")
    if isinstance(total, int) and not isinstance(total, bool) and total > 0:
        return total
    return len(entries)


def _settings_of(payload: dict[str, Any]) -> InterviewSettings:
    """提示词用的设定回读：v1 payload 没有 `settings` 时回落默认值，只为让提示词有口径。"""
    raw = payload.get("settings")
    if isinstance(raw, dict):
        try:
            return InterviewSettings.model_validate(raw)
        except ValidationError:
            pass
    return fill_settings(None, None)


def _settings_or_none(payload: dict[str, Any]) -> InterviewSettings | None:
    """读取侧的 `settings`（TECHNICAL §1.2）：**缺失 / 缺键 / 越出闭集一律 null**。

    与 `_settings_of`（提示词兜底，宁可给默认口径）刻意分开：展示与回溯必须区分
    「真的记了设定」和「老 run 没记设定」，前端据此显示「未记录设定」而不是伪造成默认值。
    解析口径不在这里另写一份：唯一实现在 `rules.settings_or_none`（QA D-5：会话页与
    历史/报告页必须给出同一答案）。
    """
    return rules.settings_or_none(payload)


def _calibration_of(payload: dict[str, Any], settings: InterviewSettings) -> dict[str, str]:
    """口径要点回读：payload 里的快照优先（旧 run 缺失就按当前设定重算，纯函数无副作用）。"""
    raw = payload.get("calibration")
    if isinstance(raw, dict) and raw:
        return {str(key): str(value) for key, value in raw.items()}
    return calibration_of(settings)


async def score_answer(
    run_id: str, question_id: str, answer: str, *, client: AIClient | None = None
) -> InterviewTurn:
    """一次轮次：评分当前发言 + 决定下一条发言；答满最后一条即把 run 置 `completed`。"""
    run = repository.get_run(run_id)
    if run is None or str(run.get("kind") or "") != INTERVIEW_KIND:
        raise AppError(NOT_FOUND, "没有找到这次面试记录，请先开始一次面试", status=404)
    if str(run.get("status") or "") == RUN_COMPLETED:
        raise AppError(VALIDATION_ERROR, "这场面试已经结束，可重开一场", status=400)

    payload: dict[str, Any] = dict(run.get("payload") or {})
    entries = _entries(payload)
    target = next((entry for entry in entries if str(entry.get("id") or "") == question_id), None)
    if target is None:
        raise AppError(NOT_FOUND, "这次面试里没有这道题，请刷新页面后重试", status=404)

    text = answer.strip()
    if not text:
        raise AppError(VALIDATION_ERROR, "回答不能为空，请写下你的思路再提交", status=400)

    # 会话是「一次一问」的单向推进（AC-9 不重计分 / AC-10 幂等）：只有当前这条发言可作答。
    # 重放旧请求（网络重试 / 旧标签页 / 双击）必须拒绝，且**在任何副作用之前**返回 ——
    # 既成事实（answer / score / comment）一字不改，也不为它多花一次 AI 调用。
    current_id = payload.get("current_id")
    if not isinstance(current_id, str) or not current_id:
        current_id = _current_of(payload, entries)  # v1 payload 没有 current_id 的降级口径
    if current_id != question_id:
        raise AppError(
            VALIDATION_ERROR,
            "这道题已经答过了，请回答当前这道题（刷新页面可从上次进度继续）",
            status=400,
        )

    settings = _settings_of(payload)
    calibration = _calibration_of(payload, settings)
    ai = client or AIClient()
    started = time.perf_counter()
    draft = await ai.complete_model(
        ROUND_SYSTEM,
        _round_input(payload, target, entries, text, settings, calibration),
        RoundDraft,
        timeout_s=SCORING_TIMEOUT_S,
    )
    elapsed_s = round(time.perf_counter() - started, 1)

    # 以下全部在内存里完成：任何异常都不会留下新发言 / 新分数 / 新 status（AC-10）。
    score = float(draft.score)
    comment = draft.comment.strip()[:MAX_COMMENT_CHARS] or DEFAULT_COMMENT
    # v1 payload 没有 `current_id`：按「首个未答发言」推导当前发言，续答才不会被当成重答旧题。
    status = str(run.get("status") or RUN_RUNNING)
    next_question: InterviewQuestion | None = None

    # 走到这里 `question_id` 必然是当前待答发言（上面已拒绝重放），因此本轮一定推进会话。
    next_question = _next_question(payload, target, draft.next, entries)
    if next_question is None:
        # 结束闸门：用「已回填本轮分数」的副本校验，不合格 502 且本轮分数也不落库。
        scored = {**target, "score": score, "comment": comment}
        validate_session([scored if entry is target else entry for entry in entries])
        payload["current_id"] = None
        status = RUN_COMPLETED
    else:
        if not any(str(entry.get("id") or "") == next_question.id for entry in entries):
            entries.append(_entry_of(next_question))
        payload["current_id"] = next_question.id
        if next_question.parent_id is not None:
            payload["follow_up_count"] = int(payload.get("follow_up_count") or 0) + 1
        payload["turn"] = int(payload.get("turn") or 0) + 1

    target.update(
        {
            "answer": text,
            "score": score,
            "comment": comment,
            "answered_at": datetime.now(UTC).isoformat(),
            "elapsed_s": elapsed_s,
        }
    )
    payload["questions"] = entries
    answered_count = sum(1 for entry in entries if _score_of(entry) is not None)
    payload["answered_count"] = answered_count
    payload["total"] = _total_of(payload, entries)
    repository.save_run(run_id, payload, status)
    if status == RUN_COMPLETED:
        # 时间线是旁路：写失败自行返回 None，绝不打断「答完最后一题」（r3 AC-1/AC-3）。
        timeline.record_run_event(
            {"id": run_id, "kind": INTERVIEW_KIND, "payload": payload, "status": status}
        )
    return InterviewTurn(
        score=score,
        comment=comment,
        next_question=next_question,
        run_status=status,
        answered_count=answered_count,
        total=payload["total"],
        interview_avg=score_of(INTERVIEW_KIND, payload),
    )


# --- 会话读取（AC-9：刷新 / 重进恢复） --------------------------------------


def _session_question(entry: dict[str, Any]) -> InterviewSessionQuestion:
    """单条发言投影：未答字段保持 None；越界的存量分数视为未评分，绝不抛错。"""
    score = _score_of(entry)
    if score is not None and not 0 <= score <= 10:
        score = None
    comment = entry.get("comment")
    return InterviewSessionQuestion(
        id=str(entry.get("id") or ""),
        kind=entry.get("kind") or "technical",
        prompt=str(entry.get("prompt") or ""),
        hint=str(entry.get("hint") or "") or DEFAULT_HINT,
        parent_id=entry.get("parent_id") if isinstance(entry.get("parent_id"), str) else None,
        answer=entry.get("answer") if isinstance(entry.get("answer"), str) else None,
        score=score,
        comment=comment if isinstance(comment, str) else None,
    )


def _current_of(payload: dict[str, Any], entries: list[dict[str, Any]]) -> str | None:
    """当前待答发言：payload 的 `current_id` 优先，缺失/已答则取首个未答（v1 降级口径）。"""
    raw = payload.get("current_id")
    if isinstance(raw, str) and raw:
        entry = next((item for item in entries if str(item.get("id") or "") == raw), None)
        if entry is not None and _score_of(entry) is None:
            return raw
    for entry in entries:
        if _score_of(entry) is None:
            entry_id = entry.get("id")
            if isinstance(entry_id, str) and entry_id:
                return entry_id
    return None


def load_session(run_id: str) -> InterviewSession:
    """读一次面试的完整会话镜像：不重出题、不重计分、不调用 AI。"""
    run = repository.get_run(run_id)
    if run is None or str(run.get("kind") or "") != INTERVIEW_KIND:
        raise AppError(NOT_FOUND, "没有找到这次面试记录，请先开始一次面试", status=404)

    payload: dict[str, Any] = dict(run.get("payload") or {})
    entries = _entries(payload)
    status = str(run.get("status") or RUN_RUNNING)
    settings = _settings_or_none(payload)
    current_id = None if status == RUN_COMPLETED else _current_of(payload, entries)
    return InterviewSession(
        run_id=run_id,
        status=status,
        settings=settings,
        questions=[_session_question(entry) for entry in entries],
        answered_count=sum(1 for entry in entries if _score_of(entry) is not None),
        total=_total_of(payload, entries),
        current_id=current_id,
        interview_avg=score_of(INTERVIEW_KIND, payload),
    )
