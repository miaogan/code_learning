# r135：修文页下拉框与补写按钮样式修复

- 日期：2026-11-19
- 发起：用户反馈「修文页面的下拉框用了浏览器原生样式，而且补写按钮有自动换行」。
- 主题：**把 r131 新增的补写面板接回全站统一样式口径**，纯前端样式/组件修复，契约与数据流零改动。

## 1. 问题定位

- r131 的「镜试缺项补写」面板里，归属部分下拉直接写了原生 `<select className="sc-polish-fact-select">`。全站 r69 已统一用 `components/ui/Select.tsx`：桌面自绘弹层（跟随深色主题）、≤640px / 触屏回退原生系统选择器（系统弹层体验更好）。这个手写 select 绕过了统一口径，在 Windows Chromium 上露出浅色原生弹层。
- 补写行的按钮（「补写 / 收起」与「添加到本次润色」）在窄栏里会被长缺项文字挤到换行：`.sc-btn` 全局没有 `white-space: nowrap`，flex 容器里也没有 `flex-shrink: 0`。

## 2. 改动

- `pages/PolishPage.tsx`：原生 `<select>` 换成 `<Select variant="compact">`，选项与 `onChange` 语义照旧（空串 → `null`，其余转 `PolishSection`）；`ariaLabel="补写内容归属部分"`；compact 高 32px，与旁边 `size="sm"` 按钮对齐。
- `styles/base.css`：append 两条局部规则——
  - `.sc-polish-fact-row .sc-polish-fact-text { min-width: 0; }`：长文本自己收缩换行；
  - `.sc-polish-fact-row .sc-btn, .sc-polish-fact-formrow .sc-btn { flex: 0 0 auto; white-space: nowrap; }`：按钮不再被压成两行。
- 旧的 `.sc-polish-fact-select` 规则保留但不再被引用（样式基线 append-only，不删既有声明）。

## 3. 验证

- 前端 typecheck / lint / build 全绿；vitest 全量通过（本机偶发 EPERM 临时目录噪音，重跑 577 passed；CI 为准）。
- Playwright 无头 Chromium + 路由 mock（900px 窄栏）实测：补写面板内原生 `select` 数 0、自绘触发按钮 1 个且文案正确；「收起」与「添加到本次润色」两个按钮的 `white-space=nowrap`、`flex-shrink=0`，按钮与下拉高度同为 32px。
- 后端工程门禁（含裸色值 / 样式 append-only）41/41 绿；无契约、无后端逻辑改动。
