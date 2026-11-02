# r19 验收报告：r6 D-7/D-8/D-9 文案说明

- 任务夹：`docs/teamflow/20261102-r19-exam-notice-clarity/`
- 验收对象（工作区未提交改动）：`frontend/src/lib/examNotice.ts`、`frontend/src/pages/ExamPage.tsx`、
  `frontend/src/test/examNotice.test.ts`、本任务夹、`docs/teamflow/memory.md`。
- 验收口径：r6 `ACCEPTANCE.md` §6 的 D-7 / D-8 / D-9（§7.3 建议优先级 D-9 > D-7 > D-8）；
  用户本轮明确只做这三条文案，r8① / r5 O-4 / r3 P3② / memory 第 45 行不在范围内。

## 1 判据逐条核对

| # | 判据 | 实测结果 | 结论 |
|---|---|---|---|
| 1 | D-7：信息行说明「为什么被过滤 / 怎样回流」 | `ExamPage.tsx:247-254` 在既有 `.sc-meta-line` 内追加 `· {noticeHint}`；文案由 `examNotice.ts:33-36` 的 `proficiencyRuleHint()` 单点产出，含「暂时跳过 / 不再算作熟练后自动回流」 | 通过 |
| 2 | D-7：没有把过滤事实塞进 hover tooltip | 全仓无 `title=` / tooltip 承载该事实；说明为常驻文本 | 通过 |
| 3 | D-8：提交后复显本卷过滤事实 | `ExamPage.tsx:333-340` 在 `ExamResultPanel` 之后渲染 `[熟练过滤] + 原句`；复用页面仍持有的 `run.filtered_count` | 通过 |
| 4 | D-8：不抢走总分焦点 / `ExamResultPanel` 零改动 | 复显行位于组件之外，只复显事实句、不回放规则说明；组件文件零改动 | 通过 |
| 5 | D-9：文案提示「个别熟练题因卷面结构重新出现」 | `proficiencyRuleHint()` 尾句逐字为「个别熟练题可能因卷面结构重新出现」 | 通过 |
| 6 | D-9：不暴露 `stage` / `backfill` | `frontend/src/api/types.ts` 零改动；UI 无 L1–L6 字样、无回流计数 | 通过 |
| 7 | 静默口径统一 | `filteredNotice` 与 `proficiencyRuleHint` 共用 `isPositiveCount()`；`0` / 负数 / `null` / `undefined` / `NaN` / `±Infinity` 一律 `null` → 不挂载节点 | 通过 |
| 8 | 阈值不落前端 | 文案不含 30 天 / 2 次 / 3 卷；测试 `not.toMatch(/\d/)` 钉住 | 通过 |
| 9 | `filteredNotice()` 逐字不变（AC-12） | 原 7 条断言全部通过（含逐字全等与静默口径） | 通过 |
| 10 | 契约零改动 | `backend/app/schemas.py` / `frontend/src/api/types.ts` 零改动；`ExamResult` 未加字段 | 通过 |
| 11 | 样式零改动 | 只用既有 `.sc-meta-line` / `Chip`；零 CSS / token 改动 | 通过 |
| 12 | 既有门禁不回归 | typecheck 0 error、lint 0 error / 28 warnings、vitest 10 文件 **136 passed**（133 → +3） | 通过 |
| 13 | 记忆收口准确 | `memory.md` 第 40 行 D-7/D-8/D-9 标已关闭并指向本报告；390px 真机走查保留开放 | 通过 |
| 14 | 任务夹自包含 | `meta.json` / `TECH-CHANGE.md` / `ACCEPTANCE.md` 齐备 | 通过 |

## 2 架构一致性

| 蓝图要求 | 实测 | 结论 |
|---|---|---|
| 组件文件只导出组件、纯函数进 `lib/` | 新增文案为 `lib/examNotice.ts` 的纯函数；`ExamPage.tsx` 无新增导出 | 符合 |
| 样式只用 token / 既有类 | 零 CSS 改动；沿用 `.sc-meta-line` 的 `flex-wrap: wrap` 处理换行 | 符合 |
| 契约两侧同步 | 未触碰契约 | 符合 |
| 任务夹不可变 | r6 / r18 夹零改动；对 r6 DESIGN §0.6/§0.5 的两处偏离写在本夹 §5 | 符合 |
| 单源实现 | 文案只在 `examNotice.ts` 一处；静默判定只在 `isPositiveCount()` 一处；阈值只在后端 `config.Settings` | 符合 |

## 3 复跑命令与实测

```powershell
cd frontend
npm run typecheck          # exit 0
npm run lint               # exit 0，0 error / 28 warnings（与 r18 基线一致）
npm test -- --run          # 10 文件 / 136 passed（examNotice.test.ts 7 → 10）
```

- 后端：本轮零改动，未重复跑 20 分钟全量；沿用 r18 基线 `534 passed, 1 skipped`。
- `ruff`：本机不可用（与历史同口径，未记为通过）。

## 4 偏离与遗留（均不阻断）

| 编号 | 内容 | 处置 |
|---|---|---|
| 偏离-1 | D-8 与 r6 `DESIGN.md` §0.6「提交后的结果面板不许重复同一条」相反 | 复显范围收窄为「只复显事实、不回放说明」且置于面板之外；理由见 `TECH-CHANGE.md` §5.1 |
| 偏离-2 | 追加规则说明后信息行不再是 §0.5-5 推导的「390px 恒单行」 | 由 §0.5-8 的 `flex-wrap` 兜底，无横向滚动；见 `TECH-CHANGE.md` §5.2 |
| P3-a | 两处文案无 DOM 级断言（项目无 RTL/jsdom） | 渲染事实由源码评审 + 真机走查覆盖（与 r18 P3-b 同口径） |
| P3-b | 信息行 2–3 行后的真实视觉未做浏览器截图 | 并入 memory 第 38 行的人眼/真机补测清单 |
| P3-c | `ruff` 本机不可用 | 与历史同口径；CI 或含 ruff 的环境补跑 |

## 5 验收判定

D-7 / D-8 / D-9 三条均有可读、可测的落地：文案单点产出、静默口径统一、契约与样式零改动、
前端门禁全绿（vitest 133 → 136）；两处对 r6 DESIGN 的偏离已留痕并收窄影响面，
剩余 3 条 P3 为环境/工艺留痕，不构成返工条件。

验收结论：✅ 通过
