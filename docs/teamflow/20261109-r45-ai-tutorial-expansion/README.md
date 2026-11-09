# r45 · AI 工程教程内容扩充（训练原理 / 微调蒸馏 / LangChain 与 LangGraph / 名词速查）

- 需求来源：用户反馈「AI工程学习的内容是不是可以补充一些场景和框架，比如模型的基本原理、微调、蒸馏，langchain、langgraph 的使用，ai 相关关键名词解释」。
- 交付形态：纯内容扩充，**不改契约、不改筛选逻辑、不改后端**。新增 4 章（AI 工程方向 4 → 8 章，全库 36 章）。

## 1. 现状缺口

| 维度 | r44 时 AI 工程已有 | 缺口 |
|---|---|---|
| 模型原理 | 无 | 不知道 loss / 梯度 / 自回归，看不懂「为什么微调贵」 |
| 微调与蒸馏 | 无 | 分不清微调 / RAG / 蒸馏 / 量化，选型容易拍脑袋 |
| 框架 | 无 | Agent 章节只讲工具调用，没有 LangChain / LangGraph 落地路径 |
| 名词 | 散落在各章 | 没有集中速查表，面试前无法快速自测 |

## 2. 新增章节

| 章节 id | 标题 | 子方向 | 难度 | 覆盖点 |
|---|---|---|---|---|
| `ai-model-basics` | 大模型是怎么训练出来的 | LLM 与 RAG | 基础 | next-token 预训练、交叉熵、因果掩码、前向/反向/更新、显存构成、手写梯度下降、常见误解 |
| `ai-finetune-distill` | 微调、对齐与蒸馏 | LLM 与 RAG | 高级 | 全量微调 vs LoRA / QLoRA、SFT → RLHF / DPO、灾难性遗忘、知识蒸馏 / 数据蒸馏 / 量化、LoRA 配置骨架 |
| `ai-langchain-langgraph` | LangChain 与 LangGraph 编排 | Agent | 进阶 | LCEL 流水线、RAG 链拼接、StateGraph / 条件边 / checkpointer、框架选型与测试方式 |
| `ai-glossary` | AI 关键名词速查 | 通用 AI | 基础 | 训练类 8 词、推理类 12 词、工程类 10 词，每个附「常见误解」+ 易混辨析自测 |

## 3. 设计取舍

- **不新增子方向**：`rules.py::SUBDIRECTIONS` 是笔试 / 面试 / 学习的共同闭集，加新项会让笔试与练习出现「选了必然空结果」的入口。本章内容按语义落进已有子方向（模型与微调 → LLM 与 RAG；框架 → Agent；名词 → 通用 AI）。
- **难度档位仍每档有内容**：新增后 AI 工程为基础 2（`ai-llm-basics`、`ai-model-basics`）/ 进阶 2（`ai-rag`、`ai-langchain-langgraph`）/ 高级 2（`ai-transformer`、`ai-finetune-distill`），满足「每方向三档齐全」门禁。
- **代码示例只作骨架**：LangChain / LangGraph 迭代快，示例锁在「结构」层面（组件边界、状态流转），不写可复制即上线的完整工程，避免版本漂移后误导。

## 4. 验证结果

| 命令 | 结果 |
|---|---|
| `npm run typecheck` | 通过 |
| `npm run lint` | 通过（0 warning） |
| `npx vitest run src/test/tutorials.test.ts` | 26 passed |
| `npm test` | 19 文件 / 231 passed |
| `npm run build` | 通过（142 modules，3.48s） |

## 5. 已知限制

- 代码示例未在真实环境执行（仓库无 `langchain` / `langgraph` / `peft` 依赖，且不属于本产品运行时依赖）；内容按官方 API 结构编写，读者需按自身版本核对参数名。
- 教程总量变化（32 → 36）由 `TUTORIALS` 数组自动推导，目录页计数、进度条、报告页入口均无需改动。
