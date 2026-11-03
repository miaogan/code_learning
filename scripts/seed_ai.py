"""生成「AI 工程」方向题库的 **staging 素材文件**（canonical 输入）。

本脚本只产出 `docs/question-bank-staging/05-ai-engineering78.json`；`question_merge`
从该文件 + 存量 260 行重建 `app/seed/questions.json`（务必在写完 staging 后跑
`python -m app.services.question_merge --write`）。这样 AI 题与既有 519 道素材走同一条
逐字节可复现的合并流水线，r12 的字节级 / 来源级门禁才成立。

约束（与 product 闭集一致）：
- 方向 direction = "AI 工程"（rules.DIRECTIONS 已新增）
- 语言 language = ""（AI 为无语言方向；rules.LANGUAGES 含 ""，归一化合法）
- 来源 source = "ai-eng"（question_merge.SOURCES 已新增）
- kind ∈ {single, multiple, judge}（r12 合并批不允许 text；practice / 笔试只认客观题）
- essentiality：核心 AI 全栈 must_know/advanced；大模型原理类标记为 nice_to_know（选修）

幂等：重跑会整体重写该 staging 文件。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGING_PATH = ROOT / "docs" / "question-bank-staging" / "05-ai-engineering78.json"

JUDGE_OPTIONS = [
    {"key": "A", "text": "正确"},
    {"key": "B", "text": "错误"},
]


def q(
    qid: str,
    kind: str,
    difficulty: str,
    essentiality: str,
    prompt: str,
    options: list[dict],
    answer: list[str],
    explanation: str,
) -> dict:
    return {
        "id": qid,
        "kind": kind,
        "difficulty": difficulty,
        "essentiality": essentiality,
        "language": "",
        "direction": "AI 工程",
        "prompt": prompt,
        "options": options,
        "answer": answer,
        "explanation": explanation,
    }


def opt(*pairs: tuple[str, str]) -> list[dict]:
    return [{"key": k, "text": t} for k, t in pairs]


# ---------------------------------------------------------------------------
# 题库内容（全客观：single / multiple / judge）
# ---------------------------------------------------------------------------
QUESTIONS: list[dict] = []

# ---- Prompt 工程 (must_know) ----
QUESTIONS += [
    q("ai-prompt-1", "single", "basic", "must_know",
      "zero-shot、one-shot、few-shot 提示的核心区别在于？",
      opt(("A", "是否提供示例：zero 无示例、one 给 1 个、few 给多个示例"),
          ("B", "模型参数量不同"), ("C", "仅在微调时才使用"), ("D", "只影响生成速度")),
      ["A"],
      "三者指推理时是否提供任务示例；示例能显著提升复杂任务的遵循度与格式一致性。"),
    q("ai-prompt-2", "multiple", "intermediate", "must_know",
      "下列哪些属于常见的高级 Prompt 技巧？",
      opt(("A", "Chain-of-Thought（思维链）"), ("B", "角色设定（system persona）"),
          ("C", "少样本示例（few-shot）"), ("D", "增大 max_tokens 即可提升推理")),
      ["A", "B", "C"],
      "CoT、角色设定、少样本都是经典提升技巧；增大 max_tokens 只是放宽输出长度，不属于提示技巧。"),
    q("ai-prompt-3", "single", "intermediate", "must_know",
      "Chain-of-Thought（思维链）提示的主要作用是？",
      opt(("A", "让模型分步推理，降低复杂任务出错率"), ("B", "加快 token 生成速度"),
          ("C", "减少上下文长度"), ("D", "强制模型只输出 JSON")),
      ["A"],
      "CoT 引导模型显式写出中间推理步骤，把复杂问题拆解为可验证子步骤，显著提升算术/逻辑/多跳推理准确率。"),
    q("ai-prompt-4", "single", "basic", "must_know",
      "系统提示（System Prompt）与用户提示（User Prompt）的主要区别是？",
      opt(("A", "系统提示设定角色/规则/边界，用户提示承载具体任务"),
          ("B", "两者完全等价"), ("C", "系统提示只在微调时有效"), ("D", "用户提示优先级更低")),
      ["A"],
      "系统提示在对话最前定义模型身份与全局规则；用户提示是每轮具体请求，系统提示通常优先级最高。"),
    q("ai-prompt-5", "judge", "basic", "must_know",
      "Prompt 越长，模型输出质量一定越高。",
      JUDGE_OPTIONS, ["B"],
      "提示过长会引入噪声、稀释关键指令、挤占上下文，反而可能降低质量；质量取决于清晰度与结构。"),
    q("ai-prompt-6", "single", "intermediate", "advanced",
      "面对 Prompt 注入攻击，下列哪种做法是有效的缓解手段？",
      opt(("A", "隔离并标注不可信外部内容，并对输出做约束与护栏"),
          ("B", "把外部文本直接拼进系统提示以提升相关性"),
          ("C", "完全禁止任何用户输入"), ("D", "仅依赖增大 temperature")),
      ["A"],
      "注入靠“劫持指令”生效；隔离不可信内容、标注来源、输出约束与最小权限工具授权是核心防线。"),
    q("ai-prompt-7", "single", "intermediate", "must_know",
      "结构化输出（JSON Mode / Function Calling）在应用开发中的核心价值是？",
      opt(("A", "让模型产出可被程序直接解析的确定格式"), ("B", "提升模型参数规模"),
          ("C", "缩短上下文窗口"), ("D", "替代所有自然语言交互")),
      ["A"],
      "结构化输出避免脆弱的正则抽取，是 LLM 接入下游逻辑、数据落库与工具调用的关键接口。"),
    q("ai-prompt-8", "multiple", "intermediate", "must_know",
      "关于“好的 Prompt”，下列说法正确的有？",
      opt(("A", "指令清晰、目标明确"), ("B", "给出必要格式与约束"),
          ("C", "复杂任务可配示例"), ("D", "越长越好、信息越堆越多越稳")),
      ["A", "B", "C"],
      "清晰指令、格式约束与适度示例是高质量提示的共性；冗长堆砌反而稀释信号。"),
]

# ---- LLM 应用开发基础 (must_know) ----
QUESTIONS += [
    q("ai-llm-1", "single", "basic", "must_know",
      "调用 LLM API 时，temperature 参数主要控制什么？",
      opt(("A", "输出的随机性/多样性"), ("B", "最大输出长度"),
          ("C", "输入 token 上限"), ("D", "计费单价")),
      ["A"],
      "temperature 越高输出越随机多样，越低越确定保守；0 适合需要稳定性的任务。"),
    q("ai-llm-2", "single", "basic", "must_know",
      "关于 LLM 的 token，下列说法正确的是？",
      opt(("A", "token 是模型处理文本的最小单位，计费与限流通常按 token 计"),
          ("B", "一个汉字固定等于一个 token"), ("C", "token 只统计输出不计输入"),
          ("D", "token 数量与字符数永远相等")),
      ["A"],
      "token 是分词后的最小单元，API 一般按输入+输出 token 计费并设总量上限。"),
    q("ai-llm-3", "single", "basic", "must_know",
      "什么是流式输出（streaming）？为什么聊天应用普遍使用它？",
      opt(("A", "逐 token 返回，降低首字延迟、提升交互体验"),
          ("B", "一次性返回完整结果以节省带宽"), ("C", "仅用于离线批处理"),
          ("D", "会显著降低生成质量")),
      ["A"],
      "流式让服务端边生成边推送，首字时间（TTFT）大幅缩短；底层常基于 SSE 或 WebSocket。"),
    q("ai-llm-4", "judge", "intermediate", "must_know",
      "max_tokens 参数限制的是单次请求中模型生成的最大输出 token 数。",
      JUDGE_OPTIONS, ["A"],
      "以 OpenAI 等主流 API 为例，max_tokens 指 completion 上限；输入长度另由模型上下文窗口约束。"),
    q("ai-llm-5", "multiple", "intermediate", "must_know",
      "应用层处理 LLM 速率限制（rate limit）的正确做法包括？",
      opt(("A", "指数退避+抖动重试"), ("B", "并发限流（令牌桶/信号量）"),
          ("C", "对可幂等请求才重试"), ("D", "忽略限流直接高频请求")),
      ["A", "B", "C"],
      "限流需退避重试、并发控制与幂等判断；对不可幂等请求重试可能放大副作用。"),
    q("ai-llm-6", "single", "basic", "must_know",
      "什么是上下文窗口（context window）？超出会发生什么？",
      opt(("A", "模型单次能处理的最大 token 数；超出会被截断或报错"),
          ("B", "用户界面的宽度"), ("C", "训练数据集大小"), ("D", "每次会话的固定费用")),
      ["A"],
      "上下文窗口是输入+输出 token 的总容量上限；超出时旧内容被截断或请求被拒，需靠截断/摘要/外部记忆解决。"),
    q("ai-llm-7", "multiple", "intermediate", "advanced",
      "关于 top_p 与 temperature，下列说法正确的有？",
      opt(("A", "top_p 按累积概率截断候选词集（核采样）"), ("B", "temperature 缩放 logits 改变分布"),
          ("C", "两者通常不必同时拉到极高"), ("D", "top_p 控制最大输出长度")),
      ["A", "B", "C"],
      "top_p 是核采样阈值，temperature 是分布温度；输出长度由 max_tokens 控制。"),
    q("ai-llm-8", "judge", "intermediate", "must_know",
      "temperature=0 时，同一 prompt 多次调用结果一定完全一致。",
      JUDGE_OPTIONS, ["B"],
      "即便 temperature=0，部分实现仍存在非确定性（并行采样、量化、服务端负载），只能说高度可复现。"),
    q("ai-llm-9", "multiple", "intermediate", "advanced",
      "LLM 调用缓存在哪些场景适用？",
      opt(("A", "幂等且结果稳定的请求"), ("B", "对时效性不敏感的知识问答"),
          ("C", "含用户私有/实时数据的请求"), ("D", "模板化生成")),
      ["A", "B", "D"],
      "缓存适合稳定、非实时、可幂等的内容；含私有/实时数据的请求禁止缓存以防串味与越权。"),
]

# ---- Embedding 与向量检索 (must_know/advanced) ----
QUESTIONS += [
    q("ai-emb-1", "single", "basic", "must_know",
      "什么是 Embedding（嵌入向量）？它如何表示语义？",
      opt(("A", "把文本映射为稠密向量，语义相近的文本向量距离更近"),
          ("B", "把文本按字符编码成 ASCII"), ("C", "仅用于图像压缩"),
          ("D", "与词袋模型完全相同")),
      ["A"],
      "Embedding 把文本投影到高维连续空间，语义相似的样本在空间中邻近，支持基于距离的语义检索。"),
    q("ai-emb-2", "multiple", "intermediate", "must_know",
      "常见的向量相似度度量包括？",
      opt(("A", "余弦相似度"), ("B", "点积"), ("C", "欧氏距离"), ("D", "词频差")),
      ["A", "B", "C"],
      "余弦衡量方向一致性、点积衡量方向与幅度、欧氏衡量绝对距离；选哪种取决于是否归一化及是否关注模长。"),
    q("ai-emb-3", "judge", "basic", "must_know",
      "Embedding 维度越高，语义表示一定越好。",
      JUDGE_OPTIONS, ["B"],
      "维度需与训练任务匹配；过高易过拟合且浪费算力，更关键的是模型质量与对齐方式。"),
    q("ai-emb-4", "single", "intermediate", "must_know",
      "向量数据库相比传统关系型数据库的核心差异是？",
      opt(("A", "原生支持近似最近邻（ANN）检索而非精确等值/范围查询"),
          ("B", "不支持任何索引"), ("C", "只能存储字符串"), ("D", "完全不支持事务")),
      ["A"],
      "向量库针对高维向量的相似性搜索做了专用索引（HNSW、IVF 等）；传统关系库擅长结构化查询。"),
    q("ai-emb-5", "multiple", "challenge", "advanced",
      "下列哪些是主流向量数据库/方案及其适用场景？",
      opt(("A", "Milvus/Qdrant/Weaviate 适合自建大规模检索"),
          ("B", "Pinecone 是托管 Serverless 方案，运维省心"),
          ("C", "pgvector 适合已用 Postgres、复用事务与 SQL 的中小场景"),
          ("D", "向量数据库不能和 SQL 共存，必须彻底替换关系库")),
      ["A", "B", "C"],
      "方案各有侧重；pgvector 等证明向量能力可内嵌于关系库，并非非此即彼。"),
    q("ai-emb-6", "single", "challenge", "advanced",
      "为什么大规模向量检索普遍采用 ANN（近似最近邻）而非精确 KNN？",
      opt(("A", "精确 KNN 随数据量超线性变慢，ANN 以可接受精度损失换数量级加速"),
          ("B", "ANN 结果永远比 KNN 更准"), ("C", "KNN 无法并行"),
          ("D", "ANN 不需要任何索引")),
      ["A"],
      "精确 KNN 在亿级向量下开销不可接受；ANN（HNSW、IVF-PQ）通过图/聚类索引快速逼近 Top-K，是 RAG 在线检索基石。"),
    q("ai-emb-7", "multiple", "challenge", "advanced",
      "关于 HNSW 索引，下列说法正确的有？",
      opt(("A", "分层可导航小世界图，查询从稀疏顶层贪心下降到底层精搜"),
          ("B", "召回高、查询快"), ("C", "建图内存占用大、写入/删除较贵"),
          ("D", "是一种精确最近邻算法，结果零误差")),
      ["A", "B", "C"],
      "HNSW 用图索引换取速度与召回，代价是内存与写放大；它仍是近似而非精确算法。"),
    q("ai-emb-8", "judge", "intermediate", "nice_to_know",
      "向量检索只能用于文本，不能用于图像或音频。",
      JUDGE_OPTIONS, ["B"],
      "多模态嵌入模型（如 CLIP）能把图像/音频编码到同一向量空间，同样可做相似检索与跨模态搜索。"),
    q("ai-emb-9", "single", "intermediate", "advanced",
      "对向量做 L2 归一化后，余弦相似度等价于？",
      opt(("A", "点积"), ("B", "欧氏距离平方的一半"), ("C", "曼哈顿距离"), ("D", "汉明距离")),
      ["A"],
      "归一化后向量模长为 1，余弦相似度 = 两向量点积；这也是很多向量库要求先 normalize 再只用点积加速的原因。"),
]

# ---- RAG 检索增强生成 (must_know/advanced) ----
QUESTIONS += [
    q("ai-rag-1", "single", "basic", "must_know",
      "RAG（检索增强生成）主要解决了 LLM 的哪些问题？",
      opt(("A", "知识滞后、幻觉、私有数据不可达"), ("B", "模型参数量不足"),
          ("C", "训练速度慢"), ("D", "仅解决中文支持")),
      ["A"],
      "RAG 在生成前先检索权威/私有文档注入上下文，缓解知识截止、减少无依据幻觉，并让模型用到私域数据。"),
    q("ai-rag-2", "multiple", "intermediate", "must_know",
      "标准 RAG 流程通常包含哪些阶段？",
      opt(("A", "检索（retrieval）"), ("B", "增强（augmentation，拼入上下文）"),
          ("C", "生成（generation）"), ("D", "模型重新训练")),
      ["A", "B", "C"],
      "RAG 是推理期流程：检索→拼入提示增强→交给 LLM 生成；不涉及训练/微调。"),
    q("ai-rag-3", "multiple", "intermediate", "must_know",
      "关于文档切分（chunking），下列说法正确的有？",
      opt(("A", "固定长度切分实现简单但可能割裂语义"),
          ("B", "按标题/语义递归切分更友好"), ("C", "滑动窗口重叠可缓解边界割裂"),
          ("D", "切得越大越好，越多上下文越准")),
      ["A", "B", "C"],
      "粒度太小丢上下文、太大引噪声；重叠可缓解边界问题，但都需结合检索器与任务调节。"),
    q("ai-rag-4", "judge", "intermediate", "must_know",
      "RAG 中检索到的文档越多，最终答案一定越准确。",
      JUDGE_OPTIONS, ["B"],
      "过多无关片段会稀释关键信号、挤占上下文并放大噪声，反而降低质量；需配合重排与相关性阈值。"),
    q("ai-rag-5", "multiple", "challenge", "advanced",
      "Advanced RAG 相对 Naive RAG 常用的优化手段包括？",
      opt(("A", "查询改写/扩展"), ("B", "混合检索（向量+关键词）"),
          ("C", "重排序（rerank）"), ("D", "上下文压缩")),
      ["A", "B", "C", "D"],
      "从检索前后两头优化：query 侧改写、召回侧混合、精排侧 rerank、送入侧压缩，全面提升相关性与信噪比。"),
    q("ai-rag-6", "single", "challenge", "advanced",
      "RAG 中的重排序（rerank）用于解决什么问题？",
      opt(("A", "对初召回结果按相关性二次精排，提升送入 LLM 的片段质量"),
          ("B", "压缩模型参数量"), ("C", "替代向量数据库"), ("D", "仅用于图像生成")),
      ["A"],
      "向量召回侧重速度、精度有限；rerank 模型（如 cross-encoder）对 query-doc 联合打分，精排出 top 片段。"),
    q("ai-rag-7", "single", "challenge", "advanced",
      "混合检索（hybrid search）相比纯向量检索的优势是？",
      opt(("A", "结合语义向量与关键词（BM25）互补，兼顾意图与精确匹配"),
          ("B", "检索速度一定更慢不可用"), ("C", "完全不需要向量"),
          ("D", "只能用于英文")),
      ["A"],
      "向量擅长语义泛化但弱于专名/编号精确匹配；BM25 反之。混合检索用 RRF 等融合两者，适合含术语的知识库。"),
    q("ai-rag-8", "multiple", "challenge", "advanced",
      "评估 RAG 检索质量常用的指标包括？",
      opt(("A", "Hit Rate（命中率）"), ("B", "MRR（平均倒数排名）"),
          ("C", "NDCG"), ("D", "模型显存占用")),
      ["A", "B", "C"],
      "离线可用命中率、MRR、NDCG 衡量片段相关性；显存占用不是检索质量指标。"),
    q("ai-rag-9", "single", "intermediate", "advanced",
      "RAG 中知识库没有答案时，较稳妥的做法是？",
      opt(("A", "检索得分低于阈值时提示模型明确拒答，避免强行编造"),
          ("B", "无论如何都要生成一个答案"), ("C", "直接返回随机片段"),
          ("D", "关闭检索只用模型参数记忆")),
      ["A"],
      "阈值/相关性兜底让模型“知之为知之”；强行编造会放大幻觉，是 RAG 落地常见坑。"),
    q("ai-rag-10", "judge", "basic", "must_know",
      "RAG 必须依赖向量数据库，不能用传统数据库做检索。",
      JUDGE_OPTIONS, ["B"],
      "RAG 本质是“检索+生成”，检索可用关键词、SQL、图谱或混合方案；向量库只是常见的语义检索实现。"),
    q("ai-rag-11", "multiple", "challenge", "nice_to_know",
      "GraphRAG 相比传统 RAG 更擅长的场景是？",
      opt(("A", "跨文档的全局归纳与主题总结"), ("B", "回答需要聚合大量文档的宏观问题"),
          ("C", "单一片段内的精确事实抽取"), ("D", "完全取代向量检索")),
      ["A", "B"],
      "GraphRAG 先抽取实体/关系构建知识图谱，擅长全局归纳；局部事实抽取仍可由传统 RAG 完成，二者可互补。"),
    q("ai-rag-12", "multiple", "challenge", "advanced",
      "RAG 的上下文压缩（context compression）技术包括？",
      opt(("A", "用 LLM 对小片段摘要后再拼接"), ("B", "只保留与 query 最相关的句子（extractive）"),
          ("C", "rerank 后仅截取 top"), ("D", "把整个知识库原样塞入上下文")),
      ["A", "B", "C"],
      "压缩聚焦关键证据、减少冗余与噪声；原样全塞会撑爆窗口并稀释信号。"),
]

# ---- Function Calling / 工具调用 (must_know/advanced) ----
QUESTIONS += [
    q("ai-fc-1", "single", "basic", "must_know",
      "什么是 Function Calling（函数调用）？它与普通文本生成的区别？",
      opt(("A", "模型输出结构化“调用某函数的请求”，由应用执行后回传结果"),
          ("B", "模型直接在内部运行代码"), ("C", "仅用于翻译"), ("D", "等价于微调")),
      ["A"],
      "模型生成符合 schema 的工具调用请求，由宿主程序调用真实 API 并把结果喂回模型继续推理。"),
    q("ai-fc-2", "multiple", "intermediate", "must_know",
      "关于工具描述（schema）的重要性，下列说法正确的有？",
      opt(("A", "清晰的描述帮助模型正确选工具"), ("B", "参数类型与约束需明确"),
          ("C", "模糊缺失会导致选错工具或参数错误"), ("D", "schema 可有可无，模型能猜")),
      ["A", "B", "C"],
      "schema 是模型理解工具能力的唯一依据；模糊会导致选错或产出非法参数。"),
    q("ai-fc-3", "judge", "intermediate", "must_know",
      "Function Calling 返回的结果就是工具已执行完毕的返回值。",
      JUDGE_OPTIONS, ["B"],
      "模型只返回“调用请求”，真正执行由应用负责；若未实现对应工具或不校验，模型拿不到真实结果。"),
    q("ai-fc-4", "multiple", "challenge", "advanced",
      "多个工具并行/串行调用时，保证结果正确聚合的做法包括？",
      opt(("A", "用唯一 call_id 关联调用与结果"), ("B", "对写库/发消息等副作用工具谨慎并行"),
          ("C", "串行需等待上一步结果再决定下一步"), ("D", "所有工具必须一次性并行才高效")),
      ["A", "B", "C"],
      "配对与顺序控制是关键；有副作用的工具并行需事务与幂等，不能盲目并发。"),
    q("ai-fc-5", "single", "intermediate", "advanced",
      "为何要对工具入参做严格的 JSON Schema 校验？",
      opt(("A", "在进业务前拦截越界/缺字段/类型错误，避免脏数据进入外部系统"),
          ("B", "仅为美观"), ("C", "提高模型参数量"), ("D", "减少提示长度")),
      ["A"],
      "模型可能生成非法参数；严格校验能返回修正提示让模型重试，避免故障扩散。"),
]

# ---- Agent 智能体 (must_know/advanced/challenge) ----
QUESTIONS += [
    q("ai-agent-1", "single", "basic", "must_know",
      "什么是 AI Agent？它与单次 LLM 调用的核心区别？",
      opt(("A", "Agent 能自主规划、调用工具、迭代反思以完成多步目标"),
          ("B", "Agent 不需要大模型"), ("C", "两者完全相同"), ("D", "Agent 只能做文本分类")),
      ["A"],
      "Agent 在 LLM 之上加规划、工具使用与记忆回路，能分解任务、执行动作并据反馈调整。"),
    q("ai-agent-2", "single", "intermediate", "must_know",
      "ReAct 范式（Reason + Act）指的是？",
      opt(("A", "交替进行“思考理由”与“执行动作”，再观察结果继续"),
          ("B", "只做推理不做动作"), ("C", "只做动作不思考"), ("D", "一种数据库事务模型")),
      ["A"],
      "ReAct 让模型输出 Thought→Action→Observation 循环，把推理与行动交织，提升可控性与可解释性。"),
    q("ai-agent-3", "multiple", "intermediate", "must_know",
      "Agent 的“规划 / 记忆 / 工具”三大能力分别解决什么？",
      opt(("A", "规划：把目标拆成可执行步骤"), ("B", "记忆：保存与复用历史上下文"),
          ("C", "工具：连接外部系统与实时数据"), ("D", "三者都只用于训练模型")),
      ["A", "B", "C"],
      "规划决定“做什么”，记忆解决“记得什么”，工具解决“能动手做什么”。"),
    q("ai-agent-4", "judge", "intermediate", "must_know",
      "Agent 应该是完全自主循环的，不该有任何人工介入。",
      JUDGE_OPTIONS, ["B"],
      "高风险动作（删数据、发消息、支付）通常需要 human-in-the-loop 确认；可控性比“全自动”更重要。"),
    q("ai-agent-5", "multiple", "challenge", "advanced",
      "关于 Agent 的短期/长期记忆设计，下列合理的做法有？",
      opt(("A", "短期用对话历史+滑动窗口/摘要控制上下文"),
          ("B", "长期用向量库存经验与用户画像"), ("C", "需去重与遗忘策略避免矛盾"),
          ("D", "记忆越长越好，永不清理")),
      ["A", "B", "C"],
      "记忆需有边界：短期控窗口、长期可检索、并做去重与遗忘以防上下文膨胀与矛盾。"),
    q("ai-agent-6", "multiple", "challenge", "advanced",
      "多 Agent 协作的常见编排模式包括？",
      opt(("A", "主管-工人（manager-worker）"), ("B", "辩论/评审（critic）"),
          ("C", "流水线（pipeline）"), ("D", "共享黑板（blackboard）")),
      ["A", "B", "C", "D"],
      "多种模式各有侧重；关键在角色边界、消息协议与冲突解决，避免无限协商。"),
    q("ai-agent-7", "multiple", "challenge", "advanced",
      "Agent 循环中避免无限循环与失控的手段包括？",
      opt(("A", "设最大步数/最大 token 预算"), ("B", "检测重复动作与无进展并提前终止"),
          ("C", "工具失败上限与兜底"), ("D", "完全不设任何上限以求最优")),
      ["A", "B", "C"],
      "必须有步数/预算护栏、停滞检测与失败上限，否则易陷入失控循环。"),
    q("ai-agent-8", "single", "challenge", "advanced",
      "Agent 可观测性（tracing）为什么重要？",
      opt(("A", "能回放每一步思考/工具/结果，便于调试、评估与成本控制"),
          ("B", "仅用于美化界面"), ("C", "会降低模型能力"), ("D", "只在训练时需要")),
      ["A"],
      "Agent 决策链路长且非确定，tracing 记录完整轨迹，是定位错误与优化 prompt/工具设计的必备能力。"),
    q("ai-agent-9", "multiple", "challenge", "advanced",
      "Agent 的“反思（reflection）”机制的价值包括？",
      opt(("A", "生成后自我批评/评估"), ("B", "发现错误再迭代改进"),
          ("C", "把“生成-评价-修正”闭环化"), ("D", "让模型一次就百分百正确")),
      ["A", "B", "C"],
      "反思将自我评审闭环化，显著提升复杂任务最终质量，但无法保证一次正确。"),
    q("ai-agent-10", "judge", "intermediate", "advanced",
      "Agent 调用工具失败时，应直接抛出异常并终止整个流程。",
      JUDGE_OPTIONS, ["B"],
      "健壮 Agent 应捕获失败、把错误回传模型让其重试或换策略，仅在超出重试/预算上限时才优雅终止。"),
    q("ai-agent-11", "multiple", "challenge", "advanced",
      "Agent 的护栏（guardrails）与安全控制包括？",
      opt(("A", "输入校验与注入防护"), ("B", "输出格式与内容审核"),
          ("C", "工具调用白名单与权限最小化"), ("D", "敏感动作人工确认与成本上限")),
      ["A", "B", "C", "D"],
      "护栏在输入/输出/工具层设约束，防止越权与有害行为，是生产落地的底线。"),
]

# ---- 评估、幻觉、可观测 (advanced) ----
QUESTIONS += [
    q("ai-eval-1", "multiple", "challenge", "advanced",
      "评估 LLM 应用质量可用的指标包括？",
      opt(("A", "任务准确率与 Faithfulness（忠实度）"), ("B", "Answer Relevancy（答案相关性）"),
          ("C", "线上采纳率/重试率/会话完成率"), ("D", "仅看模型参数量")),
      ["A", "B", "C"],
      "需离线（准确率/忠实度/相关性）与在线（采纳率/成本/延迟）结合；参数量不是质量指标。"),
    q("ai-eval-2", "single", "challenge", "advanced",
      "LLM-as-a-Judge（用模型当裁判）的主要风险是？",
      opt(("A", "裁判模型本身有偏差、易被长文本位置效应影响"), ("B", "完全客观无风险"),
          ("C", "只能用于训练不能评测"), ("D", "成本为零")),
      ["A"],
      "模型裁判存在偏好/位置偏差与自赞倾向；应校准、双人对照、关键项人工抽检。"),
    q("ai-eval-3", "multiple", "challenge", "nice_to_know",
      "RAGAS 等框架通常从哪些维度评估 RAG？",
      opt(("A", "Context Precision / Recall（检索质量）"), ("B", "Faithfulness（答案是否忠于上下文）"),
          ("C", "Answer Relevancy（答案相关性）"), ("D", "仅评估生成速度")),
      ["A", "B", "C"],
      "RAGAS 把端到端 RAG 拆成可定位瓶颈的子指标：检索质量与答案忠实/相关。"),
    q("ai-eval-4", "judge", "intermediate", "advanced",
      "人工评估不可扩展，所以 LLM 应用完全不需要人工评估。",
      JUDGE_OPTIONS, ["B"],
      "人工评估虽贵但仍是金标准，尤其用于校准自动指标、发现长尾与安全风险；应“自动筛劣+人工抽评”。"),
    q("ai-eval-5", "single", "intermediate", "must_know",
      "关于大模型幻觉（hallucination），下列说法正确的是？",
      opt(("A", "指生成看似合理但无依据的内容，RAG 可缓解但不保证消除"),
          ("B", "只发生在翻译场景"), ("C", "RAG 能 100% 消除幻觉"), ("D", "是数据库术语")),
      ["A"],
      "幻觉源于概率生成与知识缺口；RAG 通过注入证据降低概率，但检索不全/模型仍可能编造。"),
]

# ---- 成本、延迟、工程化 (advanced) ----
QUESTIONS += [
    q("ai-cost-1", "multiple", "challenge", "advanced",
      "降低 LLM 应用延迟与成本的手段包括？",
      opt(("A", "缓存高频请求"), ("B", "模型路由（简单任务用小模型）"),
          ("C", "提示精简与上下文压缩"), ("D", "增大 max_tokens 提升质量")),
      ["A", "B", "C"],
      "缓存、路由、压缩与流式是降本提速主力；盲目增大 max_tokens 只增成本。"),
    q("ai-cost-2", "single", "challenge", "nice_to_know",
      "什么是模型路由（model routing）/ 级联（cascade）？",
      opt(("A", "用轻量模型先判难度，简单请求直接答、难的才升级大模型"),
          ("B", "把请求随机分发到任意模型"), ("C", "仅用于离线训练"), ("D", "等于微调")),
      ["A"],
      "路由/级联以低成本模型覆盖多数简单请求，仅在置信度低时调用更强（更贵）模型，质量近似下显著降本。"),
    q("ai-cost-3", "judge", "intermediate", "nice_to_know",
      "小模型永远无法替代大模型完成任何任务。",
      JUDGE_OPTIONS, ["B"],
      "经蒸馏/微调的小模型在大量垂直任务上已可媲美大模型且更快更省；并非“永远”，应依任务选型。"),
    q("ai-cost-4", "multiple", "challenge", "advanced",
      "生产环境为 LLM 调用设计降级与兜底的做法包括？",
      opt(("A", "主模型超时/限流则切备用或更小模型"), ("B", "关键路径用缓存/规则兜底"),
          ("C", "返回友好错误而非崩溃"), ("D", "记录失败指标告警")),
      ["A", "B", "C", "D"],
      "多层次降级保障可用性：换模型、缓存兜底、友好错误与告警，避免雪崩。"),
]

# ---- 多模态 (nice_to_know) ----
QUESTIONS += [
    q("ai-mm-1", "single", "basic", "nice_to_know",
      "多模态模型是指？",
      opt(("A", "能同时理解和/或生成文本、图像、音频等多种模态的模型"),
          ("B", "只能处理文本"), ("C", "仅用于视频压缩"), ("D", "等同于传统 OCR")),
      ["A"],
      "多模态模型统一处理多种感官数据，如视觉-语言模型可图文互理解，支撑看图问答等应用。"),
    q("ai-mm-2", "multiple", "intermediate", "nice_to_know",
      "关于多模态检索（如图文检索），下列说法正确的有？",
      opt(("A", "用多模态嵌入把图像与文本编码到同一向量空间"),
          ("B", "文本 query 可直接检索相关图片或图注"),
          ("C", "常用于商品、文档图表、知识库配图检索"), ("D", "只能在纯文本空间内检索")),
      ["A", "B", "C"],
      "多模态嵌入让跨模态语义对齐，支持以文搜图、以图搜文等检索增强场景。"),
    q("ai-mm-3", "judge", "basic", "nice_to_know",
      "多模态模型只能接受图像和文本，不能处理音频。",
      JUDGE_OPTIONS, ["B"],
      "不少模型已支持音频（语音转写、音频理解）甚至视频；模态支持取决于具体架构与训练数据。"),
]

# ---- 大模型原理（选修 nice_to_know） ----
QUESTIONS += [
    q("ai-theory-1", "single", "intermediate", "nice_to_know",
      "Transformer 的核心机制是？",
      opt(("A", "自注意力（Self-Attention），并行建模序列中任意两位置依赖"),
          ("B", "循环单元逐个处理"), ("C", "卷积滑动窗口"), ("D", "单纯的词袋叠加")),
      ["A"],
      "Transformer 用自注意力替代 RNN 的时序递推，实现全局并行依赖建模，是现代 LLM 的骨架。"),
    q("ai-theory-2", "single", "challenge", "nice_to_know",
      "多头注意力（Multi-Head Attention）的作用是？",
      opt(("A", "在不同子空间并行捕捉多种语义/语法关系，丰富表示"),
          ("B", "减少参数量到零"), ("C", "只在解码器使用"), ("D", "等价于单层感知机")),
      ["A"],
      "多个注意力头各自关注不同关系（句法、指代、距离等），拼接后线性融合，使模型同时捕获多样化依赖。"),
    q("ai-theory-3", "single", "intermediate", "nice_to_know",
      "为什么 Transformer 需要位置编码（Positional Encoding）？",
      opt(("A", "自注意力本身无序，需显式注入 token 位置信息"), ("B", "为了压缩模型"),
          ("C", "仅在微调时需要"), ("D", "用于图像分类")),
      ["A"],
      "注意力对顺序不敏感，加入位置编码让模型感知词序，否则“猫追狗”与“狗追猫”无法区分。"),
    q("ai-theory-4", "single", "intermediate", "nice_to_know",
      "预训练（pretraining）与微调（fine-tuning）的区别是？",
      opt(("A", "预训练学通用表示，微调在特定任务数据上适配"),
          ("B", "两者完全一样"), ("C", "微调先于预训练"), ("D", "预训练只用于图像")),
      ["A"],
      "预训练习得广泛语言/世界知识；微调用小规模标注数据把通用能力迁移到下游任务。"),
    q("ai-theory-5", "single", "challenge", "nice_to_know",
      "LoRA / QLoRA 微调的核心思想是？",
      opt(("A", "冻结原权重，向注意力/线性层注入低秩可训练矩阵，仅训少量参数"),
          ("B", "重新训练整个模型全部参数"), ("C", "仅改变输入分词"), ("D", "等于提示工程")),
      ["A"],
      "LoRA 以低秩矩阵适配任务，省显存易切换；QLoRA 再叠加 4-bit 量化，把大模型微调压到单卡消费级 GPU。"),
    q("ai-theory-6", "single", "challenge", "nice_to_know",
      "RLHF（基于人类反馈的强化学习）用于？",
      opt(("A", "用奖励模型+强化学习最大化人类偏好，对齐有用/诚实/无害"),
          ("B", "仅加速推理"), ("C", "替代分词器"), ("D", "等同于数据增强")),
      ["A"],
      "RLHF 先用人工偏好训练奖励模型，再以 PPO 等微调策略模型，使输出更符合人类偏好，是 ChatGPT 类对齐关键。"),
    q("ai-theory-7", "judge", "intermediate", "nice_to_know",
      "微调一定比 Prompt Engineering 效果更好。",
      JUDGE_OPTIONS, ["B"],
      "视任务与数据而定：多数场景提示工程+检索已足够灵活；仅当需固化领域风格/低成本高并发时微调才显优势。"),
    q("ai-theory-8", "single", "challenge", "nice_to_know",
      "模型量化（quantization）主要影响什么？",
      opt(("A", "用更低精度表示权重，降低显存与推理成本，可能轻微损精度"),
          ("B", "只改变训练速度"), ("C", "提升模型参数量"), ("D", "与推理无关")),
      ["A"],
      "量化把权重压到更低比特，显著节省显存、加速推理，常伴可接受的质量折损，是部署端侧/单卡的关键。"),
    q("ai-theory-9", "single", "challenge", "nice_to_know",
      "知识蒸馏（knowledge distillation）是指？",
      opt(("A", "用大模型（教师）的输出/软标签训练小模型（学生）以迁移能力"),
          ("B", "把模型拆成多份分布式训练"), ("C", "仅用于数据清洗"), ("D", "等同于剪枝")),
      ["A"],
      "蒸馏让小模型模仿大模型的软概率分布（含暗知识），在远小体积下逼近大模型表现，常用于端侧与降本。"),
    q("ai-theory-10", "single", "challenge", "nice_to_know",
      "注意力中的 KV Cache 如何降低自回归推理成本？",
      opt(("A", "缓存历史 K/V，避免重复计算，将每步复杂度从 O(n²) 降到 O(n)"),
          ("B", "增加每步计算量"), ("C", "只在训练时使用"), ("D", "与上下文长度无关")),
      ["A"],
      "解码时每步要对所有已生成 token 的 K/V 做注意力；KV Cache 复用历史，是长序列推理提速与省算的关键。"),
    q("ai-theory-11", "multiple", "challenge", "nice_to_know",
      "关于大模型的“涌现能力（emergent abilities）”，下列说法合理的有？",
      opt(("A", "某些能力在规模/数据跨过阈值后才突然出现"),
          ("B", "小模型也可能具备部分能力，并非绝对二分"),
          ("C", "存在“看似涌现实为平滑”的学术争议"), ("D", "规模越大一定线性越好，毫无争议")),
      ["A", "B", "C"],
      "涌现指能力在阈值后突现的现象，但度量与“是否真涌现”仍有争议；并非规模越大越好这么简单。"),
    q("ai-theory-12", "multiple", "challenge", "nice_to_know",
      "关于 Self-Attention 的计算步骤，下列说法正确的有？",
      opt(("A", "由 token 映射出 Query/Key/Value 三向量"), ("B", "用 Q 与 K 点积并缩放后 softmax 得注意力权重"),
          ("C", "权重对 V 加权求和得到上下文表示"), ("D", "无需任何矩阵运算，纯查表完成")),
      ["A", "B", "C"],
      "Self-Attention 经 Q/K/V 投影、缩放点积、softmax 与加权 V 求和，全靠线性变换与归一化完成。"),
]


def to_staging(questions: list[dict]) -> list[dict]:
    """canonical → staging 素材格式（question_merge 读取的 schema）。"""
    records = []
    for index, item in enumerate(questions, start=1):
        kind = item["kind"]
        if kind == "judge":
            answer = "正确" if item["answer"] == ["A"] else "错误"
            options = JUDGE_OPTIONS
        elif kind == "single":
            answer = item["answer"][0]
            options = item["options"]
        else:  # multiple
            answer = ",".join(item["answer"])
            options = item["options"]
        records.append({
            "n": index,
            "language": item["language"],
            "direction": item["direction"],
            "kind": kind,
            "difficulty": item["difficulty"],
            "essentiality": item["essentiality"],
            "stem": item["prompt"],
            "options": options,
            "answer": answer,
            "explanation": item["explanation"],
        })
    return records


def validate(questions: list[dict]) -> None:
    seen_ids, seen_prompts = set(), set()
    for item in questions:
        assert item["id"] not in seen_ids, f"重复 id: {item['id']}"
        seen_ids.add(item["id"])
        assert item["prompt"] not in seen_prompts, f"重复 prompt: {item['prompt']}"
        seen_prompts.add(item["prompt"])
        opts, ans = item["options"], item["answer"]
        assert item["kind"] in ("single", "multiple", "judge")
        if item["kind"] == "judge":
            assert opts == JUDGE_OPTIONS, f"{item['id']} 判断题选项文案不符"
            assert ans in (["A"], ["B"]), f"{item['id']} 判断题答案应为 A 或 B"
        else:
            keys = {o["key"] for o in opts}
            assert 2 <= len(opts) <= 6, f"{item['id']} 选项数越界"
            assert set(ans).issubset(keys), f"{item['id']} answer 越出 options: {ans} vs {keys}"
            if item["kind"] == "single":
                assert len(ans) == 1, f"{item['id']} 单选答案应恰 1"
            else:
                assert len(ans) >= 2, f"{item['id']} 多选答案应 ≥2"
        assert item["explanation"].strip(), f"{item['id']} explanation 为空"
        assert item["difficulty"] in ("basic", "intermediate", "challenge")
        assert item["essentiality"] in ("must_know", "advanced", "nice_to_know")
        assert item["language"] == "", f"{item['id']} AI 题语言必须为空串"


def main() -> None:
    validate(QUESTIONS)
    records = to_staging(QUESTIONS)
    STAGING_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写出 staging 素材：{STAGING_PATH}")
    print(f"题目数：{len(records)}（下一步请运行 "
          f"`python -m app.services.question_merge --write` 重建 questions.json）")


if __name__ == "__main__":
    main()
