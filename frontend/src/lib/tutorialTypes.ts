/** 站内教程的数据结构：内容文件只依赖本文件，纯逻辑见 `lib/tutorials.ts`。 */

/** 首版只覆盖课程已有的 5 个方向（与后端 `courses.json` 的 direction 一致）。 */
export type TutorialDirection = '前端' | '后端' | '算法与数据结构' | '计算机基础' | 'AI 工程'

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
  summary: string
  sections: TutorialSection[]
}
