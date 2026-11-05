import type { TutorialChapter } from '../../lib/tutorialTypes'

/** 算法与数据结构方向：复杂度分析、哈希表与双指针。 */
export const ALGORITHM_CHAPTERS: TutorialChapter[] = [
  {
    id: 'algo-complexity',
    title: '时间复杂度与空间复杂度',
    direction: '算法与数据结构',
    level: '基础',
    summary: '用增长趋势而不是秒数衡量算法：常见复杂度、循环嵌套与递归的估算方法。',
    sections: [
      {
        id: 'why',
        title: '为什么要看复杂度',
        blocks: [
          {
            kind: 'text',
            text: '同一段代码在不同机器上的运行时间不同，但「数据量翻倍时工作量怎么涨」是稳定的。复杂度就是描述这种增长趋势的语言：忽略常数与低阶项，只看最坏情况下最重要的那一项。',
          },
          {
            kind: 'list',
            items: [
              'O(1)：与数据量无关，如数组按下标访问。',
              'O(log n)：每次把问题规模减半，如二分查找。',
              'O(n)：扫一遍数据，如单层循环。',
              'O(n log n)：排序的典型复杂度，如归并排序。',
              'O(n^2)：双重循环枚举组合，数据量大时最先出问题。',
            ],
          },
        ],
      },
      {
        id: 'estimate',
        title: '怎么快速估算',
        blocks: [
          {
            kind: 'table',
            headers: ['代码形态', '复杂度', '说明'],
            rows: [
              ['单层循环遍历 n 个元素', 'O(n)', '循环体是常数操作'],
              ['双层循环，两层都到 n', 'O(n^2)', 'n 次 × n 次'],
              ['循环里每次规模减半', 'O(log n)', '如 while (n > 1) n /= 2'],
              ['递归，每次只调用一次且规模减半', 'O(log n)', '递归深度为 log n'],
              ['递归，每次拆成两个子问题', 'O(2^n)', '未记忆化时指数增长'],
            ],
          },
          {
            kind: 'text',
            text: '空间复杂度看额外分配的存储：原地交换是 O(1)，新建与输入等长的数组是 O(n)，递归还要计算调用栈深度。面试里先说出「时间 O(...)，空间 O(...)」，再解释为什么。',
          },
          {
            kind: 'note',
            tone: 'info',
            title: '常数不是不重要',
            text: '复杂度相同不代表实际速度相同。数组顺序访问通常比链表快，因为缓存友好；但数据量很大时，复杂度更低的算法最终会胜出。',
          },
        ],
      },
      {
        id: 'example',
        title: '从 O(n^2) 到 O(n)',
        blocks: [
          {
            kind: 'text',
            text: '判断数组中是否存在两个数之和等于目标值：双层枚举是 O(n^2)；用哈希表记录已经见过的数，可以降到 O(n)。',
          },
          {
            kind: 'code',
            language: 'python',
            caption: '两数之和：一次遍历',
            code: [
              'def two_sum(nums, target):',
              '    seen = {}',
              '    for index, value in enumerate(nums):',
              '        need = target - value',
              '        if need in seen:',
              '            return [seen[need], index]',
              '        seen[value] = index',
              '    return []',
              '',
              '# 时间 O(n)：每个元素只处理一次',
              '# 空间 O(n)：最坏情况下存下所有元素',
            ].join('\n'),
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              '先想「我要找什么」：目标值的补数。',
              '再想「怎么快速判断存在」：哈希表查询近似 O(1)。',
              '最后确认边界：重复元素、无解、空数组。',
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
            title: '别把嵌套循环都当成 O(n^2)',
            text: '如果内层循环的边界随外层变化、且总执行次数是 n，例如滑动窗口，整体仍可能是 O(n)。分析要看「操作总次数」，不是看循环层数。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: 'O(n) 的算法一定比 O(n log n) 快吗？',
                answer: '不一定。复杂度描述增长趋势，小数据量下常数更小的 O(n log n) 可能更快；但数据量增大后 O(n) 会占优。',
              },
              {
                question: '递归的空间复杂度怎么算？',
                answer: '至少是递归深度，因为每层调用都要占栈帧；如果每层还创建了与规模相关的数组，要把这部分也加上。',
              },
              {
                question: '为什么排序后常用双指针？',
                answer: '排序让数据具有单调性，指针可以根据当前和的大小决定移动哪一侧，从而把枚举从 O(n^2) 降到 O(n)。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'algo-hash-pointer',
    title: '哈希表与双指针',
    direction: '算法与数据结构',
    level: '进阶',
    summary: '两类最常用的降复杂度工具：哈希表用空间换时间，双指针利用有序性减少枚举。',
    sections: [
      {
        id: 'hash',
        title: '哈希表：用空间换时间',
        blocks: [
          {
            kind: 'text',
            text: '哈希表把键映射到桶，平均情况下查找、插入、删除都是 O(1)。它适合「判断是否出现过」「统计次数」「建立值到下标的映射」这类问题。',
          },
          {
            kind: 'table',
            headers: ['场景', '哈希表存什么', '注意事项'],
            rows: [
              ['去重', '值本身', '哈希结构天然去重'],
              ['两数之和', '值 → 下标', '先查补数，再存当前值'],
              ['计数', '值 → 出现次数', '遍历结束后再筛选'],
              ['分组', '分组键 → 元素列表', '保持组内原始顺序'],
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: '最坏情况',
            text: '哈希冲突严重时，查找可能退化到 O(n)。工程上通常通过扩容与良好的哈希函数控制冲突；面试里说「平均 O(1)」更严谨。',
          },
        ],
      },
      {
        id: 'pointer',
        title: '双指针：利用有序性',
        blocks: [
          {
            kind: 'text',
            text: '双指针不是某种数据结构，而是一种枚举策略：用两个位置代表搜索空间的两端，根据当前状态排除不可能的一侧，从而减少枚举量。',
          },
          {
            kind: 'list',
            items: [
              '对撞指针：左右两端向中间移动，常见于有序数组两数之和、回文判断。',
              '快慢指针：一个走一步、一个走两步，常见于链表找中点、判断环。',
              '滑动窗口：左右边界单向移动，常见于最长子串、子数组和。',
              '使用前提是数据具有单调性或有明确的排除规则，乱序时通常要先排序。',
            ],
          },
        ],
      },
      {
        id: 'example',
        title: '有序数组的两数之和',
        blocks: [
          {
            kind: 'text',
            text: '数组已排序时，左右指针之和偏小就右移左指针，偏大就左移右指针；每步都能排除一个元素，因此是 O(n)。',
          },
          {
            kind: 'code',
            language: 'python',
            caption: '对撞双指针',
            code: [
              'def two_sum_sorted(nums, target):',
              '    left, right = 0, len(nums) - 1',
              '    while left < right:',
              '        total = nums[left] + nums[right]',
              '        if total == target:',
              '            return [left, right]',
              '        if total < target:',
              '            left += 1',
              '        else:',
              '            right -= 1',
              '    return []',
              '',
              '# 时间 O(n)，空间 O(1)',
            ].join('\n'),
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              '先确认输入有序；无序且不能排序时改用哈希表。',
              '每轮只移动一个指针，保证不会漏掉解。',
              '循环条件是 left < right，避免同一个元素被用两次。',
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
            title: '双指针不等于两层循环',
            text: '如果两个指针都可能回退，复杂度仍可能退化。对撞指针和滑动窗口的关键是「指针只前进」，总移动次数与数据量成正比。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: '哈希表解法与排序加双指针怎么选？',
                answer: '需要返回原下标时优先哈希表；只关心值、且可以排序时双指针空间更省。两者时间复杂度都是 O(n) 量级（排序为 O(n log n)）。',
              },
              {
                question: '滑动窗口什么时候可以收缩左边界？',
                answer: '当窗口内状态已经不满足题目约束时收缩，直到重新满足；每次收缩都要更新答案，避免漏掉更优区间。',
              },
              {
                question: '链表判断环为什么快慢指针一定会相遇？',
                answer: '进入环后，快指针每轮比慢指针多走一步，两者距离逐轮缩小 1，最终一定会重合。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'algo-dp-graph',
    title: '动态规划与图',
    direction: '算法与数据结构',
    level: '高级',
    summary: '动态规划只需答对三问：状态是什么、怎么转移、边界在哪；图算法则按「边权与目标」挑 BFS / Dijkstra / 拓扑。',
    sections: [
      {
        id: 'dp',
        title: '动态规划的三问',
        blocks: [
          {
            kind: 'text',
            text: '动态规划不是背题，而是把一个「大问题」拆成「规模更小的同类问题」。动手写代码前先回答三问，答不上来就别急着写循环。',
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              '状态是什么：dp[i] 的语义要能用一句话说清，例如「以 i 结尾的最长递增子序列长度」。',
              '怎么转移：dp[i] 由哪些更小的状态推出来？这一步决定时间复杂度。',
              '边界与答案：dp[0] 是什么？最终答案是 dp[n-1] 还是 max(dp)？',
            ],
          },
          {
            kind: 'table',
            headers: ['题型特征', '状态维度', '典型题'],
            rows: [
              ['线性序列、只看前缀', '一维 dp[i]', '爬楼梯、最大子数组和、打家劫舍'],
              ['两个序列/容量约束', '二维 dp[i][j]', '最长公共子序列、0-1 背包'],
              ['区间合并、依赖子区间', '区间 dp[l][r]', '最长回文子串、石子合并'],
              ['状态机（买/卖/冷却）', 'dp[i][状态]', '股票买卖系列'],
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: '先写暴力递归，再记忆化',
            text: '直接推 dp 数组容易写错转移方向。先用递归 + 记忆化把「状态 + 转移」写对，需要优化时再改成自底向上并按需滚动数组。',
          },
        ],
      },
      {
        id: 'example',
        title: '0-1 背包：二维到一维',
        blocks: [
          {
            kind: 'text',
            text: 'dp[j] 表示容量 j 能装下的最大价值。关键在逆序遍历容量：正序会让同一件物品被重复使用，那就变成完全背包了。',
          },
          {
            kind: 'code',
            language: 'python',
            caption: '0-1 背包（一维滚动）',
            code: [
              'def max_value(capacity: int, weights: list[int], values: list[int]) -> int:',
              '    dp = [0] * (capacity + 1)',
              '    for w, v in zip(weights, values):',
              '        # 逆序：保证每件物品只被选一次（正序 = 完全背包）',
              '        for j in range(capacity, w - 1, -1):',
              '            dp[j] = max(dp[j], dp[j - w] + v)',
              '    return dp[capacity]',
              '',
              'print(max_value(5, [2, 3, 4], [3, 4, 5]))   # 8',
            ].join('\n'),
          },
          {
            kind: 'list',
            items: [
              '复杂度 O(n × capacity)：n 件物品 × 容量，空间压到 O(capacity)。',
              '逆序是 0-1 背包的标记：写错方向不会报错，只会得到「物品可以无限取」的结果。',
              '容量很大但物品少时，改用「按价值做下标」或 meet-in-the-middle。',
            ],
          },
        ],
      },
      {
        id: 'graph',
        title: '图算法按边权与目标挑',
        blocks: [
          {
            kind: 'text',
            text: '图题先问两件事：边有没有权重、要最短路径还是可达性/顺序。答案基本能锁定唯一一个算法，不用试。',
          },
          {
            kind: 'table',
            headers: ['场景', '算法', '复杂度', '备注'],
            rows: [
              ['无权最短路 / 层序', 'BFS', 'O(V + E)', '第一次访问即最短'],
              ['连通块、环检测', 'DFS / 并查集', 'O(V + E) / O(α(V))', '并查集适合动态加边'],
              ['依赖顺序（课程表）', '拓扑排序', 'O(V + E)', '有环则无解，队列空但仍有入度'],
              ['非负权最短路', 'Dijkstra + 堆', 'O((V + E) log V)', '有负权边会失效'],
              ['含负权边', 'Bellman-Ford / SPFA', 'O(VE)', '能检测负环'],
            ],
          },
          {
            kind: 'note',
            tone: 'warn',
            title: 'Dijkstra 不能有负权边',
            text: '它假设「已确定的最短距离不会变小」。负权边会打破这个假设，出队即定稿的逻辑就错了。',
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
            title: '初始化写错，答案错一半',
            text: '求最大值时 dp 初始化为 0 会把「不可达」当成「价值 0」；求最小值时初始化为 0 会让所有答案都变成 0。最大值用极小值、最小值用极大值，再单独处理起点。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: '怎么判断一道题该用贪心还是动态规划？',
                answer: '能证明「局部最优可推出全局最优」才用贪心；否则用 dp。举不出反例不等于能证明，面试里说不出证明就老实写 dp。',
              },
              {
                question: '为什么背包一维写法要逆序？',
                answer: '正序遍历时 dp[j - w] 可能已经被本轮更新过，等于同一件物品被选了多次；逆序保证读到的是上一轮的值。',
              },
              {
                question: '拓扑排序怎么发现环？',
                answer: 'Kahn 算法结束时若出队节点数小于总节点数，剩下的节点入度都不为 0，说明存在环。',
              },
            ],
          },
        ],
      },
    ],
  },
]
