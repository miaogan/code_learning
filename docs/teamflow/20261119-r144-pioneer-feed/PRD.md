# r144：先锋页信息流重构（参考 aihot.news/all）

- 日期：2026-11-19
- 发起：用户要求「参考 aihot.news/all 页面重构 先锋模块」。
- 定性：**纯前端信息架构改造**。采集 / 评估 / 筛选契约与后端零改动，只把「表格式的技术清单」
  重构为 aihot 式的「日期分组 + 编号时间线 + 紧凑信息卡」动态流。

## 1. 参考对象拆解（aihot.news/all）

从 aihot 抓取的结构与交互里借鉴四点，都映射到先锋已有的数据字段：

| aihot 的做法 | 先锋的对应 |
| --- | --- |
| 按日期分组的动态流（`今天 11月19日 周四 · 221 条`） | 按 `assessed_at` 本地日分组，组头 `今天 · 11月19日 周四 · N 条` |
| 编号时间线 rail（序号 + 圆点 + 贯穿竖线，跨分组连续） | 页内跨日期分组连续编号 1..N，rail 同款 |
| 卡片 meta 行（时间 · 来源 · AI 评分）+ 大标题 + 摘要 + `#标签` | meta 行 = 结论徽章 + `HH:MM · 来源` + star/7 日增量；标题单独一行（20px）；标签行 `#方向` `#子方向` `#规则评估` `#疑似刷 star` |
| 顶部「搜索标题和摘要」 | 新增当前页过滤输入（多词 AND，命中标题 / 中英摘要 / 方向 / 来源） |

**刻意不抄**的部分：aihot 的「精选 / 热点 / 日报」多页签与 AI 评分数字。先锋的结论本来就是
四档规则评估（必学 / 选学 / 观望 / 跳过），再加一个人造分数是重复信息；页签维度由既有的
结论 / 方向多选筛选承担。

## 2. 改动

### 2.1 纯函数层（`lib/radar.ts`）

- `assessedTimeText(iso)`：本地时区 `HH:MM`，坏值返回空串（不猜时间）。
- `groupTechsByDay(items, now)`：按 `assessed_at` 本地日分组。**只合并相邻同日条目、不重排**
  （后端本就按评估时间倒序）；assessed_at 缺失 / 坏值落「时间未记录」组，不丢条目。
- `techTagList(item)`：方向 / 子方向（trim 后非空才出）+ `规则评估` / `疑似刷 star` 状态标签。
- `matchesTechQuery(item, raw)`：多词 AND 当前页过滤。**必须诚实标注「当前页」**：
  服务端分页是权威口径，前端不假装能全库搜索。

### 2.2 页面结构（`PioneerPage.tsx`）

- 清单由 `<ul className="sc-radar-list">` 改为 `.sc-radar-feed` → `.sc-radar-day`（组头）→
  `.sc-radar-timeline`（ol）→ `.sc-radar-slot`。
- `TechRow` 重写：rail（序号 / 圆点 / 竖线）+ slotcard（meta 行 / 标题 / 摘要两行 / 标签行 /
  展开详情）。「生成样例」按钮从右侧独立列移到 meta 行右端（aihot 的操作位），
  展开详情按钮收进标签行尾。行为全部保留：展开状态按 slug 记忆、国子监深链定位 / 高亮、
  外链 `safeRepoUrl` 放行、结论徽章配色不变。
- 清单卡内新增搜索行：输入 + 「清空」按钮；搜索时计数变 `本页 N / 共 M 项`，并给一句
  「只过滤当前已取回的 N 条」的 hint；0 命中给专用空态。
- 页头副标题同步为「动态流」口径。

### 2.3 样式（`base.css` append-only）

新增 `sc-radar-searchrow / searchinput / feed / day / dayhead / daylabel / daycount /
timeline / slot / rail / rank / node / slotcard / slotmeta / slotsrc / slotstars / slotact /
slothead / tagrow / tag`。设计规则：

- rail 竖线用 `::after` flex 撑满 + 末项隐藏，不引入绝对定位坐标；
- 圆点 hover 放大（aihot 同款微交互），命中高亮沿用 `--accent-tint`；
- 窄屏（≤640）隐藏序号列、保留圆点，卡片 padding 收窄；
- 全部走既有 token（fs-section / fs-meta / radius-pill / border-subtle 等），无裸色值。

旧 `.sc-radar-techrow` 系列按基线 append-only 保留（国子监等其他页面仍在引用部分类名）。

## 3. 未改动

- 后端路由 / store / 仓储、筛选参数、分页口径、采集与手工录入、生成样例链路全部零改动。
- 不新增全库搜索端点（那是契约变更，本轮以「当前页过滤」起步，够用且诚实）。

## 4. 验证

- `radar.test.ts` 18 → 23 例：时间格式化 / 分组（含今天前缀、坏值兜底）/ 标签行 / 多词 AND 过滤。
- 全量 vitest 49 files / 621 tests passed；typecheck / lint / build 全绿。
- Playwright mock（`backend/logs/tmp-r144/verify_pioneer_ui.py`）实测：
  - 两个日期分组，第一组 `今天 · 11月19日 周四`；序号跨组连续 1..8；
  - 标签 `#AI 工程 / #部署与推理 / #规则评估 / #疑似刷 star` 正确出现；
  - 搜索 `vllm` / `本地` 各命中 1 条、计数变 `本页 1 / 共 8 项`、无命中走专用空态、清空恢复 8 条；
  - 展开详情可用；390px 窄屏序号隐藏、横向溢出 0。
  - 截图 `frontend/logs/tmp-r144/pioneer-feed.png` / `pioneer-feed-mobile.png`。

## 5. 已知边界

- 搜索只作用于当前页（placeholder 与 hint 已明说）；要全库搜索需后端加 query 参数，另行立项。
- 分组按用户当前时区折算（浏览器本地时区），不回放历史 DST。
