"""r67 生成层：一条雷达技术 → 学习章节草稿 + 练习题样例（**样例仅供复核，不自动入库**）。

生成的 id 一律带 `radar-` 前缀：官方 40 章教程 id 是固定清单，雷达草稿天然落在另一个命名空间，
不维护「40 个 id 的只读副本」也就不存在清单漂移。题目 id 还带 job_id，两次生成不会互相覆盖
（`questions` 表是 `ON CONFLICT DO NOTHING`，同 id 第二次写入不会改已有行）。

自检在这里做、且**只做结构与闭集校验**：题干长度、选项数、答案键必须落在选项里、解析非空。
不合格的条目直接丢弃并计数（不静默修改），由「国子监」页如实展示「已丢弃 N 条」。
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.services.ai.ai import AIClient
from app.services.radar import normalize, rules
from app.services.report.rules import DIFFICULTIES, ESSENTIALITIES

#: 章节小节的条数区间（少于 2 节说明模型没展开，多于 6 节后台读起来太长）。
MIN_SECTIONS = 2
MAX_SECTIONS = 6
#: 题干 / 解析的最小长度（低于这个量级基本是占位文本）。
MIN_PROMPT_CHARS = 10
MIN_EXPLANATION_CHARS = 10
#: 选项数量区间：判断题为 2 个，单选 / 多选 3–4 个。
JUDGE_OPTIONS = 2
MIN_OPTIONS = 3
MAX_OPTIONS = 4
#: 题型闭集（与笔试题库 `kind` 同口径）。
KINDS = ("single", "multiple", "judge")
#: 章节档位闭集（与教程 `level` 同口径）。
LEVELS = ("basic", "intermediate", "advanced")

GENERATE_SYSTEM = """你是「逃跑计划」的课程编辑，为一位工程师写一份**新技术的入门草稿**。

给定一条技术快照，产出两样东西：
1. 一份学习章节草稿：2–6 个小节，每节一段 100–200 字中文正文 + 2–4 条要点；
2. 3–5 道练习题样例：single（单选）/ multiple（多选）/ judge（判断）。

硬性规则：
1. 只依据给定快照写「这是什么 / 解决什么问题 / 什么时候用 / 最小上手路径 / 常见坑」，
   不编造版本号、发布日期、star 数、性能基准或「官方推荐」等未经给出的事实。
2. 每道题必须给出 options（判断题为 A 正确 / B 错误两项）、answer（选项 key 的数组）与
   不少于 20 字的 explanation；answer 里的每个 key 都必须出现在 options 里。
