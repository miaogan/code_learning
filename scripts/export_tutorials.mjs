#!/usr/bin/env node
/**
 * 把前端教程语料导出成后端可读的种子 JSON（r105）。
 *
 * 为什么需要导出：教程正文只在前端 `frontend/src/content/tutorials/`（TS 模块），
 * 后端离线重建索引时拿不到——只能在浏览器里点「推送教程正文」。导出成
 * `backend/app/seed/tutorials_rag.json` 后，后端启动/重建可以自行摄取全量语料。
 *
 * 关键点：**复用前端同一个 `buildTutorialChunks()`**（通过 esbuild 打包后 import），
 * 不在 Node 脚本里复制切分/序列化逻辑——否则前端和后端会各有一套「教程怎么变成 chunk」。
 *
 * 用法（必须在前端目录下执行，esbuild 从 frontend/node_modules 解析）：
 *   cd frontend && node ../scripts/export_tutorials.mjs            # 生成
 *   cd frontend && node ../scripts/export_tutorials.mjs --check    # CI 门禁：只比对不写盘
 */

import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '..')
// ESM 的裸包名按**脚本所在目录**解析，而 esbuild 只装在前端 node_modules 里；
// 用 createRequire 指向前端 package.json 才能解析到（不是靠 cwd）。
const { build } = createRequire(join(ROOT, 'frontend', 'package.json'))('esbuild')
const ENTRY = join(ROOT, 'frontend', 'src', 'lib', 'ragIngest.ts')
const TARGET = join(ROOT, 'backend', 'app', 'seed', 'tutorials_rag.json')

async function loadItems() {
  // 打包产物落在仓库内 .tmp/（已 gitignore）：CI 与本地沙箱都可能禁止写系统临时目录。
  const scratch = join(ROOT, '.tmp')
  await mkdir(scratch, { recursive: true })
  const dir = await mkdtemp(join(scratch, 'tutorials-'))
  const outfile = join(dir, 'ragIngest.mjs')
  try {
    await build({
      entryPoints: [ENTRY],
      outfile,
      bundle: true,
      format: 'esm',
      platform: 'node',
      logLevel: 'error',
    })
    const module = await import(pathToFileURL(outfile).href)
    return module.buildTutorialChunks()
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}

function render(items) {
  return (
    JSON.stringify(
      {
        version: 'v1',
        generated_by: 'scripts/export_tutorials.mjs',
        note: '由前端教程语料导出；改教程后请重新生成（CI 有 --check 门禁）。',
        count: items.length,
        items,
      },
      null,
      2,
    ) + '\n'
  )
}

const items = await loadItems()
const content = render(items)
const checkMode = process.argv.includes('--check')

if (checkMode) {
  let existing = ''
  try {
    existing = await readFile(TARGET, 'utf8')
  } catch {
    existing = ''
  }
  if (existing !== content) {
    console.error(
      '教程种子与源不一致：请在前端目录执行 `node ../scripts/export_tutorials.mjs` 后提交 ' +
        'backend/app/seed/tutorials_rag.json',
    )
    process.exit(1)
  }
  console.log(`教程种子一致（${items.length} 小节）`)
  process.exit(0)
}

await writeFile(TARGET, content, 'utf8')
console.log(`已导出 ${items.length} 个教程小节 → backend/app/seed/tutorials_rag.json`)
