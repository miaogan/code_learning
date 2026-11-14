/** 当前产品品牌；历史任务夹、兼容标识与存储键不随品牌改名。 */
export const PRODUCT_NAME = '逃跑计划'
export const PRODUCT_NAME_EN = 'Escape Plan'
export const PRODUCT_TAGLINE = '外包工程师的跃迁工作台'
/** 页头外链：仓库主页与作者 GitHub 头像。 */
export const GITHUB_OWNER = 'miaogan'
export const GITHUB_REPO_URL = `https://github.com/${GITHUB_OWNER}/code_learning`
/**
 * 头像用站点自带静态资源（frontend/public/github-avatar.jpg），不放 GitHub 外链。
 * 两个原因：
 * 1. 生产 CSP 的 img-src 只有 'self' data: blob:，外域头像会被浏览器直接拦掉（2026-11-14 实测）；
 * 2. github.com → avatars.githubusercontent.com 这条链路对国内访客不稳定，站点自托管更可靠。
 * 注意：这是 GitHub 头像的快照，GitHub 上换头像后需重新下载覆盖本文件。
 */
export const GITHUB_AVATAR_URL = '/github-avatar.jpg'
export const PRODUCT_FOCUS = 'AI 应用 / Agent 后端'
export const PRODUCT_DESCRIPTION =
  '从外包交付到目标岗位：盘点简历证据，验证技术能力，沉淀能讲清、能复现、能衡量的项目竞争力。'
