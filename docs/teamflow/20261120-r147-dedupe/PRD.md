# r147 全站重复功能盘点与去重（第一轮）

## 背景

用户：「继续做吧 优化一下页面上的重复功能」→ 确认范围为**全站盘点**：先出一览表再逐个合并。

方法：只读探查代理逐页提取 24 个页面 + 关键子组件的**用户可见操作入口**与跨页链接，
与项目史（r41/r63/r132/r144/r146 等深链与分层设计）交叉判断，把 20 条候选分成三档：
**已经是好的复用**（不动）、**A 档本轮合并**（代码级逐字重复或本轮引入的重复）、
**B 档挂账**（刻意分层 / 信息架构常态 / 风险大于收益）。

## 结论一览

### 已经是好的复用（核实后不算重复）

| 候选 | 现状 |
|---|---|
| ResumeGate 门禁六处 | 同一组件复用，只换文案——正确形态 |
| RoleFitCard 三处（报告/JD/跃迁） | 组件复用；「带配置去召对」同走 `/interview?focus=` 一条通道（r132） |
| PhaseLoader 秒数分档「各页手写」 | 实际是统一组件 19 处复用，各页只是传不同 phases 配置（耗时段位本就不同） |
| 「去练习 / 去医案 / 去上传」等跨页跳转多入口 | 信息架构常态：每页在用户当下语境给出口，r132 明确设计深链；不是重复功能 |
| 成绩数据多视图（报告仪表条/战绩趋势/卷宗汇总/校勘对比） | 四页定位不同（当场结果 / 时间趋势 / 跨模块汇总 / 版本差值），刻意分层 |
| 薄弱方向多形态（WeaknessMap/错题本/卷宗卡04/Eval 失败分类） | 数据源各不相同，形态相近但语义不同 |
| 计划三视图（首页 TodayPlan / 报告 WeekPlan / 卷宗卡06） | r41 设计：打卡只在报告页，首页只读今天、卷宗只读进度读数——场景不重叠 |

### A 档 · 本轮合并（4 项）

| # | 重复 | 证据 | 合并方式 |
|---|---|---|---|
| A1 | Blob 下载三处逐字重复 | ReportPage.tsx:244-251 / ArchivePage.tsx:170-177 / PolishPage.tsx:398-405（同一段 createObjectURL→a→click→revoke） | 新增 `lib/exportFile.ts` 的 `downloadTextFile(text, filename)` |
| A2 | 剪贴板复制四处各自实现 | ReportPage.tsx:261-281 / ArchivePage.tsx:180-190 / PolishPage（经 exportFile）/ TaifuLauncher.tsx:513-514；toast 文案各异 | 同文件 `copyPlainText(text)`（能力判断 + `CLIPBOARD_UNAVAILABLE` 中文错误）；**页面 toast 文案保持现状**（成功文案是产品口径，不借机改） |
| A3 | 离开保护四页逐字重复 | ExamPage:208-238 / PolishPage:243-… / PracticePage:207-237 / UploadPage:222-… 的 effect 主体完全一致，`confirmLeave` 三处一致（Upload 多一个 abort 前置） | 新增 `lib/useLeaveGuard.ts`：`useLeaveGuard(active, onLeave?)` 返回 `{ pendingLeave, confirmLeave, cancelLeave }`；**ConfirmModal 留在各页**（文案是产品口径，四页各不相同） |
| A4 | 先锋页四档计数显示两遍（r146 引入） | 筛选条结论 chips（`必学 1`，可点）紧挨清单头常态计数（`共 4 项 · 必学 1 · 选学 2 …`，纯文本）——相邻两行同一信息 | `listCountText` 常态分支只留 `共 N 项`，四档计数由可点的 chips 独占；搜索态/筛选态不变 |

顺带（同属先锋页一致性）：周报卡方向点击是**覆盖式单选**（会悄悄清掉用户已勾的多选），
改为与筛选条 chips 一致的 toggle（`toggleDirectionFilter`：已选则回「全部」，未选则追加）。

### B 档 · 挂账不动（写明理由）

| 候选 | 不动理由 |
|---|---|
| 「继续学习 / 去学习 / 学堂补课 / 再来一轮 / 重新生成」等文案不统一 | 多入口本身合理，文案统一是纯视觉工作且跨 8+ 页面；单独一轮做，避免与结构性改动混批 |
| 草稿保存/恢复三处（examDraft / interviewDraft / uploadSession） | 三者数据结构、恢复时机、失效窗口各不相同，强行抽象会造出带开关的大 hook，收益小于复杂度 |
| 「列表 + 回看 + 删除」模式四处 | 数据源与行形态差异大（场次/复盘/任务/成绩），组件已各自适配 |
| 「重新生成」按钮四处 | 语义各不同（报告/学习建议/成稿/复盘），且都已有防重复扣费的确认或缓存 |
| 「先去练习」空态出口多处 | 信息架构常态（同 A 档结论），保留 |

## 改动清单

- 新增 `frontend/src/lib/exportFile.ts`（`downloadTextFile` / `copyPlainText`）
- 新增 `frontend/src/lib/useLeaveGuard.ts`
- 改 `frontend/src/lib/radar.ts`（`listCountText` 常态分支、新增 `toggleDirectionFilter`）
- 改 `frontend/src/pages/PioneerPage.tsx`（周报卡方向点击接 toggle）
- 改 `frontend/src/pages/ReportPage.tsx` / `ArchivePage.tsx` / `PolishPage.tsx` / `frontend/src/components/taifu/TaifuLauncher.tsx`（换公共工具）
- 改 `frontend/src/pages/ExamPage.tsx` / `PracticePage.tsx` / `UploadPage.tsx` / `PolishPage.tsx`（换 hook，Modal 保留）
- 测试：`frontend/src/test/radar.test.ts` 更新 `listCountText` 常态分支断言 + 新增 `toggleDirectionFilter` 用例；`exportFile.test.ts`（文件名/错误分支可测部分）

## 验证

见 AGENTS.md r147 条目（本轮收尾时回填）。
