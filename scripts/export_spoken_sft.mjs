#!/usr/bin/env node
/**
 * 把 3 章黄金稿导出成 ms-swift 能直接吃的 SFT 数据（r150 制作工具链）。
 *
 * 复用前端同一个 `buildSpokenSftSamples()`（esbuild 打包后 import），
 * 不在 Node 里复制提示词或目标结构 —— 否则「训练学的格式」与「产品门禁判的格式」
 * 会各有一套，模型输出永远对不上 `lib/spoken.ts` 的质量闸。
 *
 * 用法（必须在前端目录下执行，esbuild 从 frontend/node_modules 解析）：
 *   cd frontend && node ../scripts/export_spoken_sft.mjs
 *
 * 产物（已 gitignore，属离线生产资料）：
 *   scripts/finetune/out/spoken_sft.jsonl        训练/评估数据（每行 {messages:[...]}）
 *   scripts/finetune/out/dataset_info_entry.json 要贴进 llm-finetune-lab 的注册表条目
 */

import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '..')
// ESM 裸包名按脚本目录解析，esbuild 只装在前端 node_modules：用 createRequire 指向前端 package.json。
const { build } = createRequire(join(ROOT, 'frontend', 'package.json'))('esbuild')
const ENTRY = join(ROOT, 'frontend', 'src', 'lib', 'spokenSftExport.ts')
const OUT_DIR = join(HERE, 'finetune', 'out')

async function loadModule() {
  // 打包产物落在仓库内 .tmp/（已 gitignore）：CI 与沙箱都可能禁止写系统临时目录。
  const scratch = join(ROOT, '.tmp')
  await mkdir(scratch, { recursive: true })
  const dir = await mkdtemp(join(scratch, 'spoken-sft-'))
  const outfile = join(dir, 'spokenSftExport.mjs')
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
const samples = mod.buildSpokenSftSamples(mod.SPOKEN_SCRIPTS, mod.ALL_TUTORIAL_CHAPTERS)
const stats = mod.spokenSftStats(samples)

/**
 * 评估集按**章**切，不按样本随机切：同一章 4 个小节共享同一套梗和节奏，
 * 随机切会让「训练见过的章」泄漏到评估集，指标虚高。默认留 1 章做评估，
 * 铺到 40 章后建议留 8–10 章（且评估章不进训练）。
 */
const EVAL_CHAPTERS = new Set(['mw-observability'])
const train = samples.filter((sample) => !EVAL_CHAPTERS.has(sample.chapterId))
const evalSamples = samples.filter((sample) => EVAL_CHAPTERS.has(sample.chapterId))

const toJsonl = (list) => list.map((sample) => JSON.stringify({ messages: sample.messages })).join('\n') + '\n'

await mkdir(OUT_DIR, { recursive: true })
await writeFile(join(OUT_DIR, 'spoken_sft.jsonl'), toJsonl(samples), 'utf8')
await writeFile(join(OUT_DIR, 'spoken_sft_train.jsonl'), toJsonl(train), 'utf8')
await writeFile(join(OUT_DIR, 'spoken_sft_eval.jsonl'), toJsonl(evalSamples), 'utf8')
await writeFile(
  join(OUT_DIR, 'dataset_info_entry.json'),
  JSON.stringify(
    ['spoken_sft', 'spoken_sft_train', 'spoken_sft_eval'].map((name) => ({
      dataset_name: name,
      dataset_path: `data/${name}.jsonl`,
    })),
    null,
    2,
  ) + '\n',
  'utf8',
)

console.log(`格式版本：${mod.SPOKEN_SFT_VERSION}`)
console.log(
  `样本：${stats.samples} 条（${stats.chapters} 章） · 目标 ${stats.targetChars} 字 · 输入 ${stats.promptChars} 字`,
)
console.log(
  `切分：训练 ${train.length} 条（${stats.chapters - EVAL_CHAPTERS.size} 章）/ 评估 ${evalSamples.length} 条（${[...EVAL_CHAPTERS].join('、')}）`,
)
console.log(`粗估每条总长：≈${Math.ceil(stats.estimateTokens / Math.max(1, stats.samples))} token（中文约 1.5 字/token）`)
console.log('已写出：scripts/finetune/out/{spoken_sft,spoken_sft_train,spoken_sft_eval}.jsonl + dataset_info_entry.json')
console.log('下一步：把三个 jsonl 复制到 llm-finetune-lab/data/，并按其格式追加 dataset_info 条目。')
