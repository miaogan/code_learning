# QA-REPORT · r4 r3 验收遗留项闭合（R-1 / D-2 / D-3 / D-4）

任务夹：`docs/teamflow/20261101-r4-r3-acceptance-closure/`　基线依赖：`docs/teamflow/20261031-r3-memory-resume-polish/`
分支：`feat/dev-skill-coach`（原地，未提交）　测试时间：2026-11-01

## 0. 结论（先看这里）

**可验收（通过）**。14 条 AC 全部有**已执行**证据，无 P0/P1/P2 缺陷；4 条 P3 观察项（均不阻断，属后续收口/口径确认）。

关键判断：R-1 与 D-2 的读路径缺口确已闭合——润色响应 `resume_text` 与库内 `documents.text` **字节级相等**（真 HTTP + 直读 SQLite 双证），原版 Tab 在真实浏览器里对 104 字符短简历与 1472 字符长简历**都逐字相等**，且 40 段全部按序命中；导出名在 4 组文件名下全部落地为可读 `.md`。

## 1. 范围与环境

- 测的是交付本身（工作树未提交改动），不是 HEAD；HEAD 副本仅用于 D-3 删前/删后行为对比。
- 环境：Windows / Python 3.13 / Node + Vite 5 / React 18；后端真进程 `uvicorn`（临时库 `tests/.tmp/qa-boot.db`）+ `TestClient`（真实 app、AI 走零网络类级补丁）；前端 `frontend/dist` 真实构建产物，经本地桩服务（`scripts/serve_r4_stub.mjs`）在**真实浏览器**里跑主路径（本会话浏览器可用，非沙箱受限）。
- 本阶段自有检查器（可复跑，均在本 run 的 `logs/teamflow/tf-mvwmyqwa-j9rvt4/scripts/`）：`check_qa_r4_functional.py`（HTTP 端到端 29 条）、`check_qa_r4_interface_parity.py`（跨模块接口一致性 26 条）；并复用/复跑既有检查器 `check_polish_contract.py`、`check_d3_dead_code.py`、`check_merge_behavior_parity.py`、`check_r4_t2_t3_frontend.cjs`、`check_copy_behavior.cjs`、`check_gitignore_audit.sh`。

## 2. 用例与结果

