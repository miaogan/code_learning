import type { SpokenChapter } from '../../lib/spokenTypes'

/**
 * 黄金稿 03 · 分布式事务与最终一致性（A 类最抽象章 → 单口自问自答）。
 * 单口只给概念章：概念章的重复本来就是理解机制，不需要对话来推（§5.7）。
 * 情绪强度压到 0.4：抽象概念最怕朗诵腔，越用力越像念说明书。
 */
export const BE_DISTRIBUTED_CONSISTENCY_SCRIPT: SpokenChapter = {
  chapterId: 'be-distributed-consistency',
  form: 'solo',
  scriptVersion: '1.0.0',
  voice: {
    model: 'CosyVoice2-0.5B',
    emotionGain: 0.4,
    lead: 'solo-adult-male',
  },
  sections: [
    {
      sectionId: 'concept',
      title: '为什么本地事务不够用',
      segments: [
        {
          speaker: 'narrator',
          emotion: 'banter',
          lines: ['今天说个挺硬的话题。', '分布式事务。'],
        },
        {
          speaker: 'narrator',
          emotion: 'setup',
          lines: ['你可能觉得，加个事务注解就完了。', '一个 BEGIN，一个 COMMIT。', '数据库替你把原子性管了。'],
        },
        {
          speaker: 'narrator',
          emotion: 'deadpan',
          lines: ['单体里确实是这样。'],
        },
        {
          speaker: 'narrator',
          emotion: 'contrast',
          lines: ['可一旦跨了服务，这招就失灵了。', '两个库，各自有各自的事务。', '它们互相看不见对方。'],
        },
        {
          speaker: 'narrator',
          emotion: 'banter',
          lines: ['于是有人想到两阶段提交。', '先问一圈「都能提交吗」。', '都点头，再一起提交。'],
        },
        {
          speaker: 'narrator',
          emotion: 'setup',
          lines: ['听着挺稳。', '代价是整个过程要锁住资源。', '任何一个参与者卡住，大家都得等。'],
        },
        {
          speaker: 'narrator',
          emotion: 'deadpan',
          lines: ['吞吐和延迟，一起完蛋。'],
        },
        {
          speaker: 'narrator',
          emotion: 'contrast',
          lines: ['所以多数业务退了一步。', '不要强一致，要最终一致。'],
        },
        {
          speaker: 'narrator',
          emotion: 'punch',
          lines: ['「跨库强一致」这四个字，本质上是个愿望。'],
        },
        {
          speaker: 'narrator',
          emotion: 'wrap',
          lines: ['说白了，工程重心换了。', '从「怎么保证原子」，换成「怎么发现不一致」。'],
        },
        {
          speaker: 'narrator',
          emotion: 'wrap',
          lines: ['这个转向，是理解后面所有模式的前提。'],
        },
      ],
    },
    {
      sectionId: 'patterns',
      title: 'Saga、Outbox 与事务消息',
      segments: [
        {
          speaker: 'narrator',
          emotion: 'banter',
          lines: ['第一步是承认它不一致。', '第二步是让它自己收敛。'],
        },
        {
          speaker: 'narrator',
          emotion: 'setup',
          lines: ['Saga 的思路是补偿。', '每一步配一个反向操作。', '失败了就往前回滚。'],
        },
        {
          speaker: 'narrator',
          emotion: 'deadpan',
          lines: ['补偿不是回滚，是另一笔业务。'],
        },
        {
          speaker: 'narrator',
          emotion: 'contrast',
          lines: ['对，退款不是撤销扣款。', '它是一笔新的、方向相反的交易。'],
        },
        {
          speaker: 'narrator',
          emotion: 'banter',
          lines: ['Outbox 解决的是另一个坑。', '库改了，消息没发出去。', '两个系统，谁也不知道对方成没成。'],
        },
        {
          speaker: 'narrator',
          emotion: 'setup',
          lines: ['办法是把两件事塞进一个本地事务。', '改数据，和写一条待发事件。', '要么都成，要么都不成。'],
        },
        {
          speaker: 'narrator',
          emotion: 'deadpan',
          lines: ['然后再由别的进程去发。'],
        },
        {
          speaker: 'narrator',
          emotion: 'contrast',
          lines: ['发失败了就重试。', '重试就会重复。', '所以消费端必须幂等。'],
        },
        {
          speaker: 'narrator',
          emotion: 'punch',
          lines: ['补偿最怕的，是补偿自己也需要补偿。'],
        },
        {
          speaker: 'narrator',
          emotion: 'wrap',
          lines: ['说白了，一致性靠的是「可重试」。', '不是靠「不会重复」。'],
        },
        {
          speaker: 'narrator',
          emotion: 'wrap',
          lines: ['把重复变成无害，比杜绝重复便宜得多。'],
        },
      ],
    },
    {
      sectionId: 'practice',
      title: '落地时的三件大事',
      segments: [
        {
          speaker: 'narrator',
          emotion: 'banter',
          lines: ['落地的时候，有三件事绕不开。'],
        },
        {
          speaker: 'narrator',
          emotion: 'setup',
          lines: ['第一件是幂等键。', '补偿可能被执行两次。', '退款逻辑必须能安全重放。'],
        },
        {
          speaker: 'narrator',
          emotion: 'deadpan',
          lines: ['退两次款，财务会来找你。'],
        },
        {
          speaker: 'narrator',
          emotion: 'contrast',
          lines: ['第二件是状态机。', '每个中间态都要能查、能对账。'],
        },
        {
          speaker: 'narrator',
          emotion: 'banter',
          lines: ['第三件是可观测。', '整条链路一个 trace id。', '串起每一步，也串起每一次补偿。'],
        },
        {
          speaker: 'narrator',
          emotion: 'setup',
          lines: ['不然出了问题，你只能靠猜。', '猜错的成本，比多打一行日志高得多。'],
        },
        {
          speaker: 'narrator',
          emotion: 'deadpan',
          lines: ['日志不贵，事故很贵。'],
        },
        {
          speaker: 'narrator',
          emotion: 'punch',
          lines: ['对账脚本不写，事故复盘时就得手写。'],
        },
        {
          speaker: 'narrator',
          emotion: 'wrap',
          lines: ['说白了，分布式事务是运维问题。', '不是数据库问题。'],
        },
        {
          speaker: 'narrator',
          emotion: 'wrap',
          lines: ['先想清楚怎么发现它坏了，再谈怎么让它不坏。'],
        },
      ],
    },
    {
      sectionId: 'pitfalls',
      title: '常见坑与自测',
      segments: [
        {
          speaker: 'narrator',
          emotion: 'banter',
          lines: ['最后说几个真实的坑。'],
        },
        {
          speaker: 'narrator',
          emotion: 'setup',
          lines: ['第一个：以为最终一致等于一定一致。', '消息会丢，补偿也会失败。', '流程可能永远卡在中间态。'],
        },
        {
          speaker: 'narrator',
          emotion: 'deadpan',
          lines: ['它卡着，还挺安静。'],
        },
        {
          speaker: 'narrator',
          emotion: 'contrast',
          lines: ['所以要有超时扫描。', '还要有对账。', '这两件事不做，最终一致就是许愿。'],
        },
        {
          speaker: 'narrator',
          emotion: 'banter',
          lines: ['第二个坑是补偿写成了删除。', '业务失败，把对方的数据直接抹了。', '这在审计上是灾难。'],
        },
        {
          speaker: 'narrator',
          emotion: 'setup',
          lines: ['补偿应该是新的一笔业务。', '有记录，有方向，能追溯。'],
        },
        {
          speaker: 'narrator',
          emotion: 'deadpan',
          lines: ['第三个坑，是把幂等键交给消息 ID。'],
        },
        {
          speaker: 'narrator',
          emotion: 'contrast',
          lines: ['消息重投，ID 可能变。', '业务键不会变。', '订单号加事件类型，才是稳的。'],
        },
        {
          speaker: 'narrator',
          emotion: 'punch',
          lines: ['许愿式的一致性，最后都靠人肉兜底。'],
        },
        {
          speaker: 'narrator',
          emotion: 'wrap',
          lines: ['说白了，最终一致的兜底是人对账。', '系统只负责把账记全。'],
        },
        {
          speaker: 'narrator',
          emotion: 'wrap',
          lines: ['能重试的，才叫最终一致。'],
        },
      ],
    },
  ],
}
