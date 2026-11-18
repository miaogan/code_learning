# r125 · 镜试（反向面试）：评题与复盘

- 需求来源：用户「能不能再增加一个模块 反转过来 我作为面试官用我的简历向我自己提问 然后通过ai给出满分答案 并标注为啥这么回答 已经提问问题的水准」。
- 定位：与「召对」`/api/interviews` 完全分离的独立工具页 `/mirror`。不创建面试场次、不评分、不写成长时间线、不进历史战绩与医案；结果按账号保存，刷新后可恢复复盘。
- 页面名：**镜试**（工具组，位于演武之后）。

## 1. 产品口径

每道题一条完整复盘卡，四个核心区块 + 两块防编造披露：

| 区块 | 内容 | 防编造约束 |
|---|---|---|
| 参考满分答案 | 面试官视角的理想作答 | 简历查不到的多位数/百分比降级为〈待补充〉（`answer_sanitized`） |
| 为什么这么答 | 答案结构与表达思路 | 只解释思路，不虚构经历 |
| 简历依据 | 已校验的证据（claim + 原文 quote） | quote 必须在简历原文归一化后连续命中，命不中整条剔除（`dropped_evidence_count`） |
| 缺失信息 | 待用户补充的数据/细节 | AI 只能说缺什么，不能代填 |
| 题目水准 | 基础/合格/优秀 + 优点/改进 | 是出题建议，不是作答分数 |
| 后续追问 | 面试官可能的深挖方向 | — |

两种出题方式：用户自拟问题（`source=custom`），或 AI 依据简历推荐（`source=recommended`；推荐 quote 同样过原文闸门，全被剔除时不硬凑）。仅用于练习复盘，**不做真实面试实时提词器**（ARCHITECTURE 既有边界不变）。

## 2. 技术落点

- **DDL**：`mirror_cards`（`db.py MIRROR_SCHEMA`，TEXT 主键 + JSON payload，双库幂等）；同时进 `_STANDALONE_PROBE_TABLES`（有数据时禁止空 SQLite 自动接管覆盖）。
- **repository**：`save_mirror_card / mirror_card_row / list_mirror_cards`（均按 `user_id` 隔离；payload 坏值退化空结构）。
- **service**：`services/mirror/mirror.py`——溯源工具与 r116 画像同口径（NFKC + 去 Cf + 去空白 + 尾省略号放宽），独立实现避免反向依赖画像模块；数字闸门只拦 2 位以上或带 % 的数字（单数字多为序号，误杀高）。
- **router**：`/api/mirror/suggestions|ask|cards`；输入护栏（自拟问题，`GUARDRAIL_BLOCKED` 422，且在 `client_for` 之前，被拦不扣配额）+ 输出护栏（答案 / 理由 / 追问逐条过 `guard_output`）。
- **AI**：`user_ai.client_for(user, "heavy")`，结构化补全两次调用（推荐题一次、复盘一次）；失败在入库前抛错，不留半条记录。
- **前端**：`MirrorPage.tsx`（`latestProfile` 门禁复用 `ResumeGate`；历史复盘默认展开最近一条）；`client.ts` 三方法；类型与后端 schemas 逐字镜像。

## 3. 已知边界

- 复盘列表 `GET /api/mirror/cards` 直接回完整卡（无敏感原文风险，量级为个人练习记录，limit 上限 200）。
- 跨用户按 id 取一律 404；他人 resume_id 提问也是 404（不泄露存在性）。
- 溯源归一化沿用 r116 结论：**不用 NFKC 之外的折叠**，避免中文标点回显问题。