| AC | 结论 | 执行证据（命令 / 断言 + 实测值） |
|---|---|---|
| AC-1 契约补 `resume_text`，字节相等 | PASS | `cd backend && python -X utf8 ../logs/teamflow/tf-mvwmyqwa-j9rvt4/scripts/check_qa_r4_functional.py` → 29/29 PASS；`resume_text` 104 字符与 `SELECT text FROM documents` 逐字相等（`encode('utf-8')` 全等），无 trim/归一 |
| AC-2 原版 Tab 逐字、`buildOriginal` 删除 | PASS | 真实浏览器：原版面板 `.sc-compose-body` `textContent` === `resume_text`（短简历 104/104、长简历 1472/1472）；`grep -rn "buildOriginal" frontend/src` → 0 命中 |
| AC-3 仅覆盖 k 段时仍含全部 N 段 | PASS | 后端 + 前端双证：k=3 / N=7 时原版 7 段 `indexOf` 命中位置 `[0,14,19,44,49,71,74]` 单调递增；长简历 40 段全部命中（含未被建议覆盖的段落） |
| AC-4 只读 + 容器内滚动 + 高度 token 上限 + 两 Tab 等高 | PASS | 长简历（1472 字符）：容器 `clientHeight 426` / `scrollHeight 1792` → 自身可滚动；`overflow-y: auto`；输入类元素 0 个；高度源 `height: var(--polish-prev-h)`（token）；两 Tab 面板高度均 456，页面总高 1080 与短简历一致（未被正文拉长） |
| AC-5 成稿/导出/复制仍取服务端 `markdown`，`resume_text` 不参与拼装 | PASS | `/polish/full` 响应键集 `['dropped_count','id','markdown','regenerated']`（无 `resume_text`，原始响应体 grep 也无该字样）；浏览器拦截 `URL.createObjectURL`：Blob 文本 === 网络响应 `markdown`（1472/1472），导出仍 `new Blob([full.markdown])`；r2 检查器 6 PASS |
| AC-6 三态不白屏（中文占位/InlineError） | PASS | 覆盖 fetch 令 `resume_text=''` 后原版面板显示中文占位「这份简历没有可显示的正文，请重新上传后再试。」（22 字符，无空面板、无英文异常）；空正文后端返 400 `VALIDATION_ERROR` 中文 |
| AC-7 导出名 = `简历润色-<原名去扩展名>.md`，来源 `file_name` | PASS | 浏览器：上传 `长简历-5屏.txt` → 导出 `简历润色-长简历-5屏.md`；契约 `file_name` 与库内 `documents.file_name` 相等（非前端自造） |
| AC-8 空/脏名回退与清洗、120 上限 | PASS | 4 组实测：`a/b?简历2026:.txt` → `简历润色-b简历2026.md`（路径段剥离 + `?`/`:` 清除）；空名（桩标记）→ `简历润色-2026-11-01.md`（日期回退，不报错）；140 字原名 → 基名 120 code point（按字符非字节，中文未腰斩）；`简历.PDF` 等大小写扩展名 vitest 覆盖 |
| AC-9 `profile_merge` 零死记号、零 `BaseModel` 子类、import 成功 | PASS | `grep -rn "CONTRACT_READY\|_Fallback\|MergedProfile\|MergedSkill\|MergedProject" backend/app backend/tests --include=*.py` → `DEAD_CODE_GONE`；`check_d3_dead_code.py` → 13/13 PASS（含 HEAD 别名等价性 `is` 断言） |
| AC-10 删后合并/historical/duplicate 行为不变，pytest ≥113 全绿 | PASS | `check_merge_behavior_parity.py` 在**当前树**与 `probe/head/backend`（HEAD）各跑一遍：`COMBINED` 哈希两边完全相同 `913cecce…`（5/5 场景哈希一致 = 行为零漂移）；`cd backend && python -m pytest -p no:cacheprovider -q` → **118 passed**（基线 113，只增不减） |
| AC-11 历史能力项入口：展开 + 滚动进视口 + 焦点落容器 + `aria-controls` | PASS | 真实浏览器：按钮 `aria-controls="profile-history-skills profile-history-projects"`；点击后两分组 `aria-expanded` 均 `true`、焦点 = `#profile-history-skills`（`tabindex=-1`）、分组 rect.top 404 落在视口内 |
| AC-12 0 项不渲染 / 键盘可达有焦点环 / 48 高不换行 | PASS | 0 历史项（`nohist` 变体）：按钮数 **0**、条无 `has-action`、条高仍 48；键盘路径用**真实 Tab 键**从上一焦点位移焦 → 按钮获得 `outline: 2px solid rgb(77,163,255)` + `offset 2px`；有按钮时 `flex-wrap: nowrap` + 文本省略，条高实测 **48** |
| AC-13 门禁全绿（含无裸色值/注释） | PASS | `npm run typecheck` → 0 error；`npm run lint` → **0 error / 28 warning**（与基线同为 28，无新增）；`npm test` → 23 passed（≥7）；`npm run build` → ✓ built（248.62 kB js / 40.20 kB css）；`pytest` 118；r2 `check_copy_behavior.cjs` → 6 PASS/0 FAIL；`pytest tests/test_engineering_gates.py` → 6 passed（裸色值断言含 CSS 注释） |
| AC-14 改动面/无新依赖/错误 envelope/`/health`/四步闭环不回归 | PASS | `git status --porcelain=v1 -uall` → 14 改 + 2 新前端 + 任务夹，全部落 TECH §9 白名单；`git diff --stat` 对 `package.json`/`package-lock.json`/`requirements.txt` 为空（无新依赖）；真进程 `uvicorn` 启动后 `curl /health` 200、`/api/courses` 200、`/openapi.json` 200，润色路由仍为原 2 条（未新增）；r3 服务层行为经 118 passed 覆盖 |
| AC-15 无登录/前端无 Key/`/health` 200/错误 envelope 中文 | PASS | `grep -riE "sk-\|api_key\|AI_API_KEY" frontend/src frontend/dist` → `NO_KEY_LEAK`；真进程 `/health` 200（`{"status":"ok",...}`）；`POST /api/resumes/none-x/polish` → 404 `{"code":"NOT_FOUND","message":"没有找到这份简历，请重新上传后再润色"}`（中文、无端点/堆栈/Key） |

**提交面洁净（0c）**：`git status` 无 `dist/`、`node_modules/`、`__pycache__/`、`*.db`、`.env`、无根目录脚本；`git check-ignore` 实测 `frontend/dist`、`logs/teamflow`、`frontend/node_modules`、`backend/tests/.tmp`、`backend/app.db` 均被忽略；`.gitignore` 审计 `check_gitignore_audit.sh` → 24/24 PASS。

**架构检查（M3）**：无蓝图被注入，按「重复实现/抽象缺失/结构破坏」三项核；契约单源（`PolishResponse` 双侧字段同序同名，`check_qa_r4_interface_parity.py` 26/26）、模型单源（AC-9）、导出命名单源（`lib/exportName.ts`，页面内零第二份规则）、`ProfilePage → MergeSummaryBar` 三 prop 全部真实声明且被显式传入。未发现重复实现或结构破坏；两处**既有**轻微重复见 P3 表。

## 3. 缺陷表

**P0 / P1 / P2：未发现缺陷。**

