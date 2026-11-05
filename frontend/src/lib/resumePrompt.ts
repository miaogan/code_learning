/**
 * 「未上传简历」引导弹框的会话级开关：一个标签页会话只主动弹一次。
 *
 * 为什么用 sessionStorage 而不是模块级变量：模块变量在整页刷新（F5 / 直接输入 URL）
 * 后归零，弹框会跟着每次刷新重弹一遍，反而变成打扰。sessionStorage 恰好是
 * 「标签页会话」的语义 —— 刷新不复位，关掉标签页才清空，与「登录会话」的体感一致。
 */
const STORAGE_KEY = 'sc.resumePrompted'

export function consumeResumePrompt(): boolean {
  try {
    if (window.sessionStorage.getItem(STORAGE_KEY) === '1') return false
    window.sessionStorage.setItem(STORAGE_KEY, '1')
    return true
  } catch {
    // 存储不可用（隐私模式等）时宁可少弹不误弹：静默放弃这次引导。
    return false
  }
}

/** 登出 / 切换账号时重置，让下一位用户仍能看到一次引导。 */
export function resetResumePrompt(): void {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    /* 存储不可用时不做任何事 */
  }
}
