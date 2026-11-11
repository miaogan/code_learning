"""r77 太傅编排：读档案 → 拼提示词 → 调模型 → 白名单校验 → 落对话。

口径：
- **空档案不调模型**（零成本、零等待），直接回中文指引；
- 会话写入在模型成功之后：失败不留「有问无答」的半条历史；
- 前台交互调用，`retry_unavailable` 保持默认 False（避免用户等待翻倍）；
- 专用超时 120s：回答是自然语言短文，不该跟着画像的 600s 档位一起等。
"""

from typing import Any

from app.core import repository
from app.schemas import TaifuReply
from app.services.ai.ai import AIClient
from app.services.taifu import brief, policy

#: 回答输出只有一段文字 + 几条引用，120s 足够；与画像的 600s 档位分离（r34 之后的同类做法）。
TAIFU_TIMEOUT_S = 120


def empty_reply() -> TaifuReply:
    """没有任何站内记录时的固定出口：不花钱、不等待、不要求配 Key。"""
    return TaifuReply(notice=policy.EMPTY_BRIEF_NOTICE)


def missing_question_reply() -> TaifuReply:
    """空问句出口：连库都不查，直接告诉用户怎么问。"""
    return TaifuReply(notice=policy.EMPTY_QUESTION_NOTICE)


def gather_sections() -> list[dict[str, Any]]:
    """读当前账号的站内真值并投影成档案段（段的 href 即引用白名单）。"""
    return brief.build_sections(
        profile=repository.latest_profile(),
        report=repository.latest_report(),
        runs=repository.history_rows(limit=brief.MAX_RUNS),
        attempts=repository.list_attempts(),
        learn=repository.get_learn_progress(),
    )


async def answer(
    question: str,
    sections: list[dict[str, Any]],
    *,
    page: dict[str, str] | None = None,
    client: AIClient,
) -> TaifuReply:
    """`sections` 必须是 `gather_sections()` 的产物（href 即白名单）；`page` 来自闭集白名单。"""
    # 多取一条只为判断「有没有被窗口挤掉的消息」：溢出才需要压缩摘要。
    recent = repository.list_taifu_messages(limit=policy.HISTORY_LIMIT + 1)
    overflow = len(recent) > policy.HISTORY_LIMIT
    history = recent[-policy.HISTORY_LIMIT:]
    summary = repository.get_taifu_summary()
    memories = repository.list_taifu_memories()
    prompt = policy.build_user_prompt(
        sections,
        history,
        question,
        page,
        summary=summary,
        memories=[item["content"] for item in memories],
        compact=overflow,
    )
    draft = await client.complete_model(
        policy.TAIFU_SYSTEM,
        prompt,
        policy.TaifuDraftReply,
        timeout_s=TAIFU_TIMEOUT_S,
    )
    payload = policy.sanitize_reply(draft, sections)
    payload["summary_used"] = bool(summary)
    payload["memories_used"] = len(memories)
    if not payload["reply"]:
        # 没有回答就不写历史：避免下次打开时看到一串「有问无答」的对话。
        return TaifuReply(**payload)

    repository.insert_taifu_message(role="user", content=question)
    assistant_row = repository.insert_taifu_message(
        role="assistant",
        content=payload["reply"],
        citations=payload["citations"],
    )
    payload["created_at"] = assistant_row["created_at"]
    # 摘要与对话同批落库，且只在「窗口溢出」时更新：短线程不需要压缩，
    # 模型给了也不存（否则提示词里会出现一条其实什么也没压缩的「摘要」）。
    if overflow:
        next_summary = policy.sanitize_summary(draft.summary)
        if next_summary:
            repository.save_taifu_summary(next_summary)
    # 长期记忆与摘要独立：不要求溢出、也不随清空对话消失。
    # 去重在 policy 里做（与已有条目互相包含即视为同一件事），这里只写留下来的那几条。
    new_memories = policy.sanitize_memories(
        draft.memories, [item["content"] for item in memories]
    )
    for content in new_memories:
        repository.insert_taifu_memory(content)
    payload["memories_added"] = len(new_memories)
    return TaifuReply(**payload)
