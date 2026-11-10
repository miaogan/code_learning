# 技术方案与变更记录

## 设计

### 输入与归属

- 素材：`docs/question-bank-staging/12-acp-engineering.json`
- `source = acp-eng`，id = `acpeng-%03d`。
- 所有行：`direction="AI 工程"`、`language=""`，显式合法 `sub_direction`。
- 题型分布：single 40 / multiple 20；难度：basic 11 / intermediate 32 / challenge 17。
- 二级方向：LLM 与 RAG 12 / Agent 12 / 通用 AI 22 / Prompt 工程 5 / 部署与推理 9。

### 合并

`question_merge.py` 的 `SOURCES` / `STAGING_FILES` / `ID_PREFIX` / `SOURCE_PRIORITY` 同步登记。`SOURCE_PRIORITY` 直接引用 `SOURCES`，避免维护两份同序来源列表；优先级语义不变。

沿用 `normalize_record()`、归一化字面查重、字符 2-gram Jaccard 0.62 近重复门禁、`question_shuffle.apply()`、`question_bank.load_seed()` 复核和 `ensure_seeded()` 启动导入。无 SQL、接口或契约改动。

### ACP 大纲事实

以阿里云培训中心《阿里云大模型 ACP 考试大纲变更公告》为准：应用开发 17%、提示词 15%、检索增强 20%、微调 16%、多 Agent 及多模态 16%、生产实践 16%；官方新题型为单选 50 × 1 分、多选 25 × 2 分。URL：https://edu.aliyun.com/article/334 。

本批是补充练习，不声称是官方真题或完整模拟卷。题量按计划为 60，不为了对齐官方卷面把范围扩到 75。

### 内容复核

初稿实测为 35 单选 / 25 多选。将具有唯一最佳处理方案的 #8、#20、#24、#45 改成单选；#14 改为有唯一计算结果的 hit@10 计算题，最终 40／20。其余多选保留 2 个及以上正确项。

覆盖要点：

- 选型：私有易更新知识用 RAG、实时事实用鉴权工具、稳定格式评估微调、多步动态任务才引入 Agent。
- RAG：解析与标题／表格元数据、混合召回、重排、hit@k 与 recall@k、忠实度、版本时效与实验变量控制。
- Agent：参数纠错、429 退避、非幂等副作用超时查询、重复循环预算、部分结果、人工接管。
- 生产：限流、降级、熔断、缓存隔离与失效、输入输出安全、最小权限、审计、Tracing、告警、Token 成本。
- ACP 知识：LoRA、蒸馏、多 Agent／多模态、LlamaIndex 组件边界、托管平台发布验收。
- 面试：问题—方案—指标—踩坑，明确实测与模拟边界。

## 实际改动

- 新增 12 号 staging 素材，登记 `acp-eng` / `acpeng-`。
- `backend/app/seed/questions.json` 重算为 1224 道。
- 更新题库总量、来源、合并计数和前 260 行 SHA-256 测试基线。
- 合并器自动更新两份历史工具报表；不改历史任务夹其他内容。
- 更新 `PROVENANCE.md`、ARCHITECTURE 的当前题量与已登记前缀表、AGENTS 的变更记录。

## 选项重排说明

新增 60 道 `language=""` 题进入通用语言分桶，按既有哈希定序和均衡轮转规则，会改变部分旧题的选项 key 与位置；题干、选项文本、正确项文本和语义不变。84 道旧题解析中的选项字母引用也由既有重排器同步改写，字母引用一致性由专项测试覆盖，不能把「解析逐字不变」当作验收条件。前 260 行块仍为 199377 字节，SHA-256 按实际重算更新为 `ef125eb117f913275909a87455cdcfd14c1fa78481aae64664c6c2aa8e2803b8`。这是数据位置变化，不是产品契约或判分规则变更。

## 回滚

代码回退后，按现有 `question_merge --rollback` 删除所有登记来源（含本批），保留 260 道存量；只回退代码不会自动删除已入库的新行。不要手工删 seed 或数据库记录。
