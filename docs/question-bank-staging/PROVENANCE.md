# 素材来源与生成留痕（自建三源）

本文件是 `docs/question-bank-staging/` 下三份**自建素材**的来源凭证，关闭 r12 验收 P3-D-6。
第四份 `04-fe-interview20.json` 是第三方 MIT 素材，许可凭证在 `NOTICE-fe-interview.md`，不在本文件范围。

## 1 结论（一表看完）

| 文件 | `source` | 种子 id 前缀 | 条数 | 来源性质 | 上游 / LICENSE |
| --- | --- | --- | --- | --- | --- |
| `01-题集20.json` | `tiji` | `tiji-` | 20 | 自建：AI 生成 + 人工抽检 | 无上游，无第三方 LICENSE |
| `02-本地100题.json` | `local100` | `l100-` | 100 | 自建：AI 生成 + 人工抽检 | 无上游，无第三方 LICENSE |
| `03-七方向379题.json` | `iq380` | `iq380-` | 379 | 自建：AI 生成 + 人工抽检 | 无上游，无第三方 LICENSE |

- 合计 **499 道**（与 r12 合并报表「新增 519 = 499 自建 + 20 fe-interview」一致）。
- 三份文件内**没有任何 URL 字段**，`source_title` / `source_file` / `source_set` 均为整理期的**内部分组标记**，
  不指向外部仓库，因此不适用「MIT 需 `NOTICE-<source>.md`」流程（事实已记录于 r12 `TECH-CHANGE.md` §3.5 / §7-①）。

## 2 生成方式与时间

- 生成方式：由 AI 生成/改写题干、选项与解析（客观题口径，`kind ∈ {single, multiple, judge}`），
  再按 `rules.py` 的方向 / 语言闭集人工归位；r12 做 12 道人工抽检（每来源 3 道，任一来源正确率 <90% 整源剔除）。
- 落地时间：2026-11-02，随 r12 提交 `eada0e3` 进入仓库（任务夹 `docs/teamflow/20261102-r12-question-bank-merge/`）。
- 本文件补记：2026-11-02（r16 收口，任务夹 `docs/teamflow/20261102-r16-d4-d6-closure/`）。
- 三份素材**未引用任何第三方题目文本**；若后续发现某条与外部题库实质重合，按 r12 `TECH-CHANGE.md` §6
  剔除该条（数据只增不删，须走 `question_merge --rollback` 后重跑 `--write`）。

## 3 每份素材的结构（按文件实测）

### 3.1 `01-题集20.json`（`tiji`，20 道）

- 字段：`n` / `language` / `direction` / `kind` / `difficulty` / `essentiality` / `stem` / `options` / `answer` / `explanation`
- 题型：single 12 / multiple 4 / judge 4
- 方向：前端 12 / 后端 4 / 算法与数据结构 2 / 计算机基础 2
- 语言：js 5 / ts 2 / css 1 / html 1 / vue3 2 / react 1 / python 2 / java 1 / go 1 / 通用 4
- `n` 是源内原序号（1 起），与种子 id `tiji-%03d` 一一对应（`n=1` → `tiji-001`）。

### 3.2 `02-本地100题.json`（`local100`，100 道）

- 字段：`uid` / `source_set` / `source_title` / `source_difficulty` 等 staging 专有键（**不进种子**）
- 题型：single 75 / judge 25
- 方向：前端 26 / 后端 61 / 算法与数据结构 12 / 计算机基础 1（r12 按 `language` 纠正 8 条，见合并报表 §2）
- 语言：vue3 6 / ts 1 / html 2 / js 6 / react 3 / go 3 / java 3 / python 2 / css 6 / 通用 68
- `source_set` 是内部主题分组（4 组：「全栈基础与前端工程化」21 / 「多语言后端与数据库缓存」21 /
  「AI 工程化、RAG 与 Agent」10 / 「运维、DevOps 与系统设计」12，其余 36 条为空），
  **不是上游仓库名或第三方题集名**。
- `uid` 形如 `1-1`（组号-序号），仅供整理期定位；种子 id 由源内原序生成（`l100-%03d`），与 `uid` 不直接对应。

