# r19 · 笔试熟练过滤文案说明（技术变更单）

> 本轮只做 r6 验收遗留的三条 P3 工艺观察，且限定在**文案层**：不新增契约字段、不改组卷/判分逻辑、
> 不新增 CSS 类与 token。三条改动合计 3 个文件（1 个纯函数文案单源 + 1 个页面 + 1 个测试文件）。

## 1 背景与范围

来源（历史任务夹不可改，原文只读）：

- r6 `ACCEPTANCE.md` §6 / §7.3：D-9 优先级最高（L2 兜底回流时只报「已过滤 N 道」，没提「另有若干道被重新纳入」），
  D-7 次之（过滤信息行只给事实、无「为什么被过滤 / 怎样才能让题回流」的说明），D-8 最后（提交后结果面板不复显本卷过滤事实）。
- r6 `QA-REPORT.md:91-93`：三条均为透明度/可理解性观察，**`filtered_count` 的语义本身正确**，不涉及正确性缺陷。
- r6 `DESIGN.md:67,72,73`（本轮必须遵守的三条硬约束，见 §5.1）：
  - 过滤事实不许塞进 hover tooltip（`67`);
  - 提交后的结果面板不许重复同一条（`72`）；
  - `stage`（L1–L6）不许暴露到界面（`73`）。

本轮**不含**（按用户口径留在待办）：

- r8 ①：9 题卷追问额度 3→4（涉及预算与额度断言，需另立需求）。
- r5 O-4：`--max-warnings 28` 未在 r5 技术方案改动面声明（流程留痕，不动代码）。
- r3 P3②：DESIGN 摘要条 48 高按 border-box 回写（历史夹不可改）。
- memory 第 45 行 QA round-2 三条 P3。

## 2 改动面

| 文件 | 改动 | 行为影响 |
| --- | --- | --- |
| `frontend/src/lib/examNotice.ts` | 抽出共用正数判定 `isPositiveCount()`；新增 `proficiencyRuleHint()` 规则说明纯函数；`filteredNotice()` 输出逐字不变 | 多一处文案出口，零副作用 |
| `frontend/src/pages/ExamPage.tsx` | 作答/判分态信息行追加 `· {noticeHint}`；提交态在 `ExamResultPanel` 后复显一条过滤事实行 | 多两处文案节点；状态机、提交链路零改动 |
| `frontend/src/test/examNotice.test.ts` | 新增 3 条 `proficiencyRuleHint` 断言（正数逐字 / 静默口径 / 不含数字） | vitest 133 → 136 passed |
| `docs/teamflow/20261102-r19-exam-notice-clarity/**` | 新增本任务夹 | — |
| `docs/teamflow/memory.md` | r6 三条 P3 待办收口 | — |

契约（`backend/app/schemas.py` / `frontend/src/api/types.ts`）、后端代码、seed、依赖、CSS token：**零改动**。

## 3 方案

### 3.1 D-7：过滤信息行补「为什么被过滤 / 怎样回流」

不做 tooltip（DESIGN §0.6 第 1 条明确禁止把过滤事实塞进 hover / 折叠区 /「详情」入口）。改为在**既有** `.sc-meta-line`
（`display:flex; flex-wrap:wrap`）内追加一段常驻规则说明，零新增 CSS 类：

```
[熟练过滤] 本次已过滤 N 道你已熟练掌握的题 · 近期多次答对的题会暂时跳过，不再算作熟练后自动回流；个别熟练题可能因卷面结构重新出现
```

- 规则说明走 `lib/examNotice.ts` 的 `proficiencyRuleHint()`，与 `filteredNotice()` **共用同一静默开关**
  （`isPositiveCount()`：`N <= 0` / `null` / `undefined` / `NaN` / `±Infinity` 一律 `null` → 不挂载节点）。
  理由：L6 全库兜底时没有过滤事实，凭空解释一条不存在的事实会误导用户。
- 390px 下整段会换行（`flex-wrap:wrap` 已保证不溢出），属可接受的「信息行变两行」，不影响卷面主体。

### 3.2 D-8：提交后复显本卷过滤事实

提交态页面仍持有 `run`（`submitExam()` 只 `setResult(graded); setStage('submitted')`，不清 `run`），
因此直接复用 `run.filtered_count`，**无需契约变更**（`ExamResult` 不加字段）。

