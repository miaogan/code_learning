<!-- meta: summary="r4 验收：r3 的 4 条遗留（R-1 原版 Tab 真源、D-2 导出文件名、D-3 死代码、D-4 历史能力项入口）全部闭合，AC-1~AC-14 逐条有验收人复跑证据，r3 行为零回归（合并行为哈希双树相同），架构一致性无返工项 → 判定「✅ 通过」。" -->

# ACCEPTANCE · r4 · r3 验收遗留项闭合（R-1 / D-2 / D-3 / D-4）

- 任务夹：`docs/teamflow/20261101-r4-r3-acceptance-closure/`
- 基线依赖：`docs/teamflow/20261031-r3-memory-resume-polish/`（r3 15 条 AC 不得回归）
- 被测对象：**工作树未提交改动**（分支 `feat/dev-skill-coach` 原地继续）；HEAD `611643d` 副本仅用于 D-3 删前/删后对比
- 验收时间：2026-11-01　验收角色：产品经理（验收负责人）
- 证据分工：**【验】= 验收人本机亲自复跑并读结果**；**【交】= 交叉验证 QA-REPORT 的运行态数值**（浏览器内测量项、肉眼项，本阶段未重建浏览器会话）
- 检查器位置：`logs/teamflow/tf-mvwmyqwa-j9rvt4/scripts/`（由 host 归档，按团队约定不进仓库）

## 0. 结论

**通过**。14 条 AC 逐条有已执行证据；r3 遗留的 4 条（R-1 原版 Tab 真源、D-2 导出文件名、D-3 死分支与双份模型、D-4 历史能力项入口）全部闭合，且 r3 行为**零回归**（合并行为哈希在当前树与 HEAD 副本上完全相同）。架构一致性核查（M3）无蓝图偏离、无新增重复实现、无结构破坏，**无返工项**。QA 报告的 4 条 P3 均不阻断（2 条为口径差异、2 条为本轮未触及的既有结构）；6 项人工补测属环境限制，非交付缺陷。

## 1. 验收方法

1. **先读契约**：PRD §2 的 AC-1~AC-14、§3 范围/非目标、§4 反面目标、§9 工程约束与出口口径；TECHNICAL §9 改动面白名单与 §10 AC 映射。
2. **再复跑**：验收人不依赖 QA 的"结论"，对 6 类可独立判定的门禁与检查器全部亲自执行（见 §4 汇总）。
3. **交叉验证**：仅对需要浏览器运行态数值的判据（AC-2/3/4 的字符数与滚动高、AC-11/12 的焦点与条高、AC-7/8 的实际导出名）引用 QA 实测值，并**在代码层独立确认同一判据的实现根因**（见逐条表的两列证据）。
4. **前置确认**：`git status --porcelain=v1 -uall` 20 项改动面、无新依赖、无构建产物混入。

## 2. 逐条 AC 验收

