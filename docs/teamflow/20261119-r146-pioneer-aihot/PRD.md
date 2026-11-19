# r146 先锋借鉴 aihot.news：让清单「可扫读、可决策、可沉淀」

## 背景

用户在先锋页（r144 重构后已采用 aihot 式时间流）问：

> 正常了 看看那个网站有没有别的功能值得借鉴的

抓取 aihot.news 的 `/all`、`/hot`、`/daily`、`/leaderboard`、`/more`、`/items/:id`、
`/feed.xml` 后整理出 9 项候选（价值/成本象限图已当面对齐），用户选了四项：

| 选项 | 借鉴点 | 对应 aihot |
|---|---|---|
| A+B+C 打包 | 分面计数 / 折叠态依据 / 「怎么评的」面板 | 热度数值直给、榜单可扫读 |
| D | star 走势线 | 热点热度趋势 |
| E | 先锋周报卡（近 7 天速览） | 日报头部统计行 |
| G | 学习清单（收藏） | 收藏/稍后读 |

刻意不抄的：登录/同步、RSS 全文输出、排行榜名次页、逐条详情页（详情已在「展开详情」里）、
多语言切换（数据入库时已翻译，r144 落的口径）。

## 四批改动

### 第一批 `4c363fd` — 让「凭什么」可见

- **分面计数**：`GET /api/radar/techs` 新增 `counts`（四档结论计数）。刻意的口径：
  `counts` 只受**方向**筛选影响、不受**结论**筛选影响——否则点开「必学」后其余三档全变 0，
  用户会以为别的档空了。仓储层 `radar_tech_verdict_counts()` 不引用服务层闭集，闭集补零在
  路由层按 `rules.VERDICTS` 做。
- **三种计数口径分开**（`listCountText` 纯函数）：
  搜索态 `本页 x / 共 y 项`；筛选态 `共 x 项 / 全部 y`；常态 `共 y 项 · 必学 a · 选学 b · 观望 c · 跳过 d`。
- **折叠态依据**：每行常显 `依据` 一行，取 `reasons[0]`——`rules.rule_assess` 的 reasons 顺序
  固定为 相关度 → 采用度 → 成熟度 → 成本，首条恰是四档结论真正的判定依据。
- **「怎么评的」面板**：默认收起（一次性的心智建设不长期占屏），逐条对照 `rules.py` 真实阈值
  （必学 = 相关度 ≥4 且采用度 ≥3 等），附「疑似刷 star 降一档」说明。

### 第二批 `01ec971` — star 走势线

- 新增 `GET /api/radar/trends?slugs=a,b,c`：`radar_tech_trends()` 逐 slug 尾部查询再
  `reversed`，没快照的 slug 不出现在返回里；一次最多 100 项。
- 前端整页一把拉（一页 ≤100 条），失败静默——走势线是附加信息，不能挡清单。
- `sparklinePoints()` 纯函数：少于 2 点返回空串（不渲染）；值越大 y 越小（SVG 纵轴向下）；
  全程同值画中线（防除零）；坐标保留 1 位小数。渲染在 meta 行 star 数字旁，尾点点亮。

### 第三批 `d55cc55` — 先锋周报卡

- 新增 `GET /api/radar/weekly`：`radar_weekly_summary()` 四条 SQL
  （近 7 天新增 / 上一周期新增 / 采集轮数 / 新增条目的方向 Top5）。
- **滚动 7 天窗口而非自然周**：跨周聚合对单人仓库更稳；上一周期 = 同长的前一窗。
  时间窗在服务层算 ISO 串边界（`_now()` 全站同格式、字典序可比），仓储层只收字符串。
- `weeklyText()` 覆盖 多/少/持平/零 四个分支；方向分布是**可点的筛选入口**
  （点「AI 工程 7」= 按该方向筛清单）。

### 第四批 — 学习清单（本批）

