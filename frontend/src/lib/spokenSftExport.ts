/**
 * SFT / 起草的打包入口：只给 `scripts/export_spoken_sft.mjs` 用（esbuild 打包后 import）。
 * 不在页面里引用，避免把训练样本构造逻辑带进运行时产物。
 */
export { SPOKEN_COVERAGE } from '../content/spoken/coverage'
export { SPOKEN_SCRIPTS } from '../content/spoken'
export { ALL_TUTORIAL_CHAPTERS } from './tutorials'
export {
  SPOKEN_SFT_VERSION,
  buildSpokenDraftRequests,
  buildSpokenSftSamples,
  spokenSftStats,
} from './spokenSft'
export { coverageStats } from './spokenCoverage'