| AC | 判据 | 验收证据（实跑命令 / 实读代码 → 结果） | 判定 |
|---|---|---|---|
| **AC-1** | 契约补 `resume_text`，与 `documents.text` 字节相等，双侧同步 | 【验】`check_polish_contract.py` → 8/8 PASS：`PolishResponse` 属性序 `['polish_id','resume_id','target_role','resume_text','file_name','suggestions','dropped_count','insufficient_reason']`、`resume_text` 在 `required` 内、`/polish/full` 字段集未扩；`check_qa_r4_functional.py` → 29/29 含 `rt.encode('utf-8') == db_text.encode('utf-8')`；【验】实读 `schemas.py:326-333` 与 `types.ts:299-301` 字段名/顺序/类型一致（snake_case 零转换） | **PASS** |
| **AC-2** | 原版 Tab 文本 === `resume_text`；`buildOriginal` 删除 | 【验】`grep -rn "buildOriginal" frontend/src` → **0 命中**；`check_r4_t2_t3_frontend.cjs` → A1 PASS（SSR 真组件：“plain 单节点渲染，`textContent` 与 `resume_text` **89 字符逐字相等** · 前缀保留 · 只读”）；【验】`ComposePreview.tsx:63-115` 确认 `mode='original'` 走 plain 分支而非 `renderMarkdown()`；【交】真实浏览器 短简历 104/104、长简历 1472/1472 逐字相等 | **PASS** |
| **AC-3** | 仅覆盖 k 段、N>k 时原版仍按序含全部 N 段 | 【验】`check_qa_r4_functional.py` 命中“AC-3 仅覆盖 k=3 段时，原版仍按序含全部 N=7 段”；【交】后端+前端双证：k=3/N=7 命中位置 `[0,14,19,44,49,71,74]` 单调递增；长简历 40 段全部命中（含未被建议覆盖的段落） | **PASS** |
| **AC-4** | 只读 + 容器内滚动 + 高度用 tokens 上限 + 两 Tab 等高 | 【验】实读 `base.css:1977-1997`：`.sc-compose-body { height: var(--polish-prev-h)（428）; overflow-y:auto; overscroll-behavior:contain }`，`.is-plain` 只加 `pre-wrap`（不另设高度 → 两 Tab 天然等高，TECHNICAL §2 的设计意图成立）；`check_r4_t2_t3_frontend.cjs` C7 → 样式规则齐备；【交】容器 `clientHeight 426 / scrollHeight 1792`（自身可滚动）、输入类元素 0、两 Tab 面板高均 456、页面总高 1080 与短简历一致 | **PASS** |
| **AC-5** | 成稿/导出/复制仍取服务端 `markdown` 裸传，`resume_text` 不参与拼装 | 【验】实读 `PolishPage.tsx:277` → `new Blob([full.markdown], {type:'text/markdown;charset=utf-8'})` 原样；`check_polish_contract.py` → “`PolishFullResponse` 字段集未扩 `['id','markdown','dropped_count','regenerated']`”；`check_qa_r4_functional.py` → “`/polish/full` 不带 `resume_text`”；`check_copy_behavior.cjs` → 6 PASS/0 FAIL（r2 复制/导出无回归）；【交】Blob 文本 === 网络响应 `markdown` 1472/1472 | **PASS** |
| **AC-6** | 三态不白屏，中文占位或 InlineError | 【验】`PolishPage.tsx:468` 中文占位「这份简历没有可显示的正文，请重新上传后再试。」；`ComposePreview` 有 `emptyText` prop + 缺省中文 `EMPTY_PREVIEW`；checker A3 PASS（空正文用中文 emptyText，不出现空白右栏）；【验】空正文真值路径 → 400 `VALIDATION_ERROR` 中文 message「这份简历没有可润色的正文，请换一份可复制文本的文件重试」 | **PASS** |
| **AC-7** | 导出名 = `简历润色-<原文件名去扩展名>.md`，来源为契约 `file_name` | 【验】实读 `PolishPage.tsx:278` → `anchor.download = exportFileName(session?.fileName)`（非前端自造、非日期常量）；`EXPORT_PREFIX='简历润色-'` 只在 `lib/exportName.ts:13`；泛查 `grep -rn "简历润色-" frontend/src/pages/PolishPage.tsx` 仅命中页面标题 `h1`（无命名规则遗留）；【交】`长简历-5屏.txt` → `简历润色-长简历-5屏.md`，且契约 `file_name` 与库内 `documents.file_name` 相等 | **PASS** |
| **AC-8** | 空/缺失/脏名回退日期格式 + 路径与保留字符清洗 + 120 字符上限，不报错 | 【验】逐条读 `lib/exportName.ts:31-85` 七步：null/空白→`''`（回退日期）→按 `/`/`\` 取基名→剥 `<>:"/\|?*` 与 C0→去已知简历扩展名→去尾点→`Array.from` 按 **code point** 截 120→`EXPORT_PREFIX+base+'.md'`；【验】`npm test` → 16 条断言覆盖 8 组（正常/路径/脏字符/空/无扩展名/超长/尾点/大小写）；checker D1 PASS；【交】4 组实测：`a/b?简历2026:.txt`→`简历润色-b简历2026.md`、空名→`简历润色-2026-11-01.md`、140 字原名→基名 120 code point 未腰斩 | **PASS** |
| **AC-9** | `profile_merge` 零死记号、零 `BaseModel` 子类、import 成功 | 【验】`grep -rn "CONTRACT_READY\|_FallbackEvidence\|MergedProfile\|MergedSkill\|MergedProject" backend/app backend/tests` → **0 命中**；`python -c "import app.services.profile_merge"` → 成功；【验】模块内类定义只有 `_EvidenceSource(NamedTuple)`（**非** pydantic 模型），`BaseModel` 子类 **0**、`pydantic` 建模 import 已移除；`check_d3_dead_code.py` → **13/13 PASS**（含 HEAD 侧 `if CONTRACT_READY:` 与三个别名的存在性对照） | **PASS** |
| **AC-10** | 删后合并/historical/duplicate 行为不变；pytest ≥113 全绿 | 【验】`python -m pytest -p no:cacheprovider` → **118 passed in 4.41s**（基线 113，只增不减）；【验】`check_merge_behavior_parity.py --backend .` 与 `--backend probe/head/backend` 双跑：5 个场景哈希逐一致，`COMBINED` 两边同为 `913ceccea3cf69b856caa53ffad99c3b7f5168c6d8284508d9592bd92b2199cd`（**行为零漂移**，含 `historical` 隔离与 `duplicate` 标记） | **PASS** |
| **AC-11** | 摘要条按钮：展开 + 滚动进视口 + 焦点落容器 + `aria-controls` | 【验】`MergeSummaryBar.tsx:30-49`：`showAction = historyCount > 0 && onViewHistory !== undefined`、`aria-controls={historyControls.join(' ')}`、secondary 按钮；`ProfilePage.tsx:93-96` `HISTORY_GROUP_ID` 单一常量（按钮 controls 与容器 id 同源，零字符串漂移）、`:450-470` `viewHistory` 展开两分组 + `historyJump` 计数器，effect 内 `scrollIntoView({block:'center'})` → `focus({preventScroll:true})`、`:560-570` 容器 `id`/`ref`/`tabIndex={-1}` 且仅在 `historical.length > 0` 渲染（与 controls 过滤一一对齐，不存在指向不存在元素的 `aria-controls`）；checker B1/C5 PASS；【交】点击后两分组 `aria-expanded=true`、焦点 `#profile-history-skills`、分组 `rect.top 404` 落在视口内 | **PASS** |
| **AC-12** | 0 项不渲染、键盘可达有焦点环、条 48 高不换行 | 【验】checker B2 PASS（“0 / 缺省 / 传了 controls 也不渲染”）；C6 PASS：`2 + (4-1)*2 + 40 = 48 = --merge-bar-h`（border-box 已按 1px 边框补偿）；`base.css` 新增 5 条规则：`.has-action{flex-wrap:nowrap; padding-block:calc(var(--sp-1) - 1px)}`、文本 `min-width:0/ellipsis/nowrap`、按钮 `flex:0 0 auto`、焦点环 `outline:2px solid var(--accent)` 只取 token；【交】0 项时按钮数 0、条高实测 48、真实 Tab 键到按钮得焦点环 `2px rgb(77,163,255)`、有按钮时 `nowrap` + 省略且条高 48 | **PASS** |
| **AC-13** | 门禁全绿（含无裸色值/CSS 注释） | 【验】`npm run typecheck` → exit 0（`tsc -p tsconfig.json` 与 `tsconfig.node.json` 双跑）；`npm run lint` → **0 error / 28 warning**（与基线 28 同值、无新增）；`npm test` → **23 passed**（6 文件面 ≥7）；`npm run build` → **✓ built**（`index-*.js 248.62 kB` / `index-*.css 40.20 kB`）；`pytest tests/test_engineering_gates.py` → **6 passed**（裸色值断言扫注释）；`check_copy_behavior.cjs` → **6 PASS/0 FAIL**；`check_gitignore_audit.sh` → **24 PASS/0 FAIL** | **PASS** |
| **AC-14** | 改动面白名单内、无新依赖、错误 envelope 中文、`/health` 200、四步闭环与 r3 不回归 | 【验】`git status --porcelain=v1 -uall` → **20 项**，逐个比对 TECHNICAL §9：T1（`schemas.py`/`routers/resume.py`/`test_resume_polish.py`）、T2（`types.ts`/`lib/exportName.ts`*/`test/exportName.test.ts`*/`ComposePreview.tsx`/`PolishPage.tsx`/`base.css`）、T3（`MergeSummaryBar.tsx`/`ProfilePage.tsx`）、T4（`profile_merge.py`/`routers/profile.py`/`test_profile_merge.py`）、T5（`.gitignore`）、任务夹 4 文件 + `memory.md`（产品级约定文件），**全部命中、无越界文件**；【验】`git diff --stat` 对 `package.json`/`package-lock.json`/`requirements.txt` **为空**（无新依赖）；【验】TestClient：`/health` → **200 ok**、`/api/courses` → 200、`POST /api/resumes/none-x/polish` → 404 `NOT_FOUND`「没有找到这份简历，请重新上传后再润色」；OpenAPI 润色路径仍为**原 2 条**（`/polish`、`/polish/full`，无新增路由）；【验】行为不回归见 AC-10 双树哈希一致 | **PASS** |

