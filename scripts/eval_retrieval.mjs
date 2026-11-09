#!/usr/bin/env node
/**
 * M3「检索召回评估」独立产物，不新增任何 npm 依赖。
 *
 * 用仓库已有的 esbuild（vite 依赖，frontend/node_modules/esbuild）把前端两个
 * TS 模块打包成临时 ESM 并动态导入，然后对 docs/eval/retrieval-gold.json 的
 * 人工标注跑三个指标 + recall@5 的 Wilson 95% 区间。
 *
 * 运行（仓库根目录）：node scripts/eval_retrieval.mjs   → 退出码 0
 * 同时：① 把指标摘要打印到 stdout；② 生成 docs/eval/RETRIEVAL-REPORT.md。
 * 报告里的所有数字均来自本次 searchTutorials 的实测结果，非手写。
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath, pathToFileURL } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const FRONTEND = path.join(ROOT, 'frontend')
const GOLD = path.join(ROOT, 'docs', 'eval', 'retrieval-gold.json')
const REPORT = path.join(ROOT, 'docs', 'eval', 'RETRIEVAL-REPORT.md')

// CI 门禁阈值：写成顶层常量，便于随评估口径调整。
// --check 为只读模式：只算指标 + 打印，绝不写任何文件（用于 CI）。
const CHECK_MODE = process.argv.slice(2).includes('--check')
const CHECK_RECALL_MIN = 0.8
const CHECK_CITATION_VALID_MIN = 1.0

const pct = (x) => `${(x * 100).toFixed(1)}%`
const frac = (a, b) => `${a}/${b}`

/** Wilson score 区间（z=1.96，95%），边界钳到 [0,1]。 */
function wilson(successes, n, z = 1.96) {
  if (n === 0) return { center: 0, lower: 0, upper: 0 }
  const p = successes / n
  const z2 = z * z
  const denom = 1 + z2 / n
  const center = (p + z2 / (2 * n)) / denom
  const margin = (z / denom) * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n))
  return {
    center,
    lower: Math.max(0, center - margin),
    upper: Math.min(1, center + margin),
  }
}

/**
 * 构造临时入口 re-export 两个 TS 模块，esbuild 打包成临时 ESM，再动态 import。
 * absWorkingDir 设为仓库根，保证相对路径解析正确。
 */
async function loadSearchModule() {
  // esbuild 位于 frontend/node_modules，不是 scripts/ 的可解析祖先目录，
  // 用 createRequire 以 frontend/ 为基准解析，拿到的正是仓库这份 esbuild。
  const require = createRequire(path.join(FRONTEND, 'package.json'))
  const esbuild = require('esbuild')

  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'm3-eval-retrieval-'))
  // Windows 盘符不同（tmpdir 可能在 C:，仓库在 D:），入口里用绝对路径 re-export。
  const asImport = (p) => p.replace(/\\/g, '/')
  const entry = [
    `export { searchTutorials } from ${JSON.stringify(asImport(path.join(FRONTEND, 'src/lib/tutorialSearch.ts')))}`,
    `export { ALL_TUTORIAL_CHAPTERS } from ${JSON.stringify(asImport(path.join(FRONTEND, 'src/lib/tutorials.ts')))}`,
    '',
  ].join('\n')
  const entryPath = path.join(tmpDir, 'entry.mjs')
  fs.writeFileSync(entryPath, entry, 'utf8')

  const outfile = path.join(tmpDir, 'bundle.mjs')
  // 沙箱下 esbuild 子进程无权直接写 os.tmpdir()（会报 Access is denied），
  // 故让 esbuild 在内存里产出，再由 Node（有写权限）落盘；行为等价于 outfile 写文件。
  const result = await esbuild.build({
    entryPoints: [entryPath],
    bundle: true,
    format: 'esm',
    platform: 'node',
    outfile,
    write: false,
    absWorkingDir: ROOT,
    logLevel: 'silent',
  })
  fs.writeFileSync(outfile, result.outputFiles[0].contents)
  // 关闭 esbuild 常驻服务，避免挂住事件循环导致进程不退出。
  await esbuild.stop()

  const mod = await import(pathToFileURL(outfile).href)
  return { mod, tmpDir }
}

