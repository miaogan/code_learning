"""模拟面试（AC-3）：按画像出 ≥8 题（≥5 技术 + ≥3 项目深挖，挑战题 ≤20%）并逐题 0–10 评分。

契约：
- `create_run` 返回 `InterviewRun`（**不含答案/分数**），并把题目全量写入 `runs.payload`
  （形状见 TECHNICAL §1.2：每题带 `answer/score/comment/answered_at/elapsed_s` 空位）。
- `score_answer` 单题评分 `timeout_s=14`（< AC-3 的 15s），逐题回写 payload；
  `answered_count == total` 时才置 `completed`；重答同一题=覆盖旧分（幂等，不累加）。
- 出题不合格（数量 / 配比 / 题干重复）**一律 502，不做静默补题** —— 补题等于题目与简历脱节（anti-goal 2）。
- AI 全部经 `client=` 注入（TECHNICAL §6.1），测试零网络。
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .. import repository
from ..errors import AI_SCHEMA_INVALID, NOT_FOUND, VALIDATION_ERROR, AppError
from ..repository import RUN_COMPLETED, RUN_RUNNING
from ..schemas import InterviewQuestion, InterviewRun, Profile, ScoreResult
from . import rules
from .ai import AIClient

#: 单题评分超时：AC-3 要求 15s 内出分，留 1s 给网络与落库（默认 20s 太宽，见 TECHNICAL §5）。
SCORING_TIMEOUT_S = 14.0

#: 点评字数上限（DESIGN §2.3 同卡出分的点评区按两行展示）；超长不报错，截断即可。
MAX_COMMENT_CHARS = 120

#: run.kind 取值：仅本次面试 run 允许评分回写。
INTERVIEW_KIND = "interview"

#: 题目 id 前缀（报告页证据 chip 与 `question_ref` 都直接引用它，不得随意更改）。
QUESTION_ID_PREFIX = "iq"

INTERVIEW_SYSTEM = """你是程序员模拟面试官。依据用户的简历画像出一套可逐题作答的面试题，只输出 JSON 对象。

输出格式：
{"questions":[{"id":"iq-1","kind":"technical|project|challenge","prompt":"题面（≤120 字）","hint":"作答提示（≤40 字）"}]}

硬性规则：
1. 共 8 道题：technical ≥5、project ≥3，challenge ≤2（challenge 占总题量不超过 20%）。
2. technical 题必须对准画像里的 tech_stack / skills；project 题必须点名画像里的具体项目；
   challenge 题给一个超出舒适区的场景题，并允许没有标准答案。
3. 每题 prompt 必须互不相同，不得换句话重复同一道题。
4. id 按 iq-1、iq-2 …… 顺序编号。
5. 只输出 JSON 对象本身：不要代码围栏，不要注释，不要额外解释。"""

SCORE_SYSTEM = """你是面试评估官。根据题目与候选人的回答给出 0–10 分（一位小数）与中文点评，只输出 JSON：
{"score": 数字, "comment": "点评（≤120 字）"}

评分口径：
- 0–3：答非所问、空泛套话或与题目无关；
- 4–6：有基本思路，但缺具体做法、缺量化结果；
- 7–8：结构清楚，讲出具体做法与结果；
- 9–10：有取舍权衡，且有可验证的效果。

