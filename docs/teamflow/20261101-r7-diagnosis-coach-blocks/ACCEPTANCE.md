<!-- meta: summary="r7 诊断报告三块补强产品验收：20 条 AC（P0 18/P1 2）逐条复核全部达成，5 条 anti-goal 无一成立，门禁只增不减（pytest 297/vitest 100/typecheck 0/lint 0·28/build ok//health 200），架构无重复实现、无蓝图偏离、零新依赖、零 DDL、routers 未改；1 条口径裁定（AC-7 坏 seed 返回 500，保留）与 4 条 P3 工艺观察（文档命名漂移/.md 均分重复/polish 动效分岔）记录在案，均不阻断，另有 5 项真机人工补测。结论：通过。" -->

# r7 · 诊断报告三块补强 · 产品验收报告（ACCEPTANCE）

- 任务夹：`docs/teamflow/20261101-r7-diagnosis-coach-blocks/`（PRD / DESIGN / TECHNICAL / QA-REPORT / 本报告）
- 分支：`feat/dev-skill-coach`；交付面共 33 项未提交改动（10 M + 23 ??），Agent 未提交、未 stash，符合工程约束
- 验收人：产品经理（验收负责人） · 验收时间：2026-11-01

## 1. 结论

✅ 通过。20 条 AC 逐条复核全部达成，5 条 anti-goal 无一成立；门禁只增不减；架构干净（单一实现、无重复、零新依赖、零 DDL、路由未动）。1 条口径裁定（AC-7 坏 seed 的 HTTP 状态码）与 4 条 P3 工艺观察在 §6 记录，均不阻断交付。

## 2. 验收人独立复跑（不采信上游转述）

| 命令 | 结果 |
|---|---|
| `cd backend && python -m pytest -p no:cacheprovider -o addopts="" -q` | **297 passed / 0 failed**（基线 204） |
| `check_qa_r7_functional.py` | **91/91 全 PASS**（覆盖 AC-1/2/3/6/7/8/9/10/11/12/13/14/16/19/20） |
| `check_qa_r7_interface.py` | **ALL PASS**（前后端具名符号与文案字典双侧一致） |
| `check_r7_fix_contract.py` | **15/15**（D-1 传 TargetRole 保真、D-2 按错题数分岔、.md 同源） |
| `check_qa_r7_ui.cjs` | **25/25**（三块 DOM/降级态/旧报告态/焦点卡属性） |
| `check_qa_r7_bad_seed.py` | HTTP **500** + 中文 envelope（`VALIDATION_ERROR` / 无路径堆栈）→ 见 §6 裁定 |
| `cd frontend && typecheck / lint / test / build` | 0 error / 0 error·28 warn / **100 passed** / 构建 ok（css 55.44 kB · js 267.66 kB） |
| 起 uvicorn（:8131，空 Key，新库）→ `/health`、`/api/history`、`/api/courses` | 200 `{"status":"ok",...,"ai_configured":false}` / 200 `[]` / 200 课程清单 |

## 3. 逐条 AC 核对

| AC | 级别 | 判定 | 复核证据（我的运行或文件事实） |
|---|---|---|---|
| AC-1 | P0 | 通过 | functional AC-1 ×2 PASS；`_scored`/`history.score_of` 唯一题源，2 道简答题不入 `wrong`/`total`；静态无第二份判分实现 |
| AC-2 | P0 | 通过 | functional AC-2 ×10 PASS（三键聚合、闭集、samples 1–3 可反查、`wrong ≤ total`、`rate` 口径一致） |
| AC-3 | P0 | 通过 | functional AC-3 ×2：必备→错误率→均分→题量→id；两次调用逐字相同；AI 抛异常时顺序与模板文案不变 |
| AC-4 | P0 | 通过 | `test_resume_hints.py` 15 例：复用 `build_suggestions`（调用次数、正文逐字）、`anchor_text` 逐字命中否则整条丢弃、无第二份润色提示词 |
| AC-5 | P0 | 通过 | UI ×5（`is-focused` / 唯一 id / `tabIndex=-1` / 页面无提示词 / 无 .md 拼串）+ `polishFocus` 10 例（逐字命中、不做模糊、未命中按 section 预筛 + 中文提示） |
| AC-6 | P0 | 通过 | UI ×3（中文占位、零跳转、薄弱与竞争力仍完整）+ functional ×7（HTTP 200） |
| AC-7 | P0 | 通过（带口径裁定） | seed 四方向×3–4 级×6–8 项+必备≥3（pytest 4 条）；缺文件/坏 JSON/缺字段 → 中文 `VALIDATION_ERROR` envelope、无路径堆栈；HTTP 状态码裁定见 §6 |
| AC-8 | P0 | 通过 | functional ×8 + `test_role_fit.py` 13 例（必备→gap 降→name；幂等；`missing_must`=未命中必备；空画像不抛） |
| AC-9 | P0 | 通过 | functional ×6 + UI ×2（面试设定优先、显示「本次面试设定」、不静默取一）+ `resolve_target_role` 4 例 + .md 同源 |
| AC-10 | P0 | 通过 | functional ×7 + UI ×3（`notice`「暂无该岗位的能力模型」、空 items、其余区块与 .md 完整、200） |
| AC-11 | P0 | 通过 | functional ×10（AI 抛错/坏 JSON/无 Key 三态均 200；AI 不得增删条目；`name` 不逐字相等即丢弃） |
| AC-12 | P0 | 通过 | functional ×10（.md 三块条目数/顺序与 `Report` 逐条一致）+ 门禁 `test_r7_markdown_single_source`；我另跑 `preview_r7_markdown.py` 目视三块文本与旧报告态 |
| AC-13 | P0 | 通过 | functional ×7（旧 payload → `latest` 200、三字段 None、.md 旧报告提示）+ UI ×3 + 门禁 `test_r7_contract_mirror`（schemas↔types 镜像）；`/api/history` 实测 200 |
| AC-14 | P0 | 通过 | functional ×4：在物化 HEAD 树 `probe/head/backend` 与当前树各跑 `dump_shortfalls` → 序列**逐字相等**、3≤len≤5；`ReportPage.tsx` 渲染序 = 概览 → 短板卡(L278) → `CoachBlocks`(L289) |
| AC-15 | P0 | 通过 | pytest 297、vitest 100（基线 72，新增 28）、typecheck 0、lint 0 error/28 warn、build ok、`/health` 200（我起服务实测） |
| AC-16 | P0 | 通过（390 列人工） | 门禁 `test_r7_style_tokens_defined` + `test_style_baseline_append_only`；无裸色值同口径拦截；错误 envelope 中文无路径（functional ×3 + 实测 404）；390 无横滚属真机项（§7） |
| AC-17 | P0 | 通过 | `DESIGN.md` 38 KB：§0.7 token 逐条推导、§1.3 层级与「比短板更安静」的视觉关系、§2.4 焦点态与未命中降级、§4 组件规格、§6 AC 对照 |
| AC-18 | P0 | 通过 | `git status` 33 项全落在 TECH §1 最终白名单（含三处显式修订）；`requirements.txt`/`package.json` 零改动；`repository.py`/`db.py`/`routers/`/`rules.py` 零改动 |
| AC-19 | P1 | 通过 | UI ×4（9 条→8 条+「其余 1 条」、恰好 8 条不折叠、`[]` 中文空态）+ functional ×3 |
| AC-20 | P1 | 通过 | UI ×4（序号递增 = `first_fix` 顺序、前端不重排、带视觉标记类、`gap=0` 渲染「达标」） |

