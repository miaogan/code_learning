# r40 · QA 报告（移动端可用性收口）

- 日期：2026-11-08
- 范围：`frontend/`（样式、两个组件的 JSX、入口 HTML）；后端零改动
- 结论：**四道前端门禁全绿**；窄屏可用性通过静态推导验收，真机项见 §4 待确认清单

## 1. 门禁结果

| 命令 | 结果 |
|---|---|
| `npm run typecheck` | 通过（`tsc -p tsconfig.json` + `tsc -p tsconfig.node.json`，exit 0） |
| `npm run lint` | 通过（`eslint . --max-warnings 0`，exit 0） |
| `npm test` | 通过：**18 个测试文件 / 205 个用例全绿**，4.41s |
| `npm run build` | 通过：vite 5.4.21，140 modules，`css 115.33 kB (gzip 16.94)`、`js 421.03 kB (gzip 169.41)`，1.93s |

后端未跑 `pytest`：本轮未触达 `backend/` 任何文件，按 AGENTS §4「后端无需改动则不必跑」执行。

## 2. 需求逐项对照

| 要求 | 结论 | 证据 |
|---|---|---|
| 断点：360–430 可用 | 通过。新增 ≤430 超窄档；≤1023 全局兜底；桌面 ≥1024 未动 | base.css r40 段（§1–§12） |
| 安全区与视口（safe-area / dvh / 吸底不压内容） | 通过。`viewport-fit=cover` 沿用 r21；吸底输入区 `--iq-scroll-pad` 172 vs 实际 160；新增锚点 `scroll-padding-top` | index.html、base.css §3/§5 |
| 键盘避让 | 通过（推导级）。`interactive-widget=resizes-content` + `Composer` 聚焦兜底；输入框 16px 沿用 r22 | index.html、Composer.tsx |
| 触控可用性（尺寸/滚动/溢出/误触） | 通过。主按钮/chip/技能标签 44；`overflow-x: clip` 不破坏 sticky；`overscroll-behavior-x: contain` 防横滑带动页面 | base.css §1/§4/§6 |
| 上传页 file input 可用性 | 通过。`accept=".pdf,.docx,.txt"`、单文件、`<input>` 触发系统选择器（既有实现正确）；文案改为触屏「点击选择文件」；CTA 独占行 | UploadPage.tsx、base.css §9/§11 |
| 报告/导出窄屏可读可点 | 通过。复制/导出按钮 44；长文本 `overflow-wrap: anywhere`；零散 `<pre>` 自横滑；导出逻辑（`api.reportMarkdown` + Blob + `<a download>`）未改 | base.css §2/§6、ReportPage.tsx（未改） |
| 深浅色 | 通过（按单主题设计）。系统浅色下仍强制深色；补 `html` 底色消除闪白；`theme-color` 对齐 `--bg-canvas` | index.html、base.css §0 |

## 3. 运行预览

```
后端：python -m uvicorn app.main:app --host 127.0.0.1 --port 8000   （backend/，/health = ok）
前端：npm run dev -- --host                                         （frontend/，http://localhost:5173）
```

- 桌面预览：`http://localhost:5173`，开发者工具切 390×844。
- 手机预览：与电脑同 Wi‑Fi，浏览器打开 `http://<电脑局域网 IP>:5173`。Vite 默认只听 localhost，
  必须带 `--host` 才能被手机访问；`/api` 由 Vite 代理（手机只跟 Vite 通信），后端不必暴露到局域网。
- `interactive-widget=resizes-content` 只在真机软键盘下生效，桌面模拟看不出来。

## 4. 待真机/视口确认（本轮未覆盖）

1. **软键盘实际避让**：Chromium/ArkWeb 走 viewport meta，iOS 走 `visualViewport` 遮挡判定，二者时序需真机各验一次
   （观察点：键盘弹出后作答框与「提交回答」按钮是否都在可视区内、最后一条气泡评分区能否滚出）。
2. **安全区实际像素**：刘海遮挡顶栏、手势条压住吸底输入区，需真机确认 `env()` 真的非 0。
3. **≤430 首列标签**：`"PRIMARY"` 在 11px / 0.04em 下按 49.3 ≤ 54 推导，需 360 截图确认无贴边/截断。
4. **画像 / 报告内容页**：本地无 AI Key 与真实简历，仅验证了空态与结构规则；有数据的长文本、
   表格、课程卡需在有数据的账号下补看一次。
5. **横向溢出**：`overflow-x: clip` 已兜住整页；若后续页面出现「元素被裁掉一角」，优先检查该模块自身
   的 `white-space: nowrap` / 固定宽，而不是关掉兜底。

## 5. 回归风险

- `--fs-nano` 抬到 11 会同时影响所有仪器标签（首页流程条、画像面板、报告指标）；已按最窄列（54px）核算，
  其他列均有富余。若真机上出现标签换行，回滚该 token 即可（不影响其他改动）。
- 44px 触控只作用于 ≤1023，桌面视觉零变化；`--btn-h` 未被修改，`--iq-composer-h` 链路未受影响。
