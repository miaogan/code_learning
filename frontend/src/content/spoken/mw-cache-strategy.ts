import type { SpokenChapter } from '../../lib/spokenTypes'

/**
 * 黄金稿 01 · 缓存与失效策略（A+B 混合章 → 按小节拆单口 / 对口）。
 * 口径：VERSION-PLAN §5.6 / §5.7 —— 轻松泛听，三翻四抖，笑点只来自认知反转。
 */
export const MW_CACHE_STRATEGY_SCRIPT: SpokenChapter = {
  chapterId: 'mw-cache-strategy',
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
      sectionId: 'where',
      title: '缓存放在哪一层',
      form: 'solo',
      segments: [
        {
          speaker: 'narrator',
          emotion: 'banter',
          lines: ['咱们今天聊缓存。', '不是聊怎么装 Redis。', '是聊它该待在哪儿。'],
        },
        {
          speaker: 'narrator',
          emotion: 'setup',
          lines: [
            '你可能会觉得，缓存就是加个 Redis。',
            '把数据放近一点儿，查得快。',
            '这事儿听着挺简单。',
          ],
        },
        {
          speaker: 'narrator',
          emotion: 'contrast',
          lines: ['我一开始也这么想。', '后来发现它不是一层。', '它是一组层。'],
        },
        {
          speaker: 'narrator',
          emotion: 'deadpan',
          lines: ['层与层之间，差着好几个数量级。'],
        },
        {
          speaker: 'narrator',
          emotion: 'banter',
          lines: ['离用户最近的，是浏览器和 CDN。', '静态资源、公开接口都搁这儿。', '好处是连回源都省了。'],
        },
        {
          speaker: 'narrator',
          emotion: 'setup',
          lines: ['再往里，是进程内的本地缓存。', '一个 Map，一个 LRU。', '纳秒级，快得离谱。'],
        },
        {
          speaker: 'narrator',
          emotion: 'deadpan',
          lines: ['但它只活在这个进程里。', '重启一下，全没了。'],
        },
        {
          speaker: 'narrator',
          emotion: 'contrast',
          lines: ['再往里，才是分布式缓存。', 'Redis、Memcached 这一档。', '亚毫秒级，大家共用一份。'],
        },
        {
          speaker: 'narrator',
          emotion: 'banter',
          lines: ['最后一层是数据库自己。', 'Buffer Pool 也是缓存。', '只是它不用你操心。'],
        },
        {
          speaker: 'narrator',
          emotion: 'wrap',
          lines: ['说白了，缓存是按距离排的队。', '越近越快，也越难保证一致。'],
        },
        {
          speaker: 'narrator',
          emotion: 'setup',
          lines: ['所以第一个问题不是「用不用缓存」。', '是「这份数据能容忍多旧」。'],
        },
        {
          speaker: 'narrator',
          emotion: 'deadpan',
          lines: ['容忍不了一秒的，别随便加缓存。'],
        },
        {
          speaker: 'narrator',
          emotion: 'banter',
          lines: ['读多写少，这是前提。', '命中率长期低于八成，也是白搭。'],
        },
        {
          speaker: 'narrator',
          emotion: 'wrap',
          lines: ['先算收益，再动手。'],
        },
      ],
    },
    {
      sectionId: 'expire',
      title: 'TTL、淘汰与三类异常',
      segments: [
        {
          speaker: 'dou',
          emotion: 'banter',
          lines: ['TTL 设上，缓存就不脏了。', '这事儿也没啥好说的。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['那要是全在同一天过期呢？'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: ['那……那就是雪崩呗。', '这不重要，加机器就行。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['加机器之前，谁先扛那波回源？'],
        },
        {
          speaker: 'dou',
          emotion: 'punch',
          lines: ['行吧，我承认，那天是我值班。'],
        },
        {
          speaker: 'dou',
          emotion: 'banter',
          lines: [
            '正经说，TTL 解决的是数据会变。',
            '淘汰解决的是内存会满。',
            '这两件事，谁也替不了谁。',
          ],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['那什么时候会出事？'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: [
            '但有个事实改不了。',
            '缓存没命中的那一秒，请求会一起去敲数据库。',
          ],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['三类异常，都是在这一秒被放大的。'],
        },
        {
          speaker: 'dou',
          emotion: 'banter',
          lines: ['先说穿透。', '查一个根本不存在的东西。', '每次都回源，缓存形同虚设。'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: ['解法是空值缓存，或者布隆过滤器。', '空值也给个短 TTL，别让它一直空着。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['短到多短？'],
        },
        {
          speaker: 'dou',
          emotion: 'contrast',
          lines: ['比正常数据短一截就行。', '目的是挡住重复的无效查询。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['那这时候咋办？'],
        },
        {
          speaker: 'dou',
          emotion: 'banter',
          lines: ['再说击穿。', '单个热点键，过期那一瞬间。', '一堆并发同时回源同一行。'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: ['互斥重建，只放一个请求进去。', '或者逻辑过期，物理上不删。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['那读到的就是旧值。'],
        },
        {
          speaker: 'dou',
          emotion: 'contrast',
          lines: ['对，先让读过去。', '后台慢慢重建，别让用户等锁。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['那雪崩呢？'],
        },
        {
          speaker: 'dou',
          emotion: 'banter',
          lines: ['最后是雪崩。', '一大批键，同一时刻到期。', '回源流量整体抬升。'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: ['解法是 TTL 加随机抖动。', '同一批数据，过期时间打散。'],
        },
        {
          speaker: 'peng',
          emotion: 'punch',
          lines: ['所以「整点缓存」这四个字，最好别出现在代码里。'],
        },
        {
          speaker: 'dou',
          emotion: 'wrap',
          lines: ['说白了，三类异常都在赌一件事。', '赌那一秒没人来。'],
        },
        {
          speaker: 'dou',
          emotion: 'wrap',
          lines: ['赌输了，数据库先知道。'],
        },
      ],
    },
    {
      sectionId: 'example',
      title: 'Cache-Aside 的正确写法',
      segments: [
        {
          speaker: 'dou',
          emotion: 'banter',
          lines: ['写缓存有个经典写法。', '先查缓存，没有再查库。', '查到就回填，顺手给个 TTL。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['听着像标准答案。'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: ['标准答案里藏着两个坑。', '第一个坑是「不存在」。', '库里没有，缓存里也不留。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['那第一个坑，怎么就坑了？'],
        },
        {
          speaker: 'dou',
          emotion: 'contrast',
          lines: ['那下次还查这个不存在的 id。', '又回源一次。', '被人刷接口，数据库就热闹了。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['所以空值也要缓存。'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: ['对，短 TTL 的空值。', '挡住重复的无效查询。'],
        },
        {
          speaker: 'dou',
          emotion: 'banter',
          lines: ['第二个坑在写。', '很多人写完库，顺手更新缓存。', '看着更及时，其实是雷。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['两个写请求同时来呢？'],
        },
        {
          speaker: 'dou',
          emotion: 'contrast',
          lines: ['A 先写库，B 后写库。', 'B 先更新缓存，A 后更新。', '缓存里留下的是 A 的旧值。'],
        },
        {
          speaker: 'peng',
          emotion: 'punch',
          lines: ['您这缓存，还挺怀旧。'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: ['所以顺序是先写库、后删缓存。', '删除是幂等的，重试也安全。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['那删失败了怎么办？'],
        },
        {
          speaker: 'dou',
          emotion: 'contrast',
          lines: ['重试，或者延迟双删。', '别把「删缓存」当顺手的事。'],
        },
        {
          speaker: 'dou',
          emotion: 'wrap',
          lines: ['说白了，缓存不是数据源。', '它随时可以没有。'],
        },
        {
          speaker: 'dou',
          emotion: 'wrap',
          lines: ['写库是事实，删缓存只是通知。'],
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
          lines: ['最后一节，说说最容易踩的坑。', '先说删缓存和写库之间的窗口。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['这俩不是一前一后吗？'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: ['是一前一后。', '但中间有几毫秒的空档。', '并发读会把旧值回填回去。'],
        },
        {
          speaker: 'dou',
          emotion: 'contrast',
          lines: ['而且这次回填，没有过期时间。', '不主动删，它能活到天荒地老。'],
        },
        {
          speaker: 'peng',
          emotion: 'punch',
          lines: ['所以最稳的缓存，是没人读的那个。'],
        },
        {
          speaker: 'dou',
          emotion: 'banter',
          lines: ['解法有三个。', '先写库、后删缓存，顺序不能反。', '删失败要重试，别吞异常。'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: ['读多写少的场景，可以延迟双删。', '删一次，隔一会儿再删一次。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['隔多久？'],
        },
        {
          speaker: 'dou',
          emotion: 'contrast',
          lines: ['比一次读的回填窗口稍长就行。', '别拍脑袋写个十分钟。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['那粒度怎么选？'],
        },
        {
          speaker: 'dou',
          emotion: 'banter',
          lines: ['还有个大坑是粒度。', '缓存整个列表，不如缓存单条。', '列表里任何一条变了，整张缓存都脏。'],
        },
        {
          speaker: 'dou',
          emotion: 'setup',
          lines: ['命中率低于八成，先怀疑粒度。', '别急着加机器。'],
        },
        {
          speaker: 'peng',
          emotion: 'deadpan',
          lines: ['机器不背这个锅。'],
        },
        {
          speaker: 'dou',
          emotion: 'wrap',
          lines: ['说白了，缓存的难点不在存。', '在什么时候让它走。'],
        },
        {
          speaker: 'dou',
          emotion: 'wrap',
          lines: ['先写库，后删缓存，删失败要重试。'],
        },
      ],
    },
  ],
}
