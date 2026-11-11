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
    # 多取一条只为判断「有没有被窗口挤掉的消息」：溢出才需要压缩记忆。
    recent = repository.list_taifu_messages(limit=policy.HISTORY_LIMIT + 1)
    overflow = len(recent) > policy.HISTORY_LIMIT
    history = recent[-policy.HISTORY_LIMIT:]
    memory = repository.get_taifu_memory()
    prompt = policy.build_user_prompt(
        sections, history, question, page, memory=memory, compact=overflow
    )
    draft = await client.complete_model(
        policy.TAIFU_SYSTEM,
        prompt,
        policy.TaifuDraftReply,
        timeout_s=TAIFU_TIMEOUT_S,
    )
    payload = policy.sanitize_reply(draft, sections)
    payload["memory_used"] = bool(memory)
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
    # 记忆与对话同批落库，且只在「窗口溢出」时更新：短线程不需要摘要，
    # 模型给了也不存（否则提示词里会出现一条其实什么也没压缩的「记忆」）。
    if overflow:
        next_memory = policy.sanitize_memory(draft.memory)
        if next_memory:
            repository.save_taifu_memory(next_memory)
    return TaifuReply(**payload)
