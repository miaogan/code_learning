import type { TutorialChapter } from '../../lib/tutorialTypes'
import { AI_CHAPTERS } from './ai'
import { ALGORITHM_CHAPTERS } from './algorithms'
import { BACKEND_CHAPTERS } from './backend'
import { CS_CHAPTERS } from './cs'
import { FRONTEND_CHAPTERS } from './frontend'

/** 全部教程章节，按侧栏方向的展示顺序聚合；目录页与报告页入口都从这里读。 */
export const TUTORIAL_CHAPTERS: TutorialChapter[] = [
  ...FRONTEND_CHAPTERS,
  ...BACKEND_CHAPTERS,
  ...ALGORITHM_CHAPTERS,
  ...CS_CHAPTERS,
  ...AI_CHAPTERS,
]
