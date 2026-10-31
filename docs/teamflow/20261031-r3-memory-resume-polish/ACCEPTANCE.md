# 验收报告 · r3 长期记忆（成长时间线 + 增量合并画像）与简历 AI 润色

- 任务夹：`docs/teamflow/20261031-r3-memory-resume-polish/`
- 被测分支：`feat/dev-skill-coach`（46 项改动：22 修改 + 24 新增；无新提交、无新分支）
- 基线：`docs/teamflow/20261031-r2-ac5-copy-markdown/`（PRD 标注「取代 r1#AC-2：新简历上传改为增量合并」）
- 验收依据：本夹 `PRD.md`（15 条 AC）、`DESIGN.md`、`TECHNICAL.md`、`QA-REPORT.md` + 本轮**独立复跑**

## 1. 复跑实况（验收人亲自执行，非转引 QA）

| 项 | 实跑结果 |
|---|---|
| 后端 `python -m pytest` | **113 passed**（0 failed / 0 skipped；既有 73 条未删、未 skip） |
| `npm run typecheck` | exit 0，**0 error**（T6 契约基座已落地，dev 期 13 条错误确已归零） |
| `npm run lint` | exit 0，0 error / 28 warning（全部为既有 `react-refresh` 风格类） |
| `npm test` / `npm run build` | **7 passed** / **✓ built**（246.70 kB JS + 39.76 kB CSS）—— 旧轮「沙箱 EPERM」结论本轮已不成立 |
| `check_qa_r3_functional.py` | **18/18 PASS**（真实 HTTP 旅程：上传→合并→面试×2→笔试→润色→重跑→成稿） |
| `check_qa_interface_parity.py` | **14/14 PASS**（9 个契约模型字段集双侧相等 + 16 个前端端点全部命中 OpenAPI） |
| `check_polish_ui_behavior.cjs` | **15/15 PASS**（真实组件渲染：三态/占位/成稿 1:1/空错载/导出单源/零持久化） |
| `check_memory_polish.mjs` | **28/28 PASS**（≥8 断言要求满足，exit 0） |
| `check_copy_behavior.cjs`（r2 契约） | **6/6 PASS**（复制 103B 字节相等、Toast 时长、忙态、失败兜底、导出不回归） |
| T6/T7/T8/T3/T1 检查器 | 15/15、25/25、30/30、28/28、21/21、46/46 全 PASS |
| `ruff check app tests` | 环境阻塞（`No module named ruff`）→ 需开发机/CI 复跑，非代码问题 |

> 复跑注记：`check_t7_timeline_ui.cjs` 需在 `frontend/` 下以 `NODE_PATH="$PWD/node_modules"` 运行，直接 `node` 调用会 `Cannot find module 'esbuild'`（工具使用姿势，非检查器缺陷）。

## 2. 逐条 AC 核对

| AC | 结论 | 独立证据 |
|---|---|---|
| AC-1 事件落库 + `GET /api/timeline` 倒序、字段双侧同步 | 通过 | P07（11 字段逐一相等、`occurred_at` 严格倒序）；interface_parity I01–I08 |
| AC-2 指标单一来源（差 ≤0.05、不依赖报告） | 通过 | P08 `interview_avg` 与 `/api/history` 差 **0.000**；P09 `exam_total == total`；`timeline.py` 只调 `history.score_of` + `diagnosis.build_shortfalls`（源码核对） |
| AC-3 `(type,ref_id)` 幂等、失败不写不半成品 | 通过 | P10（重复提交事件数 4→4）、P17（`duplicate=true`、证据/事件不重复）+ pytest 失败注入用例；`db.py` 唯一索引兜底 |
| AC-4 历史页时间线区（时间/类型/指标/短板/新增消失 + 空错载） | 通过 | T7 25/25（四态分支、首次态无 NaN、失败不隐藏趋势表、独立滚动）；typecheck/lint 0 error |
| AC-5 同类上一条对比（delta 1 位小数、服务端 `comparison`） | 通过 | P11（`delta=0.0`、复现 3/消失 0）；T7 对比块直渲染、无减法 |
| AC-6 增量合并（同 `profile_id`、证据旧→新、逐字命中、`historical` 保留） | 通过 | P04/P05（`same_id`、证据累积且 `[0]` 为旧简历原文、historical=[TypeScript,Python,SQLite]）；merge_rules 28/28 |
| AC-7 name 归一 + 历史项不进画出题/诊断、active<3 兜底 | 通过 | P06（`react`/`React` 归一）、P18（历史项零进题）、P05（`tech_fallback`） |
| AC-8 逐条建议 ≥3 条 / ≥2 section / `original_text` 字节相等 / 临时岗位不落库 | 通过 | P12（5 条 / 4 section / 逐字命中）、P14（临时岗位不回写画像） |
| AC-9 反幻觉后置校验（数字降级、专名丢弃、`dropped_count`） | 通过 | P13（`Doc2Vec` 整条丢弃、`55%`→`〈待补充〉` + `numeric_added`） |
| AC-10 采纳/忽略即时反映成稿、`documents.text` 不变、不跨会话持久化 | 通过 | P16（正文原文未变；`clear_cache()` 后 `regenerated=true`）；UI 检查器 F1/F2（零 localStorage / 零 PATCH/PUT） |
| AC-11 一键成稿 + 导出与响应单源零变换 + 失败 InlineError | 通过（附 D-1/D-2 偏离） | P15（224B 幂等）、E1（`new Blob([full.markdown])` 裸传）、E2（预览服务端优先）、D3 失败态 |
| AC-12 临时 `target_role` 只作用于本次、画像不变 | 通过 | P14（回显临时岗位、画像仍「前端开发工程师」、下次调用回落） |
| AC-13 润色只在 `services/resume_polish.py` 单入口、路由/页面零提示词、可单测 import | 通过 | grep：`routers/` 零提示词零模型名；`frontend/src/` 零 Key 零模型名；`test_resume_polish.py` 直接 import；`build_suggestions/validate_suggestions/compose_full` 齐备 |
| AC-14 门禁不回归 + 检查器 ≥8 断言 | 通过（ruff 待复跑） | §1 全部实跑；`check_memory_polish` 28 断言；r2 检查器 6/6 |
| AC-15 无登录、前端无 Key、`/health` 200、错误 envelope 中文 | 通过 | P01（200 `status=ok`、零 Key 痕迹）、P02 404 / P03 422 均为中文 envelope、无路径泄露；前端 grep 零命中 |

