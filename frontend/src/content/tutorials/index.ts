import type { TutorialChapter } from '../../lib/tutorialTypes'
import { AI_CHAPTERS } from './ai'
import { ALGORITHM_CHAPTERS } from './algorithms'
import { BACKEND_CHAPTERS } from './backend'
import { CS_CHAPTERS } from './cs'
import { ENGINEERING_CHAPTERS } from './engineering'
import { FRONTEND_CHAPTERS } from './frontend'
import { MIDDLEWARE_CHAPTERS } from './middleware'
import { SQL_CHAPTERS } from './sql'

/**
 * 全部教程章节，按 `TUTORIAL_DIRECTIONS` 的顺序聚合；目录页与报告页入口都从这里读。
 * 顺序同时决定文章页「上一章 / 下一章」的走向，调整方向顺序要同步改 `lib/tutorials.ts`。
 */
export const TUTORIAL_CHAPTERS: TutorialChapter[] = [
  ...FRONTEND_CHAPTERS,
  ...BACKEND_CHAPTERS,
  ...SQL_CHAPTERS,
  ...MIDDLEWARE_CHAPTERS,
  ...ALGORITHM_CHAPTERS,
  ...CS_CHAPTERS,
  ...AI_CHAPTERS,
  ...ENGINEERING_CHAPTERS,
]
