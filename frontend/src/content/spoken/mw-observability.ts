import type { SpokenChapter } from '../../lib/spokenTypes'

/**
 * 黄金稿 02 · 可观测性与线上排障（B 类场景章 → 全对口抬杠）。
 * 场景章的价值在「错误做法 → 后果 → 正确做法」，所以通篇是逗哏装懂、捧哏推矛盾。
 */
export const MW_OBSERVABILITY_SCRIPT: SpokenChapter = {
  chapterId: 'mw-observability',
  form: 'duo',
  scriptVersion: '1.0.0',
  voice: {
    model: 'CosyVoice2-0.5B',
    emotionGain: 0.55,
    lead: 'dou-adult-male',
    support: 'peng-adult-male',
  },
  sections: [
    {
      sectionId: 'signals',
      title: '三支柱与两套方法',
      segments: [
        {
          speaker: 'dou',
          emotion: 'banter',
          lines: ['今天聊线上排障。', '不是聊怎么重启服务。'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: ['很多人一听说接口慢，就去翻日志。', '翻半天，最后发现是下游的问题。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['那您翻日志，是给谁看的？'],
        },
        {
          speaker: 'dou',
          emotion: 'contrast',
          lines: ['所以得先认三根柱子。', '指标、日志、链路。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['那先看哪个？'],
        },
        {
          speaker: 'dou',
          emotion: 'banter',
          lines: ['指标回答「有没有变慢」。', '日志回答「当时发生了什么」。', '链路回答「慢在哪一跳」。'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: ['三个问题，三个工具。', '别拿一个当三个用。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['有人拿日志当指标。'],
        },
        {
          speaker: 'dou',
          emotion: 'punch',
          lines: ['那叫肉眼监控。'],
        },
        {
          speaker: 'dou',
          emotion: 'wrap',
          lines: ['说白了，先问「我要回答哪个问题」。', '再挑工具。'],
        },
        {
          speaker: 'dou',
          emotion: 'wrap',
          lines: ['问错了问题，工具再好也白搭。'],
        },
      ],
    },
    {
      sectionId: 'trace',
      title: '一次慢请求的排查路径',
      segments: [
        {
          speaker: 'dou',
          emotion: 'banter',
          lines: ['线上说接口变慢了。', '第一件事是确认范围。', '是所有接口，还是某一个。'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: ['然后看是哪个服务。', '最后才看具体那一行。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['顺序反了会怎样？'],
        },
        {
          speaker: 'dou',
          emotion: 'contrast',
          lines: ['会花两小时，证明不是你的问题。'],
        },
        {
          speaker: 'peng',
          emotion: 'punch',
          lines: ['这结论不用查，我信。'],
        },
        {
          speaker: 'dou',
          emotion: 'banter',
          lines: ['看链路的时候，先找最长的那一跳。', '再分清楚，是自己算得慢，还是在等下游。'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: ['等下游，看对方的时间。', '自己算得慢，看 CPU 和锁。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['那 P99 呢？'],
        },
        {
          speaker: 'dou',
          emotion: 'contrast',
          lines: ['P99 才是用户的感受。', '平均值会把长尾抹平。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['那报表上不就挺好看？'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: ['好看是好看。', '一千个请求里，九个慢的。', '但那九个人，记你一辈子。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['这句能进总结吗？'],
        },
        {
          speaker: 'dou',
          emotion: 'wrap',
          lines: ['说白了，平均值是给报表看的。', '分位数才是给用户看的。'],
        },
        {
          speaker: 'dou',
          emotion: 'wrap',
          lines: ['排查从范围开始，不从日志开始。'],
        },
      ],
    },
    {
      sectionId: 'example',
      title: '一条能用的告警规则',
      segments: [
        {
          speaker: 'dou',
          emotion: 'banter',
          lines: ['告警规则，很多人写成心跳。', '每分钟响一次，响到大家关通知。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['关了通知，就清净了。'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: ['一条能用的告警，要有三样东西。', '阈值、持续时长、还有 runbook。'],
        },
        {
          speaker: 'dou',
          emotion: 'contrast',
          lines: ['只看瞬时值，抖一下就报。', '加上持续时长，噪音少一大半。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['runbook 是啥？'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: ['就是「响了之后先看哪儿」。', '没有 runbook 的告警，只是提醒你焦虑。'],
        },
        {
          speaker: 'peng',
          emotion: 'punch',
          lines: ['那还不如直接放个闹钟。'],
        },
        {
          speaker: 'dou',
          emotion: 'banter',
          lines: ['指标标签别塞高基数字段。', 'user_id 塞进去，时序数量能爆炸。'],
        },
        {
          speaker: 'dou',
          emotion: 'wrap',
          lines: ['说白了，告警要指向下一步动作。', '指不了，就删掉。'],
        },
        {
          speaker: 'dou',
          emotion: 'wrap',
          lines: ['告警的价值，在于让人少想一步。'],
        },
      ],
    },
    {
      sectionId: 'pitfalls',
      title: '常见坑与自测',
      segments: [
        {
          speaker: 'dou',
          emotion: 'banter',
          lines: ['最后说几个常见坑。', '第一个：监控全绿，用户说慢。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['谁在说谎？'],
        },
        {
          speaker: 'dou',
          emotion: 'contrast',
          lines: ['都没说谎。', '监控看的是服务端耗时。', '没算网络，也没算前端渲染。'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: ['第二个坑是采样。', '采样率太低，慢请求全漏掉。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['那采样调高呢？'],
        },
        {
          speaker: 'dou',
          emotion: 'contrast',
          lines: ['成本也高。', '关键接口全采，其他按比例。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['那怎么调？'],
        },
        {
          speaker: 'dou',
          emotion: 'banter',
          lines: ['第三个坑是日志。', '日志里没有统一的 trace id。', '一次请求散在五个服务里。'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: ['入口生成，全链路透传。', '再带上业务键，别打全量请求体。'],
        },
        {
          speaker: 'peng',
          emotion: 'punch',
          lines: ['打全量请求体，法务和运维一起找你。'],
        },
        {
          speaker: 'dou',
          emotion: 'wrap',
          lines: ['说白了，可观测性不是装个面板。', '是让问题自己能开口。'],
        },
        {
          speaker: 'dou',
          emotion: 'wrap',
          lines: ['问题开口之前，你先别急着猜。'],
        },
      ],
    },
  ],
}