- **后端**：新表 `radar_watchlist(id, user_id, tech_slug, created_at)` +
  `UNIQUE (user_id, tech_slug)` 让重复收藏幂等（`added=false` 表示原本已收藏）；
  删除是硬删（清单不是历史，不留痕）。路由：`GET /watchlist`、`POST /watchlist/add`、
  `POST /watchlist/remove`（slug 形如 `github:owner/repo` 带斜杠，走 POST + 请求体
  而不是 DELETE 路径参数，免踩路径转义）、`GET /techs?watchlist=true`。
  `watchlist_only` 挂进 `_radar_tech_where()`，与方向/结论筛选同一套 where——不造第二套口径。
  `counts` 同样透传 `watchlist_only`：只看清单时分面计数也按清单收窄。
- **前端**：每行「加入清单 / 已在清单」按钮（本地乐观渲染 + 失败回滚，失败只弹 toast）；
  筛选条右侧「只看清单」开关（带收藏数徽标）；清单为空的专属空态。
- **顺带修的真 bug**：
  1. `techs.items.length > 0 || filtering` 漏了 `watchOnly`——清单为空时切「只看清单」，
     整块清单卡（含开关本身）不渲染，用户关不回去。
  2. **同名按钮歧义**：手工录入的提交按钮原本也叫「加入清单」，与收藏撞名（页面上两个
     「加入清单」含义完全不同）→ 手工录入改「录入技术清单」，toast 同步。
  3. 空态提示原文「在下面的条目上点『加入清单』」——清单视图下面根本没有条目，改为
     「关掉『只看清单』，在条目上点『加入清单』」。

## 测试

后端（`tests/test_r67_radar.py`，32 passed）：

| 用例 | 钉住的口径 |
|---|---|
| `test_techs_api_counts_are_facet_not_page` | counts 是分面不是分页数 |
| `test_trends_api_returns_snapshot_series` | 走势序列时间正序、无快照不出现 |
| `test_weekly_summary_counts_new_techs_and_rounds` | 滚动窗口与环比 |
| `test_watchlist_roundtrip_and_filter` | 收藏幂等、清单筛选、移出恢复 |

前端（`src/test/radar.test.ts`，31 例）：

- 分面计数与折叠态依据（4 例）：`verdictCountText` 补零、`verdictChipLabel`、`listCountText`
  三态、`whyText` 首条。
- 走势线坐标串（2 例）：升序/降序点位、少于 2 点返回空串。
- 周报卡文案（2 例）：多/少/持平/零。

走查（`frontend/logs/tmp-r146/verify_pioneer_counts.py`，Playwright 全 mock）：
chip 计数、清单三态计数、走势线渲染数（≥2 点才画）、说明面板开合、周报卡与方向筛选、
窄屏横向溢出 0；学习清单段：加入 → 按钮变「已在清单」+ 开关计数 →「只看清单」收窄且
请求带 `watchlist=true` → 移出后空态提示出现且**开关仍在** → 关回全量恢复。

## 验证

- 前端：`tsc --noEmit` 0 错；`eslint --max-warnings 0` 过；vitest 46 files / 527 passed
  （3 errors 为本机 fs shim EPERM 噪音，与 r142/r144 同源，以 CI 为准）；
  `npm run build` 成功（215.21 kB CSS / 907.98 kB JS）。
- 后端：雷达专项 32 passed；`ruff check app tests` 全过；全量 pytest 结果见 AGENTS.md r146 条目。
- 生产 CI：见 AGENTS.md r146 条目（push dev 后复核）。

## 已知边界

- 走势线只在当前页内批量拉，翻页不预取；快照数量取决于采集轮数（新库前几轮只有 1 点，不渲染）。
- 周报卡的方向分布最多 5 条（Top5），点击叠加到方向筛选（单选覆盖）。
- 学习清单按账号隔离（带 `user_id`），共享账号场景下所有人共用一份——与 radar_jobs 同口径。