3. 全部中文，只输出 JSON，不要解释性文字或 Markdown。"""


class SectionDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    body: str = ""
    bullets: list[str] = Field(default_factory=list)


class ChapterDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    summary: str = ""
    level: str = ""
    sections: list[SectionDraft] = Field(default_factory=list)


class OptionDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str = ""
    text: str = ""


class QuestionDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: str = ""
    difficulty: str = ""
    essentiality: str = ""
    prompt: str = ""
    options: list[OptionDraft] = Field(default_factory=list)
    answer: list[str] = Field(default_factory=list)
    explanation: str = ""


class GenerateDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chapter: ChapterDraft = Field(default_factory=ChapterDraft)
    questions: list[QuestionDraft] = Field(default_factory=list)


def _clean_key(text: str) -> str:
    """选项 key 只留一个大写字母（A–F），其余一律视为无效。"""
    key = re.sub(r"[^A-Z]", "", (text or "").strip().upper())[:1]
    return key


def build_user_prompt(item: dict[str, Any], verdict: str) -> str:
    return "\n".join(
        [
            f"技术名称：{item.get('name')}",
            f"方向：{item.get('direction')} / {item.get('sub_direction')}",
            f"简介：{item.get('summary') or '（无）'}",
            f"链接：{item.get('url') or '（无）'}",
            f"雷达结论：{verdict}",
            f"题目数量上限：{get_settings().radar_gen_max_questions}",
        ]
    )


def clean_chapter(
    draft: ChapterDraft, item: dict[str, Any], chapter_id: str
) -> dict[str, Any] | None:
    """章节草稿 → 可展示章节；小节不足 `MIN_SECTIONS` 视为不合格（返回 None）。"""
    title = normalize.clean_text(draft.title or item.get("name") or "未命名章节", 120)
    sections: list[dict[str, Any]] = []
    for index, section in enumerate(draft.sections[:MAX_SECTIONS], start=1):
        section_title = normalize.clean_text(section.title, 80)
        body = normalize.clean_text(section.body, 600)
        if not section_title or not body:
            continue
        bullets = [normalize.clean_text(b, 120) for b in section.bullets if normalize.clean_text(b, 120)]
        sections.append(
            {
                "id": f"{chapter_id}-s{index}",
                "title": section_title,
                "body": body,
                "bullets": bullets[:4],
            }
        )
    if len(sections) < MIN_SECTIONS:
        return None
    level = draft.level if draft.level in LEVELS else "intermediate"
    return {
        "id": chapter_id,
        "title": title,
        "direction": str(item.get("direction") or ""),
        "sub_direction": str(item.get("sub_direction") or ""),
        "level": level,
        "summary": normalize.clean_text(draft.summary, 200),
        "sections": sections,
    }


def clean_question(
    draft: QuestionDraft,
    item: dict[str, Any],
    question_id: str,
) -> dict[str, Any] | None:
    """单题自检：题型闭集、选项成对、答案键 ⊆ 选项键、解析足够长。任一不过 → None。"""
    kind = draft.kind if draft.kind in KINDS else "single"
    options: list[dict[str, str]] = []
    for option in draft.options[:MAX_OPTIONS]:
        key = _clean_key(option.key)
        text = normalize.clean_text(option.text, 160)
        if not key or not text or any(o["key"] == key for o in options):
            continue
        options.append({"key": key, "text": text})
    expected_min = JUDGE_OPTIONS if kind == "judge" else MIN_OPTIONS
    if len(options) < expected_min:
        return None
    if kind == "judge" and len(options) != JUDGE_OPTIONS:
        return None
    keys = {option["key"] for option in options}
    answer = [key for key in (_clean_key(a) for a in draft.answer) if key in keys]
    answer = list(dict.fromkeys(answer))
    if not answer:
        return None
    if kind != "multiple" and len(answer) != 1:
        return None
    prompt = normalize.clean_text(draft.prompt, 400)
    if len(prompt) < MIN_PROMPT_CHARS:
        return None
    explanation = normalize.clean_text(draft.explanation, 600)
    if len(explanation) < MIN_EXPLANATION_CHARS:
        return None
    difficulty = draft.difficulty if draft.difficulty in DIFFICULTIES else "basic"
    essentiality = draft.essentiality if draft.essentiality in ESSENTIALITIES else "advanced"
    return {
        "id": question_id,
        "direction": str(item.get("direction") or ""),
        "sub_direction": str(item.get("sub_direction") or ""),
        "kind": kind,
        "difficulty": difficulty,
        "essentiality": essentiality,
        "prompt": prompt,
        "options": options,
        "answer": answer,
        "source": "radar",
        "language": "",
        "explanation": explanation,
    }


def build_samples(
    draft: GenerateDraft,
    item: dict[str, Any],
    job_id: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], int]:
    """草稿 → `(章节, 通过自检的题目, 被丢弃的题数)`。题数上限只夹在通过自检之后。"""
    limit = max(int(get_settings().radar_gen_max_questions), 1)
    direction, sub = rules.normalize_direction(
        item.get("direction"), str(item.get("sub_direction") or "")
    )
    item = {**item, "direction": direction, "sub_direction": sub}
    chapter_id = f"radar-{job_id}-chapter"
    chapter = clean_chapter(draft.chapter, item, chapter_id)
    questions: list[dict[str, Any]] = []
    seen: set[str] = set()
    discarded = 0
    for index, raw in enumerate(draft.questions, start=1):
        question = clean_question(raw, item, f"radar-{job_id}-q{index}")
        if question is None:
            discarded += 1
            continue
        if question["prompt"] in seen:
            discarded += 1
            continue
        seen.add(question["prompt"])
        questions.append(question)
    return chapter, questions[:limit], discarded


async def generate(
    item: dict[str, Any], verdict: str, job_id: str, client: AIClient
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], int]:
    """调一次模型，产出 `(章节, 题目, 丢弃数)`；异常不吞，由任务层转为 failed 中文原因。"""
    draft = await client.complete_model(
        GENERATE_SYSTEM,
        build_user_prompt(item, verdict),
        GenerateDraft,
        timeout_s=get_settings().radar_gen_timeout_s,
        retry_unavailable=True,
    )
    return build_samples(draft, item, job_id)