## 3. 架构一致性核查（M3 质量门）

- **符合技术方案**：`services/timeline.py` 是唯一组装点（分数只走 `history.score_of`、短板只走 `diagnosis.build_shortfalls`，不复制算式）；时间线 SQL 仅在 `repository.py`，DDL 仅在 `db.py`（`CREATE TABLE` 全仓 1 处）；`resume_polish.py` 为唯一提示词入口；`routers/timeline.py` 只做参数校验、不排序不写 SQL；`profile_merge.py` 为纯函数合并。
- **未发现活跃的重复实现 / adapter drift**；两侧契约字段集由真实 pydantic 模型与真实 TS interface 比对（14/14）。
- **既有结构未破**：r2 复制/导出 6/6 未回归；时间线失败时既有趋势表照常显示；上传后「从未调用 `generateProfile`」的既有死链已修（A26）。
- **偏离**：1 处死代码保留双模型定义（D-3）、2 处 UI 未完全按 DESIGN 落地（D-1/D-2/D-4）——不构成结构破坏，但属本报告 §4 的整改面。

## 4. 缺陷与偏离（本轮验收新发现，QA 报告未记录）

| 编号 | 级 | 内容 | 影响 |
|---|---|---|---|
| D-1 | **P2** | 润色页「原版」Tab 显示的是**被改写句的原文拼接**（`buildOriginal` 取 `original_text` 拼 `\n\n`），而非整篇简历正文；但 meta 标「原版 · 逐字取自简历正文」，与 `DESIGN.md` §240「`原版` = 简历正文（只读、可滚动）」不符 | 用户无法核对「未被改写的段落是否还在」；成稿与导出仍取服务端整篇 `resume_text`（无数据丢失），属可见性/表述缺陷 |
| D-2 | P3 | 导出文件名 `简历润色-<yyyy-mm-dd>.md`，`DESIGN.md` §284 约定 `<原文件名>.md`（`Profile` 无 `file_name`，dev 已记此契约缺口） | 命名规则与设计不一致，不影响单源字节相等（E1 通过） |
| D-3 | P3 | `services/profile_merge.py` 的 `CONTRACT_READY=False` 分支（`_FallbackEvidence` / `MergedSkill` / `MergedProject` / `MergedProfile`）在契约落地后已成死代码，仍与 `schemas.py` 双份定义 | 双源风险，QA 已建议下一轮删除 |
| D-4 | P3 | 画像页合并摘要条未做 `DESIGN` 的「查看历史能力项」按钮（历史项在页内下方折叠分组，信息可达） | 入口可达性弱于设计 |
| D-5 | P3 | 仓库根出现 0 字节 `nul` 文件（untracked，Windows 重定向误产物） | 交付面污染，`git add -A` 会带进提交 |
| D-6 | P3 | 反幻觉专名规则只覆盖 ASCII 词与 `「…」/《…》`，中文自由编造不拦截（PRD R5 已声明边界，保留人工抽检） | 已知边界，非缺陷 |

## 5. 有条件通过的闭合门槛

- **R-1（对应 D-1，必须闭合）**：原版 Tab 改为真实简历正文（补一条只读正文接口并双侧同步契约），或经产品确认后降级设计（改 `DESIGN.md` §240 并把 meta 改为「被改写句原文」），二者择一。
- **R-2（对应 D-5，必须闭合）**：删除仓库根 `nul`，确认 `git status` 仅含本需求改动。
- **R-3（对应 D-2/D-3/D-4，可随下一轮清理）**：导出文件名按设计取原文件名；删除 `CONTRACT_READY` 死分支；补摘要条「查看历史能力项」入口。
- 复核方式：修完只需重跑 `typecheck` / `lint` / `pytest` + 受影响检查器（`check_polish_ui_behavior` / `check_memory_polish`），**无需重跑全量旅程**。

## 6. 需人工复跑（不阻断，QA §4 清单沿用）

真机剪贴板（非安全上下文禁用态）、Toast 时长与 `aria-live` 播报、375×667 与 `safe-area`、生成中离开保护、超 20s 追加提示、反幻觉人工抽检、`ruff`、真实 Key 端到端计时。本轮无浏览器/截图证据，视觉项以检查器断言 + QA 清单为准。

## 7. 验收意见

功能面 15 条 AC 全部由**本轮亲自复跑的真实执行证据**支撑（无一条为"存在性检查"或转引），未发现 P0/P1 缺陷；但存在 1 条 P2 可见性偏离（D-1）与 4 条 P3（含仓库根 `nul` 污染），其中 D-1、D-5 属交付闭合项，故判**有条件通过**：按 §5 整改 R-1、R-2 后即可快速复核转「通过」，无需重做功能。

验收结论：⚠️ 有条件通过
