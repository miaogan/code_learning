# r69 · 技术实现

## 实现路径

- 公共选择器 `.sc-filter-select, .sc-radar-select, .sc-form select` 统一盒模型、表面、箭头、字体、交互状态与 `appearance: none`。
- 公共类保留紧凑清单控件的桌面 32px 高度，与标准 40px 控件区分；≤640px 都提升到 44px / 16px。
- `SettingsPage` 的 JSON 模式 `<select>` 补 `.sc-filter-select`；配置保存、连接测试和密钥状态未改。
- `ExamPage` 只重排开局 idle 分支的展示结构；`filterDirection`、`filterSubDirection`、`filterDifficulty`、`filterCount`、`startExam()` 及组卷参数均不变。
- `tokens.css` 新增 `--select-icon-size`、`--select-chevron` 与既有引用所需的 `--lab-rule`。SVG 的颜色与 `--text-secondary` 同值，注释明确同步关系。
- 无新增依赖、运行时服务、数据结构和后端修改。

## 浏览器验收

使用隔离 Edge profile + CDP；`logs/teamflow/r69-form-polish/preview.mjs` 注入合成用户、画像、简历版本和一条雷达演示条目。所有 HTTP 读取均在页面内以演示响应处理，未使用真实账号、未触发 AI 调用。

最终脚本采用：

1. 等待页面 `readyState !== 'loading'`；
2. 调用应用自身的 `login` 状态入口（演示登录响应）；
3. 等待目标下拉挂载；
4. 读取实际 DOM、计算样式、布局宽度，并通过 CDP `Input.dispatchKeyEvent` 发送原生键盘事件；
5. 截取桌面 / 移动页面。

早期预览中模块加载时序、注入字符串的正则转义导致过登录页截图，已通过就绪等待、去除脚本内正则和浏览器异常监听修正；这些临时截图不作为验收证据。图片读取工具在当前模型不可用，故不声称人工看图；验收基于浏览器实际渲染、DOM 文本、计算样式与几何检查，并附可复核截图。

## 关键实测

- 笔试桌面：标准下拉 40px / 14px；未选方向时子方向禁用，箭头保留。
- 笔试 390px：四个下拉 148px × 44px / 16px，页面 scrollWidth = innerWidth = 390；操作按钮高 44px。
- 原生 ArrowDown：一级方向变为「前端」，子方向启用并显示该方向选项；`:focus-visible = true`，outline 为 `rgb(198,242,78) solid 2px`。
- 版本 390px：两条含长文件名下拉各 326px × 44px，页面无横滚。
- 先锋：采集方向为标准 40px；清单筛选为桌面 32px，移动均 44px；共用表面、边框与箭头。
- 设置：禁用态仍使用 `--bg-surface` 与三级文字，箭头不消失。实测 390px 高 44px、字号 16px；背景在 120ms 过渡中短暂读到 `rgb(15,18,22)`，等待 250ms 后为设计值 `rgb(11,13,16)`，不是选择器被覆盖。已删除重复的禁用背景声明。

## 工作区边界

`base.css` 在本需求开始前已有雷达样式修改，本需求仅在末尾 r69 段追加表单样式，未回退、未重写既有段落。工作区随后出现的 `practice.py`、`WrongBookList.tsx` 及相关测试改动亦不归本需求所有。最终前端测试数包含整个当前工作区，不将其拆分归功于 r69。

## 构建

r69 产品文件完成后，`npm run lint`、`npm run typecheck`、`npm test -- --run`（31 files / 415 tests）、`npm run build`（含 typecheck，166 modules）与 `git diff --check` 通过。构建保留 Vite 对单 JS chunk >500kB 的既有警告，不影响成功退出；未借本视觉需求改路由分包。

最后 JSX 缩进整理后 lint 仍通过；此时另一个并发需求正把 `types.ts` 的练习筛选改为数组，而 `PracticePage.tsx` 尚未同步，最新全工作区 typecheck 因此出现 13 个单值 → 数组错误，build 也在该前置检查停止。这些文件不属于 r69，未回退或擅自修补；415 项测试再次全过。

**2026-11-11 16:23 后续复核**：并发改动已同步，最新 `lint`、`typecheck`、31 files / 420 tests、`build`（167 modules）与 `git diff --check` 全部通过，外部阻塞解除。r69 产品文件和本任务夹已随 `9e4d596` 提交并推送，当前无本轮产品代码漏提交。工作区后续未提交的笔试多选筛选与 r70 样式不属于本需求；历史阻塞描述以 `ACCEPTANCE.md` 的提交后复核为最终状态。
