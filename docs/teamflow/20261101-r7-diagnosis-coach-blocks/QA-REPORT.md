# r7 · 诊断报告「提升路线」三块补强 · QA 报告（第 2 轮 · 修复复测）

- 任务夹：`docs/teamflow/20261101-r7-diagnosis-coach-blocks/`
- 分支：`feat/dev-skill-coach`（未提交改动 33 项：10 M + 23 ??；agent 未提交、未 stash）
- 被测交付：`backend/app/services/{diagnosis,weakness,role_fit,resume_hints,coach_copy}.py` + `seed/role_models.json` + `{schemas,markdown}.py` + 前端三块 UI 与 `/polish` 定位
- 本轮性质：**修复复测**（上轮 2 条 P2：D-1 岗位来源误标、D-2 0 错题组文案自相矛盾）——先复跑上轮全部检查器，再补 2 个上轮未覆盖的面
- 结论：**可验收**（P0/P1/P2 已全部关闭；4 条 P3 观察仍开放，均不阻断）

## 1. 环境与限制

| 项 | 情况 |
|---|---|
| 后端 | Python 3.13 + pytest **297 例**全通过；`ruff` 未安装（`No module named ruff`）→ 后端 lint 未执行，按策略不换命令绕行，留开发机复跑 |
| 前端 | typecheck 0 error、lint 0 error/28 warning、vitest 100 passed、build ok |
| 浏览器 | 沙箱内无法启动真实 Chromium（host token 限制，**非交付缺陷**）→ 渲染层用 `react-dom/server` 脚本化断言；真实滚动/真机进人工补测清单 |
| AI | 全程 `AI_API_KEY=` 空 + 注入式 Fake/Boom client，零外网、零扣费 |
| 真实工作树 | 两个新检查器只在 `logs/.../probe/mut/gate/` 副本上做变异，**未改动任何源码**（收尾校验：副本还原后门禁复绿） |

## 2. 门禁结果（阈值只增不减）

| 门禁 | 命令 | 本轮结果 | 判定 |
|---|---|---|---|
| 后端单测 | `cd backend && python -m pytest -p no:cacheprovider -o addopts="" -q` | **297 passed / 0 failed**（基线 204 + r7 新增 + 3 条修复门禁） | 通过 |
| 前端类型 | `cd frontend && npm run typecheck` | 0 error | 通过 |
| 前端 lint | `cd frontend && npm run lint` | 0 error / **28 warning**（阈值 ≤28） | 通过 |
| 前端单测 | `cd frontend && npm test` | **100 passed**（基线 72，+28） | 通过 |
| 构建 | `cd frontend && npm run build` | ok（css 55.44 kB / js 267.66 kB） | 通过 |
| 探活 | `DB_PATH=tests/.tmp/qa-boot-r7b.db AI_API_KEY= python -m uvicorn app.main:app --port 8126` + `curl /health` | 200 `{"status":"ok","version":"0.1.0","ai_configured":false,"db":"sqlite"}` | 通过 |
| 密钥泄露 | `cd frontend && grep -riE "sk-\|api_key\|AI_API_KEY" src/ dist/` | `NO_KEY_LEAK` | 通过 |
| 后端 lint | `cd backend && python -m ruff check app tests` | 环境缺失（`No module named ruff`），按策略未重试/未绕行 | 阻塞（环境） |
| 提交面卫生 | `git status --porcelain=v1 -uall` | 33 项全部为源码/文档；`node_modules`/`dist`/`__pycache__`/`.pytest_cache`/`.ruff_cache`/`tests/.tmp`/`*.db`/`.env`/`*.tsbuildinfo` **9/9 均被 .gitignore 覆盖**，无噪音 | 通过 |

## 3. 上轮检查器复跑（回归契约，逐条给数）

| 检查器 | 覆盖 | 本轮结果 | 上轮 |
|---|---|---|---|
| `check_qa_r7_functional.py` | AC-1/2/3/6/7/8/9/10/11/12/13/14/16/19/20 + 真实 `POST /reports/generate`→`latest`→`markdown` 全链路 | **91 PASS / 0 FAIL** | 88 PASS / 3 FAIL |
| `check_qa_r7_interface.py` | 71 个前端具名导入符号 + 4 组文案字典双侧一致 | **12/12** | 12/12 |
| `check_qa_r7_ui.cjs` | 三块 DOM 顺序/折叠/空态/遗留态/`/polish` 命中卡属性 | **25/25** | 25/25 |
| `check_r7_selfcheck.cjs`（dev 自检） | 三块渲染 + 命中卡 | **19/19** | 19/19 |
| `check_t1_contract_seed.py` | 契约/文案/seed 自检（16 模型 / 4 岗位 / 6 文案） | PASS | PASS |
| `check_t3_role_fit.py` | 纯函数差距表、排序、空画像、坏 seed 中文报错 | **17/17** | 17/17 |
| `check_qa_r7_bad_seed.py` | 坏 `role_models.json` 的 envelope 形态 | HTTP **500** + 中文 `VALIDATION_ERROR`（D-3 口径未变，见缺陷表） | 同 |

