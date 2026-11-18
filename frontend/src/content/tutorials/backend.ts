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
  {
    id: 'be-python-concurrency',
    title: 'Python 的 GIL、线程与异步 IO',
    direction: '后端',
    sub_direction: 'python',
    level: '进阶',
    summary: '为什么 CPU 密集任务用多线程不快、IO 密集任务却能并发：从 GIL 到 asyncio 的事件循环，给出选型依据。',
    sections: [
      {
        id: 'gil',
        title: 'GIL 到底限制了什么',
        blocks: [
          {
            kind: 'text',
            text: 'CPython 的全局解释器锁（GIL）保证同一时刻只有一个线程执行 Python 字节码。它不是「Python 不能并发」，而是「同一进程内的 Python 字节码不能并行执行 CPU 工作」。线程在等待 IO 时会释放 GIL，这是 IO 密集任务能靠线程提速的原因。',
          },
          {
            kind: 'table',
            headers: ['任务类型', '多线程', '多进程', 'asyncio'],
            rows: [
              ['CPU 密集（压缩、计算）', '受 GIL 限制，几乎不提速', '真正并行，推荐', '不适用，仍受 GIL 限制'],
              ['IO 密集（网络、磁盘）', '有效，等待时释放 GIL', '有效但开销更大', '最省资源，高并发首选'],
              ['混合型', '可用但需实测', '隔离性好', '把 CPU 部分丢给进程池'],
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: '不是所有 Python 实现都有 GIL',
            text: 'PyPy、Jython 等实现有无 GIL 的版本；numpy 等 C 扩展会在执行原生代码时主动释放 GIL。讨论性能前先确认运行的是哪种解释器、热点是否在 Python 字节码里。',
          },
        ],
      },
      {
        id: 'asyncio',
        title: '事件循环与协程的协作',
        blocks: [
          {
            kind: 'text',
            text: 'asyncio 用一个事件循环在单线程里调度大量协程。协程遇到 await 就把控制权交还循环，循环转去执行其他就绪任务。这里的并发来自「等待期间不占着线程」，不是来自多核。',
          },
          {
            kind: 'list',
            items: [
              'await 只能等待可等待对象（协程、Task、Future）；普通函数里的阻塞调用不会让出控制权。',
              'time.sleep 是阻塞的，协程里要用 asyncio.sleep；requests 是同步库，要用 httpx.AsyncClient 或 aiohttp。',
              '一个协程里跑了同步的 CPU 密集循环，会卡住整个事件循环，其他协程全部跟着停。',
            ],
          },
          {
            kind: 'note',
            tone: 'warn',
            title: '别在协程里混入阻塞调用',
            text: '这是最常见的性能事故：代码用了 async/await，但底层库还是同步阻塞的，结果并发度没有任何提升。排查方法是给关键路径打点，看协程是不是串行完成的。',
          },
        ],
      },
      {
        id: 'example',
        title: '把同步请求改成并发请求',
        blocks: [
          {
            kind: 'text',
            text: '面对一批独立的 HTTP 查询，同步写法逐个等待；用 asyncio.gather 可以同时发起并在全部完成后收集结果，总耗时接近最慢的那一个而不是所有请求之和。',
          },
          {
            kind: 'code',
            language: 'python',
            caption: '并发抓取多个 URL',
            code: [
              'import asyncio',
              'import httpx',
              '',
              'async def fetch(client, url):',
              '    response = await client.get(url, timeout=5)',
              '    return response.status_code',
              '',
              'async def main(urls):',
              '    async with httpx.AsyncClient() as client:',
              '        tasks = [fetch(client, url) for url in urls]',
              '        return await asyncio.gather(*tasks, return_exceptions=True)',
              '',
              '# return_exceptions=True：单个请求失败不影响其他结果',
            ].join('\n'),
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              '确认客户端库是异步实现，否则 await 无从谈起。',
              '为每次请求设置超时，避免一个慢调用拖住整批 gather。',
              '用 return_exceptions=True 保留部分成功的结果，再逐个处理异常。',
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
            title: '线程池的真正用途',
            text: 'asyncio.to_thread 把阻塞函数丢到线程池执行，适合没有异步版本的库；它不突破 GIL，只避免阻塞事件循环。CPU 密集任务应该用 ProcessPoolExecutor。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: '为什么爬虫用多线程能提速，但矩阵乘法用多线程几乎不快？',
                answer: '爬虫大部分时间在等网络响应，等待时线程释放 GIL，可以并发；矩阵乘法全程执行 Python/原生计算，受 GIL 串行化，CPU 密集任务应使用多进程。',
              },
              {
                question: '协程里调用了 time.sleep(10) 会发生什么？',
                answer: '它阻塞整个线程，事件循环无法切换，所有协程都被卡住 10 秒。应改用 await asyncio.sleep(10)，让出控制权给其他任务。',
              },
              {
                question: 'asyncio.gather 加 return_exceptions=True 的作用是什么？',
                answer: '让失败的任务以异常对象的形式出现在结果列表里，而不是直接中断整批等待；适合部分失败仍要保留其他结果的批量场景。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'be-distributed-consistency',
    title: '分布式事务与最终一致性',
    direction: '后端',
    sub_direction: '通用后端',
    level: '高级',
    summary: '跨服务没有本地事务可用：从 2PC 的代价讲到 Saga、Outbox 与幂等，掌握最终一致性的工程落地。',
    sections: [
      {
        id: 'concept',
        title: '为什么本地事务不够用',
        blocks: [
          {
            kind: 'text',
            text: '单体里一条 BEGIN/COMMIT 就能保证原子性，但跨服务、跨库之后，各自己的本地事务无法互相感知。强一致的两阶段提交（2PC）需要协调者在整个过程中锁住资源，任一参与者卡住都会拖长阻塞窗口，吞吐和低延迟场景难以接受。',
          },
          {
            kind: 'list',
            items: [
              'CAP 取舍：分区不可避免时，要在一致性与可用性之间明确选择。',
              '多数业务真正需要的是「最终一致」：允许短暂中间态，但保证最终收敛。',
              '工程重心从「怎么保证原子」转向「怎么检测并修复不一致」。',
            ],
          },
        ],
      },
      {
        id: 'patterns',
        title: 'Saga、Outbox 与事务消息',
        blocks: [
          {
            kind: 'table',
            headers: ['模式', '核心思路', '适用'],
            rows: [
              ['Saga（补偿）', '每步配一个反向操作，失败时逐层回滚', '跨服务长流程'],
              ['Outbox', '业务数据与消息在同一本地事务写入，异步投递', '避免「库改了消息没发」'],
              ['事务消息', '先发半消息，提交本地事务后再确认投递', '依赖 MQ 支持'],
            ],
          },
          {
            kind: 'text',
            text: 'Outbox 的关键是把「改数据」和「记待发事件」放进同一个本地事务：两者要么都成、要么都不成。再由独立投递进程扫描 outbox 表发消息，发送成功后标记，从根上消除双写不一致。',
          },
          {
            kind: 'note',
            tone: 'warn',
            title: '补偿操作必须幂等',
            text: 'Saga 的补偿步骤可能因为重试被执行多次，回滚逻辑要能安全重放。用业务幂等键或状态机约束，避免「退两次款」。',
          },
        ],
      },
      {
        id: 'practice',
        title: '落地时的三件大事',
        blocks: [
          {
            kind: 'list',
            ordered: true,
            items: [
              '幂等：每个写操作带唯一键，服务端按 key 去重，重试不产生重复副作用。',
              '可观测：给整个流程一个 trace_id，串起每一步与补偿，能对账、能定位。',
              '对账与修复：定时扫描长期处于中间态的记录，触发补偿或人工介入。',
            ],
          },
          {
            kind: 'code',
            language: 'python',
            caption: 'Outbox 与业务写入同事务',
            code: [
              'def create_order(conn, order, event):',
              '    with conn.transaction():',
              '        conn.insert("orders", order)',
              '        conn.insert("outbox", {',
              '            "event_id": event.id,',
              '            "payload": event.to_json(),',
              '            "status": "pending",',
              '        })',
              '    # 事务提交后，投递进程再异步处理 outbox',
            ].join('\n'),
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
            title: '别把最终一致当作不做对账的借口',
            text: '「最终会一致」不等于「一定会一致」。消息丢失、补偿失败都会让流程永久卡在中间态，必须有超时扫描与对账兜底。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: 'Saga 和 2PC 的本质区别是什么？',
                answer: '2PC 追求强一致，用锁和协调者保证要么全成要么全不成，代价是阻塞与性能；Saga 接受中间态，把大事务拆成本地事务序列，失败时用补偿回滚，换取可用性与吞吐。',
              },
              {
                question: 'Outbox 模式解决什么问题？',
                answer: '解决「数据库改了但消息没发出去」的双写不一致。把业务数据和待发事件放进同一个本地事务，投递进程从 outbox 读取并重试，保证事件不丢。',
              },
              {
                question: '为什么幂等是最终一致性的地基？',
                answer: '异步链路里消息可能重复投递、补偿可能重放。没有幂等，重试就会产生重复扣款、重复下单。幂等键加去重表或状态机是让重试安全的前提。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'be-rate-limit-resilience',
    title: '限流、熔断与服务韧性',
    direction: '后端',
    sub_direction: '通用后端',
    level: '高级',
    summary: '面对突发流量和下游故障，用限流、熔断、超时与降级保护系统，避免局部故障演变成雪崩。',
    sections: [
      {
        id: 'concept',
        title: '韧性是设计出来的',
        blocks: [
          {
            kind: 'text',
            text: '下游变慢不会只影响它自己：上游线程被占满、连接池耗尽、请求排队，最终整条链路一起超时，这就是雪崩。韧性设计的目标是给故障划边界：限制进入的流量、快速失败、保留核心功能。',
          },
          {
            kind: 'list',
            items: [
              '限流：控制进入系统的请求速率，保护自身不被打垮。',
              '熔断：下游错误率过高时暂时断开调用，给它恢复时间。',
              '超时与降级：设合理超时，失败时返回兜底结果而不是无限等待。',
            ],
          },
        ],
      },
      {
        id: 'algorithms',
        title: '限流算法怎么选',
        blocks: [
          {
            kind: 'table',
            headers: ['算法', '特点', '注意'],
            rows: [
              ['固定窗口', '实现简单', '临界点可能瞬时两倍流量'],
              ['滑动窗口', '更平滑', '需记录时间点，成本略高'],
              ['令牌桶', '允许一定突发', '桶容量决定突发上限'],
              ['漏桶', '恒定速率输出', '不允许突发，过于死板'],
            ],
          },
          {
            kind: 'code',
            language: 'python',
            caption: '滑动窗口限流的计数思路',
            code: [
              'def allow(key, now, limit=100, window=60):',
              '    # 只保留窗口内的时间戳',
              '    hits = [t for t in store.get(key, []) if now - t < window]',
              '    if len(hits) >= limit:',
              '        store.set(key, hits)',
              '        return False',
              '    hits.append(now)',
              '    store.set(key, hits)',
              '    return True',
            ].join('\n'),
          },
        ],
      },
      {
        id: 'circuit',
        title: '熔断的状态与降级',
        blocks: [
          {
            kind: 'list',
            ordered: true,
            items: [
              '闭合：正常调用，同时统计错误率与慢调用比例。',
              '打开：错误率超阈值后快速失败，不再打真实下游。',
              '半开：冷却期后放少量探测流量，成功则闭合，失败则继续打开。',
            ],
          },
          {
            kind: 'note',
            tone: 'warn',
            title: '超时时间比重试次数更重要',
            text: '没有超时的重试只会放大故障：每次重试都占住连接，下游越慢、上游重试越猛。先设合理超时，再谈重试次数与退避，并给重试加抖动避免同步风暴。',
          },
        ],
      },
      {
        id: 'pitfalls',
        title: '常见坑与自测',
        blocks: [
          {
            kind: 'qa',
            items: [
              {
                question: '固定窗口限流为什么会在临界点出问题？',
                answer: '在两个窗口交界处，前一窗口末尾和后一窗口开头各能放入一批请求，瞬间流量可能达到限额的两倍。对突发敏感的场景要改用滑动窗口或令牌桶。',
              },
              {
                question: '熔断和限流的保护对象有什么不同？',
                answer: '限流保护自己，控制进入系统的请求量；熔断保护调用链，当下游故障时快速失败，避免上游被拖垮。两者常配合使用。',
              },
              {
                question: '降级返回什么比较合适？',
                answer: '按业务定：读场景可返回缓存或默认值，写场景可转异步消息队列稍后处理。关键是核心链路可用，而不是所有功能都保持原样。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'be-go-concurrency',
    title: 'Go 并发模型与泄漏排查',
    direction: '后端',
    sub_direction: 'go',
    level: '高级',
    summary: '从 goroutine 与 channel 的调度语义出发，掌握 context 取消、常见泄漏模式与 pprof 实战排查。',
    sections: [
      {
        id: 'concept',
        title: '并发的原语与代价',
        blocks: [
          {
            kind: 'text',
            text: 'goroutine 是轻量线程，由 Go 运行时在少量 OS 线程上多路复用；channel 提供带同步语义的通信。轻量不等于免费：每个 goroutine 有独立栈，阻塞的 goroutine 会累积，泄漏时内存和调度开销都会失控。',
          },
          {
            kind: 'list',
            items: [
              'don’t communicate by sharing memory：优先用 channel 传递数据所有权。',
              'context 是跨 goroutine 传递取消信号和超时的标准方式。',
              '通道的缓冲与阻塞语义决定了背压行为。',
            ],
          },
        ],
      },
      {
        id: 'leaks',
        title: '常见泄漏模式',
        blocks: [
          {
            kind: 'table',
            headers: ['模式', '症状', '修复'],
            rows: [
              ['无人接收的发送', 'goroutine 卡在 send', '用 select + context.Done()'],
              ['未关闭的 ticker', '后台循环永不退出', 'defer ticker.Stop()'],
              ['被遗忘的子任务', '父任务结束子任务还在跑', '派生 context 并传递取消'],
            ],
          },
          {
            kind: 'code',
            language: 'go',
            caption: '可被取消的生产者',
            code: [
              'func produce(ctx context.Context, out chan<- int) {',
              '    defer close(out)',
              '    for i := 0; ; i++ {',
              '        select {',
              '        case <-ctx.Done():',
              '            return',
              '        case out <- i:',
              '        }',
              '    }',
              '}',
            ].join('\n'),
          },
          {
            kind: 'note',
            tone: 'warn',
            title: 'select 里别忘了取消分支',
            text: '只写发送分支的 select 在接收方退出后会永久阻塞。任何可能长期阻塞的操作都要同时监听 ctx.Done()，让取消信号能打断它。',
          },
        ],
      },
      {
        id: 'pprof',
        title: '用 pprof 定位问题',
        blocks: [
          {
            kind: 'list',
            ordered: true,
            items: [
              'goroutine profile：看阻塞在哪些调用上，数量是否随时间增长。',
              'heap profile：定位内存增长对象，配合 inuse_space 与 alloc_space 区分泄漏与分配频繁。',
              'CPU profile：找热点函数，确认是否在忙等或序列化上耗费过多。',
              'mutex / block profile：定位锁竞争与阻塞点。',
            ],
          },
        ],
      },
      {
        id: 'pitfalls',
        title: '常见坑与自测',
        blocks: [
          {
            kind: 'qa',
            items: [
              {
                question: '为什么 context 要一路往下传？',
                answer: '取消信号只有沿着调用链传递，才能让所有子 goroutine 一起退出。中途用 context.Background() 重新起一条链，会让下游失去取消能力，上游超时后它们仍在运行。',
              },
              {
                question: '带缓冲的 channel 就没有背压了吗？',
                answer: '缓冲只能吸收短时突发，缓冲区写满后发送方依然阻塞。它改变的是瞬态行为，不改变整体生产消费速率必须匹配的事实。',
              },
              {
                question: 'goroutine 泄漏为什么危险？',
                answer: '泄漏的 goroutine 持有栈和引用对象，会阻止垃圾回收，长期累积导致内存上涨和调度变慢。它们还在等待永远不会发生的信号，问题往往在压力消退后才暴露。',
              },
            ],
          },
        ],
      },
    ],
  },
]
