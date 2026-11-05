import type { TutorialChapter } from '../../lib/tutorialTypes'

/** 中间件与运维方向：缓存失效、容器化与 Docker、消息队列语义、可观测性与线上排障。 */
export const MIDDLEWARE_CHAPTERS: TutorialChapter[] = [
  {
    id: 'mw-cache-strategy',
    title: '缓存与失效策略',
    direction: '中间件与运维',
    level: '基础',
    summary: '先问「缓存放在哪一层」，再讲 TTL、淘汰与穿透/击穿/雪崩三类异常，最后落到 Cache-Aside 的正确写法。',
    sections: [
      {
        id: 'where',
        title: '缓存放在哪一层',
        blocks: [
          {
            kind: 'text',
            text: '缓存不是「加一个 Redis」这么简单，而是一组按距离近远排布的层：越靠近用户的层越快、越便宜，但越难保证一致。判断要不要加缓存，先看这份数据「读多写少、能容忍多旧」。',
          },
          {
            kind: 'table',
            headers: ['层级', '典型位置', '命中收益', '失效手段'],
            rows: [
              ['浏览器 / CDN', '静态资源、公开接口', '省掉全部回源', 'Cache-Control、URL 版本号'],
              ['进程内', '本地 Map / LRU', '纳秒级', '进程重启、TTL、主动删除'],
              ['分布式缓存', 'Redis / Memcached', '亚毫秒级', 'TTL、删除键、版本号'],
              ['数据库', 'Buffer Pool、物化视图', '省磁盘 IO', '由数据库自己管理'],
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: '先算收益再动手',
            text: '缓存只有当「命中率 × 单次回源耗时」明显大于维护成本时才值得。命中率长期低于 80% 的缓存，往往是粒度选错了：缓存整个列表比缓存单条记录更容易失效。',
          },
        ],
      },
      {
        id: 'expire',
        title: 'TTL、淘汰与三类异常',
        blocks: [
          {
            kind: 'text',
            text: 'TTL 解决「数据会变」，淘汰策略解决「内存会满」。两者都不能消除一个事实：缓存未命中的那一刻，请求会同时打到数据库。三类异常都是在这一刻被放大的。',
          },
          {
            kind: 'table',
            headers: ['异常', '触发条件', '表现', '常用解法'],
            rows: [
              ['穿透', '查询不存在的数据，每次都回源', '缓存形同虚设，DB 被无效查询打满', '空值缓存（短 TTL）、布隆过滤器'],
              ['击穿', '单个热点键过期瞬间', '大量并发同时回源同一行', '互斥重建、逻辑过期、热点不过期'],
              ['雪崩', '大批键同一时刻过期', '回源流量整体抬升', 'TTL 加随机抖动、分层过期、限流降级'],
            ],
          },
          {
            kind: 'note',
            tone: 'warn',
            title: 'TTL 别写成同一个值',
            text: '批量预热时给 TTL 加 ±10% 的随机抖动，能把「同一秒集体过期」摊平到几分钟内，是成本最低的雪崩防护。',
          },
        ],
      },
      {
        id: 'example',
        title: 'Cache-Aside 的正确写法',
        blocks: [
          {
            kind: 'text',
            text: '读路径：先读缓存，未命中回源并回填。写路径：先写数据库，再删除缓存（不是更新缓存）。删除失败要能重试，否则会留下一个永远读不到的旧值。',
          },
          {
            kind: 'code',
            language: 'ts',
            caption: '读穿透保护 + 写后删除',
            code: [
              'async function getUser(id: string): Promise<User | null> {',
              '  const key = `user:${id}`',
              '  const cached = await redis.get(key)',
              '  if (cached !== null) return cached === NULL_MARK ? null : JSON.parse(cached)',
              '',
              '  const user = await db.findUser(id)',
              '  // 不存在也要缓存，TTL 短一些，避免穿透反复回源',
              '  await redis.set(key, user === null ? NULL_MARK : JSON.stringify(user), {',
              '    EX: user === null ? 60 : 600 + Math.floor(Math.random() * 60),',
              '  })',
              '  return user',
              '}',
              '',
              'async function renameUser(id: string, name: string): Promise<void> {',
              '  await db.updateUser(id, { name })',
              '  await retry(() => redis.del(`user:${id}`), { times: 3 })',
              '}',
            ].join('\n'),
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              '空值也缓存，但 TTL 更短：挡住穿透，又不会把「后来创建的数据」挡太久。',
              'TTL 带随机抖动：同一批预热的数据不会同时失效。',
              '写后删除而不是写后更新：并发写时「更新缓存」会留下旧值，删除是幂等的。',
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
            title: '先删缓存再写库 = 一定读到旧值',
            text: '删缓存与写库之间有窗口：并发的读请求会把旧值重新回填，且这次回填不会过期。顺序必须是「先写库、后删缓存」，并给删除加延迟双删或重试。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: '缓存击穿和雪崩的区别是什么？',
                answer: '击穿是单个热点键失效导致的瞬时回源；雪崩是一大批键同时失效导致的整体回源。前者用互斥重建，后者用 TTL 抖动与分层过期。',
              },
              {
                question: '为什么推荐删除缓存而不是更新缓存？',
                answer: '并发写时两次更新可能乱序，最终缓存留下先写的那份；删除是幂等的，下一次读会按数据库的最新值回填。',
              },
              {
                question: '命中率一直上不去，先查什么？',
                answer: '先查缓存粒度与 key 设计：key 里带时间戳、带用户 ID 或带分页参数，都会让同一份数据裂成大量互不复用的键。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'mw-message-queue',
    title: '消息队列与投递语义',
    direction: '中间件与运维',
    level: '进阶',
    summary: '解耦、削峰与最终一致分别靠什么保证；at-least-once 下如何用幂等表把「重复投递」变成无害。',
    sections: [
      {
        id: 'why',
        title: '为什么需要消息队列',
        blocks: [
          {
            kind: 'text',
            text: '同步调用把「生产者」和「消费者」的可用性绑在一起：下游一抖动，上游跟着超时。队列把这段调用变成一次「投递 + 后续处理」，代价是系统从「强一致」变成「最终一致」。',
          },
          {
            kind: 'list',
            items: [
              '解耦：下单只负责写「订单已创建」事件，发券、积分、通知各自订阅，新增消费者不改生产者。',
              '削峰：突发流量先进队列，消费者按自己的速率消费，数据库不会被瞬时打满。',
              '最终一致：跨服务的事务用「本地事务 + 事件」实现，失败靠重试与补偿收敛。',
              '顺序与延迟：只有需要严格顺序的场景（同一订单的状态变更）才值得付出单分区串行的代价。',
            ],
          },
        ],
      },
      {
        id: 'delivery',
        title: '三种投递语义与幂等',
        blocks: [
          {
            kind: 'text',
            text: '「恰好一次」在分布式里几乎无法端到端保证（网络超时后生产者不知道是否投递成功）。工程上的标准答案：队列保证至少一次，业务侧用幂等把重复变成无害。',
          },
          {
            kind: 'table',
            headers: ['语义', '实现方式', '风险', '适用场景'],
            rows: [
              ['至多一次', '先确认后处理 / 不重试', '丢消息', '可丢的埋点、日志'],
              ['至少一次', '处理成功才确认，失败重投', '重复消费', '绝大多数业务事件'],
              ['恰好一次', '幂等键 + 去重表 / 事务消息', '实现复杂、仍有边界情况', '账务、库存扣减'],
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: '幂等键怎么选',
            text: '幂等键要来自业务，而不是消息 ID：订单号 + 事件类型、支付流水号。消息重投时消息 ID 可能变化，业务键不会。',
          },
        ],
      },
      {
        id: 'example',
        title: '用去重表做幂等消费',
        blocks: [
          {
            kind: 'text',
            text: '去重表与业务写入放在同一个本地事务里：插入去重记录成功才执行业务；插入冲突说明这条消息处理过，直接确认。',
          },
          {
            kind: 'code',
            language: 'sql',
            caption: '去重表：幂等键唯一',
            code: [
              'CREATE TABLE consumed_event (',
              '  event_key   TEXT PRIMARY KEY,   -- 业务幂等键，如 order-1001:paid',
              '  consumed_at TEXT NOT NULL',
              ');',
              '',
              '-- 消费事务：插入成功才继续，冲突即视为已处理',
              'BEGIN;',
              'INSERT INTO consumed_event (event_key, consumed_at)',
              'VALUES (:event_key, :now);',
              'UPDATE account SET balance = balance + :amount WHERE id = :account_id;',
              'COMMIT;',
            ].join('\n'),
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              '去重表与业务表同库，才能放进同一个事务；跨库时退化为「先占位、再执行、失败补偿」。',
              '冲突（唯一键报错）不是异常，是「这条消息已经处理过」，直接确认并跳过。',
              '去重记录要保留足够久：至少覆盖队列的最大重投窗口（常见 7 天）。',
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
            title: '先确认后处理 = 会丢消息',
            text: '拿到消息立刻确认、再去做业务，消费者一崩溃这条消息就永远消失了。顺序必须是「处理成功 → 确认」；处理失败要能抛出，让队列重投或进死信。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: '消费积压了几十万条，先做什么？',
                answer: '先判断是消费者变慢还是流量突增：看消费速率与处理耗时。扩容消费者（注意分区数上限）比优化单条逻辑见效快，同时要评估下游能否承受。',
              },
              {
                question: '为什么同一分区内才能保证顺序？',
                answer: '顺序靠「单分区串行消费」换来的。跨分区并发消费无法保证先后，所以顺序键（如订单号）要作为分区键。',
              },
              {
                question: '死信队列的作用是什么？',
                answer: '把重试超过阈值的消息挪走，避免它无限重投阻塞正常消费；同时保留现场，便于人工排查后重放。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'mw-observability',
    title: '可观测性与线上排障',
    direction: '中间件与运维',
    level: '高级',
    summary: '指标、日志、链路三支柱各回答什么问题，以及一次「接口变慢」从告警到定位的完整路径。',
    sections: [
      {
        id: 'signals',
        title: '三支柱与两套方法',
        blocks: [
          {
            kind: 'text',
            text: '可观测性不是「多打日志」，而是能用外部输出回答「系统现在怎么样、哪里慢、为什么慢」。三类信号各管一段：指标告诉你「有没有问题」，链路告诉你「慢在哪一跳」，日志告诉你「那一跳发生了什么」。',
          },
          {
            kind: 'table',
            headers: ['信号', '典型工具', '回答的问题', '成本'],
            rows: [
              ['指标 Metrics', 'Prometheus、云监控', '错误率 / 延迟 / 饱和度是否异常', '低（聚合存储）'],
              ['链路 Traces', 'OpenTelemetry、Jaeger', '一次请求慢在哪个服务、哪个 SQL', '中（采样）'],
              ['日志 Logs', 'ELK、Loki', '具体错误、参数、上下文', '高（量大、要治理）'],
            ],
          },
          {
            kind: 'text',
            text: '看指标用两套现成方法：面向请求的 RED（Rate、Errors、Duration），面向资源的 USE（Utilization、Saturation、Errors）。先看 RED 定位「哪个接口坏了」，再看 USE 定位「哪台机器满了」。',
          },
        ],
      },
      {
        id: 'trace',
        title: '一次慢请求的排查路径',
        blocks: [
          {
            kind: 'text',
            text: '线上说「接口变慢了」，不要一上来就翻日志。按「先确认范围、再定位层级、最后看细节」的顺序走，能把排查从几小时压到几分钟。',
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              '确认范围：只有某个接口慢，还是全部慢？只有某个机房/实例，还是全局？全局多为依赖或流量问题，单实例多为资源或配置问题。',
              '看 RED：延迟分布看 P95 / P99，不要只看平均值——平均值会被大量快请求稀释。',
              '看链路：找出耗时最长的那一跳，区分「自身计算」与「等下游」。',
              '看 USE：该实例 CPU、内存、连接池、磁盘 IO 是否打满；连接池耗尽常伪装成「下游慢」。',
              '看日志与慢查询：把 trace id 串起来，确认是锁等待、全表扫描还是外部调用超时。',
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: 'P99 才是用户感受',
            text: '平均 50ms 但 P99 是 3s，意味着每 100 个用户就有 1 个在等 3 秒。容量评估与告警都应基于高分位。',
          },
        ],
      },
      {
        id: 'example',
        title: '一条能用的告警规则',
        blocks: [
          {
            kind: 'text',
            text: '告警要满足三条：能反映用户感受、有明确处置动作、不轻易抖动。下面这条规则盯「5 分钟内 P95 延迟超过 800ms 且持续 10 分钟」，并带上路由与说明。',
          },
          {
            kind: 'code',
            language: 'yaml',
            caption: 'Prometheus 告警规则片段',
            code: [
              'groups:',
              '  - name: api-latency',
              '    rules:',
              '      - alert: ApiLatencyHigh',
              '        expr: |',
              '          histogram_quantile(',
              '            0.95,',
              '            sum by (le, route) (rate(http_request_duration_seconds_bucket[5m]))',
              '          ) > 0.8',
              '        for: 10m',
              '        labels:',
              '          severity: warning',
              '        annotations:',
              '          summary: "{{ $labels.route }} P95 延迟超过 800ms"',
              '          runbook: "先看依赖耗时，再看实例 CPU 与连接池"',
            ].join('\n'),
          },
          {
            kind: 'list',
            items: [
              '`for: 10m` 是防抖：瞬时抖动不该叫人起床。',
              '按 route 聚合而不是按实例：用户感受的是接口，不是某一台机器。',
              '带 runbook：告警必须能指向下一步动作，否则只是噪音。',
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
            title: '别把用户 ID 打进指标标签',
            text: '指标标签的每种组合都是一条独立时间序列。把 user_id、原始 URL 这类高基数字段做标签，会让时序数量爆炸，直接把监控打挂——这类信息属于日志与链路，不属于指标。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: '监控全绿但用户说慢，可能是什么原因？',
                answer: '常见三种：告警只看平均值掩盖了长尾；监控覆盖的是服务端耗时，没算网络与前端渲染；采样率过低漏掉了慢请求。补前端真实用户监控（RUM）与高分位指标。',
              },
              {
                question: '日志里应该带什么才能串起一次请求？',
                answer: '统一 trace id（入口生成、全链路透传）+ 用户/租户标识 + 关键业务键。不要打全量请求体，敏感字段要脱敏。',
              },
              {
                question: '告警风暴怎么治理？',
                answer: '按服务聚合、设置抑制规则（上游故障时抑制下游告警）、分级路由（warning 进群、critical 才呼叫），并给每条告警配 runbook。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'mw-docker',
    title: '容器化与 Docker 基础',
    direction: '中间件与运维',
    level: '基础',
    summary: '镜像、容器、分层与多阶段构建：为什么「在我机器上是好的」能被 Docker 治好，以及 Dockerfile 的常见写错方式。',
    sections: [
      {
        id: 'why',
        title: '镜像与容器',
        blocks: [
          {
            kind: 'text',
            text: '镜像是一个只读模板：打包了应用代码、运行时和依赖。容器是镜像的运行实例——启动时在镜像顶部加一层可写层，进程跑在里面。与传统虚拟机的区别：容器共享宿主内核，只隔离进程视图（命名空间）与资源配额（cgroup），所以启动是秒级、开销接近零。',
          },
          {
            kind: 'list',
            items: [
              '镜像不可变：要更新就构建新镜像、换新容器，不要进容器里手改文件——那台机器从此不可复现。',
              '一个容器一个进程：应用和 MySQL 分开跑，各自独立升级与伸缩。',
              '容器是临时的：崩溃重启、扩缩容都会换实例，任何需要持久化的数据（数据库文件、上传文件）必须挂载卷或外置。',
            ],
          },
        ],
      },
      {
        id: 'layers',
        title: '分层与缓存',
        blocks: [
          {
            kind: 'text',
            text: 'Dockerfile 每条指令生成一层，层会被缓存复用：某层的输入没变，它之后的重建才会快。所以 Dockerfile 的排序原则只有一条：越常变的越靠后。',
          },
          {
            kind: 'list',
            items: [
              '先 COPY package.json 再 npm ci，最后 COPY 源码：改代码不重装依赖，这是前端/后端镜像提速最明显的一招。',
              '.dockerignore 与 .gitignore 同等重要：node_modules、.git 不进构建上下文，构建快且镜像小。',
              '选小基础镜像（alpine/slim），镜像从 1GB 降到 150MB 量级，拉取部署都受益。',
              '合并 RUN 指令、清理包管理缓存，减少无意义层数。',
            ],
          },
        ],
      },
      {
        id: 'example',
        title: '多阶段构建',
        blocks: [
          {
            kind: 'text',
            text: '构建期需要编译器与全部 devDependencies，运行期只需要产物——多阶段构建把两者分开，最终镜像里不留编译工具链。',
          },
          {
            kind: 'code',
            language: 'dockerfile',
            caption: 'Node 应用多阶段 Dockerfile',
            code: [
              '# 构建阶段：装全部依赖并编译',
              'FROM node:20 AS build',
              'WORKDIR /app',
              'COPY package*.json ./',
              'RUN npm ci',
              'COPY . .',
              'RUN npm run build',
              '',
              '# 运行阶段：只带产物与生产依赖',
              'FROM node:20-slim',
              'WORKDIR /app',
              'COPY --from=build /app/dist ./dist',
              'COPY --from=build /app/node_modules ./node_modules',
              'USER node',
              'CMD ["node", "dist/server.js"]',
            ].join('\n'),
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              '依赖清单先拷、npm ci 先跑，源码改动不会触发依赖重装。',
              'USER node 用非 root 跑进程，容器被攻破也拿不到宿主 root。',
              'CMD 用 exec 形式，进程能正确接收 SIGTERM 优雅退出。',
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
            title: '把容器当虚拟机用',
            text: '进容器手动装包、改配置、补依赖，下次重建全部丢失——容器随时可能被替换。任何变更都该落到 Dockerfile/编排文件里，重建即可复现。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: '容器里的日志怎么收集？',
                answer: '写 stdout/stderr，由 Docker 或编排系统的日志驱动收集；不要写容器本地文件——容器一删日志就没了。',
              },
              {
                question: '镜像 tag 用 latest 有什么风险？',
                answer: 'latest 是会漂移的引用，今天和明天拉到的可能不是同一个镜像，回滚也没依据。生产应使用不可变 tag（版本号或内容摘要）。',
              },
              {
                question: '为什么容器里 JVM 内存参数要显式设置？',
                answer: '老版本 JVM 看到的是宿主机内存而不是容器配额，堆按宿主机算会撞上 cgroup 限制被 OOM 杀掉。显式 -Xmx 或开容器感知。',
              },
            ],
          },
        ],
      },
    ],
  },
]