### 3.3 `03-七方向379题.json`（`iq380`，379 道）

- 字段：`uid` / `source_file` / `source_title` 等 staging 专有键（**不进种子**）
- 题型：single 288 / judge 91
- 方向：前端 62 / 后端 281 / 算法与数据结构 24 / 计算机基础 12（r12 按 `language` 纠正 1 条）
- 语言：vue3 14 / react 16 / ts 7 / html 6 / css 3 / js 2 / java 60 / python 60 / go 50 / 通用 161
- `source_file` 指向 7 个整理期的内部 markdown 分组（`01-frontend.md` 60 / `02-java.md` 60 / `03-python.md` 60 /
  `04-go.md` 50 / `05-ai.md` 69 / `06-devops.md` 40 / `07-system-design.md` 40）；**这些 md 未随仓库提交**，
  分组信息只保留在该字段，不是外部文件路径。
- `uid` 形如 `01-1`；种子 id 按源内原序生成（`iq380-%03d`）。

## 4 与种子 / 契约的关系

- `source` 只写进 `backend/app/seed/questions.json` 与 `questions.source` 列，**不进 HTTP 契约**
  （`backend/app/schemas.py` / `frontend/src/api/types.ts` 零改动）。
- 三源全部并入且未被去重丢弃（r12 合并报表 §2：读入 = 新增 = 20/100/379，越界 0、字面重复 0、近重复 0）。
- 可复现：`cd backend && python -X utf8 -m app.services.question_merge --check` 必须 0 差异；
  素材被改动会让该命令变红，故本目录是**输入真源**，不得随手编辑。
- 回滚：`python -X utf8 -m app.services.question_merge --rollback` 按 `tiji-` / `l100-` / `iq380-` / `fei-`
  四个前缀删库内本批行（存量 260 行不受影响）。

## 5 与 fe-interview 的边界

`04-fe-interview20.json`（20 道）是唯一第三方素材（上游 `haizlin/fe-interview`，MIT），
上游 URL、LICENSE 全文与 AI 改写说明在 `NOTICE-fe-interview.md`；
`backend/tests/test_r12_question_merge.py::test_license_notice_present_when_third_party_source_in_seed`
把它钉成机器门槛。本文件只覆盖 01/02/03 三份自建素材，不与 NOTICE 重复叙述。

## 6 追加素材 `10-ai-engineering-advanced.json`（r47，2026-11-09）

| 文件 | `source` | 种子 id 前缀 | 条数 | 来源性质 | 上游 / LICENSE |
| --- | --- | --- | --- | --- | --- |
| `10-ai-engineering-advanced.json` | `ai-adv` | `aiadv-` | 40 | 自建：AI 生成 + 人工逐条复核 | 无上游，无第三方 LICENSE |

- 面向「高级 AI 应用工程师」，全部为 AI 工程方向、`language=""` 的通用题；
  子方向分布：部署与推理 12 / LLM 与 RAG 12 / Agent 7 / Prompt 工程 6 / 通用 AI 3；
  难度：challenge 30 / intermediate 10；题型：single 24 / multiple 11 / judge 5。
- 与 01/02/03 的差异：**素材显式声明 `sub_direction`**（合法值由 `rules.SUBDIRECTIONS` 校验后随行落盘，
  非法值不猜、回落方向通用兜底），因此新题不会被统一标成「通用 AI」；老素材不带该键，键序断言不变。
- 题干与既有全库做过 2-gram Jaccard 查重（阈值 0.62，实测最高相似度 < 0.40），
  `--write` 报表确认读入 40 / 新增 40 / 越界 0 / 字面重复 0 / 近重复 0。
- 未引用任何第三方题目文本；`--check` 逐字节 0 差异是唯一幂等判据，
  回滚按 `question_merge.SOURCES` 全量删本批行（含 `aiadv-`），存量 260 行不受影响。

## 7 追加素材 `11-ai-engineering-systems.json`（r48，2026-11-09）

| 文件 | `source` | 种子 id 前缀 | 条数 | 来源性质 | 上游 / LICENSE |
| --- | --- | --- | --- | --- | --- |
| `11-ai-engineering-systems.json` | `ai-sys` | `aisys-` | 36 | 自建：AI 生成 + 人工逐条复核 | 无上游，无第三方 LICENSE |

