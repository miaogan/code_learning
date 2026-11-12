"""太傅的两个零成本出口。

r83 起，编排搬进了 `graph.py`（LangGraph），取料搬进了 `tools.py`，档案投影仍在 `brief.py`。
留在这里的只有两个**不查库、不建客户端、不消耗额度**的固定回答 —— 路由层在最前面直接调用，
用户不会因为「没问清楚」或「还没上传简历」而白等一次模型往返。
"""

from app.schemas import TaifuReply
from app.services.taifu import policy


def empty_reply() -> TaifuReply:
    """没有任何站内记录时的固定出口：不花钱、不等待、不要求配 Key。"""
    return TaifuReply(notice=policy.EMPTY_BRIEF_NOTICE)


def missing_question_reply() -> TaifuReply:
    """空问句出口：连库都不查，直接告诉用户怎么问。"""
    return TaifuReply(notice=policy.EMPTY_QUESTION_NOTICE)
