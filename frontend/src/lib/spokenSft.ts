/**
 * 相声口播稿「写稿任务」的 SFT 样本构造（r150 / M1 制作工具链）。
 *
 * 定位：**离线生产工具**（VERSION-PLAN §5.8）——只在制作期把教程小节改写成口播稿，
 * 不进产品、不进容器、不产生运行期出网。微调目标不是「让模型讲段子」，
 * 而是「稳定输出符合 §5.6/§5.7 口径的结构化稿子」：JSON 结构、情绪标签、
 * 逗哏/捧哏轮次、小句长度都由 `lib/spoken.ts` 的质量闸定义。
 *
 * 为什么按**小节**出样本而不是整章：
 * 1. 一份音频就是一个文件（§5.3），小节天然是生成单位；
 * 2. 4B 模型在 2048 token 内写不出整章 3000+ 字，强行整章只会截断；
 * 3. 质量闸逐节可判，坏样本能定位到具体小节。
 *
 * 输入是**原文骨架**（教程该小节的文本），输出是口播稿 JSON——两者都在同一个样本里，
 * 模型学到的是「这段技术内容该怎么讲成相声」，不是背下某一章的词。
 */
import type { SpokenChapter } from './spokenTypes'
import { sectionForm } from './spoken'
import { isListenable, spokenFormFor, type SpokenCoverageEntry } from './spokenCoverage'
import type { TutorialBlock, TutorialChapter, TutorialSection } from './tutorialTypes'

/** 样本格式版本：改提示词或目标结构就升版本，训练记录里要能对上（与 schema 化的评估同源）。 */
export const SPOKEN_SFT_VERSION = 'spoken-sft-v2'

export interface SpokenSftMessage {
  role: 'system' | 'user' | 'assistant'
  content: string
}

export interface SpokenSftSample {
  chapterId: string
  sectionId: string
  messages: SpokenSftMessage[]
}

/**
 * 写稿规则 = 训练目标 = 质量闸口径。三处必须一致：
 * 改这里的规则要同时改 `lib/spoken.ts` 的常量，否则模型学的标准与门禁判的标准会漂移。
 */
export const SPOKEN_SFT_SYSTEM_PROMPT = [
  `你是「逃跑计划」的相声写手，把技术教程小节改写成轻松的口播稿（泛听，可以走神）。输出格式版本 ${SPOKEN_SFT_VERSION}。`,
  '',
  '硬性规则：',
  '1. 只输出一个 JSON 对象，不要解释、不要 markdown 代码块。',
  '2. 结构：{"form":"solo|duo","segments":[{"speaker":"dou|peng|narrator","emotion":"banter|setup|deadpan|punch|realize|contrast|wrap","lines":["一句"]}]}',
  '3. form=solo 时只用 narrator；form=duo 时 dou 与 peng 都必须出现。',
  '4. lines 一句一个元素；单个逗号小句不超过 20 字。',
  '5. 逗哏连续发言不超过 5 句，中间必须有捧哏插话。',
  '6. 捧哏只推矛盾、不讲解；「嗯」「对」「是啊」这类纯附和最多占捧哏发言的 1/3。',
  '7. punch（抖包袱）硬上限 6 处：写完自己数一遍，多一个都不合格；少于 2 处也不合格。至少 1 处以「说白了」开头的小结。',
  '8. 笑点只来自认知反转，不用网络流行语、谐音梗，不贬低任何技术栈。',
  '9. 代码和表格不逐行念，转述成「这段干三件事」。',
  '10. 用「你」不用「您」（抬杠调侃除外）；语气词每处最多一个。',
].join('\n')

const FORM_LABEL: Record<string, string> = {
  solo: 'solo（单口自问自答）',
  duo: 'duo（对口：逗哏 dou + 捧哏 peng）',
}

function blockLines(block: TutorialBlock): string[] {
  switch (block.kind) {
    case 'text':
      return [block.text]
    case 'list':
      return block.items
    case 'table':
      return [block.headers.join(' | '), ...block.rows.map((row) => row.join(' | '))]
    case 'qa':
      return block.items.map((item) => `问：${item.question} 答：${item.answer}`)
    case 'note':
      return [`${block.title}：${block.text}`]
    case 'code':
      return [block.caption ? `代码块（${block.caption}，转述不逐行念）` : '代码块（转述不逐行念）']
    case 'demo':
      return [block.caption ? `交互演示（${block.title}）：${block.caption}` : `交互演示：${block.title}`]
  }
}