放置位置：`ExamResultPanel` 之后、逐题复核卡之前，渲染一条 `.sc-meta-line`（`Chip[熟练过滤]` + 原句）。
只复显事实，**不回放规则说明**：提交后页面焦点应是 40px 总分与逐题复核，长句说明会抢走焦点。

### 3.3 D-9：L2 兜底回流时的「另有 N 道」提示

前端拿不到 `backfill`（`ExamRun` 响应只暴露 `filtered_count`，`stage`/`backfill` 只落 `runs.payload`）。
两条候选：

1. 扩契约暴露 `reintroduced_count`（或 `stage`）→ **否决**：DESIGN §0.6 明确禁止把 `stage`（L1–L6）暴露到界面
   （层号用户读不懂、兜底看起来像缺陷），且为一个文案需求扩契约不划算。
2. 纯文案口径：在规则说明里给出「个别熟练题可能因卷面结构重新出现」这句**归因级**说明 → **采纳**。
   它回答「为什么卷面里还有熟练题」，但不写具体回流数字（前端没有该数字，硬编造就是假话）。

### 3.4 阈值不落在前端

文案只描述规则方向（「近期多次答对」「不再算作熟练」），**不写 30 天 / 答对 2 次 / 近 3 卷**：
这些阈值只住后端 `config.Settings`，前端写死会在阈值调整后变成假话。
`examNotice.test.ts` 用 `expect(proficiencyRuleHint(80)).not.toMatch(/\d/)` 钉住。

## 4 验证计划

- 前端：`npm run typecheck` / `npm run lint` / `npm test -- --run`。
- 后端：本轮零改动，不重复跑 20 分钟全量 pytest（与 r18 基线 `534 passed, 1 skipped` 同口径）。
- 文档自查：`memory.md` 第 40 行已标关闭；`git status` 只含预期文件。

## 5 取舍与偏离

### 5.1 D-8 对 r6 `DESIGN.md` §0.6 的偏离（记录在此，不改历史夹）

r6 DESIGN 写的是「提交后的结果面板**不重复**同一条」，本轮的 D-8 正是要求复显。裁决：

- 任务夹建后不可变 → 偏离口径只落本夹 + `memory.md`，不回写 r6 夹。
- 复显范围收窄：**只复显事实句，不回放规则说明**，且放在结果面板之外（结果面板组件零改动），
  以降低对总分焦点的干扰；这点已写进页面注释，避免后来者把它扩成「连规则说明一起复读」。

### 5.2 信息行从「390px 恒单行」变为可换行（偏离 r6 DESIGN §0.5-5）

r6 §0.5-5 按「AC-12 原句 ≈188px ≤ 268px」推导出 390px 下恒单行；本轮追加的规则说明（约 48 全角字）
远超该宽度，信息行会变成 2–3 行。裁决与兜底：

- r6 §0.5-8 已预留「更长内容由 `flex-wrap: wrap` 落到第二行、仍无横向滚动」的兜底，几何上安全；
- 行上 24 / 行下 16 的纵向节奏约束（§0.5-6）针对信息行整体外间距，仍是 `margin: 0`，未新增 margin/padding；
- 这是 D-7 的直接代价：要么常驻说明、要么不说（tooltip 被 §0.6 禁止）。选择前者，并在此留痕。

### 5.3 D-9 不暴露 `stage` / `backfill`

见 §3.3：宁可只给归因级说明，也不把层号与回流计数搬上界面——与 DESIGN §0.6 的反对理由保持一致。

### 5.4 其余取舍

1. **不新增 `reintroduced_count` 契约字段**：本轮授权是「文案」，扩契约属于功能变更；将来若产品坚持要数字，
   需两侧契约同步 + 前端测试 + 390px 重排，另立需求。
2. **不把规则说明做成可折叠/可关闭**：常驻一行成本最低，且与既有信息行同款；折叠交互会引入新状态。
3. **不做 DOM 级断言**：本项目无 RTL/jsdom，渲染事实由源码评审 + 真机走查覆盖（与 r18 同口径）。
4. **`filteredNotice()` 措辞不动**：它是 r6 AC-12 的逐字验收口径，本轮只在其后追加说明，不改原句。

## 6 风险与回滚

- 风险极低：三处均为展示层文案，无状态机、无契约、无落库、无网络行为变化。
- 唯一可见变化是信息行变长（390px 下换行），已由 `flex-wrap:wrap` 兜住。
- 回滚：单文件 `git checkout -- <file>` 即可；无数据副作用。