点评要求：先一句说明得分理由，再一条具体可改的改进点；不要复述题目，不要编造候选人没说的经历。"""


class InterviewDraft(BaseModel):
    """出题响应模型（内部模型，不进 HTTP 契约；`run_id` 之类多余字段忽略）。"""

    model_config = ConfigDict(extra="ignore")

    questions: list[InterviewQuestion]


class ScoreDraft(BaseModel):
    """评分响应模型（内部模型）：分数硬约束 0–10，点评按 `MAX_COMMENT_CHARS` 截断。"""

    model_config = ConfigDict(extra="ignore")

    score: float = Field(ge=0, le=10)
    comment: str = ""


# --- 出题 -----------------------------------------------------------------


def _squash(text: str) -> str:
    """去掉全部空白后比对：模型改换行 / 多空格不算新题，但同一题换个说法必须能判出重复。"""
    return "".join(text.split())


def _profile_brief(profile: Profile) -> str:
    """画像 → 出题输入（只送结构化维度，不送整份简历正文，避免题目漂到无关段落）。"""
    return json.dumps(
        {
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
        },
        ensure_ascii=False,
    )


def _bad_paper(reason: str) -> AppError:
    """统一的出题不合格错误：502 + 可重试，message 中文且不回显模型原文。"""
    return AppError(
        AI_SCHEMA_INVALID,
        f"本次出题不合格（{reason}），请重试一次",
        status=502,
        retryable=True,
    )


def validate_questions(questions: list[InterviewQuestion]) -> None:
    """出题配比闸门：数量 / 技术 / 项目 / 挑战题占比 / 题干去重，任一不达标即 502。

    独立成函数是为了被单测直接钉住口径（`test_interview_service` 的配比例）。
    """
    total = len(questions)
    kinds = [question.kind for question in questions]
    technical = kinds.count("technical")
    project = kinds.count("project")
    challenge = sum(1 for kind in kinds if rules.is_challenge_kind(kind))
    prompts = [_squash(question.prompt) for question in questions]

    if total < rules.MIN_INTERVIEW_QUESTIONS:
        raise _bad_paper(f"题目数量不足 {rules.MIN_INTERVIEW_QUESTIONS} 道")
    if technical < rules.MIN_TECHNICAL_QUESTIONS:
        raise _bad_paper(f"技术题不足 {rules.MIN_TECHNICAL_QUESTIONS} 道")
    if project < rules.MIN_PROJECT_QUESTIONS:
        raise _bad_paper(f"项目题不足 {rules.MIN_PROJECT_QUESTIONS} 道")
    if challenge > rules.max_challenge_count(total):
        raise _bad_paper("挑战题超过总题量的 20%")
    if len(set(prompts)) != len(prompts):
        raise _bad_paper("出现了重复的题干")


async def create_run(profile_id: str, *, client: AIClient | None = None) -> InterviewRun:
    """读画像 → 出题 → 配比校验 → 题目入 payload（答案位留空）→ 返回题目清单。"""
    profile = repository.get_profile(profile_id)
    if profile is None:
        raise AppError(NOT_FOUND, "没有找到这份画像，请先生成画像再来面试", status=404)

    ai = client or AIClient()
    draft = await ai.complete_model(INTERVIEW_SYSTEM, _profile_brief(profile), InterviewDraft)
    validate_questions(draft.questions)

    questions = [
        InterviewQuestion(
            id=f"{QUESTION_ID_PREFIX}-{index + 1}",
            kind=question.kind,
            prompt=question.prompt.strip(),
            hint=question.hint.strip() or "结合具体经历，说明做法、取舍与结果",
        )
        for index, question in enumerate(draft.questions)
    ]
    payload: dict[str, Any] = {
        "questions": [
            {
                **question.model_dump(),
                "answer": None,
                "score": None,
                "comment": None,
                "answered_at": None,
                "elapsed_s": None,
            }
            for question in questions
        ],
        "answered_count": 0,
        "total": len(questions),
    }
    run_id = uuid.uuid4().hex
    repository.insert_run(run_id, INTERVIEW_KIND, profile_id, payload)
    return InterviewRun(run_id=run_id, questions=questions)


# --- 逐题评分 -------------------------------------------------------------


def _entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """payload 里的题目条目（就地返回，供回写时直接更新同一份列表）。"""
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


def _scoring_input(entry: dict[str, Any], answer: str) -> str:
    """评分输入：题干 + 提示 + 候选人作答（结构化投喂，避免把回答当成新指令）。"""
    return json.dumps(
        {
            "kind": entry.get("kind"),
            "prompt": entry.get("prompt"),
            "hint": entry.get("hint"),
            "answer": answer,
        },
        ensure_ascii=False,
    )


async def _score_once(ai: AIClient, entry: dict[str, Any], answer: str) -> ScoreDraft:
    """单题评分：14s 预算直接由 `AIClient.complete_model(timeout_s=...)` 控制（TECHNICAL §5）。

    AC-3 的「15s 内出分」不再依赖服务层 `asyncio.wait_for` 兜底：客户端参数是唯一入口，
    超时统一由 `ai.py` 映射为 `AI_UNAVAILABLE` + 503 + retryable，不会抛裸 `TimeoutError`。
    """
    system, user = SCORE_SYSTEM, _scoring_input(entry, answer)
    return await ai.complete_model(system, user, ScoreDraft, timeout_s=SCORING_TIMEOUT_S)


async def score_answer(
    run_id: str, question_id: str, answer: str, *, client: AIClient | None = None
) -> ScoreResult:
    """单题作答 → 0–10 分并回写 payload；答满最后一题即把 run 置 `completed`。"""
    run = repository.get_run(run_id)
    if run is None or str(run.get("kind") or "") != INTERVIEW_KIND:
        raise AppError(NOT_FOUND, "没有找到这次面试记录，请先开始一次面试", status=404)

    payload: dict[str, Any] = dict(run.get("payload") or {})
    entries = _entries(payload)
    target = next(
        (entry for entry in entries if str(entry.get("id") or "") == question_id), None
    )
    if target is None:
        raise AppError(NOT_FOUND, "这次面试里没有这道题，请刷新页面后重试", status=404)

    text = answer.strip()
    if not text:
        raise AppError(VALIDATION_ERROR, "回答不能为空，请写下你的思路再提交", status=400)

    ai = client or AIClient()
    started = time.perf_counter()
    draft = await _score_once(ai, target, text)
    elapsed_s = round(time.perf_counter() - started, 1)

    comment = draft.comment.strip()[:MAX_COMMENT_CHARS] or "已记录本次作答，建议补充量化结果"
    target.update(
        {
            "answer": text,
            "score": float(draft.score),
            "comment": comment,
            "answered_at": datetime.now(UTC).isoformat(),
            "elapsed_s": elapsed_s,
        }
    )

    answered_count = sum(1 for entry in entries if _score_of(entry) is not None)
    payload["questions"] = entries
    payload["answered_count"] = answered_count
    payload["total"] = len(entries)
    status = RUN_COMPLETED if answered_count >= len(entries) and entries else RUN_RUNNING
    repository.save_run(run_id, payload, status)
    return ScoreResult(score=float(draft.score), comment=comment)
