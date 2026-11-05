let promptedThisSession = false

/**
 * 「未上传简历」引导弹框的会话级开关：整段登录会话只主动弹一次。
 * 用户第一次进入任一依赖画像的页面时返回 true，之后一律 false，
 * 避免在面试 / 笔试 / 报告等页面来回切换时被同一个弹框反复打断。
 */
export function consumeResumePrompt(): boolean {
  if (promptedThisSession) return false
  promptedThisSession = true
  return true
}

/** 登出 / 切换账号时重置，让下一位用户仍能看到一次引导。 */
export function resetResumePrompt(): void {
  promptedThisSession = false
}
