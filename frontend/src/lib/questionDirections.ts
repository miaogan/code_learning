/** 题库方向闭集：与后端 `services/report/rules.py` 的 `DIRECTIONS` / `SUBDIRECTIONS`
 * 逐字一致，改动必须同步两处。科考与召对的筛选控件都从这里派生选项。 */

export const DIRECTIONS: string[] = [
  '前端',
  '后端',
  '算法与数据结构',
  '计算机基础',
  'AI 工程',
  '中间件与运维',
  'SQL 与数据库',
  '研发工程实践',
]

/** 二级方向闭集：direction → 其下所有合法 sub_direction（末项即「通用 XX」兜底）。 */
export const SUBDIRECTIONS: Record<string, string[]> = {
  前端: ['react', 'vue3', 'js', 'ts', 'css', 'html', '通用前端'],
  后端: ['python', 'java', 'go', '通用后端'],
  算法与数据结构: ['动态规划', '二叉树与递归', '链表', '排序', '图', '复杂度', '哈希', '通用算法'],
  计算机基础: ['操作系统', '网络', '组成原理', '通用基础'],
  'AI 工程': ['LLM 与 RAG', 'Agent', 'Prompt 工程', '部署与推理', '通用 AI'],
  中间件与运维: ['Docker 与容器', 'Nginx', 'Redis', '消息队列', '监控与日志', 'CI-CD', '通用运维'],
  'SQL 与数据库': ['SQL 基础', '事务与 ACID', '索引', 'NoSQL', '通用数据库'],
  研发工程实践: ['Git 与版本控制', '测试', 'CI-CD', '架构设计', '通用工程实践'],
}

export function subDirectionsOf(direction: string): string[] {
  return SUBDIRECTIONS[direction] ?? []
}