/** 由实测结果拼出 stdout 摘要与报告共用的格式化字符串。 */
function formatResult(R) {
  return {
    recallPct: pct(R.recall),
    recallFrac: frac(R.hitCount, R.n),
    rejectPct: pct(R.rejectRate),
    rejectFrac: frac(R.noCitationCount, R.n),
    validPct: R.citationValidRate === null ? 'N/A' : pct(R.citationValidRate),
    validFrac: frac(R.validCitations, R.totalCitations),
    wilsonCenter: R.w.center.toFixed(4),
    wilsonLower: R.w.lower.toFixed(4),
    wilsonUpper: R.w.upper.toFixed(4),
    wilsonLowerPct: pct(R.w.lower),
    wilsonUpperPct: pct(R.w.upper),
    pointEst: R.recall.toFixed(4),
  }
}

/** --check 门禁：返回中文失败原因数组，空数组表示通过。只读，不写任何文件。 */
function evaluateGate(R, S) {
  const failures = []
  if (R.recall < CHECK_RECALL_MIN) {
    failures.push('recall@5 ' + S.recallPct + ' 低于门禁阈值 ' + pct(CHECK_RECALL_MIN))
  }
  if (R.citationValidRate === null || R.citationValidRate < CHECK_CITATION_VALID_MIN) {
    failures.push('引用有效率 ' + S.validPct + ' 未达到门禁阈值 ' + pct(CHECK_CITATION_VALID_MIN))
  }
  return failures
}

function buildStdout(R, S, checkMode = false) {
  const bar = '─'.repeat(64)
  const L = []
  L.push(bar)
  L.push(' M3 检索召回评估摘要（检索增强 / 非 RAG；无 embedding、无向量库）')
  L.push(bar)
  L.push(' 标注数据  : docs/eval/retrieval-gold.json (version ' + R.version + ', ' + R.createdAt + ')')
  L.push(' 样本量 n  : ' + R.n)
  L.push(' recall@5  : ' + S.recallPct + '  (' + S.recallFrac + ')')
  L.push(' 无命中拒答率: ' + S.rejectPct + '  (' + S.rejectFrac + ')')
  L.push(' 引用有效率 : ' + S.validPct + '  (' + S.validFrac + ' 条 citation 的 section_id 有效)')
  L.push(
    ' recall@5 Wilson 95% (z=1.96): center ' + S.wilsonCenter +
      '  CI [' + S.wilsonLower + ', ' + S.wilsonUpper + '] = [' +
      S.wilsonLowerPct + ', ' + S.wilsonUpperPct + ']',
  )
  L.push(bar)
  L.push(' 逐组明细:')
  for (const d of R.details) {
    L.push('  ' + d.id + ' | ' + d.query + ' | ' + d.hitChapters + ' | ' + (d.hit ? '命中' : '未命中'))
  }
  L.push(bar)
  L.push(checkMode ? ' --check 只读模式：未写入任何文件' : ' 报告生成: docs/eval/RETRIEVAL-REPORT.md')
  return L.join('\n')
}