## 4. 反面目标（anti-goal）逐条判定

1. **首屏被顶走**：不成立。短板卡（L278）在 `CoachBlocks`（L289）之前，三块无 sticky/absolute。
2. **错题数与历史页对不上**：不成立。题源只有 `_scored`/`score_of`，functional 用同一 run 交叉核对。
3. **要点指向不存在的句子**：不成立。`anchor_text` 逐字命中否则丢弃（pytest），前端不做模糊匹配、未命中退 section 预筛 + 中文提示。
4. **差距像 AI 编的**：不成立。`items`/`gap`/排序全纯函数，AI 只补 `conclusion`，`name` 不符即丢。
5. **变慢或 AI 挂就白屏**：不成立。两路 AI `asyncio.gather` 并发、任一路异常降级为模板文案；空 Key 下 functional 全绿且 200。

## 5. 架构与改动面（M3 质量门）

- **单一实现成立**：算分 `history.score_of`、短板 `diagnosis.build_shortfalls`、润色 `POLISH_SYSTEM`、`.md` `markdown.to_markdown`、岗位模型 `seed/role_models.json` —— 无第二份拷贝；门禁变异自检 10/10 证明新增门禁**非空转**。
- **编排收敛**：`diagnosis.build_report` 保持编排职责（先纯算、再两路 AI），新模块只做投影（`weakness`/`resume_hints`/`role_fit` 纯函数），文案常量收进 `coach_copy` 且 `test_r7_copy_parity` 双侧逐字。
- **无结构破坏**：零 DDL（`db.py` 未改）、SQL 未动（`repository.py` 未改）、routers 未改、零新依赖；样式只 append（删一行即门禁 FAIL，已由变异自检证伪空断言）。
- **观察（不阻断）**：`weakness` 依赖 `diagnosis._scored` 私有函数（TECH 指定的唯一题源，已有哨兵用例）；`role_fit` 自做 `lower()` 归一（TECH §3.3 显式规定）。

## 6. 口径裁定与遗留

- **D-3（AC-7 状态码，我的裁定：保留 500）**：实测坏 seed 返回 HTTP 500 + 中文 envelope（`code/message/retryable` 齐全、无路径堆栈）。理由是内置 seed 属服务端资产，损坏时返回 4xx 会把部署错误误导成客户端错误；PRD 该句的真实意图「不得裸 500 / 不得栈泄露」已满足，且该路径只在资源损坏时触发。AC-7 记「通过（带口径裁定）」，建议 r8 把 PRD 措辞改为「返回结构化中文错误、不裸 500」。
- **D-4（文档漂移）**：DESIGN §1.2 写 `CoachSection.tsx`/`RoleFit.tsx`/`.sc-link-btn`，实现为 `CoachBlocks.tsx`/`RoleFitCard.tsx`/`.sc-btn`；AC-17 的内容要求已满足，r8 更正文档即可。
- **D-5（.md 文案重复）**：薄弱纪要行「`summary`（组内均分 X/10）」，当 `summary` 本身已含均分时同句重复；r8 去重。
- **D-6（动效分岔）**：`PolishPage` 的 `scrollIntoView` 未传 `behavior`（恒瞬时），与 DESIGN §2.4 的 `prefers-reduced-motion` 分岔不一致；r8 补一行。
- **提交面**：33 项全为源码/文档，无 `node_modules`/`dist`/`__pycache__`/`*.db`/`.env` 噪音；`logs/teamflow/` 为 run 暂存，收尾由 host 归档。

## 7. 人工补测（环境限制，非交付缺陷）

1) 真实浏览器点「去改这一条」的滚动 + 焦点环 2) `prefers-reduced-motion` 动效分岔 3) 390×844 真机：无横滚、堆叠序 薄弱→简历→竞争力 4) 配真实 Key 跑一次 0 错题组，确认 AI 改写后文案不矛盾 5) 屏幕阅读器三段朗读顺序。

验收结论：✅ 通过
