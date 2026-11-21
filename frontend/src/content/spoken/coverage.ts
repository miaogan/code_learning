import type { SpokenLayer } from '../../lib/spokenCoverage'

/**
 * 章节可听性分层（r150 / M1）：判据不是代码占比，而是**这段内容能否脱离视觉独立成立**
 * （VERSION-PLAN §3.1）。
 *
 * - A 复杂概念：有清晰因果链、可连续推理 → 单口自问自答
 * - B 常见场景：有过程、有「错误做法 → 后果 → 正确做法」→ 对口抬杠
 * - C 必须看：语法 / API / 布局 / 命令 / 可视结构，念出来记不住 → 不做音频
 * - C′ 算法演示类：需要看过程推进 → 做交互演示，不做音频
 *
 * 这张表是**唯一真源**：起草流水线按它挑章、听入口按它决定是否显示「听」。
 * 新增 / 重命名教程章必须同步这里（`spokenCoverage.test.ts` 会拦住漏项）。
 */
export interface SpokenCoverageEntry {
  chapterId: string
  layer: SpokenLayer
  /** 为什么是这一层：评审与后续复盘都靠这句，别写空话。 */
  reason: string
  /** 混合章可覆盖默认形态（A 默认 solo、B 默认 duo）。 */
  form?: 'solo' | 'duo'
}