function buildReport(R, S) {
  const L = []
  L.push('# M3 检索召回评估报告')
  L.push('')
  L.push('> 生成命令：`node scripts/eval_retrieval.mjs` ｜ 数据：`docs/eval/retrieval-gold.json`（version `' + R.version + '`）｜ 样本量 n = ' + R.n)
  L.push('>')
  L.push('> 本报告由 `scripts/eval_retrieval.mjs` 真实运行输出生成，所有数字来自 `searchTutorials` 的实测结果，非手写编造。')
  L.push('')

  L.push('## 口径说明')
  L.push('')
  L.push('- 评估对象：`frontend/src/lib/tutorialSearch.ts` 的纯函数 `searchTutorials(query, filters, chapters, limit)`，以及 `frontend/src/lib/tutorials.ts` 的 `ALL_TUTORIAL_CHAPTERS`。')
  L.push('- **这是「检索增强」（retrieval-augmented），不是 RAG**：实现与评估全程 **无 embedding、无向量库、无大模型生成**。`searchTutorials` 在小节级文档上做 BM25 关键词召回 + 方向/子方向元数据硬过滤，返回带 `chapter_id` / `section_id` 的 `Citation` 作为引用锚点，不参与任何文本生成。')
  L.push('- 调用方式：对每组标注执行 `searchTutorials(case.query, { direction, sub_direction }, ALL_TUTORIAL_CHAPTERS, 5)`，取 top-5 的 `chapter_id`。')
  L.push('- 指标定义：')
  L.push('  - **recall@5** = top-5 至少命中一个 `expected_chapter_ids` 的组数 / 总组数 n。')
  L.push('  - **无命中拒答率** = 返回空 `citation` 的组数 / 总组数 n。')
  L.push('  - **引用有效率** = 所有返回 `citation` 中 `section_id` 确实存在于对应章节 `sections` 的比例（用 `ALL_TUTORIAL_CHAPTERS` 校验）。')
  L.push('- 数据来源：`docs/eval/retrieval-gold.json`（version `' + R.version + '`，created_at `' + R.createdAt + '`），人工标注，共 ' + R.n + ' 组。')
  L.push('')
  L.push('### 解读限制（不要把 100% 当能力宣传）')
  L.push('')
  L.push('- 样本量仅 ' + R.n + ' 组，且标注查询与教程语料同源（由同一批章节标题启发写成），**存在标注泄漏风险**；recall@5 满分只能证明「实现可用、引用锚点有效」，不能证明对真实用户自由输入的泛化能力。')
  L.push('- 对外引用请使用 Wilson 95% 区间的下界；扩充到 ≥100 组真实用户查询后再更新结论。')
  L.push('- 本评估只覆盖教程侧 BM25，不含题目侧 FTS5，也不含 RRF 融合后的端到端排序。')
  L.push('')

  L.push('## 生成命令')
  L.push('')
  L.push('在仓库根目录执行：')
  L.push('')
  L.push('```bash')
  L.push('node scripts/eval_retrieval.mjs')
  L.push('```')
  L.push('')
  L.push('脚本会：① 用 `frontend/node_modules/esbuild` 把两个 TS 模块打包成临时 ESM 并动态导入；② 跑全部标注并计算指标；③ 把指标摘要打印到 stdout；④ 生成/覆写本报告文件。成功运行时退出码 0。')
  L.push('')

  L.push('## 样本量与三个指标')
  L.push('')
  L.push('| 指标 | 实测值 | 说明 |')
  L.push('| --- | --- | --- |')
  L.push('| 样本量 n | ' + R.n + ' | gold.json 的标注 case 数 |')
  L.push('| recall@5 | ' + S.recallPct + '（' + S.recallFrac + '） | 点估计；不以裸百分比单独给出，Wilson 区间见下节 |')
  L.push('| 无命中拒答率 | ' + S.rejectPct + '（' + S.rejectFrac + '） | 返回空 citation 的组数 / n |')
  L.push('| 引用有效率 | ' + S.validPct + '（' + S.validFrac + '） | section_id 存在于对应章节 sections 的 citation 比例 |')
  L.push('')

  L.push('## recall@5 的 Wilson 95% 置信区间')
  L.push('')
  L.push('z = 1.96，n = ' + R.n + '，命中组数 k = ' + R.hitCount + '，点估计 p = ' + S.pointEst + '。')
  L.push('')
  L.push('```text')
  L.push('denom  = 1 + z^2 / n')
  L.push('center = (p + z^2 / (2n)) / denom')
  L.push('half   = (z / denom) * sqrt( p(1-p)/n + z^2/(4n^2) )')
  L.push('CI     = [center - half, center + half]   （钳到 [0,1]）')
  L.push('```')
  L.push('')
  L.push('- Wilson center = ' + S.wilsonCenter)
  L.push('- **Wilson 95% CI = [' + S.wilsonLower + ', ' + S.wilsonUpper + ']，即 [' + S.wilsonLowerPct + ', ' + S.wilsonUpperPct + ']**')
  L.push('')
  L.push('> recall@5 属于小样本（n=' + R.n + '）比例，故不以裸百分比单独给出，随附 Wilson 区间以反映估计的不确定性。')
  L.push('')

  L.push('## 逐组明细')
  L.push('')
  L.push('| id | query | 命中章节 | 是否命中 |')
  L.push('| --- | --- | --- | --- |')
  for (const d of R.details) {
    L.push('| ' + d.id + ' | ' + d.query + ' | ' + d.hitChapters + ' | ' + (d.hit ? '✅ 命中' : '❌ 未命中') + ' |')
  }
  L.push('')
  L.push('> 「命中章节」列列出该组 top-5 返回的 `chapter_id`（去重保序），前缀 `✓` 表示该章节属于该组 `expected_chapter_ids`；`—` 表示该组未返回任何 citation。「是否命中」为 ✅ 当且仅当至少一个返回 `chapter_id` ∈ `expected_chapter_ids`。')
  L.push('')
  return L.join('\n')
}

