# r136：镜试缺项补写按重要性排序

- 日期：2026-11-19
- 发起：用户反馈「这个补写能不能按重要性排序」
- 主题：修文页「镜试缺项补写」列表的**展示顺序**，纯前端确定性规则；契约、AI 输出、事实边界零改动。

## 1. 问题与口径

- r131 的缺项列表按「最近 10 张镜试复盘卡的首次出现顺序」展示。AI 生成 `missing_info` 时没有重要性字段，用户看到的是采集顺序，真正值得先补的项常被泛泛补充淹没。
- 「重要性」不能靠再问一次 AI（不稳定、要多扣额度、旧卡也无法回填）。本轮定义为**两个本地可解释信号**：
  1. **跨卡重复提及次数**：同一条缺项在多张复盘卡里出现，说明是跨题目的稳定短板（客观信号，权重最高加成）；
  2. **内容对简历竞争力的影响**：量化结果 > 业务影响 > 责任/落地 > 技术细节 > 泛泛补充。命中多档取最高档，避免关键词堆砌刷分。
- 只排序、不改写文本——「候选人亲口补充」的事实边界不能被规则动过；`toUserFacts()` 与后端反幻觉门禁照旧。

## 2. 实现

- `frontend/src/lib/mirrorFacts.ts`
  - `MirrorFactItem` 新增 `occurrences` / `score` / `importance`（high / medium / low），均为本地展示字段，不进 HTTP 契约。
  - `contentScore()`：量化 `40`（量化+业务影响 `46`）、业务影响 `34`、责任/落地 `26`、技术细节 `18`、泛泛补充 `4`、其他 `10`；重复提及每条 `+12`，上限 `+36`。
  - `rankMissingFactsByImportance()`：按 `score → occurrences → 首次出现顺序` 排序；分数相同保持原稳定次序。
- `frontend/src/pages/PolishPage.tsx`：`missingItems` 改为 `rankMissingFactsByImportance(collectMissingFacts(...))`；面板说明补「已按重要性排序（多次提及、量化指标优先）」。
- 深链自动展开（`state.mirrorMissing`）仍按文本 `find`，排序不影响；无新 CSS、无新错误码、无后端改动。

## 3. 验证

- `mirrorFacts.test.ts` 从 4 例扩到 9 例：量化优先、泛泛措辞与量化同时出现按高档、跨卡重复提升顺序且文本不变、同分稳定、high/medium/low 档位、既有去重/空数组回归。
- 前端 typecheck / lint / build 全绿；全量 vitest 47 files / 585 tests passed（本机仍有已知 EPERM 临时目录噪音，非断言失败，CI 为准）。
- 后端工程门禁（含裸色值 / 样式 append-only）41/41 绿；本轮未碰样式与后端代码。