- 承接 r47，继续面向「高级 AI 应用工程师」，但主题收敛到**系统设计与评测基础设施**，
  三组各 12 道：多 Agent 编排（`Agent`）、RAG 评审（`LLM 与 RAG`）、harness / 评测流水线工程（`通用 AI`）。
- 全部为 `difficulty=challenge`、`essentiality=advanced`、`language=""` 的 AI 工程通用题；
  题型：单选 18 / 多选 14 / 判断 4（判断「正确」「错误」各 2，避免扰动判定题极性分布）。
- 沿用 r47 的显式 `sub_direction` 通道（合法值随行落盘），三组分别落在 `Agent` / `LLM 与 RAG` / `通用 AI`；
  与 01/02/03 老素材的键序互不干扰。
- 与全库逐条做过题干 2-gram Jaccard 查重（阈值 0.62，实测 ≥0.40 的配对为 0）；
  解析不含孤立字母引用、正确项长度比均 ≤3、越界丢弃 0。
- `--write` 报表确认读入 36 / 新增 36 / 字面重复 0 / 近重复 0；
  `--check` 逐字节 0 差异是唯一幂等判据，回滚按 `question_merge.SOURCES` 全量删本批行（含 `aisys-`），
  存量 260 行不受影响。

## 8 追加素材 `12-acp-engineering.json`（r55，2026-11-10）

| 文件 | `source` | 种子 id 前缀 | 条数 | 来源性质 | 上游 / LICENSE |
| --- | --- | --- | --- | --- | --- |
| `12-acp-engineering.json` | `acp-eng` | `acpeng-` | 60 | 自建：AI 原创生成 + 逐条复核 | 无第三方题目来源，无第三方 LICENSE |

