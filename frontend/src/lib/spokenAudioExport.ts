/**
 * 音频计划导出入口：只给 `scripts/export_spoken_audio.mjs` 用（esbuild 打包后 import）。
 * 不在页面里引用，避免把制作期逻辑带进运行时产物。
 */
export { SPOKEN_SCRIPTS } from '../content/spoken'
export { buildAudioPlan } from './spokenAudioPlan'
