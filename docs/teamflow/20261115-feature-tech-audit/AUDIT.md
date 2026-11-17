# 全功能审计与技术性评估报告（2026-11-15）

> 触发：用户判断「当前功能不足以体现项目的技术性」。
> 方法：通读 README / ARCHITECTURE / memory + 全量代码盘点（backend/app、frontend/src、scripts、.github/workflows、docker-compose*）。
> 结论先行：**工程深度被低估（藏在可靠性/运维层，界面不可见）；AI 深度是真短板（README 自己声明了边界）。问题不是"没有技术"，而是"技术不可见 + AI 能力浅水区"。**

---

## 1. 功能全景（代码现状盘点）

### 1.1 规模指标

| 维度 | 数量 |
|---|---|
| 后端 API 端点 | ~50 个（17 个 router） |
| 前端页面/路由 | 19 个 |
| 数据库表 | 24 张（PostgreSQL 16，无迁移框架、幂等 DDL 演进） |
| AI 调用场景 | 12 类（统一收口在 `services/ai/ai.py` 的 AIClient） |
| 后端测试 | 58 个文件 / 810+ 用例（连真实 PG，零网络） |
| 前端测试 | 42 个文件（vitest） |
| CI | 4 job（前端 / 后端含 PG+Redis services / release-gate / deploy） |
| 部署 | 4 容器 compose + TLS + 受限 SSH 推模式 CD + 自动回滚 |

### 1.2 六大功能域

| 域 | 功能 | 技术要点 |
|---|---|---|
| 简历与画像 | PDF/DOCX/TXT/图片(视觉模型)上传、异步画像任务、逐条润色、成稿导出、版本对比 | 部分唯一索引幂等受理、心跳判死、惰性清扫、乐观读-合并-写、source_quote 原文逐字命中反幻觉闸门 |
| 测评 | 模拟面试（多轮对话流、追问配额、6 项设定）、笔试（1224+ 题库、L1–L6 阶梯组卷、结构闸门）、练习、错题本 | runs.payload v2 会话状态机零新表、熟练度滑动窗口回流、exam_selector 确定性组卷 |
| 报告与计划 | 短板诊断、岗位匹配、简历修改要点、7 天学习计划、md 导出、成长时间线 | 两路 AI asyncio.gather 并发 + 模板降级（报告恒 200）、事件快照 UNIQUE(type,ref_id) 定格不回写 |
| 学习 | 40 章教程、章内目录 scroll-spy、阅读进度上云、AI 学习教练（材料白名单） | IntersectionObserver 双实例、localStorage 即时写 + 防抖上云 |
| 雷达与内容生产 | 六源并发采集（github/HN/arxiv/openai/googleai/manual）、评估、翻译、章节+题目生成任务 | 单源 8s 超时失败不连坐、input_sha256 评估缓存、应用内极简排程（不引 APScheduler） |
| 太傅 Agent | SSE 流式对话、LangGraph agent⇄tools 循环、工具轮次上限 3、线程摘要、长期记忆 | 流式 tool_calls 分片按 index 重组、引用只能由工具结果产生（反幻觉） |

## 2. 已有技术深度清单（被低估的资产）

这些已经在代码里，但从 UI 和 README 看不出来：

1. **SQLite→PG 在线迁移工程**：`to_pg_sql()` 哨兵法占位符翻译让 2261 行 repository 零改动；窗口函数取代 rowid 做存量收敛；pg_trgm GIN 取代 FTS5（且论证了 tsvector 对中文不适用）。
2. **幂等体系**：三张部分唯一索引（只压 running 行）+「先查在途→插入撞约束→再查复用」受理闭环 + ON CONFLICT DO NOTHING。
3. **可靠性工程**：熔断器（三态、半开单探针）、指数退避+对称抖动、滑动窗口限流（Redis 共享窗口优先、进程内兜底）、生产档启动门禁 `production_blockers()`。
4. **故障注入评测**：`eval_reliability.py` 模拟故障验证兜底路径，进 CI 门禁。
5. **金标集离线评测**：30 例回归门禁 + 教程侧 BM25 / 题目侧 PG 检索召回门禁，全部 `--check` 只读进 CI。
6. **安全**：SSRF 校验（DNS 解析后查 IP 段）、Fernet 密钥加密、scrypt 密码、login_guard 防枚举、X-Request-Id 全链路、安全响应头单点管理。
7. **CD 工程**：受限 deploy key（command= 钉死）、flock 串行、部署前备份、冒烟失败自动回滚且回滚后复核、umask 事故教训固化进脚本。
8. **测试基座**：按 DSN 自动建库的 PG 测试基座，CI 用 services 容器跑真库，杜绝「没有数据库的假绿」。