- 面向「阿里云大模型工程师 ACP 知识覆盖 + AI 应用／Agent 后端工程短板」的练习题，
  **不是官方真题或第三方题库转载**。大纲事实核对来源为阿里云培训中心
  [《阿里云大模型 ACP 考试大纲变更公告》](https://edu.aliyun.com/article/334)：
  应用开发 17% / 提示词 15% / 检索增强 20% / 微调 16% / 多 Agent 及多模态 16% / 生产实践 16%；
  官方新题型为单选 50 × 1 分、多选 25 × 2 分。本批仅 60 道、40 单选 / 20 多选，
  不声称复刻正式考试 75 题的卷面结构。
- 全部属于 `AI 工程`、`language=""`；二级方向：LLM 与 RAG 12 / Agent 12 /
  通用 AI 22 / Prompt 工程 5 / 部署与推理 9；难度：基础 11 / 进阶 32 / 挑战 17。
- 内容覆盖场景选型、文档解析与混合检索、hit@k / recall@k / 重排与忠实度、工具错误分类、
  幂等超时与循环止损、降级熔断与限流、缓存权限与失效、输入输出安全、审计与可观测性、
  Token 成本、Bad Case 回流、LoRA / 蒸馏、多 Agent / 多模态和托管平台发布验收。
- 与全库逐条执行题干归一化与字符 2-gram Jaccard 查重；阈值 0.62，本批与其他题最高相似度
  约 0.218。`--write` 实测读入 60 / 新增 60 / 越界 0 / 字面重复 0 / 近重复 0；
  题库总量 1164 → 1224，AI 工程方向 233 → 293。
- 初稿曾按 35 单选 / 25 多选编写，复核后把 5 道具有唯一最佳处理方式的题改为单选，
  并新增 hit@10 计算场景，最终严格为 40 单选 / 20 多选；不是统计时篡改题型。
- 未引用任何第三方题目文本；`--check` 与 `question_shuffle --check` 均逐字节 0 差异。
  回滚按 `question_merge.SOURCES` 全量删本批行（含 `acpeng-`），存量 260 行不受影响。

## 9 追加素材 `13-system-architecture-scenarios.json`（2026-11-11）

| 文件 | `source` | 种子 id 前缀 | 条数 | 来源性质 | 上游 / LICENSE |
| --- | --- | --- | --- | --- | --- |
| `13-system-architecture-scenarios.json` | `sys-arch` | `sysarch-` | 60 | 自建：AI 原创生成 + 逐条复核 | 无第三方题目来源，无第三方 LICENSE |

- 全部归入 `研发工程实践 / 架构设计`、`language=""`，填补该二级方向原有 0 道的空筛选入口；
  不迁移「通用后端」「通用运维」等其他方向中的缓存、幂等、限流或分库分表旧题。
- 题型：single 40 / multiple 11 / judge 9（正确 6 / 错误 3）；
  难度：basic 12 / intermediate 33 / challenge 15；必备度：must_know 29 / advanced 31。
- 内容覆盖高并发读写、缓存一致性、幂等重试、异步任务、消息积压与乱序、分库分表、
  服务拆分、最终一致、故障降级、多租户、分布式锁和容灾，强调业务约束与失败兜底，而非名词背诵。
- 与全库逐条执行归一化题干及字符 2-gram Jaccard 查重，阈值 0.62；与原 1224 道题的
  最高相似度约 0.1452。`--write` 实测读入 60 / 新增 60 / 越界 0 / 字面重复 0 / 近重复 0；
  题库总量 1224 → 1284，研发工程实践 50 → 110，架构设计 0 → 60。
- `question_merge --check` 与 `question_shuffle --check` 均逐字节 0 差异。
  回滚按 `question_merge.SOURCES` 删除全部登记素材（含 `sysarch-`），保留存量 260 行；
  不手工删 seed 或数据库记录。

## 10 追加素材 `14-acp-official-quizzes.json`（r107，2026-11-16）

| 文件 | `source` | 种子 id 前缀 | 条数 | 来源性质 | 上游 / LICENSE |
| --- | --- | --- | --- | --- | --- |
| `14-acp-official-quizzes.json` | `acp-official` | `acpof-` | 32 | 第三方转录：阿里云 ACP 官方开源教程课后小测验 | [atomgit/alibabaclouddocs/aliyun_acp_learning](https://atomgit.com/alibabaclouddocs/aliyun_acp_learning)，LICENSE = Apache-2.0 |

- 来源为阿里云大模型 ACP 认证**官方开源教程仓库**（Apache-2.0，仓库内 `LICENSE` 文件确认），
  教程中文版 `大模型ACP认证教程/` 下各 notebook 末尾的「🔥 课后小测验」折叠块：
  从 `<details>` 的 `<b>` 题干、`- A.` 选项、`✅ 参考答案`、`📝 解析` 四段忠实转录，
  仅做 HTML/markdown 标记清理（见 `.tmp/parse_acp_quiz.py` 的一次性解析口径，不随仓库提交）。
- 共 32 道客观题：单选 29 / 多选 3；难度 basic 9 / intermediate 20 / challenge 3；
  全属 `AI 工程`、`language=""`，二级方向 Agent 14 / 通用 AI 7 / LLM 与 RAG 6 /
  Prompt 工程 3 / 部署与推理 2。覆盖 temperature/top_p、多轮对话、RAG 召回排查、
  Ragas 指标、提示词要素、MCP、多 Agent、Memory、Skill、Qwen Code、部署选型与安全合规。
- 另有 1 道「案例分析题 2.1.2」是开放问答（无选项/答案），不符合本项目客观题闭集，未纳入。
- 2 道多选题为 5 选项（A–E）：`acpof-008`（推理模型提示词技巧）、`acpof-031`（安全纵深防御），
  均按 `question_shuffle.ALL_KEYS`（A–F，与 `question_merge._OPTION_KEYS` 对齐）前缀
  **正常参与重排**，解析里的字母引用同步改写（`B.D.E.` 点分隔清单与 `A. 是错误的` 句式也已纳入判角）。
  选项数 2–6 是 schema 合法范围，判分按 key 集合不受影响。
- 与全库（含同批 15 号素材）逐条执行题干归一化与字符 2-gram Jaccard 查重（阈值 0.62）：
  字面重复 0 / 近重复 0。`--write` 实测读入 32 / 新增 32 / 越界 0；题库总量 1284 → 1316。
- **版权**：Apache-2.0 允许再分发，此处标注原始来源与许可证；解析与答案属原教程，未改写其技术结论。

## 11 追加素材 `15-acp-v24-extension.json`（r107，2026-11-16）

| 文件 | `source` | 种子 id 前缀 | 条数 | 来源性质 | 上游 / LICENSE |
| --- | --- | --- | --- | --- | --- |
| `15-acp-v24-extension.json` | `acp-ext` | `acpext-` | 18 | 自建：依据官方教程正文原创 + 逐条复核 | 事实依据同上仓库 V2.4 章节正文；题目文本为本项目原创 |

- 基于 ACP 教程 **V2.4 新增/改写章节正文**（Agent Skills、Memory、Harness/Loop Engineering、
  蒸馏、生产实践、安全合规等）创作，只取正文里明确陈述的知识点作为事实依据，题目与解析均为本项目原创。
- **刻意剔除与 14 号官方小测验同知识点换问法的题**（如 Ragas Precision、句子窗口、MCP 集成、
  部署选型等官方题已覆盖），只保留官方小测验未涉及的独立考点：无状态性、三种记忆策略辨析、
  agent_control 主动记忆、Skills-as-Code / 按需加载、Harness 闭环写回规则、数据合成蒸馏流程与指标、
  TTFT/TPOT、上下文缓存、query 改写、自定义业务规则评测、成本效益口径、黑名单局限、多模态选型等。
- 全部 18 道为单选、`AI 工程`、`language=""`；子方向 Agent 9 / 通用 AI 4 / LLM 与 RAG 3 /
  部署与推理 2。`--write` 实测读入 18 / 新增 18 / 越界 0 / 字面重复 0 / 近重复 0；
  题库总量 1316 → 1334。
- 初稿 34 道中 16 道因与官方题同考点被剔除；4 道正确项长度比 >3 的题经压缩正确项、
  加长干扰项修正，最终全库 length>3x = 0、解析字母引用违规 = 0。
- `question_merge --check` 与 `question_shuffle --check` 均逐字节 0 差异；
  回滚按 `question_merge.SOURCES` 删除全部登记素材（含 `acpof-` / `acpext-`），存量 260 行不受影响。

## 12 追加素材 `19-multimodal-models.json`（r141，2026-11-19）

| 文件 | `source` | 种子 id 前缀 | 条数 | 来源性质 | 上游 / LICENSE |
| --- | --- | --- | --- | --- | --- |
| `19-multimodal-models.json` | `multimodal` | `mm-` | 40 | 自建：AI 原创生成 + 逐条复核 | 无第三方题目来源，无第三方 LICENSE |

- 面向「多模态大模型工程」的系统性考点，与同期学习笔记 `docs/多模态模型工程笔记.md` 同源：
  按 **训练 / 微调 / 部署 / 调用** 四块各 10 道。训练块含对比学习 N×N 矩阵与温度系数、
  模态对齐两阶段、ViT patch 数量、AnyRes 分块、2D 位置、分布式负载；微调块含 LoRA / QLoRA /
  DoRA、冻结视觉塔、连接器-only、灾难性遗忘、rank 与 alpha、幻觉评测；部署块含 prefill/decode、
  KV cache 显存估算、量化顺序、continuous batching、chunked prefill、OOM 排查、预处理瓶颈、
  可观测指标；调用块含 messages 图文数组、detail 精度、多模态 RAG、异步任务、图像注入防护、
  token 计费、grounding、base64 膨胀、幂等与限流。
- 全部为 `AI 工程`、`language=""` 通用题；子方向 通用 AI 17 / 部署与推理 11 /
  LLM 与 RAG 9 / Agent 3；题型单选 20 / 多选 12 / 判断 8；难度 challenge 14 / intermediate 22 /
  basic 4；必备度 must_know 20 / advanced 18 / nice_to_know 2。
- 与全库逐条执行题干归一化与字符 2-gram Jaccard 查重（阈值 0.62）：字面重复 0 / 近重复 0。
  `--write` 实测读入 40 / 新增 40 / 越界 0 / 字面重复 0 / 近重复 0；
  题库总量 1554 → 1594，AI 工程方向 406 → 446。
- 质量口径遵守 r124：解析 ≥30 字且**不引用选项字母**（避免选项轮转后指代失效），
  正确项长度比 ≤3、全库中位 ≤2.0；判断题「正确 / 错误」各 4 道，避免扰动极性分布。
- 全部通用桶新题再次触发存量前 260 行确定性选项轮转：字节数仍为 199377，
  `R13_SEED_SHA256` 刷新为 `fe8b6336…2f3`；`question_merge --check` 与
  `question_shuffle --check` 均逐字节 0 差异。回滚按 `question_merge.SOURCES`
  删除全部登记素材（含 `mm-`），存量 260 行不受影响。

## 13 追加素材 `20-retrieval-vectors.json`（r143，2026-11-19）

| 文件 | `source` | 种子 id 前缀 | 条数 | 来源性质 | 上游 / LICENSE |
| --- | --- | --- | --- | --- | --- |
| `20-retrieval-vectors.json` | `retrieval` | `ret-` | 40 | 自建：AI 原创生成 + 逐条复核 | 无第三方题目来源，无第三方 LICENSE |

- 面向「检索向量化与混合检索」的系统性考点，与同期学习笔记 `docs/检索向量化与混合检索笔记.md` 同源：
  按 **稠密向量 / 稀疏向量 / RRF 与融合 / 索引与工程 / 重排与评测** 五块组织——稠密块含对比学习
  in-batch 负样本与大 batch、hard negatives、归一化与 cosine/内积等价、指令前缀、换模型代价清单、
  Matryoshka 截断、ColBERT late interaction、稠密检索的精确词面盲区；稀疏块含 BM25 三参数
  （k1 饱和 / b 长度归一 / IDF）、饱和动机、SPLADE 学习型稀疏与隐式词扩展、(indices, values)
  稀疏存储、倒排索引方向、BM25 零模型依赖；RRF 块含公式手算题（两路都第 2 胜过 1+4）、
  k 平滑方向、rank fusion vs score fusion、ID 对齐去重、单路失败退化、裸分数加权求和反例；
  索引块含 HNSW 三参数、千万级向量内存账、PQ 原理与 OPQ、pre-filter vs post-filter 权限空洞、
  IVF nprobe；重排评测块含 cross-encoder vs bi-encoder、「重排的天花板是召回」、recall@k /
  nDCG / MRR、调优顺序（chunking → embedding → 混合 → 重排 → 参数）、端到端净收益、
  golden set 构建。
- 与存量题（l100-070 / iq380-237 / aieng-033 / aiadv-013 / aim-002 等已有的 RRF / HNSW /
  混合检索基础概念题）做了差异化：本批走参数细节、数值手算、工程权衡与反例，不复述已有概念题。
- 全部为 `AI 工程`、`language=""` 通用题；子方向 LLM 与 RAG 28 / 部署与推理 6 / 通用 AI 6；
  题型单选 20 / 多选 12 / 判断 8（正确 / 错误各 4）；难度 challenge 20 / intermediate 16 /
  basic 4；必备度 must_know 25 / advanced 15。
- 与全库逐条执行题干归一化与字符 2-gram Jaccard 查重（阈值 0.62）：字面重复 0 / 近重复 0。
  `--write` 实测读入 40 / 新增 40 / 越界 0 / 字面重复 0 / 近重复 0；
  题库总量 1594 → 1634，AI 工程方向 446 → 486。
- 质量口径遵守 r124/r141：解析 ≥30 字且**不引用选项字母**，正确项长度比 ≤3、
  全库中位 ≤2.0；判断题「正确 / 错误」各 4 道。
- 全部通用桶新题再次触发存量前 260 行确定性选项轮转：字节数仍为 199377，
  `R13_SEED_SHA256` 刷新为 `f8c1392e…2da1`；`question_merge --check` 与
  `question_shuffle --check` 均逐字节 0 差异。回滚按 `question_merge.SOURCES`
  删除全部登记素材（含 `ret-`），存量 260 行不受影响。
