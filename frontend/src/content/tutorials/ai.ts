import type { TutorialChapter } from '../../lib/tutorialTypes'

/** AI 工程方向：注意力机制与 Transformer、检索增强生成（RAG）。 */
export const AI_CHAPTERS: TutorialChapter[] = [
  {
    id: 'ai-transformer',
    title: '注意力机制与 Transformer',
    direction: 'AI 工程',
    summary: '从「一句话里每个词该看谁」出发，拆开 Q/K/V、多头注意力与位置编码，理解 Transformer 为什么能并行。',
    sections: [
      {
        id: 'concept',
        title: '注意力在解决什么问题',
        blocks: [
          {
            kind: 'text',
            text: '循环神经网络按顺序读词，前面的信息要一路「传递」到后面，长句里容易丢失。注意力机制换了个思路：处理某个词时，直接去看句子里所有词，按相关程度加权汇总。这样任意两个位置的距离都是 1 步，长距离依赖不再被层层稀释。',
          },
          {
            kind: 'list',
            items: [
              'Query（Q）：当前这个词想找什么信息。',
              'Key（K）：每个词能提供什么信息的索引。',
              'Value（V）：每个词真正要交出去的内容。',
              '注意力权重：Q 与 K 的相似度归一化后，决定从每个 V 取多少。',
            ],
          },
        ],
      },
      {
        id: 'compute',
        title: '一次注意力计算的四个步骤',
        blocks: [
          {
            kind: 'table',
            headers: ['步骤', '计算', '作用'],
            rows: [
              ['打分', 'Q 与 K 做点积', '得到每对词的相关性'],
              ['缩放', '除以 √d_k', '避免维度过大时点积过大、softmax 饱和'],
              ['归一化', 'softmax', '把分数变成总和为 1 的权重'],
              ['加权求和', '权重 × V', '得到当前词的新表示'],
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: '为什么要缩放',
            text: '向量维度 d_k 越大，点积的数值方差越大，softmax 会变得极尖锐，梯度接近消失。除以 √d_k 让方差回到 1 附近，训练更稳定。',
          },
        ],
      },
      {
        id: 'example',
        title: '用数字走一遍',
        blocks: [
          {
            kind: 'text',
            text: '下面的例子固定了 2 维向量，只演示形状与加权过程，不含真实模型参数。重点看「权重和为 1」「输出是 V 的加权平均」这两个性质。',
          },
          {
            kind: 'code',
            language: 'python',
            caption: '单头注意力的最小实现（numpy，无训练）',
            code: [
              'import numpy as np',
              '',
              'def softmax(x):',
              '    e = np.exp(x - x.max(axis=-1, keepdims=True))',
              '    return e / e.sum(axis=-1, keepdims=True)',
              '',
              'def attention(q, k, v):',
              '    scores = q @ k.T',
              '    scores = scores / np.sqrt(k.shape[-1])',
              '    weights = softmax(scores)',
              '    return weights @ v, weights',
              '',
              'q = np.array([[1.0, 0.0]])',
              'k = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])',
              'v = np.array([[2.0, 0.0], [0.0, 3.0], [4.0, 5.0]])',
              '',
              'out, weights = attention(q, k, v)',
              'print(weights.sum(axis=-1))  # [1.] 权重恒为 1',
              'print(out)                   # V 的加权平均',
            ].join('\n'),
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              'Q·Kᵀ 得到 1×3 的分数，分别表示当前词对三个词的关注度。',
              '除以 √2 后 softmax，三个权重加起来等于 1。',
              '用权重对 V 加权求和，得到 1×2 的输出向量。',
              '多头注意力会并行做多组这样的计算，再把结果拼接后投影。',
            ],
          },
        ],
      },
      {
        id: 'pitfalls',
        title: '常见坑与自测',
        blocks: [
          {
            kind: 'note',
            tone: 'warn',
            title: '注意力本身不知道顺序',
            text: '把所有词打乱，注意力算出的结果只是跟着换位置，模型无法区分「我打你」和「你打我」。因此必须额外加位置编码（正弦编码或可学习的位置向量），顺序信息才进入表示。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: '为什么说 Transformer 比 RNN 更容易并行？',
                answer: '注意力对整句做矩阵运算，所有位置同一次计算完成，不依赖上一步的输出；RNN 必须按时间步串行。',
              },
              {
                question: '多头注意力的「多头」有什么用？',
                answer: '每个头用不同的投影，能同时关注不同关系（语法、指代、位置等），最后拼接融合，比单头表达能力更强。',
              },
              {
                question: '注意力权重能直接当解释吗？',
                answer: '不能。权重高不等于因果重要，多层多头的叠加让归因变得复杂；解释模型行为需要专门方法，别只看一张热力图。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'ai-rag',
    title: '检索增强生成（RAG）',
    direction: 'AI 工程',
    summary: '把「先查资料再回答」拆成切分、向量检索、重排、拼装上下文四步，并给出控制幻觉与引用来源的做法。',
    sections: [
      {
        id: 'flow',
        title: 'RAG 的完整链路',
        blocks: [
          {
            kind: 'text',
            text: '大模型的知识固化在参数里，问到私有文档或最新资料就容易编。RAG（Retrieval-Augmented Generation）在生成前先检索相关片段，把原文作为上下文交给模型，让回答有据可依。',
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              '离线：文档切分成片段，逐个向量化后写入向量库。',
              '在线：用户问题向量化，在库中找最相似的 Top-K 片段。',
              '重排：用更精细的模型对候选片段重新打分，去掉噪声。',
              '生成：把片段编号后拼进提示词，要求模型引用编号作答。',
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: '切分是效果上限',
            text: '片段太大，检索精度下降、上下文浪费；片段太小，语义被切断、答案不完整。常见做法是按结构（标题、段落）切，再留一定重叠，避免边界信息丢失。',
          },
        ],
      },
      {
        id: 'retrieval',
        title: '检索与重排的关键选择',
        blocks: [
          {
            kind: 'table',
            headers: ['环节', '常见做法', '要关注的问题'],
            rows: [
              ['向量化', '通用 embedding 或领域微调模型', '查询与文档要用同一模型'],
              ['检索', '余弦相似度 + Top-K', 'K 太小漏召回，太大引入噪声'],
              ['混合检索', '向量 + 关键词（BM25）', '专有名词、编号类查询更稳'],
              ['重排', 'cross-encoder 精排', '延迟与效果的权衡'],
            ],
          },
          {
            kind: 'text',
            text: '只做向量检索时，精确术语和数字容易被「语义相近但事实不同」的片段挤掉。工程上常用混合检索：向量负责语义，关键词负责精确命中，两路结果合并后再重排。',
          },
        ],
      },
      {
        id: 'example',
        title: '一次带引用的问答',
        blocks: [
          {
            kind: 'text',
            text: '提示词里给片段编号，并要求「每个结论后标注来源编号，没有依据就说不知道」。这样既约束了幻觉，也让用户能回到原文核对。',
          },
          {
            kind: 'code',
            language: 'text',
            caption: '拼装上下文与回答格式',
            code: [
              '你是一个只依据资料回答的助手。',
              '',
              '资料：',
              '[1] 本产品支持上传 PDF，单文件上限 10 MB。',
              '[2] 上传后只保留抽取正文，不保存原文件。',
              '[3] 简历解析失败时可重新上传，最多重试 3 次。',
              '',
              '问题：上传的文件会被永久保存吗？',
              '',
              '回答要求：',
              '- 每个结论后用 [编号] 标注来源；',
              '- 资料没有覆盖时回答「资料中未提及」，不要猜测。',
            ].join('\n'),
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              '检索命中 [2]，回答「不会保存原文件，只保留抽取正文」。',
              '引用编号 [2]，用户可点击回到原片段。',
              '若 Top-K 里没有相关片段，模型应明确说资料未提及。',
            ],
          },
        ],
      },
      {
        id: 'pitfalls',
        title: '常见坑与自测',
        blocks: [
          {
            kind: 'note',
            tone: 'warn',
            title: '检索错了，生成再强也救不回来',
            text: '很多「RAG 答错」的根因是没召回正确片段，而不是模型不行。排查顺序应该是：先看召回结果，再看重排，最后才调提示词与温度。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: 'RAG 和微调该怎么选？',
                answer: '知识经常变、需要引用来源时优先 RAG；要固定风格、格式或领域表达习惯时考虑微调，两者也可以组合。',
              },
              {
                question: '怎么评估 RAG 效果？',
                answer: '分开评：召回率/命中率衡量检索，答案正确率与引用准确率衡量生成；只看最终回答会掩盖检索问题。',
              },
              {
                question: '为什么要把片段编号写进上下文？',
                answer: '编号让模型能指出来源，也方便程序校验引用是否真实存在，减少「看似有据、实则编造」的回答。',
              },
            ],
          },
        ],
      },
    ],
  },
]
