# r34：画像生成超时治理

## 现象与定位

用户实测失败文案：**「AI 服务响应超时，请稍后重试」**（r33 之后能看到了具体原因）。

排查链路：

- 文案来自 `AIClient._chat` 的 `httpx.TimeoutException` 分支（`AI_UNAVAILABLE`，retryable=True）。
- 生效配置（`backend/.env`）：`AI_BASE_URL=https://api.deepseek.com/v1`、`AI_MODEL=deepseek-chat`、
  **`AI_TIMEOUT_S=20`**、`AI_MAX_RETRIES=1`。
- `generate_profile` 未传 `timeout_s`，因此吃全局 20s。而该调用要求模型输出
  「技能 / 技术栈 / 项目 / 逐条 source_quote」的大 JSON，真实体量简历上耗时很容易超过 20s：
  本地实测 448 字简历约 2~4s，1048 字 / 6 章节简历已到 **11s**，再长或遇到模型高峰必然撞线。
- 另外 `complete_model` 的重试只覆盖「JSON 结构不符」，**超时立刻判死** —— 一次网络抖动就让
  整个后台任务失败。

## 修复

1. `services/ai.py`：`complete_model` 新增 `retry_unavailable: bool = False`。
   开启时，`retryable=True` 的失败（超时 / 5xx / 429）按 `ai_max_retries` 自动重来；
   `retryable=False`（鉴权 / 额度 / 参数）即使开启也不重发，避免重复扣配额。
   **默认关闭**：前台交互调用（面试、润色、报告）保持一次超时立刻返回，不让用户等待翻倍。
2. `services/profile.py`：新增 `PROFILE_TIMEOUT_S = 120.0`，`generate_profile` 显式传入并开启
   `retry_unavailable=True`。生成自 r30 起就是后台任务，用户不在同步等待，拉长超时不伤交互。
3. 无需改前端：失败原因经 `profile_jobs.error` 原样展示，重试入口已有。

## 验证

- 新增 `tests/test_ai_timeout_retry.py`（4 条，零网络）：
  超时在开启时重试并成功（calls=2）；未开启时一次即失败（calls=1）；
  401 类拒绝即使开启也不重试（calls=1）；`generate_profile` 确实传了长超时且开启重试。
- 顺带补齐 `tests/conftest.py`、`test_resume_hints.py`、`test_resume_polish.py` 里假
  `complete_model` 的新参数签名。
- 真实链路：1048 字 / 6 章节 docx 上传 → 200 全通 → **11s** 完成并进「查看画像」。
- `ruff` 全绿；后端全量回归通过。

## 经验

- 超时值要按「调用形态」区分：交互式一次问答 20s 合理，离线/后台的大结构化生成必须单独放宽。
- 后台任务的失败治理要和前台一致地给「可重试」语义，否则一次抖动就变成用户可见的失败。