let tmpDir = null
let checkOutcome = null
try {
  const loaded = await loadSearchModule()
  tmpDir = loaded.tmpDir
  const { searchTutorials, ALL_TUTORIAL_CHAPTERS } = loaded.mod

  const gold = JSON.parse(fs.readFileSync(GOLD, 'utf8'))

  // 章节 -> 其下 section_id 集合，供「引用有效率」校验。
  const sectionIdsByChapter = new Map()
  for (const ch of ALL_TUTORIAL_CHAPTERS) {
    sectionIdsByChapter.set(ch.id, new Set(ch.sections.map((s) => s.id)))
  }

  let hitCount = 0
  let noCitationCount = 0
  let totalCitations = 0
  let validCitations = 0
  const details = []

  for (const c of gold.cases) {
    const citations = searchTutorials(
      c.query,
      { direction: c.direction, sub_direction: c.sub_direction },
      ALL_TUTORIAL_CHAPTERS,
      5,
    )
    const returnedIds = citations.map((x) => x.chapter_id)
    const expected = new Set(c.expected_chapter_ids)
    const hit = returnedIds.some((id) => expected.has(id))
    if (hit) hitCount += 1
    if (citations.length === 0) noCitationCount += 1

    for (const cite of citations) {
      totalCitations += 1
      const set = sectionIdsByChapter.get(cite.chapter_id)
      if (set && set.has(cite.section_id)) validCitations += 1
    }

    // 展示：去重保序的 chapter_id，命中期望的打 ✓。
    const seen = new Set()
    const display = []
    for (const id of returnedIds) {
      if (seen.has(id)) continue
      seen.add(id)
      display.push((expected.has(id) ? '✓' : '') + id)
    }
    details.push({
      id: c.id,
      query: c.query,
      hitChapters: display.length ? display.join(', ') : '—',
      hit,
    })
  }

  const n = gold.cases.length
  const R = {
    version: gold.version,
    createdAt: gold.created_at,
    n,
    hitCount,
    noCitationCount,
    totalCitations,
    validCitations,
    recall: hitCount / n,
    rejectRate: noCitationCount / n,
    citationValidRate: totalCitations === 0 ? null : validCitations / totalCitations,
    w: wilson(hitCount, n),
    details,
  }
  const S = formatResult(R)

  // 报告与 stdout 共用同一份 S / R，保证数字完全一致。
  if (CHECK_MODE) {
    // --check：只计算 + 打印，绝不写任何文件；门禁结论在 finally 之后统一给出。
    checkOutcome = evaluateGate(R, S)
    console.log(buildStdout(R, S, true))
  } else {
    fs.writeFileSync(REPORT, buildReport(R, S), 'utf8')
    console.log(buildStdout(R, S))
  }
} catch (err) {
  console.error('[eval_retrieval] 运行失败:', err)
  process.exitCode = 1
} finally {
  if (tmpDir) {
    try {
      fs.rmSync(tmpDir, { recursive: true, force: true })
    } catch {
      /* 临时目录清理失败不影响评估结果 */
    }
  }
}

// --check 的退出判定放在 finally 之后，确保临时目录已清理再退出。
if (CHECK_MODE && checkOutcome !== null) {
  if (checkOutcome.length > 0) {
    console.error('检索评估门禁未通过（--check 只读，未写入任何文件）：')
    for (const reason of checkOutcome) {
      console.error('  - ' + reason)
    }
    process.exit(1)
  }
  console.log(
    '检索评估门禁通过（--check 只读，未写入任何文件）：recall@5 >= ' +
      pct(CHECK_RECALL_MIN) + ' 且 引用有效率 == ' + pct(CHECK_CITATION_VALID_MIN),
  )
  process.exit(0)
}