| 编号 | 严重级 | 功能模块 | 复现步骤 | 期望行为 | 实际行为 | 关联验收项 | 检测命令 | 通过判据 |
|---|---|---|---|---|---|---|---|---|
| D-QA-1 | P3 | 样式（摘要条） | 查看 `base.css` `.sc-merge-bar.has-action` | 按 DESIGN r3 §0.5-4 推导为 `padding: var(--sp-3)`（12px）+ 正文 22 → 48 | 实现改为 `padding: calc(var(--sp-1) - 1px)`（3px）以满足 border-box 下含 40 高按钮仍为 48 | AC-12 | 运行态量高：浏览器 `getBoundingClientRect().height` | 已达标 48；属口径差异，建议回写 DESIGN 推导 |
| D-QA-2 | P3 | 架构（后端） | 读 `backend/app/services/profile.py:150` | 删掉兼容层后不应保留恒真防御分支 | `if "merge_summary" in getattr(ProfileWithMerge, "model_fields", {})` 恒真，为历史防御残留 | AC-9 / AC-14 | `sed -n '145,155p' backend/app/services/profile.py` | 该文件本轮 READ-ONLY 且不在白名单，未改；后续应删该分支或加注释 |
| D-QA-3 | P3 | 架构（前端） | 对比 `frontend/src/lib/exportName.ts` 与 `frontend/src/pages/ReportPage.tsx:39-43` | 文件名清洗应单源 | 润色用 `lib/exportName.ts`（新，单源），诊断报告仍是页面内 `markdownFileName()` 自持规则（本轮未引入重复） | AC-14 | `grep -rn "简历润色-\|诊断报告-" frontend/src` | 两处各管一功能、未互相漂移；未来可抽公共 sanitizer |
| D-QA-4 | P3 | 交互（可达性） | 用读屏语义读「原版」tabpanel | tabpanel 的文本应只含正文 | `tabpanel.textContent` 含 Tab meta 前缀「原版 · 逐字取自简历正文」（13 字符），读屏时 meta 与正文连读；属 r3 既有结构 | AC-2 | 浏览器 `panel.textContent.length` 117 vs 正文 104 | 正文容器 `.sc-compose-body` 内 104 字符逐字相等；仅提示结构可优化 |

## 4. 人工补测清单（环境限制，非交付缺陷）

1. **ruff 静态检查**：本机 `python -m ruff check app tests` → `No module named ruff`（环境缺依赖，按策略未重试）。方法：开发机执行同命令；判据 0 error。
2. **真实 AI + 真实后端的四步闭环回归**：本轮 AI 走零网络类级补丁（`AIClient.complete_model`），后端真进程仅探活 `/health`/`/api/courses`/错误 envelope。方法：配置 `backend/.env` 的真实 Key，走 上传→画像→面试/笔试→报告→润色 全链；判据 每步无中文外报错、数据贯通。
3. **真实文件落盘**：导出验证拦截了 `HTMLAnchorElement.click` 读 `download` 名（文件名与 Blob 文本已断言），**未验证浏览器实际写盘路径**。方法：人工在 Chrome/Edge 导出 4 组文件名；判据 均落地为可读 `.md`、无静默截断。
4. **屏幕阅读器**：`aria-controls`/`aria-expanded`/焦点转移的语音播报。方法：NVDA/VoiceOver 实测。
5. **产品口径确认**：导出名是否保留「简历润色-」前缀（PRD §10 openQuestion，当前按 DESIGN 原文带前缀）。方法：产品经理一句话确认；若改裸原名需同步改 `EXPORT_PREFIX` 与 DESIGN。
6. **视觉手感**（hover/动画/间距目测）：按钮已复用 `.sc-btn--secondary`（含 hover/active），焦点环已脚本断言；手感需人眼。

## 5. 备注（口径变化与误报说明）

- 本轮**修正**了一条历史断言口径：r3 期「原版 = `original_text` 拼接」的运行态期望与 DESIGN §240 不符，现口径改为「原版 === `resume_text`」；旧检查器 `check_r4_t2_t3_frontend.cjs` 已按新口径运行（14/14 PASS），本次 QA 未复活旧断言。
- QA 过程中自查出两条**我自己的**误报并已修正（非交付缺陷）：①把「被建议覆盖且已采纳」的段落错当成「未覆盖段落」断言成稿保留（修正为断言未覆盖段 `姓名/工作经历/项目经历/技能` 全部保留、采纳段以 `suggested_text` 落进成稿）；②按 `original_text` 全采纳后仍期望原文残留。修正后 `check_qa_r4_functional.py` 29/29 PASS。
- 桩服务的 `/polish/full` 用固定 `original_text` 做替换，对自定义正文不命中 → 桩返回的 markdown 恰好等于正文；因此「Blob === `markdown`」的证明以**网络响应 vs Blob 文本**为准（已逐字比对通过），不依赖该巧合。

## 6. 验收建议

可进入验收。若验收方坚持要求 28 条既有 lint warning 与 ruff 一并归零，请转下一轮非阻塞清理；本轮的 4 项遗留（R-1/D-2/D-3/D-4）均已闭合且不回归 r3。