## 3. 架构一致性核查（M3 · 强制）

本轮**无架构蓝图注入**，按「蓝图偏离 / 重复实现 / 结构破坏」三项核查：

| 核查项 | 结论 | 依据 |
|---|---|---|
| 契约单源 | ✅ 无双写 | `PolishResponse` 双侧 8 字段同序同名（`check_qa_r4_interface_parity.py` **26/26**、`check_r4_t2_t3_frontend.cjs` C4 “镜像字段 8 个且顺序一致”）；服务端一次 `repository.get_document` 回填 `text`/`file_name`，无第二处构造点（contract checker「`_load_resume` 定义唯一 / `PolishResponse` 构造唯一」） |
| 模型单源 | ✅ 无双份定义 | 死记号 0 命中、`BaseModel` 子类 0、模块内仅 `NamedTuple`；`profile_merge` 的 `Evidence/ProfileMergeSummary/ProfileWithMerge/Profile` **与 `schemas` 同对象**（13/13 含 `is` 断言） |
| 命名单源 | ✅ 无重复规则 | 导出名规则只在 `lib/exportName.ts`（页面零规则、`checker C2`）；`HISTORY_GROUP_ID` 一处常量供 `aria-controls` 与容器 `id` |
| 装配/接线 | ✅ 显式无隐式默认 | `ProfilePage.tsx:615-620` 三个新 prop（`historyCount`/`historyControls`/`onViewHistory`）**全部显式传入**且与 `MergeSummaryBar` 接口声明一一对应（无「声明了但没传」的半成品） |
| 抽象缺失 | ✅ 未发现 | R-1/D-2 走既有读路径与既有 `.sc-compose-body`，不新建组件/路由/表（新增路由 0、新 SQL 0）；D-4 复用摘要条槽位与既有折叠 chip，未新增信息架构 |
| 结构破坏 | ✅ 未发现 | 删除面仅限死分支与别名；`git diff` 无白名单外文件；样式只增 5 条规则且只引 token，`--merge-bar-h` 等既有 token 未被改写（C6） |

