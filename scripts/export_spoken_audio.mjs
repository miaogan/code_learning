#!/usr/bin/env node
/**
 * 把口播稿导出成「音频计划」JSON（r150 / M1），给 `scripts/tts/synthesize.py` 用。
 *
 * 复用前端同一个 `buildAudioPlan()`（esbuild 打包后 import）：停顿、路径、合成单元
 * 都不在 Node/Python 里复制一份，避免「文案改了音频没改」。
 *
 * 用法（在 frontend 目录下执行）：
 *   cd frontend && node ../scripts/export_spoken_audio.mjs
 *
 * 产物（gitignore）：`scripts/tts/out/plans/<chapterId>.json` + `index.json`
 */

import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '..')
const { build } = createRequire(join(ROOT, 'frontend', 'package.json'))('esbuild')
const ENTRY = join(ROOT, 'frontend', 'src', 'lib', 'spokenAudioExport.ts')
const OUT_DIR = join(HERE, 'tts', 'out', 'plans')

async function loadModule() {
  const scratch = join(ROOT, '.tmp')
  await mkdir(scratch, { recursive: true })
  const dir = await mkdtemp(join(scratch, 'spoken-audio-'))
  const outfile = join(dir, 'spokenAudioExport.mjs')
  try {
    await build({
      entryPoints: [ENTRY],
      outfile,
      bundle: true,
      format: 'esm',
      platform: 'node',
      logLevel: 'error',
    })
    return await import(pathToFileURL(outfile).href)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}

const mod = await loadModule()
const plans = mod.SPOKEN_SCRIPTS.map((chapter) => mod.buildAudioPlan(chapter))

await mkdir(OUT_DIR, { recursive: true })
const index = []
for (const plan of plans) {
  await writeFile(join(OUT_DIR, `${plan.chapterId}.json`), JSON.stringify(plan, null, 2) + '\n', 'utf8')
  const sections = plan.sections.length
  const units = plan.sections.reduce((sum, section) => sum + section.units.length, 0)
  const estimateMinutes = Math.round((plan.sections.reduce((sum, section) => sum + section.estimateMs, 0) / 60000) * 10) / 10
  index.push({ chapterId: plan.chapterId, form: plan.form, sections, units, estimateMinutes })
  console.log(`${plan.chapterId}: ${sections} 节 / ${units} 个合成单元 / 估时 ${estimateMinutes} 分钟`)
}

await writeFile(join(OUT_DIR, 'index.json'), JSON.stringify(index, null, 2) + '\n', 'utf8')
console.log(`已写出 ${plans.length} 份音频计划 → scripts/tts/out/plans/`)
console.log('下一步：python scripts/tts/synthesize.py --backend mock（先跑通契约）或 --backend cosyvoice')
