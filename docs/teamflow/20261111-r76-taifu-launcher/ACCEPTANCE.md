# r76 · 验收报告：太傅悬浮入口

> 结论：PRD 中 13 条验收标准全部满足。纯前端改动，未改后端、HTTP 契约、`api/types.ts` 与既有页面逻辑；新增 3 个 token、9 条单测、1 套真实浏览器脚本。尚未提交 / 推送。

## 1. 交付内容

| 文件 | 改动 |
| --- | --- |
| `frontend/src/lib/taifuPosition.ts` | 新增（167 行）：位置常量、四边夹紧、默认右下、浮窗布局（上下翻转 / 缩高）、按账号读写位置 |
| `frontend/src/components/taifu/TaifuLauncher.tsx` | 新增（346 行）：方印、Pointer Events 拖拽、点击展开浮窗、键盘微调、Esc / 外部点击 / 路由变化收起 |
| `frontend/src/App.tsx` | +4 行：登录后挂载 `<TaifuLauncher userId={me.id} />`，在 `Routes` 与 `ToolNav` 之外 |
| `frontend/src/styles/tokens.css` | +9 行：`--taifu-panel-w` / `--taifu-panel-h` / `--font-serif` |
| `frontend/src/styles/base.css` | +323 行（append-only）：`.sc-taifu-fab` 方印与 `.sc-taifu-panel` 浮窗全套，含 ≤640px 底部面板与 `prefers-reduced-motion` |
| `frontend/src/test/taifuPosition.test.ts` | 新增 9 条位置与存储用例 |

## 2. 验收标准

| AC | 结果 | 证据 |
| --- | --- | --- |
| AC-1 默认位置 | 通过 | 1440×900 下印章 56×56、`left=1360`（右 24）、`top=756`（底 88）、文案「傅」、`z-index=15` |
| AC-2 可拖拽不误触 | 通过 | 真实指针序列拖到 (400,300) 生效；单测覆盖拖拽起点取 `getBoundingClientRect()`；5px 阈值与 `suppressClickRef` 在实现层拦截「拖完自动展开」 |
| AC-3 拖出即夹紧 | 通过 | 拖向四个边角后 `x ∈ [8, 视口宽-64]`、`y ∈ [8, 视口高-64]`；800→640 缩窗后夹回 `right=632 / bottom=592`；单测覆盖视口小于印章的退化情形 |
| AC-4 位置记忆 | 通过 | 拖动后 localStorage 为 `{version:1,x:400,y:300}`；刷新后恢复到 (500,200)；单测覆盖按账号隔离、越界重夹、损坏 JSON、旧版本、非法数值、写盘失败、匿名不读写 |
| AC-5 键盘可用 | 通过 | 聚焦后 →/↓ 各移 8px，Home 回右下；`title` 与 `aria-label` 告知可拖可调 |
| AC-6 浮窗不压印章 | 通过 | 默认位展开时 `panel.top >= fab.bottom + 12`；单测另验「上下都放不下 600 时缩高」（期望 `height=524 / top=368`，印章在 756 不被覆盖） |
| AC-7 窄屏底部面板 | 通过 | 390×844 下 `left=12 / right=378 / bottom=832`、`documentElement.scrollWidth === clientWidth`（无横滚）；打开时印章 `opacity=0`，关闭后回 `1` |
| AC-8 层级正确 | 通过 | 印章 `z-index=15`；设计上低于 Toast 20 / Modal 40，Toast 弹出时覆盖印章位置 |
| AC-9 收起路径 | 通过 | Esc、外部 pointerdown、路由变化三条路径均收起；Esc 后 `document.activeElement` 回到印章 |
| AC-10 窗口变化自适应 | 通过 | `resize` 与 `visualViewport.resize` 双监听，缩窗后位置自动夹紧（见 AC-3 证据） |
| AC-11 不伪造能力 | 通过 | 面板含「入口预览」徽标；输入框 `disabled` 且 `placeholder="问答接口接入中"`；脚注写明「只读站内记录，不替你修改画像或自动投递」 |
| AC-12 不进导航 | 通过 | 无新增路由、`ToolNav` 未改；未登录不渲染（组件在 `me` 就绪后挂载） |
| AC-13 不回归 | 通过 | typecheck / lint 0 warning / 35 文件 457 测试 / build 全过 |

## 3. 验证命令与结果

```text
npm run typecheck  → passed（tsconfig.json + tsconfig.node.json 双配置）
npm run lint       → passed，--max-warnings 0
npm test -- --no-file-parallelism
                   → 35 test files / 457 tests passed
npm run build      → passed，174 modules
                     dist/assets/index-*.js  576.34 kB（gzip 235.19 kB）
                     仅既有「>500kB chunk」提示，非本轮引入
```

真实 Chromium（CDP 驱动，`logs/teamflow/r76-taifu-launcher/scripts/check.cjs`，gitignored）：

```text
PASS 默认右下 56px 方印，避开 Toast
PASS 拖拽夹紧并写入账号位置
PASS 桌面浮窗位于印章下方且不重叠
PASS 归位回右下
PASS 方向键微调与 Home 归位
PASS 刷新后恢复账号位置
PASS 窗口缩小后自动夹回视口
PASS 390px 底部面板、无横向滚动、开合印章正确收起
RESULT: PASS
```

脚本复用 r75 的 `check-support.cjs`（新标签页 + `Fetch.enable` 合成 `/api/*` 响应），因此**未改后端、不依赖真实 Key** 也能进入登录态页面。

## 4. 验收中发现并修复的问题

1. **浮窗盖住印章**：初版在「上下都放不下 600」时直接贴 `EDGE` 算 `top`，印章被浮窗整个盖住，点不回去。改为「按空间大的一侧缩高」，并补单测锁定（`height=524 / top=368`）。
2. **移动端印章残边**：底部面板铺满宽度后，印章从面板右缘露出一条边（截图确认）。新增 `.sc-taifu-fab.is-open { opacity: 0; pointer-events: none }`（仅 ≤640px），并在脚本里加开合透明度断言。
3. **两处裸尺寸**：`inset: 3px` 与 contextdot `6px` 违反「禁止裸尺寸」约定，改为 `var(--sp-1)`。
4. **CDP 脚本自身两处错误**：`newTarget()` 返回 `{ target, close }` 被整体当 target 用（`TypeError: Invalid URL`）；`urlPattern: '*api/*'` 误把 `src/api/client.ts` 也拦成 404 导致白屏。分别改为解构取用与 `http://127.0.0.1:5173/api/*`。
5. **断言写错而非实现错**：`/问答接口接入中/` 匹配 `innerText` 失败——`placeholder` 不进 `innerText`，改断言 `placeholder` 属性值 + `disabled === true`。

## 5. 已知限制

- 问答能力未接入：面板是「入口预览」，点击发送无任何行为（按钮 `disabled`）。
- iOS Safari 触屏长按拖动未真机验证（DevTools 触屏模拟通过）。
- 浮窗无「展开成大窗」中间态；长对话只能内部滚动。
- 多标签页同时拖动位置会互相覆盖。

## 6. 下一需求建议（不在本轮范围）

接入问答时按此顺序落地，避免一次做太大：

1. 后端只读工具层（画像摘要 / 最近测评 / 错题分布 / 学习进度 / 报告短板），一切回答必须带站内引用；
2. 复用 r65 的引用白名单：href 不在材料集合即丢弃并计数，空结果给中文说明而不 500；
3. 对话历史按 `user_id` 落库（新增表，沿用 r30/r42 的任务表范式）；
4. 收起态零请求、零轮询；发送走 `user_ai` 的 `light` 档并复用每日配额。