**M3 判定：无返工项。** 未发现「动过设计的兼容壳残留」「同一规则两份实现」「跨模块耦合被破坏」。两处**既有**轻微重复（`backend/app/services/profile.py:150` 恒真防御分支、`ReportPage.tsx` 自持的 `markdownFileName()`）均在本轮白名单之外、未因本轮改动漂移，记入 §5 P3。

## 4. 门禁实测汇总（验收人本机复跑）

| 门禁 | 命令 | 实测 | 基线 | 判定 |
|---|---|---|---|---|
| 后端测试 | `cd backend && python -m pytest -p no:cacheprovider` | **118 passed in 4.41s**，exit 0 | 113 | ✅ 只增不减 |
| 前端 typecheck | `cd frontend && npm run typecheck` | exit 0（双 tsconfig） | 0 error | ✅ |
| 前端 lint | `npm run lint` | **0 error / 28 warning** | 0 error / 28 warning | ✅ 无新增 |
| 前端单测 | `npm test` | **23 passed**（2 文件；新增 exportName 16 条） | ≥7 | ✅ |
| 前端构建 | `npm run build` | ✓ built 745ms（248.62 kB js / 40.20 kB css） | 通过 | ✅ |
| 工程门禁测试 | `pytest tests/test_engineering_gates.py -q` | **6 passed**（裸色值断言含 CSS 注释） | 绿 | ✅ |
| 契约检查器 | `check_polish_contract.py` | **8/8 PASS** | — | ✅ |
| 死代码检查器 | `check_d3_dead_code.py` | **13/13 PASS** | — | ✅ |
| 合并行为平价 | `check_merge_behavior_parity.py --backend .` / `probe/head/backend` | 双树 `COMBINED` 同为 `913cecce…`，5/5 场景一致 | 行为等价 | ✅ 零漂移 |
| r2 复制/导出 | `check_copy_behavior.cjs` | **6 PASS / 0 FAIL** | 6/6 | ✅ |
| 前端回归检查器 | `check_r4_t2_t3_frontend.cjs`（SSR 真组件 + 源码契约 + 样式算术） | **14/14 PASS** | — | ✅ |
| QA 功能级 HTTP | `check_qa_r4_functional.py` | **29/29 PASS** | — | ✅ |
| 接口一致性 | `check_qa_r4_interface_parity.py` | **26/26 PASS** | — | ✅ |
| gitignore 审计 | `check_gitignore_audit.sh` | **24 PASS / 0 FAIL** | — | ✅ |
| 探活/错误形态 | TestClient `/health`、`/api/courses`、润色 404 | 200 / 200 / 404 `NOT_FOUND` 中文 | — | ✅ |

## 5. 遗留与观察（均不阻断本次判定）

**P3（承接 QA，验收人复核确认成立，2 条为本轮未触及的既有结构）**