## 4. 本轮新增探针（上轮未覆盖面）

上轮缺口：**只证明门禁「通过」，从未证明门禁「会失败」**（r6 轮有变异自检，r7 轮漏做）；修复后也没验证「接线不变量」（`build_report` 到底把什么交给纯函数）与 `.md` 同源的最后一段。故新增两个检查器：

| 新增检查器 | 覆盖（上轮未覆盖的原因） | 结果 |
|---|---|---|
| `scripts/check_r7_gate_mutation.py` | backend + frontend/src 物化到 `probe/mut/gate/`（自带 git 基线），逐条注入真实回归，断言 8 条 r7 门禁**转为 FAIL**；另有未变异对照与还原后复绿 | **10/10** |
| `scripts/check_r7_fix_contract.py` | ①D-1 接线不变量（AST：第二参必须是 `resolved` 这个 TargetRole，不得是 `.role`）；②D-2 文案不变量（AST：`错题` 只允许出现在 `wrong != 0` 分支）；③`.md` 同源自真实 `to_markdown`；④AC-8 兼容（TargetRole 直通 + 裸名兜底） | **15/15** |

变异自检明细（每条 = 一条真实回归形态，期望 FAIL）：

| 注入的回归 | 门禁 | 结果 |
|---|---|---|
| base.css 删掉一行既有声明 | `test_style_baseline_append_only` | FAIL ✓（rc=1, 1 failed） |
| `types.ts` 少 `weakness_map:` | `test_r7_contract_mirror` | FAIL ✓ |
| `weakness.py` 复制闭集字面量 `"前端"` | `test_r7_closed_sets_not_duplicated` | FAIL ✓ |
| `coach_copy.LEGACY_BLOCK_NOTICE` 改字 | `test_r7_copy_parity` | FAIL ✓ |
| `lib/coach.ts` 塞入 `## 知识薄弱地图` | `test_r7_markdown_single_source` | FAIL ✓ |
| `tokens.css` 改掉 `--weak-rank-w` | `test_r7_style_tokens_defined` | FAIL ✓ |
| 回退 D-2（无条件「再过一遍错题」） | `test_zero_wrong_group_never_claims_redoing_wrong_questions` | FAIL ✓ |
| 回退 D-1（传 `resolved.role` 裸串） | `test_role_source_stays_interview_when_settings_match_profile` | FAIL ✓ |

结论：8 条门禁全部**非空转**——真回归会被抓住，不是「写着好看」。

## 5. 缺陷类命中数复算（与修复摘要对账）

| 缺陷类 | 修复摘要的扫描 | 本轮独立复算 | 判定 |
|---|---|---|---|
| D-1「把 TargetRole 降级成裸串」 | `grep -rn "build_role_fit(" backend/app` → 1 → 0 | 原始 grep 3 命中（1 定义 + 1 docstring + 1 调用），其中**降级调用 = 0**（AST 断言第二参为 `Name(resolved)`）；改回降级形态（变异）门禁即 FAIL | 一致（摘要的「0」指降级调用点，非原始 hit 数） |
| D-2「无条件提错题」 | `grep -rn "再过一遍错题" backend/app` → 1 → 0 | 原始 grep 2 命中（1 行注释 + 1 行 `else` 分支代码），**条件外出现 = 0**；回退变异后门禁 FAIL | 一致（摘要的「0」指条件外出现） |

## 6. 缺陷表（仅列仍开放项）

