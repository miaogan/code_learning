/** 站内教程的数据结构：内容文件只依赖本文件，纯逻辑见 `lib/tutorials.ts`。 */

/** 覆盖题库全部 8 个方向（与后端 `questions.json` 的 direction 取值一致）。 */
export type TutorialDirection =
  | '前端'
  | '后端'
  | 'SQL 与数据库'
  | '中间件与运维'
  | '算法与数据结构'
  | '计算机基础'
  | 'AI 工程'
  | '研发工程实践'

/**
 * 难度档位：目录页的第二级筛选（方向 → 难度）。
 * 三档是闭集，同时用于筛选参数、卡片标签与 URL 校验；新增档位必须同步 `TUTORIAL_LEVELS`。
 */
export type TutorialLevel = '基础' | '进阶' | '高级'

/** 正文块：渲染层按 kind 分支，新增块类型必须同步 `TutorialArticle`。 */
export type TutorialBlock =
  | { kind: 'text'; text: string }
  | { kind: 'list'; ordered?: boolean; items: string[] }
  | { kind: 'code'; language: string; code: string; caption?: string }
  | { kind: 'note'; tone: 'info' | 'warn'; title: string; text: string }
  | { kind: 'table'; headers: string[]; rows: string[][] }
  | { kind: 'qa'; items: { question: string; answer: string }[] }

export interface TutorialSection {
  /** 章内唯一、ASCII：用于文内锚点与 `aria-labelledby`。 */
  id: string
  title: string
  blocks: TutorialBlock[]
}

export interface TutorialChapter {
  /** 全局唯一 ASCII slug：URL 只用它，中文方向只进查询参数。 */
  id: string
  title: string
  direction: TutorialDirection
  /** 二级方向：属于该 direction 的闭集（与后端 `rules.SUBDIRECTIONS` 同源，见 `lib/questionDirections`）。 */
  sub_direction: string
  /** 难度档位：决定它在「二级筛选」里归到哪一档，也是卡片上的标签。 */
  level: TutorialLevel
  summary: string
  sections: TutorialSection[]
}
