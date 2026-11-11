"""r77 太傅：只读站内档案的问答。

分层口径：
- `brief`   —— 纯函数，把服务端真值（画像 / 报告 / 测评 / 练习 / 学习）投影成「段 + 行」，段即引用白名单；
- `policy`  —— 纯函数，问句清洗、提示词拼装、回答净化与引用白名单校验；
- `taifu`   —— 编排：读库 → 调模型 → 校验 → 落对话。

**不写业务表**：本包唯一的写操作是 `repository.insert_taifu_message()`（对话本身）。
"""

from app.services.taifu import brief, policy, taifu

__all__ = ["brief", "policy", "taifu"]