| 编号 | 问题 | 验收意见 |
|---|---|---|
| A-1 | `.has-action` 的 48 高实现为 `calc(var(--sp-1) - 1px)`（3px），DESIGN（r3）§0.5-4 推导写 `sp-3`（12px）+正文 22 | **实现正确、设计推导过时**：`.sc-merge-bar` 是 border-box 且 2px 边框，`sp-3` 版实测 50 高。已写入 `memory.md` 待办：回写 DESIGN 推导 |
| A-2 | `backend/app/services/profile.py:150` `if "merge_summary" in getattr(ProfileWithMerge, "model_fields", {})` 恒真 | 该文件本轮 READ-ONLY、不在白名单，**未改**；已写入 `memory.md` 待办，后续删除或补注释 |
| A-3 | `ReportPage.tsx` 仍自持 `markdownFileName()` 与 `lib/exportName.ts` 同类规则 | 两处各管一功能（诊断报告 / 简历润色），本轮**未引入重复**、未阻塞；抽出公共 sanitizer 留后续需求 |
| A-4 | 「原版」tabpanel 的 `textContent` 含 meta 前缀「原版 · 逐字取自简历正文」 | 正文容器 `.sc-compose-body` 内逐字相等（AC-2 判据成立）；读屏连读属 r3 既有提示结构，可后续优化 |

**人工补测清单（环境限制，非交付缺陷）**

1. `python -m ruff check app tests` → 本机 `No module named ruff`（按环境策略未重试）；需开发机补跑，判据 0 error。
2. 真实 AI + 真实 Key 的四步闭环计时：本轮 AI 走零网络类级补丁，仅探活与错误形态走真进程；真实 Key 留人工。
3. 真实浏览器**落盘**（本次仅断言 `download` 名与 Blob 文本，未验证写盘路径），需人工在 Chrome/Edge 各导一次。
4. 屏幕阅读器语音播报（`aria-controls`/`aria-expanded`/焦点转移）。
5. 视觉手感（hover/动画/间距目测）。

## 6. 变更面与提交面审计

- **改动面**：14 改 + 2 新（`frontend/src/lib/exportName.ts`、`frontend/src/test/exportName.test.ts`）+ 本任务夹 4 文件 + `docs/teamflow/memory.md`，逐项命中 TECHNICAL §9 白名单，**零越界**（见 AC-14 证据）。
- **无新依赖**：`package.json`/`package-lock.json`/`backend/requirements.txt` 的 `git diff --stat` 为空。
- **提交面洁净**：`git status` 无 `dist/`、`node_modules/`、`__pycache__/`、`*.db`、`.env`、无根目录脚本；检查器与日志全部在 `logs/teamflow/<runId>/`（gitignored、由 host 归档）。
- **`.gitignore` 审计结论（PRD §9 要求）**：**补 2 条**——把 `backend/.pytest_cache/`、`backend/.ruff_cache/` 收敛为通用 `.pytest_cache/`、`.ruff_cache/`（覆盖 backend 运行与根目录/插件落点）；**确认本来就已覆盖**——`__pycache__/`(18)、`dist/`(11)、`node_modules/`(8) 与 `node_modules-*/`、`*.db` 及 SQLite 旁路 `*.db-wal`/`*.db-shm`/`*.db-journal`(32-34)、`.venv/`、`.env` 且 `!.env.example`(41-43)、`logs/teamflow/`(2)；**未新增无关条目**（`target/`、`.pnpm-store` 不属本栈）。

## 7. 口径确认（验收定稿，关闭 PRD §10 的 fact 待澄清）

1. **导出文件名保留「简历润色-」前缀**：按 DESIGN §284 原文口径与 AC-7 判据**采纳**（`简历润色-<原文件名>.md`），改名只需动 `frontend/src/lib/exportName.ts` 的 `EXPORT_PREFIX` 一处；本轮以此为准验收。
2. **「查看历史能力项」交互形态**：采纳推荐方案①（仅展开 + 滚动定位 + 焦点，不临时高亮、不弹层），符合「不做新功能」约束，已实现并验收。
3. **「原版」Tab 高度策略**：采纳推荐方案①（与「润色版」等高、容器内滚动），实测两 Tab 等高且页面不被正文拉长。

## 8. 验收意见

r3 的「⚠️ 有条件通过」已完整闭合为「通过」：唯一阻塞项 R-1 按设计补齐真实正文（不再是降级设计），D-2/D-3/D-4 同步收口，且**没有以"测试变绿"掩盖产品问题**——AC-3 的「未改写段落是否还在」与 AC-10 的「删代码后溯源是否断裂」两条反面目标均以可判定证据守住。本轮无新增功能、无越界改动、无回归，判定通过；§5 的 4 条 P3 与 5 项人工补测转后续轮次清理，不阻塞交付。

验收结论：✅ 通过