| 编号 | 严重级(P0/P1/P2/P3) | 功能模块 | 复现步骤 | 期望行为 | 实际行为 | 关联验收项 | 检测命令 | 通过判据 |
|---|---|---|---|---|---|---|---|---|
| D-3 | P3 | 后端·岗位模型加载器（口径确认项） | `role_fit.SEED_PATH` 指向不存在文件后 `POST /api/reports/generate` | PRD AC-7 字面「抛中文 VALIDATION_ERROR，**不 500**」；TECH §3.3 显式选择 500 | HTTP 500 + 中文 envelope（code/message/retryable 齐全、无路径堆栈） | AC-7 | `cd backend && python -X utf8 ../logs/teamflow/tf-mvxhokwc-w1hxht/scripts/check_qa_r7_bad_seed.py` | 验收方裁定：保留 500（按 TECH §3.3）即本行关闭；改 400 则脚本应输出 HTTP 400 且 envelope 不变 |
| D-4 | P3 | 前端·文档一致性（工艺观察） | 对照 `DESIGN.md §1.2/§4` 与实现文件名/类名 | 设计文档与实现一致 | DESIGN 写 `CoachSection.tsx`/`RoleFit.tsx`/`.sc-link-btn`，实现为 `CoachBlocks.tsx`/`RoleFitCard.tsx`/`.sc-btn` | AC-17 | - | - |
| D-5 | P3 | 后端·`.md` 渲染（工艺观察） | 生成报告导出 `.md` 看薄弱地图行 | 一行信息不重复 | `…均分 4.8/10…（组内均分 4.8/10）` 同一行重复均分 | AC-12 | - | - |
| D-6 | P3 | 前端·`/polish` 定位动效（工艺观察） | 点报告「去改这一条」进入命中态 | DESIGN §2.4：`prefers-reduced-motion` 才 `auto`，否则平滑 | `PolishPage.tsx:216` `scrollIntoView({block:'center'})` 未带 `behavior`，恒为瞬时 | AC-5 | - | - |

## 7. 上轮缺陷逐条复验对照（本轮结论，非开放缺陷）

| 编号 | round-2 级 | 模块 | 上轮判定 | 本轮复验 | 结论 |
|---|---|---|---|---|---|
| D-1 | P2（已关闭） | 后端·报告编排 / 竞争力对标 | 面试设定与画像同值时 `role_source` 误标为 profile | `check_qa_r7_functional.py` 91/0（原 3 条 FAIL 全转 PASS）；`test_role_source_stays_interview_when_settings_match_profile` 通过且变异后 FAIL；`.md` 输出 `（来源：本次面试设定）` 且无 `（来源：简历画像）`；AC-8 兼容（TargetRole 直通 + 裸名兜底）通过 | **已关闭** |
| D-2 | P2（已关闭） | 后端·薄弱地图（文案） | 0 错题组仍写「再过一遍错题」 | `check_qa_r7_functional.py` AC-2 判据 PASS；AST 证明「错题」只在 `wrong != 0` 分支；`.md` 出现「错 0 题 + 全部答对」且无「再过一遍错题」；反向用例证明有错题组仍保留错题复盘指引（未删功能） | **已关闭** |
| D-3 | P3（仍开放） | 后端·岗位模型加载器 | 500 vs PRD 字面「不 500」 | 复跑 `check_qa_r7_bad_seed.py`：仍 500，envelope 与中文 message 未变 | 仍开放（口径待验收方裁定） |
| D-4 | P3（仍开放） | 前端·文档一致性 | DESIGN 文件名与实现不符 | 复核：DESIGN §1.2 仍写 `CoachSection.tsx`/`RoleFit.tsx`，实现为 `CoachBlocks.tsx`/`RoleFitCard.tsx` | 仍开放（观察） |
| D-5 | P3（仍开放） | 后端·`.md` 渲染 | 均分重复 | 复跑 `to_markdown`：`…均分 4.8/10，…（组内均分 4.8/10）` 仍重复 | 仍开放（观察） |
| D-6 | P3（仍开放） | 前端·`/polish` 动效 | 未按 reduced-motion 分岔 | `PolishPage.tsx:216` 仍无 `behavior` | 仍开放（观察） |

## 8. 接口一致性（静态，跨模块调用逐条核）

- `check_qa_r7_interface.py` 12/12：**71 个**前端具名导入符号在目标模块都有导出；`SECTION_LABEL`/`DIFFICULTY_LABEL`/`ESSENTIALITY_LABEL` 双侧逐字一致。
- 后端关键调用点（AST）：`diagnosis.build_report` → `role_fit.build_role_fit(profile, resolved)` 参数形状与签名 `(profile, target_role: str | TargetRole | None)` 匹配；`build_role_fit` 内 `_as_target` 是**唯一**来源归一入口（无第二套推断）；`weakness.build_summary` / `coach_copy.ROLE_SOURCE_LABEL` 由 297 例 pytest + functional 检查器运行时覆盖。
- 无「文件存在但成员不存在」的死调用：若有，pytest 收集期或 `check_qa_r7_functional.py` 会直接崩。