/** 原文骨架：把该小节的内容块压成「训练输入」的要点行，训练时模型只看这一份。 */
export function sectionOutline(section: TutorialSection): string[] {
  return section.blocks.flatMap(blockLines)
}

export function renderSectionPrompt(
  chapter: TutorialChapter,
  section: TutorialSection,
  index: number,
  form: string,
  chapterForm: string,
): string {
  return [
    `章节：${chapter.title}`,
    `方向：${chapter.direction} · ${chapter.sub_direction} · ${chapter.level}`,
    `本章形态：${FORM_LABEL[chapterForm] ?? chapterForm}`,
    `小节：${section.title}（${index + 1}/${chapter.sections.length}）`,
    `本节形态：${FORM_LABEL[form] ?? form}`,
    '原文骨架：',
    ...sectionOutline(section).map((line) => `- ${line}`),
    '请按系统提示输出本节口播稿 JSON。',
  ].join('\n')
}

/** 逐小节展开样本：章 → 教程章 → 小节形态（混合章按小节覆盖）。 */
export function buildSpokenSftSamples(
  scripts: readonly SpokenChapter[],
  tutorials: readonly TutorialChapter[],
): SpokenSftSample[] {
  const byId = new Map(tutorials.map((chapter) => [chapter.id, chapter]))
  const samples: SpokenSftSample[] = []
  for (const script of scripts) {
    const tutorial = byId.get(script.chapterId)
    if (!tutorial) continue
    script.sections.forEach((scriptSection, index) => {
      const section = tutorial.sections.find((item) => item.id === scriptSection.sectionId)
      if (!section) return
      const form = sectionForm(script, scriptSection)
      const target = {
        form,
        segments: scriptSection.segments.map((segment) => ({
          speaker: segment.speaker,
          emotion: segment.emotion,
          lines: segment.lines,
        })),
      }
      samples.push({
        chapterId: script.chapterId,
        sectionId: scriptSection.sectionId,
        messages: [
          { role: 'system', content: SPOKEN_SFT_SYSTEM_PROMPT },
          { role: 'user', content: renderSectionPrompt(tutorial, section, index, form, script.form) },
          { role: 'assistant', content: JSON.stringify(target) },
        ],
      })
    })
  }
  return samples
}

export interface SpokenSftStats {
  samples: number
  chapters: number
  targetChars: number
  promptChars: number
  /** 粗估 token（中文约 1.5 字/token）：只用来判断 max_length 够不够，不是精确值。 */
  estimateTokens: number
}

/**
 * 起草请求（只有 system + user，没有 assistant）：给「提示词版 baseline」用。
 * 覆盖范围 = 全部可听章（A/B）× 各自小节，形态按 coverage 的默认值
 * （A → 单口，B → 对口；混合章可在 coverage 表里显式覆盖）。
 */
export interface SpokenDraftRequest {
  chapterId: string
  sectionId: string
  form: 'solo' | 'duo'
  messages: SpokenSftMessage[]
}

export function buildSpokenDraftRequests(
  tutorials: readonly TutorialChapter[],
  coverage: readonly SpokenCoverageEntry[],
): SpokenDraftRequest[] {
  const byId = new Map(coverage.map((entry) => [entry.chapterId, entry]))
  const requests: SpokenDraftRequest[] = []
  for (const chapter of tutorials) {
    const entry = byId.get(chapter.id)
    if (!entry || !isListenable(entry.layer)) continue
    const form = spokenFormFor(entry)
    chapter.sections.forEach((section, index) => {
      requests.push({
        chapterId: chapter.id,
        sectionId: section.id,
        form,
        messages: [
          { role: 'system', content: SPOKEN_SFT_SYSTEM_PROMPT },
          { role: 'user', content: renderSectionPrompt(chapter, section, index, form, form) },
        ],
      })
    })
  }
  return requests
}

export function spokenSftStats(samples: readonly SpokenSftSample[]): SpokenSftStats {
  const chapters = new Set(samples.map((sample) => sample.chapterId))
  let targetChars = 0
  let promptChars = 0
  for (const sample of samples) {
    const [system, user, assistant] = sample.messages
    promptChars += system.content.length + user.content.length
    targetChars += assistant.content.length
  }
  return {
    samples: samples.length,
    chapters: chapters.size,
    targetChars,
    promptChars,
    estimateTokens: Math.ceil((promptChars + targetChars) / 1.5),
  }
}
