import type { TutorialChapter } from '../../lib/tutorialTypes'

/** 后端方向：HTTP/REST 接口设计、数据库索引与事务。 */
export const BACKEND_CHAPTERS: TutorialChapter[] = [
  {
    id: 'be-http-rest',
    title: 'HTTP 与 REST 接口设计',
    direction: '后端',
    summary: '用资源和动作来设计接口：方法、状态码、幂等与统一错误结构，一次讲清。',
    sections: [
      {
        id: 'resources',
        title: '先想资源，再想动作',
        blocks: [
          {
            kind: 'text',
            text: 'REST 的核心不是「用 GET 还是 POST」，而是把系统里的东西建模成资源：用户、订单、简历。URL 表示资源，HTTP 方法表示对这个资源做什么。把动作塞进 URL（如 /getUser、/deleteOrder）说明资源模型还没有想清楚。',
          },
          {
            kind: 'list',
            items: [
              '集合资源：/reports；单个资源：/reports/{id}。',
              '子资源表达从属关系：/reports/{id}/shortfalls。',
              '过滤、分页、排序放在查询参数里，不改变资源路径。',
              '动作确实无法映射到增删改查时，才用动词子资源，如 /reports/{id}/rerun。',
            ],
          },
        ],
      },
      {
        id: 'methods',
        title: '方法、状态码与幂等',
        blocks: [
          {
            kind: 'table',
            headers: ['方法', '语义', '幂等', '成功状态码'],
            rows: [
              ['GET', '读取资源，不应修改数据', '是', '200'],
              ['POST', '创建资源或触发一次处理', '否', '201 / 200'],
              ['PUT', '整体替换资源', '是', '200 / 204'],
              ['PATCH', '部分更新资源', '不一定', '200 / 204'],
              ['DELETE', '删除资源', '是', '204 / 200'],
            ],
          },
          {
            kind: 'text',
            text: '幂等的意思是「同一请求重复执行，结果与执行一次相同」。网络超时后客户端常常会重试，GET/PUT/DELETE 可以放心重试；POST 重试可能重复创建，需要幂等键或去重策略。',
          },
          {
            kind: 'note',
            tone: 'info',
            title: '状态码选择',
            text: '参数错误用 400，未登录用 401，无权限用 403，资源不存在用 404，冲突用 409，限流用 429，服务端错误用 500。不要所有失败都返回 200 再在 body 里写 code。',
          },
        ],
      },
      {
        id: 'example',
        title: '一个可用的错误结构',
        blocks: [
          {
            kind: 'text',
            text: '成功响应只返回客户端需要的数据；失败响应保持同一结构，客户端才能统一处理。错误信息写给用户看，不要暴露路径、堆栈或内部标识。',
          },
          {
            kind: 'code',
            language: 'json',
            caption: '统一错误 envelope',
            code: [
              '{',
              '  "error": {',
              '    "code": "PROFILE_NOT_FOUND",',
              '    "message": "还没有生成技术画像",',
              '    "retryable": false',
              '  }',
              '}',
            ].join('\n'),
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              'code 是闭集，客户端可以按它分支。',
              'message 是中文、可直接展示。',
              'retryable 明确告诉客户端「重试有没有意义」。',
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
            title: '不要用 GET 改数据',
            text: 'GET 可能被浏览器预取、被爬虫访问、被缓存，一旦带副作用就会产生难以排查的脏数据。删除、状态变更都应该用 POST/PUT/PATCH/DELETE。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: 'PUT 和 PATCH 的区别是什么？',
                answer: 'PUT 表示用请求体整体替换资源，未提供的字段应回到默认值；PATCH 只改请求体里出现的字段。团队里要约定清楚，避免同一接口两种语义。',
              },
              {
                question: '为什么创建资源返回 201 而不是 200？',
                answer: '201 明确表示「资源已创建」，通常还会带 Location 响应头指向新资源；200 只表示请求成功，语义不够精确。',
              },
              {
                question: '接口返回 404 和返回空数组，哪个更好？',
                answer: '集合资源为空用 200 + 空数组；单个资源不存在才用 404。两者混用会让客户端无法区分「没有数据」和「路径写错」。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'be-db-index',
    title: '数据库索引与事务',
    direction: '后端',
    summary: '索引为什么能加速、联合索引怎么排、事务隔离解决什么问题，配一条 EXPLAIN 示例。',
    sections: [
      {
        id: 'why',
        title: '索引到底加速了什么',
        blocks: [
          {
            kind: 'text',
            text: '没有索引时，查询要逐行扫描全表；有索引时，数据库先在有序结构里定位到目标行，再回表取数据。索引的代价是额外存储与写入维护成本，所以不是越多越好。',
          },
          {
            kind: 'list',
            items: [
              '索引通常是有序的树结构，支持等值查询与范围查询。',
              '查询条件对索引列做函数运算（如 WHERE DATE(created_at) = ...）会失去索引能力。',
              '区分度低的列（如性别）单独建索引收益很小。',
              '写多读少的表要控制索引数量，避免每次写入维护过多索引。',
            ],
          },
        ],
      },
      {
        id: 'composite',
        title: '联合索引与最左前缀',
        blocks: [
          {
            kind: 'text',
            text: '联合索引 (a, b, c) 相当于按 a 排序、a 相同再按 b 排序、再按 c 排序。查询必须从最左列开始连续使用，才能命中索引。',
          },
          {
            kind: 'table',
            headers: ['查询条件', '能否命中 (a, b, c)', '原因'],
            rows: [
              ['WHERE a = ?', '能', '使用最左列 a'],
              ['WHERE a = ? AND b = ?', '能', '连续使用 a、b'],
              ['WHERE b = ?', '不能', '跳过了最左列 a'],
              ['WHERE a = ? AND c = ?', '部分命中', 'a 用于定位，c 无法继续利用有序性'],
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: '排序也能用索引',
            text: '如果查询的 ORDER BY 顺序与联合索引顺序一致，数据库可以直接按索引顺序读取，省掉额外排序。',
          },
        ],
      },
      {
        id: 'example',
        title: '用 EXPLAIN 验证',
        blocks: [
          {
            kind: 'text',
            text: '不要凭感觉判断索引是否生效，先看执行计划。重点观察 type、key、rows 与 Extra：type 为 ALL 表示全表扫描，key 为 NULL 表示没有用索引。',
          },
          {
            kind: 'code',
            language: 'sql',
            caption: '联合索引与执行计划',
            code: [
              'CREATE INDEX idx_events_user_created',
              '  ON timeline_events (user_id, created_at);',
              '',
              'EXPLAIN SELECT id, kind, created_at',
              'FROM timeline_events',
              'WHERE user_id = 42',
              'ORDER BY created_at DESC',
              'LIMIT 20;',
            ].join('\n'),
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              '先用 user_id 定位，再按 created_at 有序读取。',
              'LIMIT 20 让数据库提前停止扫描。',
              '若 type 仍是 ALL，检查是否对列做了函数运算或类型不一致。',
            ],
          },
        ],
      },
      {
        id: 'pitfalls',
        title: '事务与常见坑',
        blocks: [
          {
            kind: 'text',
            text: '事务把多条写操作打包成一个整体：要么全部成功，要么全部回滚。它解决的是并发下的可见性与一致性问题，不是「加锁越多越安全」。',
          },
          {
            kind: 'table',
            headers: ['隔离级别', '能避免的问题', '代价'],
            rows: [
              ['读未提交', '几乎不能避免', '可能读到未提交数据'],
              ['读已提交', '脏读', '同一事务内两次读取可能不同'],
              ['可重复读', '脏读、不可重复读', '可能出现幻读（取决于实现）'],
              ['串行化', '上述全部', '并发度最低'],
            ],
          },
          {
            kind: 'note',
            tone: 'warn',
            title: '长事务会拖垮系统',
            text: '事务里不要做网络请求、不要让用户交互等待，也不要在事务中执行大批量更新。长事务会持有锁与旧版本数据，放大锁等待与存储压力。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: '为什么给 created_at 单独建索引，按用户查询还是慢？',
                answer: '单列索引只能按时间定位，无法同时按 user_id 过滤。应建 (user_id, created_at) 联合索引，让过滤与排序都用同一棵索引。',
              },
              {
                question: '索引一定能让查询变快吗？',
                answer: '不一定。返回行数占比很高时，优化器可能选择全表扫描；索引失效、回表过多、区分度低都会让索引没有收益。',
              },
              {
                question: '事务回滚后自增 ID 会回退吗？',
                answer: '通常不会。自增值一旦分配就前进，回滚只撤销数据变更，不撤销自增计数。',
              },
            ],
          },
        ],
      },
    ],
  },
]