export const SPOKEN_COVERAGE: readonly SpokenCoverageEntry[] = [
  // ── 前端 ───────────────────────────────────────────────
  { chapterId: 'fe-event-loop', layer: 'A', reason: '事件循环是纯因果链，没有必须盯着看的结构' },
  { chapterId: 'fe-react-render', layer: 'A', reason: '状态 → 渲染是因果链，可脱离代码讲' },
  { chapterId: 'fe-render-performance', layer: 'B', reason: '有优化前后的过程与错误做法' },
  { chapterId: 'fe-react-concurrent', layer: 'A', reason: '并发渲染是调度概念，无强视觉依赖' },
  { chapterId: 'fe-typescript', layer: 'C', reason: '语法与类型写法，听了记不住' },
  { chapterId: 'fe-css-layout', layer: 'C', reason: '布局与尺寸必须边看边试' },
  { chapterId: 'fe-ts-advanced', layer: 'C', reason: '类型体操是代码密集型' },

  // ── 后端 ───────────────────────────────────────────────
  { chapterId: 'be-http-rest', layer: 'B', reason: '接口设计有对错对比与场景' },
  { chapterId: 'be-db-index', layer: 'A', reason: '索引原理与代价是纯因果链' },
  { chapterId: 'be-concurrency-idempotency', layer: 'C', reason: '代码密集型：幂等实现要盯着代码' },
  { chapterId: 'be-auth-session', layer: 'B', reason: '认证流程有过程与常见错法' },
  { chapterId: 'be-python-concurrency', layer: 'A', reason: 'GIL 与调度模型是概念，可讲清' },
  { chapterId: 'be-distributed-consistency', layer: 'A', reason: '全站最抽象的章，无视觉依赖（黄金稿 01）' },
  { chapterId: 'be-rate-limit-resilience', layer: 'B', reason: '限流熔断有故障过程与兜底做法' },
  { chapterId: 'be-go-concurrency', layer: 'C', reason: 'goroutine 与泄漏排查必须看代码' },

  // ── SQL 与数据库 ───────────────────────────────────────
  { chapterId: 'sql-join-null', layer: 'B', reason: '查询写错 → 结果错的对比天然是段子结构' },
  { chapterId: 'sql-window-explain', layer: 'C', reason: '窗口函数与执行计划是语法 / 图示' },
  { chapterId: 'sql-lock-isolation', layer: 'A', reason: '隔离级别是取舍与因果，可讲' },
  { chapterId: 'sql-schema-design', layer: 'A', reason: '范式取舍是概念判断' },
  { chapterId: 'sql-nosql-choice', layer: 'B', reason: '选型有业务场景与反例' },

  // ── 中间件与运维 ───────────────────────────────────────
  { chapterId: 'mw-cache-strategy', layer: 'A', reason: '概念 + 场景混合（黄金稿 02）', form: 'duo' },
  { chapterId: 'mw-message-queue', layer: 'A', reason: '投递语义与幂等是概念' },
  { chapterId: 'mw-observability', layer: 'B', reason: '排障有完整过程与错误做法（黄金稿 03）' },
  { chapterId: 'mw-docker', layer: 'C', reason: 'Dockerfile 与命令必须看' },
  { chapterId: 'mw-cicd-pipeline', layer: 'B', reason: '流水线门禁有失败场景与修法' },
  { chapterId: 'mw-redis-ha', layer: 'B', reason: '主从 / 哨兵切换有过程与坑' },

  // ── 计算机基础 ─────────────────────────────────────────
  { chapterId: 'cs-process-thread', layer: 'A', reason: '进程线程是概念对比，可讲' },
  { chapterId: 'cs-tcp-http', layer: 'A', reason: '握手与状态码是因果链' },
  { chapterId: 'cs-memory-virtual', layer: 'A', reason: '虚拟内存是抽象机制' },
  { chapterId: 'cs-io-model', layer: 'A', reason: '五种 IO 模型是概念对比' },
  { chapterId: 'cs-computer-network-ip', layer: 'B', reason: '分层职责有排障场景' },

  // ── 算法与数据结构（C′：看过程才有效）─────────────────
  { chapterId: 'algo-complexity', layer: 'C2', reason: '复杂度靠曲线对比，演示比朗读有效' },
  { chapterId: 'algo-hash-pointer', layer: 'C2', reason: '双指针要逐步走动' },
  { chapterId: 'algo-dp-graph', layer: 'C2', reason: 'DP 表格逐格推进' },
  { chapterId: 'algo-binary-tree', layer: 'C2', reason: '递归与遍历要看树' },
  { chapterId: 'algo-sorting-stability', layer: 'C', reason: '排序稳定性是过程演示与代码结合' },

  // ── AI 工程 ───────────────────────────────────────────
  { chapterId: 'ai-transformer', layer: 'A', reason: '注意力机制是因果链' },
  { chapterId: 'ai-rag', layer: 'A', reason: '检索增强是架构概念' },
  { chapterId: 'ai-llm-basics', layer: 'A', reason: '预训练与推理是概念' },
  { chapterId: 'ai-model-basics', layer: 'A', reason: '训练流程是因果链，可讲清' },
  { chapterId: 'ai-glossary', layer: 'C', reason: '名词速查表，听了记不住，适合查' },
  { chapterId: 'ai-langchain-langgraph', layer: 'C', reason: '框架 API 与图编排必须看代码' },
  { chapterId: 'ai-finetune-distill', layer: 'A', reason: '微调与蒸馏是方法论取舍' },
  { chapterId: 'ai-agent-tools', layer: 'A', reason: '工具调用是协议概念' },
  { chapterId: 'ai-inference-serving', layer: 'A', reason: '批处理与显存估算是取舍' },
  { chapterId: 'ai-multi-agent', layer: 'A', reason: '编排拓扑与终止判据是概念' },
  { chapterId: 'ai-eval-harness', layer: 'A', reason: '评测口径与偏差是方法论' },
  { chapterId: 'ai-prompt-engineering', layer: 'B', reason: '提示词有写坏 → 改好的实例' },
  { chapterId: 'ai-prompt-injection-defense', layer: 'B', reason: '注入攻击有场景与防护对比' },
  { chapterId: 'ai-context-engineering', layer: 'A', reason: '上下文预算与压缩是取舍' },
  { chapterId: 'ai-rag-advanced-retrieval', layer: 'A', reason: '改写 / 混合检索是机制' },
  { chapterId: 'ai-llm-eval-judge', layer: 'A', reason: '裁判偏差是方法论' },
  { chapterId: 'ai-mcp-tools', layer: 'A', reason: '协议与工具边界是概念' },
  { chapterId: 'ai-inference-quantization', layer: 'A', reason: '量化与 KV Cache 是原理 + 取舍' },
  { chapterId: 'ai-agent-memory', layer: 'A', reason: '状态与持久化是机制' },

  // ── 研发工程实践 ───────────────────────────────────────
  { chapterId: 'eng-git-review', layer: 'C', reason: 'Git 命令必须边敲边记' },
  { chapterId: 'eng-test-ci', layer: 'B', reason: '测试分层与门禁有失败场景' },
  { chapterId: 'eng-incident-capacity', layer: 'B', reason: '故障复盘与容量规划是场景' },
  { chapterId: 'eng-refactoring', layer: 'B', reason: '坏味道有具体案例与改法' },
  { chapterId: 'eng-tech-debt', layer: 'B', reason: '技术债有识别与偿还的过程' },
]
