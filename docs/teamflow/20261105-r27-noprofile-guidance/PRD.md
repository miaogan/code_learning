# r27 · 无简历状态下的功能引导修复

## 1. 背景与问题

用户反馈：「当用户没有上传简历的时候，其他功能的引导似乎有问题。」

用真实后端（FastAPI + 测试账号，无画像 / 无简历）+ Playwright 走查全部页面后，确认 4 处问题：

| # | 问题 | 根因 |
|---|---|---|
| 1 | 「未上传简历」引导弹框在 dev（StrictMode）下**永不出现** | `ResumeGate` 的 `useEffect` 被 StrictMode 双跑：第一遍消费掉会话配额并置 open=true，第二遍 consume 返回 false 把弹框重新关上 |
| 2 | 弹框在生产环境**每次整页刷新都重弹** | 会话标记是模块级变量，F5 / 直输 URL 后归零；「会话级」从未真正实现 |
| 3 | 上传页对新用户**零引导** | 首页只有拖拽框；不想 / 不能立刻传简历的用户不知道「练习 / 学习」无需简历可用 |
| 4 | 成绩趋势空态「开始测评」→ `/exam` 是**两跳死胡同** | 测评依赖画像，无简历用户点过去只撞到另一道门禁；门禁旁路也只有「先去练习」一个出口，教程同样是免画像入口却没提 |

## 2. 修复方案

### 2.1 弹框会话语义（lib/resumePrompt.ts 重写）

- 标记从模块级变量迁到 **`sessionStorage`（`sc.resumePrompted`）**：刷新不复位，关标签页才清空——与「登录会话」体感一致。
- 存储不可用（隐私模式等）时静默放弃引导，宁可少弹不误弹。
- `ResumeGate` 加 `consumedRef` 守卫：StrictMode 双跑只消费一次，弹框在 dev 下恢复出现。

### 2.2 登出清理只认真实跳变（App.tsx）

原 effect `if (auth.me === null) resetResumePrompt()` 在**每次整页加载的启动首帧**都会触发（此时 me 尚未拉到，也是 null），把刚写好的会话标记清掉，问题 2 换了个形式复发。改为记录上一次的 me（`prevMeRef`），只在「已登录 → null」跳变时才 `resetResumePrompt()` / `dismissKeyRequired()`。

### 2.3 三处免简历引导出口

- **上传页**：新用户（无画像、非上传中、无错误）首屏加一行「暂时没有简历？在线练习和站内教程不需要简历，现在就能用」，内联链接直达 `/practice` `/learn`。
- **ResumeGate**：旁路从单链接扩成两个——「不需要画像？先去练习」+「或先看教程」。
- **成绩趋势空态**：主 CTA「开始测评」保留（有画像用户正确），下方加旁路行「还没上传简历？测评前需要先有画像：去上传简历 / 先去练习」，省掉一跳。

## 3. 验收（AC）

- AC-1 dev StrictMode 下，首次进入任一门禁页弹框出现一次；同会话内客户端切页、整页刷新均不再弹。
- AC-2 登出后标记重置：同标签页重新登录，回到原路由时弹框再出现一次。
- AC-3 上传页（无画像）显示免简历入口行；已有画像的老用户不显示。
- AC-4 门禁页有两个免画像出口（练习 / 教程）。
- AC-5 成绩趋势空态有上传与练习两个旁路出口。
- AC-6 `typecheck / lint / vitest / build` 全绿。

## 4. 改动清单

| 文件 | 改动 |
|---|---|
| `lib/resumePrompt.ts` | 会话标记迁 sessionStorage；存储不可用静默降级 |
| `components/ui/ResumeGate.tsx` | `consumedRef` 防双跑；旁路加「或先看教程」 |
| `App.tsx` | 登出清理只认「已登录 → null」跳变（`prevMeRef`） |
| `pages/UploadPage.tsx` | 新用户免简历入口行 |
| `pages/HistoryPage.tsx` | 空态旁路行 |
| `test/resumePrompt.test.ts` | 重写为 sessionStorage 语义：单次弹、刷新不重弹、登出重置、存储不可用降级 |

## 5. 验证记录

真后端 + 测试账号 Playwright 断言：

```
首访 /profile 弹框 = 1；同会话切 /exam = 0；整页刷新 /interview = 0
登出后标记 = null；重登瞬间（回到 /profile）弹框 = 1；再刷新 = 0
```

全量校验：`typecheck` ✓ · `lint` 0 warning ✓ · vitest 17 文件 / **198 条** ✓ · `build` ✓。