## 9. 架构核对（M3）

- D-1 修复方向正确：来源信息以 `TargetRole` 值对象**贯通**编排层→纯函数，而不是在纯函数里反向猜；纯函数签名与字符串兜底保持（AC-8 兼容未被破坏）。无第二份来源推断实现。
- 单一实现仍成立：算分 `history.score_of`、短板聚类 `diagnosis.build_shortfalls`、润色提示词 `POLISH_SYSTEM`、`.md` 渲染 `markdown.to_markdown`、岗位模型数据 `seed/role_models.json`——本轮检查器与门禁都从这些入口读取，未发现第二份拷贝。
- 新服务未复制闭集字面量（门禁 40，且变异自检证明非空转）；样式只 append（门禁 39 在删一行时 FAIL，说明不是空断言）。
- 观察（不阻断）：`weakness` 依赖 `diagnosis._scored` 私有函数（TECH 指定的唯一题源，改名会静默断裂，已有哨兵用例兜底）；`role_fit` 自行实现岗位名 `lower()` 归一（TECH §3.3 显式规定该匹配口径）。
- **无 P1 架构缺陷**。

## 10. 人工补测清单（环境限制，非交付缺陷）

| # | 项 | 验收点 | 方法/工具 |
|---|---|---|---|
| 1 | 真实浏览器滚动 + 焦点高亮 | 点「去改这一条」后平滑滚动并高亮命中卡 | Chrome/Edge 打开报告页 → `/polish?focus=…`，肉眼 + DevTools Elements 看 `is-focused` |
| 2 | `prefers-reduced-motion` 动效 | 与 D-6 一起验收（平滑 vs 瞬时） | DevTools Rendering 面板模拟 reduced-motion |
| 3 | 390px 真机窄屏 | 无横向滚动、堆叠序 薄弱→简历→竞争力 | DevTools 设备模式 390×844 + 真机各一次 |
| 4 | 真实 AI（有 Key）0 错题组 | AI 改写后的 summary 仍不得出现「错题」矛盾；三块结构不增删条目 | `backend/.env` 配 Key 后跑一次真实面试+笔试，再生成报告导出 `.md` |
| 5 | 屏幕阅读器 | 三块 `<section aria-labelledby>` 朗读顺序与标题 | NVDA / VoiceOver |

## 11. 结论

**可验收**。上轮 2 条 P2 已按原文检测命令复验关闭（functional 91/0、两条新门禁通过且回退时 FAIL、`.md` 同源文案正确、AC-8 兼容未破）；本轮补测的两个面（门禁变异自检 10/10、修复契约 15/15）证明新增门禁非空转、修复不靠巧合。门禁全绿（pytest 297 / vitest 100 / typecheck 0 / lint 0 error 28 warn / build ok / `/health` 200 / NO_KEY_LEAK），架构无 P1，提交面无噪音。4 条 P3 开放项（D-3 口径确认 + D-4/D-5/D-6 工艺观察）均不阻断交付；真实浏览器、真机 390、真实 AI 与屏幕阅读器属环境限制，已列入人工补测清单。

## 12. 验证脚本清单

1. `cd backend && python -X utf8 ../logs/teamflow/tf-mvxhokwc-w1hxht/scripts/check_qa_r7_functional.py`
2. `cd backend && python -X utf8 ../logs/teamflow/tf-mvxhokwc-w1hxht/scripts/check_qa_r7_interface.py`
3. `cd backend && python -X utf8 ../logs/teamflow/tf-mvxhokwc-w1hxht/scripts/check_r7_gate_mutation.py`
4. `cd backend && python -X utf8 ../logs/teamflow/tf-mvxhokwc-w1hxht/scripts/check_r7_fix_contract.py`
5. `cd frontend && NODE_PATH=$PWD/node_modules node ../logs/teamflow/tf-mvxhokwc-w1hxht/scripts/check_qa_r7_ui.cjs`
6. `cd backend && python -X utf8 ../logs/teamflow/tf-mvxhokwc-w1hxht/scripts/check_qa_r7_bad_seed.py`
7. `cd backend && python -m pytest -p no:cacheprovider`
8. `cd frontend && npm run typecheck && npm run lint && npm test && npm run build`
9. `cd backend && DB_PATH=tests/.tmp/qa-boot-r7b.db AI_API_KEY= python -m uvicorn app.main:app --port 8126` + `curl -sS http://127.0.0.1:8126/health`