## 3. 核心判断：技术深度 ≠ 技术可见度

「不足以体现技术性」的真实原因拆解：

| 层 | 现状 | 问题 |
|---|---|---|
| 界面可见层 | 上传 → 画像 → 面试/笔试 → 报告 的 CRUD 式流程 | 面试官/读者看到的只是一个表单流应用 |
| 工程深度层 | 幂等/熔断/故障注入/CD 回滚（上文 §2） | 全部藏在后端与脚本里，无展示面 |
| AI 能力层 | OpenAI 兼容单次调用 + pydantic 校验 | README 自述：「没有向量检索、多 Agent 编排或模型训练；不是 RAG 系统」——这是 AI 全栈求职场景的核心提问区 |

对照「AI 全栈工程师」能力矩阵的差距：

| 能力项 | 现状 | 差距 |
|---|---|---|
| LLM 调用工程（超时/重试/结构化） | ✅ 强 | — |
| 流式输出 | 🟡 只有太傅一个 SSE 场景 | 面试逐字流式、任务进度推送未做 |
| RAG / 向量检索 | ❌ 无（trigram ILIKE 关键词检索） | pgvector 语义检索是面试高频题 |
| Agent 编排 | 🟡 太傅单 Agent + ≤3 轮工具循环 | 无多 Agent / 无规划-执行分离 |
| 在线评测（真实模型） | ❌ eval_live 只 dry-run，报告标注不能当质量指标 | 有脚手架没真跑 |
| 可观测性 | 🟡 /eval 看板只有调用元数据 | 无 OpenTelemetry / metrics / tracing |
| 性能验证 | 🟡 benchmark.py 还是 SQLite 口径 | 无 PG 基准、无负载测试 |

## 4. 改进建议（按投入产出排序）

### A. 让现有深度「可见」（1–2 天，纯展示面，收益最高）

1. **工程证据中心**：把 `/eval` 页扩成一站式的「Reliability / Eval / Deploy」看板——可靠性故障注入结果、金标集回归趋势、CI 门禁历史、部署版本与回滚记录。素材全部已存在（RELIABILITY-REPORT / eval 报告 / deploy-state），只差聚合展示。
2. **README 架构图 + 技术指标表**：50 端点 / 24 表 / 810+ 测试 / 幂等三件套 / 自动回滚 CD，这些数字目前分散在十几篇文档里，首页看不到。

### B. 补 AI 能力短板（建议按此顺序做）

1. **pgvector 语义检索**（中成本、最高频面试题）：题库与教程接向量检索，与现有 trigram 路径并存做对比实验——检索召回门禁（eval_question_retrieval）已存在，改动有现成验证框架。
2. **在线评测真跑**（低成本）：`AI_LIVE=1 eval_live.py --live` 已有脚手架，跑一轮真实模型金标集，把 LIVE-REPORT.md 从 DRY-RUN 变成真报告（注意脱敏口径已定义）。
3. **面试流式化**（中成本）：面试逐题评分/出题改 SSE 逐字输出，复用太傅的流式基础设施；把「2s 轮询任务进度」升级为 SSE 推送。
4. **教练 Agent 深化**（高成本、差异化最强）：把太傅从单 Agent 扩成「教练编排」——规划器按报告短板调度工具（出题、判分、调整 7 天计划、查教程），这是从「调 API」到「做 Agent 系统」的质变。

### C. 工程加分项（有空再做）

- OpenTelemetry + Prometheus + Grafana（可观测性是简历加分关键词）
- `benchmark.py` 改写为 PG 基准 + k6 负载测试
- Playwright E2E（README 已承认「首版无浏览器自动化」）

## 5. 推荐路线

> 先做 A（让已有深度可见，立刻改变观感）→ B1 pgvector（补最高频短板）→ B2 在线评测（让 AI 质量有据可查）→ B3/B4 视时间投入。

**一句话：这个项目不需要「加功能」来显得有技术，需要的是把已有的可靠性工程摆上台面，再补 RAG 与 Agent 编排这两块 AI 全栈的核心拼图。**
