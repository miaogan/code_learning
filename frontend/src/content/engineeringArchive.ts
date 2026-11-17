/**
 * r100 工程证据中心的静态档案（考工页「营造」区）：架构数字 / 幂等与可靠性 /
 * 迁移工程 / RAG 管线 / 自动评审 / CD 与部署。
 *
 * 口径：这些卡片描述**已经落盘**的工程事实，随代码评审同步更新；
 * 行数类的活数字（题库规模 / 表数 / chunk 数）不写死在这里——由
 * `GET /api/evidence/summary` 实时聚合，避免静态数字与库漂移。
 */

export interface ArchiveCard {
  tag: string
  title: string
  points: string[]
}

export const ENGINEERING_STATS: { label: string; value: string }[] = [
  { label: 'API 端点', value: '50+' },
  { label: '数据表', value: '26' },
  { label: '后端测试', value: '800+ 用例' },
  { label: '前端测试', value: '42 文件' },
  { label: 'CI 评测门禁', value: '8 道' },
  { label: '容器', value: '4 服务' },
]

export const ENGINEERING_ARCHIVE: ArchiveCard[] = [
  {
    tag: 'IDEMPOTENCY',
    title: '幂等三件套',
    points: [
      '三张部分唯一索引只压 running 行：画像 / 图片识别 / 雷达生成任务的「同任务不重复受理」由数据库约束保证，不靠应用层加锁',
      '受理闭环：先查在途 → 插入撞唯一约束 → 再查复用，两个副本同时受理也只有一个在跑',
      '读路径惰性清扫 + 图片任务逐页心跳：按「无进展」判死，僵尸任务按 failed 落库给中文原因',
    ],
  },
  {
    tag: 'MIGRATION',
    title: 'SQLite → PostgreSQL 在线迁移',
    points: [
      'to_pg_sql() 哨兵法把 149 处 ? 占位符翻译成 %s，2261 行数据层零改动',
      '窗口函数取代 rowid 收敛存量重复行；SQL_NOW_ISO 复刻毫秒时间串，保住「字符串排序 = 时间排序」',
      '全文检索从 FTS5 换 pg_trgm GIN，并论证了 tsvector 把连续中文当一个词、不可用',
    ],
  },
  {
    tag: 'RAG PIPELINE',
    title: 'RAG 检索管线（r100）',
    points: [
      'chunk（题库 + 教程小节）→ embedding → pgvector ivfflat 余弦索引 → 向量 / 关键词两腿 RRF(k=60) 融合',
      '默认离线 HashingEmbedder：char-bigram + crc32 特征哈希，确定性、零网络、CI 可复跑；配 AI_EMBED_MODEL 即换真实语义模型',
      '无 pgvector 扩展时自动降级为取回后 Python 余弦，engine 字段如实报告，不伪装',
    ],
  },
  {
    tag: 'RAG EVAL',
    title: 'RAG 自动评审（r100）',
    points: [
      '检索轨：关键词 / 语义 / 混合三态同金标对比（recall@5 / MRR@5 / hit@1），门禁要求融合不回退、召回达线',
      '生成轨：LLM-as-judge 对检索增强回答自动打分（忠实度 / 相关性 0-10），DRY-RUN 走规则替身零网络，AI_LIVE=1 才真跑',
      '引用白名单：生成的 citations 必须落在检索命中的 chunk 内，越界引用丢弃并计数——与画像 source_quote 同一套反幻觉纪律',
    ],
  },
  {
    tag: 'RELIABILITY',
    title: '可靠性与防护',
    points: [
      '熔断器三态（在飞上限 32 → 30s 打开 → 半开单探针），滑动窗口限流 Redis 共享窗口优先、进程内兜底',
      '故障注入评测（eval_reliability.py）模拟上游 5xx / 超时验证降级路径，进 CI 门禁',
      'X-Request-Id 全链路贯穿（trace → 限流 → origin guard），403/429/503 也带 id 可追',
    ],
  },
  {
    tag: 'CD',
    title: '部署与回滚',
    points: [
      '受限 deploy key（authorized_keys 钉死 command=），flock 串行 + freeze 冻结开关',
      '先 build 再一次性切换，90s 冒烟（/health + 首页 + /docs 404）失败自动回滚上一 SHA，且回滚后复核',
      '部署前 pg_dump 备份；umask 077 生产事故教训固化进 checkout_tree，并有 CI 门禁防回归',
    ],
  },
]
