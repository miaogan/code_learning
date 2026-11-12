/**
 * 新用户指引的纯函数层（r86）：五步闭环的入口路由、术语对照与「当前步」判定。
 *
 * 步骤数组本身留在 UploadPage（要合并页内上传阶段），这里只放**不随交互变化**的部分：
 * 每一步的站内入口、给新用户的术语说明（侧栏叫法与页面叫法的对照），
 * 以及「第一个还没完成的步骤」的判定——新用户照着它走就是完整闭环。
 */

/** 五步闭环的站内入口（顺序与 UploadPage 的 pipeline 一一对应）。 */
export const STEP_HREFS = ['/', '/profile', '/interview', '/exam', '/report'] as const

/** 每步的新手术语对照：页面叫法 ↔ 侧栏叫法，第一次用不至于对不上号。 */
export const STEP_HINTS = [
  '选择一份 PDF / Word / 图片简历，正文入库、原文件不保存',
  '画像页逐条核溯源，目标岗位可以在那里手动补充',
  '即侧栏的「召对」：AI 面试官模拟真实面试并计分',
  '即侧栏的「科考」：模拟笔试，按方向与难度出题',
  '即侧栏的「医案」：短板诊断报告，含推荐课程与 7 天计划',
] as const

/** 五步闭环的一句话总览（只给还没上传简历的新用户看）。 */
export const NEWCOMER_GUIDE =
  '第一次用？从 01 到 05 走一遍：上传简历建立画像，再做一次召对（模拟面试）和科考（模拟笔试），最后在医案里看差距与补强路线。暂时没有简历的话，演武和学堂现在就能用。'

/**
 * 当前步 = 第一个还没完成的步骤（0 起）；全部完成返回 -1（闭环走完，不再指路）。
 * 入参是 pipeline 各步的 state（'done' / 'now' / 'todo'），本函数不感知业务语义。
 */
export function firstOpenStepIndex(states: readonly string[]): number {
  return states.findIndex((state) => state !== 'done')
}
