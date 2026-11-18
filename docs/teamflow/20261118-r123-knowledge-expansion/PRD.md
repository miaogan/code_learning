# r123 · 学堂 / 演武知识量均衡扩充

- 需求来源：用户「补充一下『学堂』『演武』两个模块的知识量」。确认口径为**均衡扩充**：八个方向各加 1 章教程、各加约 12–13 道题。
- 交付形态：纯内容扩充 + 派生种子重算，**不改契约、不改页面逻辑、不改筛选闭集、不改运行时代码**。
- 规模：学堂 40 → **48 章**；演武 1334 → **1434 道**；教程 RAG 种子 165 → **197 小节**。

## 1. 现状缺口

| 模块 | 存储 | 扩充前 | 缺口 |
|---|---|---|---|
| 学堂 | `frontend/src/content/tutorials/*.ts`（构建期静态常量） | 40 章 = AI 12 + 其余 7 方向各 4 | 每方向 4 章，CSS / Go / 排序 / 组成原理 / Nginx / 索引 / CI-CD / NoSQL 等子方向无教程入口 |
| 演武 | `backend/app/seed/questions.json`（离线合并 → 运行时入库） | 1334 道，15 个来源 | 题量在八方向分布不均；缺少「场景化题干 + 完整解析」型新题 |

## 2. 新增教程章节（每方向 1 章）

| 章节 id | 方向 | 子方向 | 难度 | 覆盖点 |
|---|---|---|---|---|
| `fe-css-layout` | 前端 | css | 基础 | 盒模型 / 层叠上下文 / Flex 与 Grid / 响应式断点 |
| `be-python-concurrency` | 后端 | python | 进阶 | GIL / 线程与多进程 / asyncio 事件循环 / gather 与 to_thread |
| `algo-sorting-stability` | 算法与数据结构 | 排序 | 进阶 | 稳定性 / 多关键字排序 / 堆 Top-K / 快排退化 |
| `cs-computer-network-ip` | 计算机基础 | 网络 | 基础 | 分层职责 / 三次握手 / keep-alive 与 TIME_WAIT / 逐层排查 |
| `ai-prompt-injection-defense` | AI 工程 | 通用 AI | 高级 | 注入成因 / 输入-执行-输出三层防线 / 工具权限闸门 |
| `mw-cicd-pipeline` | 中间件与运维 | CI-CD | 进阶 | CI/CD 三段 / 绿灯≠部署 / SHA 固定与 umask / 回滚 |
| `sql-nosql-choice` | SQL 与数据库 | NoSQL | 进阶 | 四类 NoSQL / 一致性取舍 / 文档建模 / 选型反模式 |
| `eng-tech-debt` | 研发工程实践 | 通用工程实践 | 基础 | 识别 / 记账模板 / 偿还时机 / 表征测试 |

全部遵循既有 4 节模板（概念 → 规则/对比 → 可运行示例 → 常见坑与自测），末节带 `qa`；代码块标注真实语言；表格每行列数与表头一致。

**子方向取舍**：`ai-prompt-injection-defense` 归入「通用 AI」而非「Prompt 工程」。原因是 `studyPlan.test.ts` 的 r49 用例刻意依赖「Prompt 工程是 AI 工程中唯一没有高级章的子方向」来验证难度递降回落；注入防护本身是跨Prompt/Agent/部署的通用安全主题，归「通用 AI」语义更准且不改行为测试。

## 3. 新增题库批次

- 素材：`docs/question-bank-staging/16-knowledge-expansion.json`，100 道，来源 `kb-expand`，ID 前缀 `kbx-`。
- 分布：前端 13 / 后端 13 / 算法 12 / 计算机基础 12 / AI 13 / 中间件 12 / SQL 12 / 研发 13；单选 64 / 多选 20 / 判断 16；难度 32/48/20；必备度 63/30/7。
- 质量口径：题干为具体场景（非「以下说法正确的是」模板），解析 ≥30 字且**不引用选项字母**（避免选项轮转后指代失效），语言恒空串，子方向全落既有闭集。
- 合并结果：越界丢弃 0 / 字面重复 0 / 近重复 0；`--check` 逐字节幂等。

## 4. 改动清单

| 文件 | 改动 |
|---|---|
| `frontend/src/content/tutorials/{frontend,backend,algorithms,cs,ai,middleware,sql,engineering}.ts` | 各追加 1 章 |
| `backend/app/seed/tutorials_rag.json` | 由 `export_tutorials.mjs` 重新导出（197 小节） |
| `docs/question-bank-staging/16-knowledge-expansion.json` | 新增 100 道素材 |
| `backend/app/services/assessment/question_merge.py` | 登记 `kb-expand` 到 SOURCES / STAGING_FILES / ID_PREFIX |
| `backend/app/seed/questions.json` | 由 `question_merge --write` 重算（1434 道，1336392 字节） |
| `backend/tests/test_r12_question_merge.py` | 刷新冻结 SHA-256、EXPECTED_TOTAL、EXPECTED_SOURCES、计数与注释 |
| `backend/tests/test_question_bank_quality.py` | 刷新 R12_SOURCES / R12_SOURCE_COUNTS / R12_TOTAL |
| `backend/tests/test_r11_practice_service.py` | 刷新导入题量与架构设计筛选断言（60 → 62：原 sys-arch 60 + 新 kbx 2） |
| `docs/teamflow/20261102-r15-question-text-cleanup/{QUESTION-BANK-MERGE-REPORT,SHUFFLE-REPORT}.md` | 工具自动重算产物 |
| `AGENTS.md` §5 | 追加变更记录 |

## 5. 冻结基线迁移说明

新增 100 道通用题（`language=""`）进入打乱器的通用桶，触发存量前 260 行**选项位置的确定性轮转**：题干、选项文本集合、正确答案文本均不变，仅选项 key 与解析中的对应字母改写。字节数仍为 199377，`R13_SEED_SHA256` 随轮转态由 `c3254c31…` 刷新为 `931c639f…`。与 r47 / r48 / r55 / r107 同类处理，`question_merge --check` 已确认重算幂等，非历史数据篡改。
