# r109 技术方案与走查记录

## 1. 验证方法（关键）

WorkBuddy 内置浏览器视口固定 **712px**，无法覆盖 ≤430 超窄档。采用
**Edge headless + CDP**（`Emulation.setDeviceMetricsOverride`）做精确视口截图与 DOM 量测：

- 起本地最新后端（含 `/api/leap-archive`）+ Vite dev server（:5173，代理 :8000）；
- 一次性建可视化账号 `visualcheck@example.com`（脚本 + Cookie 仅落 `logs/teamflow/r109-mobile/`，已 gitignore）；
- `cdp_shot_only.py <w> <h> <route> [scrollY]`：注入会话 Cookie、设设备视口、截图；
- `cdp_diagnose.py <w> <h> <route>`：输出 `scrollWidth / clientWidth`、溢出元素、小于 44px 的触控目标。

## 2. 走查结果（360 / 390 / 430）

| 页面 | scrollWidth vs clientWidth | 结论 |
|---|---|---|
| /leap | 相等（360/390/430） | 三块排版正常，无溢出/截断/重叠 |
| / /report /interview /exam /practice | 相等 | 无整页横向溢出 |

溢出元素全部来自 `.sc-topstepper`（`overflow-x:auto` 的横向滚动导航），属 r21/r22 既有设计，
非缺陷。报告页环形进度、分数、窄屏表格均可读。

## 3. 发现并修复的缺陷

**筛选 chip 触控高度只有 28px（应 ≥44px）**：

- 根因：r40 DESIGN §2 规定可点击 chip 在 ≤640 抬到 `--touch-min`(44)，规则选择器是
  `.sc-chip.is-clickable`；但 `ChipRow.tsx`（单选/多选筛选组）与 `PracticeFilters.tsx`（无命中建议）
  的可点击 `<button>` 只有 `sc-chip sc-iq-chip sc-qa-chip`，**漏了 `is-clickable`**。
- 影响：笔试页 / 练习页 / 学习页的方向、子方向、难度、语言筛选 chip 在手机上只有 28px 高，
  低于触控下限；桌面上 `.sc-iq-chip.is-clickable:hover` 的反馈也一并失效。
- 证据：`cdp_diagnose.py 390 844 exam` 修复前报 25 个小触控目标，其中 21 个是 28px 高的筛选 chip。

修复（语义补全，不是加特例）：给三处可点击 chip 补 `is-clickable`：

- `frontend/src/components/ui/ChipRow.tsx`（`ChipRow` / `MultiChipRow` 各一处）
- `frontend/src/components/practice/PracticeFilters.tsx`（无命中建议一处）

既有正确范例：`InterviewSetupForm.tsx` 的 chip 一直是 `sc-chip sc-iq-chip is-clickable`，证明这是漏加而非设计取舍。

修复后复测：筛选 chip 高度 **28 → 44px**，`smallTargets` 25 → 8（余下为顶栏紧凑元素与宽度略窄的短标签，
高度均已达 44）。桌面因 `.sc-chip.is-clickable` 只加 cursor/transition，零回归。

## 4. 未改动项及理由

- **太傅 FAB 遮挡**：`position:fixed` 右下角可拖拽（r77 设计），窄屏滚动时会压到右侧文字。
  但用户可拖走，且是全局既有交互，改尺寸/透明度会影响全站视觉，风险大于收益，保留。
- **顶部导航横滑无视觉提示**：`.sc-topstepper` 的 `overflow-x:auto` + 隐藏滚动条是 r21/r22 的
  全站约定，新增入口（含 r108「跃迁」）需横滑发现。属全站一致性问题，非本轮范围。
