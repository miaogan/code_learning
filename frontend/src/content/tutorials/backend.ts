import type { TutorialChapter } from '../../lib/tutorialTypes'

/** 后端方向：HTTP/REST 接口设计、数据库索引与事务、并发与幂等、认证与会话。 */
export const BACKEND_CHAPTERS: TutorialChapter[] = [
  {
    id: 'be-http-rest',
    title: 'HTTP 与 REST 接口设计',
    direction: '后端',
    sub_direction: '通用后端',
    level: '基础',
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
    sub_direction: '通用后端',
    level: '进阶',
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
  {
    id: 'be-concurrency-idempotency',
    title: '并发控制与接口幂等',
    direction: '后端',
    sub_direction: '通用后端',
    level: '高级',
    summary: '「读-改-写」在并发下必然丢更新；三种解法各有代价，再叠加幂等键，才能让重试与双击都安全。',
    sections: [
      {
        id: 'race',
        title: '丢失更新是怎么发生的',
        blocks: [
          {
            kind: 'text',
            text: '库存 1，两个请求同时读到 1，各自算出 0 并写回——最终只扣了一次，或者卖出了两件。根因是「读」和「写」之间有窗口，而数据库默认不会替你关掉这个窗口。',
          },
          {
            kind: 'table',
            headers: ['解法', '做法', '优点', '代价'],
            rows: [
              ['原子更新', 'UPDATE … SET stock = stock - 1 WHERE stock >= 1', '一条 SQL、无锁等待', '只能表达简单算式，难做复杂校验'],
              ['乐观锁', '读版本号，UPDATE … WHERE version = 读到的值', '不加锁、冲突才重试', '冲突多时重试成本高'],
              ['悲观锁', 'SELECT … FOR UPDATE 先锁行', '逻辑最直观', '锁等待、死锁风险、吞吐受限'],
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: '优先选能一条 SQL 解决的',
            text: '`UPDATE … WHERE stock >= n` 影响行数为 0 就代表库存不足，天然并发安全。只有业务规则复杂到无法在一条 SQL 里表达时，才升级到乐观锁或悲观锁。',
          },
        ],
      },
      {
        id: 'idempotency',
        title: '幂等：让重复请求变成同一次',
        blocks: [
          {
            kind: 'text',
            text: '用户双击、网关重试、消息重投都会让同一个请求到达两次。幂等不是「别重试」，而是「重试也只有一个效果」。两个抓手：业务幂等键 + 唯一约束，以及带前置状态的状态机。',
          },
          {
            kind: 'list',
            items: [
              '幂等键来自客户端或业务单号（订单号 + 操作类型），不要用请求 ID——重试时它会变。',
              '用唯一索引兜底，而不是「先查再插」：两个请求同时查不到，还是会插两次。',
              '状态机约束：UPDATE … WHERE status = \'待支付\'，影响 0 行说明状态已流转，直接返回成功。',
              '幂等记录要有清理策略：保留覆盖最大重试窗口即可，不要无限增长。',
            ],
          },
          {
            kind: 'note',
            tone: 'warn',
            title: '幂等的边界是「副作用」',
            text: '把「扣款」做成幂等，不等于把「发短信通知」也做成幂等。副作用类操作要单独判断，或统一放进幂等记录的处理结果里。',
          },
        ],
      },
      {
        id: 'example',
        title: '扣库存的三种写法',
        blocks: [
          {
            kind: 'text',
            text: '同一需求三种实现，看影响行数就知道结果。第三种把「幂等」与「状态校验」压进同一条 UPDATE，是生产里最常用的一档。',
          },
          {
            kind: 'code',
            language: 'sql',
            caption: '从会超卖，到并发安全',
            code: [
              '-- 1) 先查再改：并发下必然超卖',
              'SELECT stock FROM products WHERE id = :id;   -- 读到 1',
              'UPDATE products SET stock = :stock - 1 WHERE id = :id;  -- 两个请求都写 0',
              '',
              '-- 2) 原子更新：影响行数为 0 即库存不足',
              'UPDATE products SET stock = stock - 1',
              'WHERE id = :id AND stock >= 1;',
              '',
              '-- 3) 幂等 + 状态机：同一订单只能扣一次',
              'UPDATE orders',
              'SET status = \'已扣减\', updated_at = :now',
              'WHERE id = :order_id AND status = \'待扣减\';   -- 影响 0 行 = 已处理过',
            ].join('\n'),
          },
          {
            kind: 'table',
            headers: ['写法', '并发安全', '重复请求', '适用'],
            rows: [
              ['先查再改', '否', '重复扣减', '单线程脚本，不可用于接口'],
              ['原子更新', '是', '仍会重复扣减', '无线程/请求重试的简单场景'],
              ['幂等 + 状态机', '是', '重复请求无副作用', '订单、支付、券核销'],
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
            title: '分布式锁不等于幂等',
            text: '锁只保证「同一时刻只有一个人在改」，请求串行执行两遍依然是两遍效果。锁还要处理续期与「删错别人的锁」（用值比对删除或 Lua 原子删除）。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: '乐观锁冲突了怎么办？',
                answer: '有限次重试（如 3 次）并加随机退避；冲突率长期很高说明热点太集中，应改为原子更新或把热点行拆开。',
              },
              {
                question: '「先查幂等表再插入」为什么不够？',
                answer: '查与插之间有窗口，两个并发请求会同时查不到。必须让唯一索引承担最终裁决，插入冲突即视为已处理。',
              },
              {
                question: '如何在接口层快速判断重复提交？',
                answer: '客户端带幂等键（或由业务参数哈希生成），网关/服务端按「用户 + 键」做短期去重，命中直接返回上次结果。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'be-auth-session',
    title: '认证与会话管理',
    direction: '后端',
    sub_direction: '通用后端',
    level: '进阶',
    summary: '从「HTTP 本身不记得谁是谁」出发，对比 Session 与 JWT 两条路线，把密码存储、令牌过期与注销讲透。',
    sections: [
      {
        id: 'concept',
        title: '认证解决什么问题',
        blocks: [
          {
            kind: 'text',
            text: 'HTTP 是无状态的：每个请求互相独立，服务端默认不知道「这个请求是谁发的」。认证（Authentication）解决「你是谁」，授权（Authorization）解决「你能做什么」。所有会话方案，本质都是在无状态协议上重新建立身份。',
          },
          {
            kind: 'list',
            items: [
              '凭证：用户第一次出示的东西（密码、验证码、第三方授权码），验证通过后换取会话凭证。',
              '会话凭证：后续请求随身携带的东西（Session ID 或 JWT），避免每次都出原始密码。',
              '传输层：凭证放在 Cookie 或 Authorization 头里，全程必须 HTTPS，否则等于明文广播。',
              '密码存储：只存慢哈希（bcrypt/argon2），绝不明文、不用 MD5/SHA1。',
            ],
          },
        ],
      },
      {
        id: 'compare',
        title: 'Session 与 JWT 的取舍',
        blocks: [
          {
            kind: 'table',
            headers: ['维度', 'Session（服务端存状态）', 'JWT（客户端存令牌）'],
            rows: [
              ['存储位置', '服务端（内存/Redis），客户端只拿 ID', '令牌本身在客户端，服务端只存密钥'],
              ['注销', '删服务端记录即可，立刻生效', '难：只能等过期或维护黑名单'],
              ['横向扩展', '共享存储（如 Redis）后无压力', '无状态天然易扩展'],
              ['载荷', '不暴露给客户端', '仅 Base64 编码，任何人都可读，不能放敏感信息'],
              ['典型场景', '传统 Web 应用、需要强制下线', '开放 API、多端/服务间调用'],
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: '折中方案很常见',
            text: '短效 JWT（15 分钟）+ 服务端可吊销的 refresh token，兼顾无状态校验与强制下线：access 丢了损失有限，refresh 泄露可在服务端作废。',
          },
        ],
      },
      {
        id: 'example',
        title: '注册、登录与令牌校验',
        blocks: [
          {
            kind: 'text',
            text: '三条铁律体现在代码里：注册只存慢哈希；登录成功才签短效令牌；每个受保护接口先验签名与过期，再谈业务。',
          },
          {
            kind: 'code',
            language: 'javascript',
            caption: '最小认证流程（bcrypt + JWT）',
            code: [
              "import bcrypt from 'bcryptjs'",
              "import jwt from 'jsonwebtoken'",
              '',
              '// 注册：cost 因子 12，只存哈希',
              'const hash = await bcrypt.hash(password, 12)',
              'await db.users.insert({ email, passwordHash: hash })',
              '',
              '// 登录：先比哈希，再签 15 分钟短效令牌',
              'const ok = await bcrypt.compare(password, user.passwordHash)',
              'if (!ok) throw new AuthError()',
              'const token = jwt.sign({ sub: user.id }, SECRET, { expiresIn: "15m" })',
              '',
              '// 受保护接口：先验签，再取身份',
              'function requireAuth(req) {',
              '  const payload = jwt.verify(req.headers.authorization.slice(7), SECRET)',
              '  req.userId = payload.sub',
              '}',
            ].join('\n'),
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              'jwt.sign 的载荷只放 sub（用户 ID）与过期时间，不要塞邮箱、手机号等敏感字段。',
              '校验放在中间件统一做，业务代码只读 req.userId，避免某个接口漏验。',
              'refresh token 存库并带过期，注销时作废；access token 不落库，天然无状态。',
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
            title: 'JWT 签了不等于安全',
            text: '常见事故：密钥写死在仓库里、alg 字段被篡改成 none 仍接受、把用户角色放进载荷且前端据此显示按钮（后端却不复核）。签名保证「没被改」，不保证「内容合理」，授权判断必须在服务端重新做。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: '为什么密码要用 bcrypt 而不是 SHA256？',
                answer: 'SHA256 太快，GPU 每秒能算几十亿次，撞库成本低；bcrypt/argon2 故意慢且可调 cost，把暴力破解拖到不可行。',
              },
              {
                question: 'JWT 怎么实现「强制下线」？',
                answer: '维护服务端黑名单（按 jti 或用户 + 签发时间），校验时多查一次；或者干脆改用可随时删除的 Session。',
              },
              {
                question: 'Cookie 里放 token，怎么防 CSRF？',
                answer: '浏览器会自动带 Cookie，第三方站点可借用户身份发请求。用 SameSite=Strict/Lax、CSRF Token，或把 token 放 Authorization 头由 JS 显式携带。',
              },
            ],
          },
        ],
      },
    ],
  },
]
