import type { TutorialChapter } from '../../lib/tutorialTypes'

/** SQL 与数据库方向：连接与 NULL 语义、窗口函数与执行计划。 */
export const SQL_CHAPTERS: TutorialChapter[] = [
  {
    id: 'sql-join-null',
    title: '多表连接与 NULL 语义',
    direction: 'SQL 与数据库',
    level: '基础',
    summary: '三种连接各自的语义边界，加上 NULL 的三值逻辑——「统计结果少了几行」八成出在这两处。',
    sections: [
      {
        id: 'joins',
        title: '先分清连接在保留谁',
        blocks: [
          {
            kind: 'text',
            text: '连接不是「把表拼起来」，而是「按条件匹配，并决定没匹配上的行怎么处理」。判断写法对不对，只问一句：我要保留哪一侧没有匹配的行？',
          },
          {
            kind: 'table',
            headers: ['写法', '保留范围', '没匹配的一侧', '典型用途'],
            rows: [
              ['INNER JOIN', '两侧都匹配上的行', '丢弃', '取交集，如「已下单用户的订单」'],
              ['LEFT JOIN', '左表全部行', '右表补 NULL', '「用户 + 可选订单」，包含没下单的人'],
              ['RIGHT JOIN', '右表全部行', '左表补 NULL', '少见，通常改写成 LEFT JOIN 更好读'],
              ['FULL JOIN', '两侧全部行', '对侧补 NULL', '对账、差异比对'],
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: '反连接的两种写法',
            text: '「A 里没有对应 B 的行」有两种写法：LEFT JOIN 后判右表主键 IS NULL，或 NOT EXISTS。两者语义相同，NOT EXISTS 在右表有重复时更不容易出错（不会让行数翻倍）。',
          },
        ],
      },
      {
        id: 'null',
        title: 'NULL 不是「空字符串」',
        blocks: [
          {
            kind: 'text',
            text: 'NULL 表示「未知」。任何与未知比较的结果也是未知，而 SQL 的 WHERE 只接受 TRUE，未知等同于不通过。这就是「明明有数据却查不出来」的根源。',
          },
          {
            kind: 'table',
            headers: ['表达式', '结果', '说明'],
            rows: [
              ['NULL = NULL', 'UNKNOWN', '要判空只能用 IS NULL / IS NOT NULL'],
              ["name <> 'x'", 'UNKNOWN（当 name 为 NULL）', '该行不会出现在结果里'],
              ['COUNT(*)', '包含 NULL 行', '数的是行数'],
              ['COUNT(name)', '跳过 NULL', '数的是非空值个数'],
              ["id NOT IN (1, NULL)", '永远为空', 'NOT IN 遇到 NULL 会整体失效，改 NOT EXISTS'],
            ],
          },
          {
            kind: 'note',
            tone: 'warn',
            title: '聚合里的 NULL 会静默吞数据',
            text: 'AVG(score) 会跳过 score 为 NULL 的行，分母跟着变小，均值偏高。需要把 NULL 计入分母时用 SUM(score) / COUNT(*) 并显式处理空值。',
          },
        ],
      },
      {
        id: 'example',
        title: '统计「一次都没下单的用户」',
        blocks: [
          {
            kind: 'text',
            text: '同一需求三种写法，结果必须一致：左连接判空、NOT EXISTS、NOT IN（前提是子查询不会返回 NULL）。最后一种正是最常见的坑。',
          },
          {
            kind: 'code',
            language: 'sql',
            caption: '三种反连接写法',
            code: [
              '-- 1) LEFT JOIN 判空',
              'SELECT u.id, u.name',
              'FROM users u',
              'LEFT JOIN orders o ON o.user_id = u.id',
              'WHERE o.id IS NULL;',
              '',
              '-- 2) NOT EXISTS（右表有重复也安全）',
              'SELECT u.id, u.name',
              'FROM users u',
              'WHERE NOT EXISTS (',
              '  SELECT 1 FROM orders o WHERE o.user_id = u.id',
              ');',
              '',
              '-- 3) NOT IN：子查询一旦返回 NULL，结果恒为空',
              'SELECT id, name FROM users',
              'WHERE id NOT IN (SELECT user_id FROM orders);',
            ].join('\n'),
          },
          {
            kind: 'table',
            headers: ['写法', 'orders.user_id 全非空', 'orders.user_id 含一行 NULL'],
            rows: [
              ['LEFT JOIN … IS NULL', '正确', '正确'],
              ['NOT EXISTS', '正确', '正确'],
              ['NOT IN', '正确', '返回 0 行（错）'],
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
            title: 'WHERE 会把 LEFT JOIN 变回 INNER JOIN',
            text: '写成 LEFT JOIN orders o … WHERE o.status = \'paid\'，那些「没有订单」的行因为 o.status 为 NULL 被过滤掉，等于 INNER JOIN。条件要挪到 ON 里才会保留左表全部行。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: 'LEFT JOIN 后行数为什么变多了？',
                answer: '右表在连接键上不唯一，一行左表会匹配多行右表。要么先去重（子查询/DISTINCT），要么改用 EXISTS 语义避免行数爆炸。',
              },
              {
                question: 'COUNT(*) 和 COUNT(col) 结果不同，哪个对？',
                answer: '看你要数什么：数行数用 COUNT(*)，数「该列有值的行」用 COUNT(col)。两者不同正是因为该列存在 NULL。',
              },
              {
                question: 'ON 和 WHERE 的条件写在连接里有什么区别？',
                answer: '外连接时，ON 只决定「如何匹配」，左表行依然保留；WHERE 是在连接结果上再过滤，会把补 NULL 的行筛掉。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'sql-window-explain',
    title: '窗口函数与执行计划',
    direction: 'SQL 与数据库',
    level: '进阶',
    summary: '用窗口函数做组内排名与 TopN，再用 EXPLAIN 判断这条 SQL 到底走没走索引、扫了多少行。',
    sections: [
      {
        id: 'window',
        title: '窗口函数：不合并行的聚合',
        blocks: [
          {
            kind: 'text',
            text: 'GROUP BY 会把多行压成一行；窗口函数则在保留每一行的同时，算出「它所在的这一组」的聚合值。骨架永远是三件事：按什么分组（PARTITION BY）、组内怎么排序（ORDER BY）、取第几个（排名函数）。',
          },
          {
            kind: 'table',
            headers: ['函数', '并列时', '结果示例（分数 90,90,80）', '适用场景'],
            rows: [
              ['ROW_NUMBER()', '强制分出先后', '1, 2, 3', '去重、分页取一条'],
              ['RANK()', '并列同名次，之后跳号', '1, 1, 3', '榜单（并列后留空位）'],
              ['DENSE_RANK()', '并列同名次，不跳号', '1, 1, 2', '分档、取「第 N 名」'],
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: '窗口函数不能写在 WHERE 里',
            text: 'WHERE 先于窗口计算执行，此时排名还不存在。要过滤排名，必须套一层子查询或 CTE，在外层 WHERE 里用别名。',
          },
        ],
      },
      {
        id: 'topn',
        title: '每组取 TopN 的两种写法',
        blocks: [
          {
            kind: 'text',
            text: '「每个部门薪资前三」是面试高频题，也是窗口函数最典型的落地点。窗口函数写法只需扫一遍表；相关子查询写法可读但复杂度是 O(n²) 量级。',
          },
          {
            kind: 'code',
            language: 'sql',
            caption: '窗口函数 vs 相关子查询',
            code: [
              '-- 写法一：窗口函数（推荐）',
              'WITH ranked AS (',
              '  SELECT id, dept_id, name, salary,',
              '         DENSE_RANK() OVER (PARTITION BY dept_id ORDER BY salary DESC) AS rk',
              '  FROM employees',
              ')',
              'SELECT * FROM ranked WHERE rk <= 3;',
              '',
              '-- 写法二：相关子查询（同分时会把更多人算进来，且更慢）',
              'SELECT e.*',
              'FROM employees e',
              'WHERE (',
              '  SELECT COUNT(*) FROM employees x',
              '  WHERE x.dept_id = e.dept_id AND x.salary > e.salary',
              ') < 3;',
            ].join('\n'),
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              '先想清楚「并列怎么算」：并列都要 → DENSE_RANK；只取固定条数 → ROW_NUMBER。',
              '窗口定义里的 ORDER BY 决定排名方向，漏写会得到不确定结果。',
              '外层过滤用 CTE 包一层，别试图把 rk 直接写进 WHERE。',
            ],
          },
        ],
      },
      {
        id: 'example',
        title: '用 EXPLAIN 判断有没有走索引',
        blocks: [
          {
            kind: 'text',
            text: 'EXPLAIN 输出里先看四列：type（访问方式）、key（实际用的索引）、rows（预估扫描行数）、Extra（是否回表、是否排序）。看到 type=ALL 或 rows 接近全表，就是该加索引了。',
          },
          {
            kind: 'code',
            language: 'sql',
            caption: '一个典型的三列联合索引查询',
            code: [
              'EXPLAIN SELECT id, amount, created_at',
              'FROM orders',
              'WHERE tenant_id = 42          -- 等值',
              '  AND status = \'paid\'        -- 等值',
              '  AND created_at >= \'2026-11-01\'  -- 范围',
              'ORDER BY created_at DESC',
              'LIMIT 20;',
              '',
              '-- 索引：(tenant_id, status, created_at)',
              '-- 范围列放最后，前面的等值列才能被完整用上',
            ].join('\n'),
          },
          {
            kind: 'table',
            headers: ['字段', '健康值', '危险信号'],
            rows: [
              ['type', 'ref / range', 'ALL（全表扫描）、index（扫全索引）'],
              ['rows', '远小于表行数', '接近或等于总行数'],
              ['Extra', 'Using index（覆盖索引）', 'Using filesort、Using temporary'],
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
            title: '在索引列上套函数 = 索引失效',
            text: 'WHERE DATE(created_at) = \'2026-11-05\' 会让 created_at 上的索引失效，因为要对每行求值。改写成范围条件 created_at >= \'2026-11-05\' AND created_at < \'2026-11-06\'。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: '联合索引为什么强调最左前缀？',
                answer: '索引按列顺序排序。跳过第一列直接用第二列，无法定位到有序区间的起点，只能退化为扫描。范围条件之后的列也基本用不上用于过滤。',
              },
              {
                question: 'LIMIT 100000, 20 为什么越翻越慢？',
                answer: '它要扫描并丢弃前 10 万行。改成基于游标的分页：WHERE id > 上一页最后一条的 id ORDER BY id LIMIT 20，或先用覆盖索引取主键再回表。',
              },
              {
                question: 'Using index 和 Using where 同时出现说明什么？',
                answer: '用到了覆盖索引（不需要回表），但仍有条件下推到存储引擎后过滤。若 rows 很大，值得检查条件列是否都进了索引。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'sql-lock-isolation',
    title: '事务隔离级别与锁',
    direction: 'SQL 与数据库',
    level: '高级',
    summary: '三种读异常、四个隔离级别、两把常见的锁：把「为什么同一段 SQL 在 MySQL 和 PostgreSQL 上表现不同」讲清。',
    sections: [
      {
        id: 'anomalies',
        title: '三种读异常',
        blocks: [
          {
            kind: 'text',
            text: '隔离级别是为了防这三件事。它们都发生在「同一事务读了两次」的场景里，区别只在第二次读到了什么。',
          },
          {
            kind: 'table',
            headers: ['异常', '现象', '例子'],
            rows: [
              ['脏读', '读到了别人未提交的修改', '对方最终回滚了，你却按这个值做了决策'],
              ['不可重复读', '同一事务内两次读同一行，值变了', '第一次读到余额 100，第二次读到 50'],
              ['幻读', '同一事务内两次范围查询，行数变了', '第一次 3 行，第二次 5 行（别人插入了新行）'],
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: '幻读针对的是「行数」',
            text: '不可重复读是「同一行内容变了」，幻读是「结果集里多了或少了行」。加行锁只能锁住已存在的行，锁不住「尚不存在的行」——这就是间隙锁存在的原因。',
          },
        ],
      },
      {
        id: 'levels',
        title: '四个级别与各库默认',
        blocks: [
          {
            kind: 'text',
            text: '隔离级别越高，并发越差。工程上的默认选择是「读已提交」，需要对账、报表一类的场景才升到可重复读。',
          },
          {
            kind: 'table',
            headers: ['级别', '脏读', '不可重复读', '幻读', '备注'],
            rows: [
              ['读未提交', '可能', '可能', '可能', '几乎不用'],
              ['读已提交', '不可能', '可能', '可能', 'PostgreSQL / Oracle 默认'],
              ['可重复读', '不可能', '不可能', '可能（InnoDB 用间隙锁基本挡住）', 'MySQL 默认'],
              ['串行化', '不可能', '不可能', '不可能', '读也会加锁，并发最低'],
            ],
          },
          {
            kind: 'list',
            items: [
              'MVCC（多版本）让「读」不加锁：读已提交每次读最新快照，可重复读整个事务共用第一次读的快照。',
              'InnoDB 的可重复读额外用间隙锁（Next-Key Lock）阻止范围内插入，所以幻读基本不会出现。',
              '写操作之间仍然会互相阻塞：两个事务改同一行，后到的等锁。',
            ],
          },
        ],
      },
      {
        id: 'example',
        title: '同一段业务在两种级别下的行为',
        blocks: [
          {
            kind: 'text',
            text: '「先查有没有，再插一条」在可重复读下最容易出事：两个事务的快照都看不到对方，于是都插成功。用唯一索引或 SELECT … FOR UPDATE 才能真的挡住。',
          },
          {
            kind: 'code',
            language: 'sql',
            caption: '加锁读 vs 唯一约束',
            code: [
              '-- 读已提交：两次读可能不同（不可重复读）',
              'BEGIN;',
              'SELECT balance FROM accounts WHERE id = 1;  -- 100',
              '-- 另一个事务提交了 UPDATE ... SET balance = 50',
              'SELECT balance FROM accounts WHERE id = 1;  -- 50',
              'COMMIT;',
              '',
              '-- 加锁读：对「不存在」的行加间隙锁，阻止并发插入',
              'BEGIN;',
              'SELECT id FROM coupons WHERE user_id = 9 AND type = \'新人\' FOR UPDATE;',
              'INSERT INTO coupons (user_id, type) VALUES (9, \'新人\');',
              'COMMIT;',
              '',
              '-- 更省事：让唯一索引兜底，冲突时按「已领取」处理',
              'ALTER TABLE coupons ADD UNIQUE KEY uk_user_type (user_id, type);',
            ].join('\n'),
          },
          {
            kind: 'table',
            headers: ['做法', '并发安全', '代价'],
            rows: [
              ['先查再插（无锁）', '否，可重复读下也会重复插入', '无'],
              ['SELECT … FOR UPDATE', '是', '锁等待、可能死锁'],
              ['唯一索引 + 捕获冲突', '是', '需要处理唯一键报错'],
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
            title: '长事务把锁握到天荒地老',
            text: '事务里夹了 HTTP 调用或人工确认，锁就一直不释放，后面全在等。事务要短：只包住数据库操作，外部调用放事务外。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: '死锁发生了怎么处理？',
                answer: '数据库会选一个事务回滚（死锁检测），业务侧要能重试。预防手段：所有事务按同一顺序访问资源、缩短事务、给热点行加合适索引减少锁范围。',
              },
              {
                question: '为什么加了索引还是锁很多行？',
                answer: '如果条件列没走索引，InnoDB 会扫描并锁住扫过的行（甚至全表）。先用 EXPLAIN 确认命中索引，再看锁的实际范围。',
              },
              {
                question: '可重复读下为什么我的读看不到别人刚提交的数据？',
                answer: '快照在事务第一次读时建立，之后的普通读都读这个快照。需要看最新数据要用加锁读（FOR UPDATE）或切到读已提交。',
              },
            ],
          },
        ],
      },
    ],
  },
]
