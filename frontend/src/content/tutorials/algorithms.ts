import type { TutorialChapter } from '../../lib/tutorialTypes'

/** 算法与数据结构方向：复杂度分析、哈希表与双指针。 */
export const ALGORITHM_CHAPTERS: TutorialChapter[] = [
  {
    id: 'algo-complexity',
    title: '时间复杂度与空间复杂度',
    direction: '算法与数据结构',
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
]
