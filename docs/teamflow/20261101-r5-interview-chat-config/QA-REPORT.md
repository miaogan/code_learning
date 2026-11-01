# r5 质量报告（第 2 轮 · 修复后复测）

> 任务夹：`docs/teamflow/20261101-r5-interview-chat-config/`｜分支 `feat/dev-skill-coach`（未提交，34 项改动）｜runId `tf-mvx9f223-m8ms9l`
> 复测口径：第 1 轮 6 条缺陷各自留下的**检测命令 / 通过判据**原样复跑 + 上轮 6 个检查器全量重跑 + 只针对上轮**未覆盖**的面新增探针。

## 1. 结论

**通过（可验收）**。第 1 轮 6 条缺陷（D-1…D-6，1×P1 / 3×P2 / 2×P3）逐条按原文判据复跑，**全部关闭**；无 P0/P1/P2 开放项；2 条 P3 工艺观察（§4）不阻塞。

回归契约（上轮留下的检查器 = 本需求的回归合同）逐条重跑，计数与 dev 修复声明**逐项一致**：`pytest 140 passed`、`functional 65/65`、`REPLAY_IDEMPOTENCY_OK`、`parity 17 组 0 失败`、`engine 15 PASS/0 FAIL`、`projection 33/0`、`t5 render 57/0`、`t6 44/0`；前端 `typecheck 0`、`lint 0 error/28 warning`（=r4 基线，且门禁会跳）、`vitest 65`、`build ok`；`/health` 200、`NO_KEY_LEAK`、零新依赖、零新表。

本轮新增覆盖（上轮未碰的面）共 **35 条断言全通过**，并用真实浏览器复核了修复轮动过的页面主路径（配置 → 对话 → 结束态 → 刷新恢复 → 历史/报告）。

## 2. 范围与环境

- 环境：Windows 10 + Python 3.13 + Node（vite/vitest）+ **真实 Chromium（经 dsh browser 驱动，本轮实测可用）**。
- 后端证据：`fastapi.testclient.TestClient`（与生产同一份 `app` + lifespan）+ 临时 SQLite + 与 `AIClient.complete_model(system, user, model_cls, *, timeout_s)` **同签名**的替身（提示词是真实拼装产物，可逐字断言；零外网）。
- 前端证据三层：① vitest 纯函数 65 例 ② `react-dom/server` 真渲染检查器（t5 57 + t6 44）③ 真实浏览器交互（点击/输入/Ctrl+Enter/刷新/390px iframe）。
- **修复轮实际改动面**（按 mtime 判定）：`services/interview.py`、`services/rules.py`、`services/history.py`（13:21）、`tests/conftest.py`（13:20）、`chatModel.ts`、`setupModel.ts`（13:22）、`InterviewPage.tsx`、`ChatStream.tsx`、`TrendTable.tsx`（13:23）。**CSS 未动**（`base.css` 12:55、`tokens.css` 12:33 均早于第 1 轮 QA），故上轮的色彩/几何证据仍成立，本轮仍复测了 390px 不横向滚动。
- 沙箱不可用项：`python -m ruff check app tests` → `No module named ruff`（环境限制，非交付缺陷，列入 §6）。

## 3. 用例与结果

### A 组：第 1 轮缺陷逐条复验（原命令、原判据，不替代）

| 编号 | round-1 级 | 第 2 轮复跑结果（原样） | 原判据 | 判定 |
|---|---|---|---|---|
| D-1 后端测试套件红灯 | P1 | `pytest` → **140 passed in 7.96s**，exit 0（上轮 15 failed/121 passed） | exit 0 且 0 failed、≥118 passed | 关闭 |
| D-2 重放已答旧题被接受并改写分数 | P2 | `check_qa_r5_replay.py` → `REPLAY_IDEMPOTENCY_OK`；拒绝文案「这道题已经答过了…」status=400 | exit 0 且打印 REPLAY_IDEMPOTENCY_OK | 关闭 |
| D-3 lint 警告 39 > 上限 28 | P2 | `npm run lint` → `28 problems (0 errors, 28 warnings)` exit 0；`npx eslint . --max-warnings 27` → **exit 1** | 0 error 且 warning ≤28 | 关闭（且门禁会跳） |
| D-4 项目根散落 2 个 dump | P2 | `git status --porcelain=v1 -uall \| grep _r5_` → 无输出；根目录无 `*.txt` | 无输出 | 关闭 |
| D-5 settings 读侧两套解析器漂移 | P3 | 缺键 payload：会话/历史 `None`、`None`（上轮 `None` vs `中型`）；`rules.settings_or_none` 为唯一实现，`interview._settings_or_none` / `history._interviews_settings_of` 均为薄委托 | 两行结论一致 | 关闭 |
| D-6 文档多算 1 个 token | P3 | `grep -c "^  --iq-" tokens.css` → **7**；`TECHNICAL/DESIGN` 无「8 个 token」 | 与 DESIGN §0.2 列举数一致 | 关闭 |

**命中数对比**：D-1 失败用例 15 → 0；D-2 重放改写 1 → 0；D-3 警告 39 → 28（门禁 28）；D-4 根目录 dump 2 → 0；D-5 双解析器 2 → 1；D-6 文档口径不一致 5 处 → 0。**与修复轮自报一致，无分歧**。

### B 组：回归契约全量重跑（上轮 `scripts/` 的 6 个检查器 + 门禁）

| 检查器 | 第 2 轮计数 | 修复轮自报 | 一致 |
|---|---|---|---|
| `check_qa_r5_functional.py`（真实 HTTP+SQLite，AC-1~12/14/16） | 65 passed / 0 failed | 65 | ✅ |
| `check_qa_r5_replay.py`（AC-9/10 幂等） | `REPLAY_IDEMPOTENCY_OK` | OK | ✅ |
| `check_contract_parity.py`（双侧契约 17 组） | 17 组 / 0 失败 | 17/0 | ✅ |
| `check_interview_engine.py`（引擎闸门/配额/追问） | 15 PASS / 0 FAIL | 15/0 | ✅ |
| `check_t3_projection.py`（回溯投影 + 端到端 wire） | 33 PASSED / 0 FAILED | 33/0 | ✅ |
| `check_t5_interview_chat_render.tsx`（气泡/评分并置/汇总） | 57 passed / 0 failed | 57 | ✅ |
| `check_t6_styles_history.tsx`（设定条/时间线/报告） | 44 passed / 0 failed | 44 | ✅ |
| `backend pytest` | 140 passed | 140 | ✅ |
| `frontend typecheck / lint / test / build` | 0 / 0 error 28 warn / 65 / ok | 同 | ✅ |

### C 组：本轮新增面（上轮未覆盖，故必须新测）

上轮 A/B/C 三组覆盖的是**主路径**；下面 4 个面此前完全没测，且都是「修复动作可能带出问题」的相邻面：

| 用例组 | 结果 | 证据 |
|---|---|---|
| **404 家族**（不存在 run / 笔试 run 当面试读写 / 不存在画像开局） | 9/9 通过 | 新增 `check_qa_r5_edges.py` E1：404 + 中文 envelope、不泄漏 `/api/`·`Traceback`·`.py`、被拒时 `runs` 行数不变 |
| **终态只读**（已完成会话再提交） | 9/9 通过 | E3：推进到 completed（8~12 轮）→ 再提交 400「这场面试已经结束」、payload 逐字不变、**未多花一次 AI 调用**、仍可重复只读 |
| **非法输入零副作用**（不存在 question_id / 空串 / 纯空白 / 越界枚举） | 12/12 通过 | E2：404/400/422 均为中文 envelope，payload 与 AI 调用计数零变化，422 不落 run |
| **D-5 一般化**（多余未知键 / 缺键+多余键 / 全空串） | 5/5 通过 | E4：会话 / 历史 / 报告三处投影逐字一致；不达标一律 `None`（不补默认值） |
| **接口一致性（静态）** | 309 项 / 0 失败 | 新增 `check_qa_r5_interface.py`：AST 遍历 `app/`+`tests/` 全部 import 解析 + 交付面 30 个跨模块成员 + 3 组路由→service 签名；变异自检（注入 `bogus_member_probe`）→ `MUTATION_DETECTED`，证明非空转 |

### D 组：工程门禁（AC-15/16）

| 命令 | 结果 | 判据 |
|---|---|---|
| `cd backend && python -m pytest -p no:cacheprovider` | 140 passed（≥118） | 通过 |
| `cd frontend && npm run typecheck` | exit 0 | 通过 |
| `cd frontend && npm run lint` | 0 error / 28 warning（=r4 基线；`--max-warnings 27` → exit 1） | 通过 |
| `cd frontend && npm test` | 65 passed（4 文件，≥23） | 通过 |
| `cd frontend && npm run build` | `dist/assets/index-BxsLTLp5.js 258.78 kB`，built in 1.25s | 通过 |
| `cd backend && python -m ruff check app tests` | `No module named ruff` | 环境限制（§6） |
| 裸色值（r5 新增 CSS 段） | `sc-iq-*` 段无 hex/rgba，7 个 `--iq-*` token | 通过 |
| 依赖 / 表结构 | `package.json` 仅 `lint` 脚本加 `--max-warnings 28`，依赖零变化；无 `repository.py`/`db.py` 改动 | 通过 |
| `/health` | 真实 uvicorn `127.0.0.1:8123/health` → 200 `{"status":"ok",...,"ai_configured":false}` | 通过 |
| Key 泄漏 | `grep -riE "sk-\|api_key\|AI_API_KEY" frontend/src dist` → `NO_KEY_LEAK` | 通过 |
| 提交卫生 | `git status --porcelain=v1 -uall` 仅源码 + 任务夹；`dist/`、`node_modules/`、`__pycache__/`、`.pytest_cache/`、`logs/teamflow/` 均被 `.gitignore` 命中 | 通过 |

### E 组：真实浏览器复核（修复轮动过的页面）

| 步骤 | 实测 |
|---|---|
| 配置态 | 4 字段 + 5/4/3 档 chip；画像预填 `Android 开发工程师` + 「来自画像」徽章 + 「按画像 2.5 年 → 1-3年」；改动后预览逐字变化 `将按：Android 开发工程师 · 5-10年 · 国内 · 中型` |
| 配置真实入请求（AC-2 前端半边） | 拦截 fetch：`POST /api/interviews` body = `{"profile_id":"profile-t5","settings":{"years_experience":"5-10年","market":"欧洲","company_size":"大厂","target_role":"Android 开发工程师（资深）"}}`（四项与点选逐字一致） |
| 开局只投放 1 条发言（AC-4） | 开局面板仅 1 个面试官气泡（`.sc-iq-bubble--interviewer` 计数 = 1），无题目列表/卡片队列 |
| 每轮评分并置 + 点评逐字（AC-5/6） | Ctrl+Enter 提交后：候选泡内「本题得分 7.5 / 10 · 良好」+ 点评整段（含首部双空格）；下一问同轮追加；第 2 问带「↳ 追问自 Q1」 |
| 结束态（AC-9/17） | 6 泡（3 面试官 + 3 候选）、`已提出 3 题 · 已答 3 题 · 本场已结束`、textarea 消失、只读条「本场面试已结束 · 输入区已关闭」、均分 6.5、技术 5.7 / 项目深挖 8.2 / 进阶 —、双 CTA |
| 刷新恢复（AC-9） | 刷新后 6 泡、分数 `7.5/3.9/8.2` 全在、`.sc-iq-slot.is-new` = 0（不重播入场动画）、无 textarea（只读）、URL 保留 `?run_id=` |
| 390px 无横向滚动（AC-18） | 390px iframe 内 `scrollWidth 375 = clientWidth 375`，溢出 0 |
| 历史/报告回溯（AC-11/12） | `/history`：新行 `Android 开发工程师 · 1-3年 · 北美 · 初创`、旧行 `未记录设定`、笔试行无设定行，全文无 `undefined`；`/report`：「本场设定」区块 + `来源题目 iq-3` 反查 + 复制 Markdown / 导出 .md 仍在（复制能力未回归） |

## 4. 缺陷表

**未发现 P0/P1/P2 缺陷**（第 1 轮 6 条全部关闭，本轮新增面 35 条断言 + 接口一致性 309 项均无失败）。下列 2 条为**工艺观察**（P3，仅观察、不阻塞验收，不计入返工）：

| 编号 | 严重级(P0/P1/P2/P3) | 功能模块 | 复现步骤 | 期望行为 | 实际行为 | 关联验收项 | 检测命令 | 通过判据 |
|---|---|---|---|---|---|---|---|---|
| O-1 | P3 | 工艺（面试页状态可见性） | 打开 `/interview` 停在配置态并对比开场后 | 配置态也有「本场尚未开始」一类会话状态行，状态在任一时态可见 | 「已提出 N 题 · 已答 N 题」只在 chat/ended 渲染（`InterviewPage.tsx:288`），配置态该行为空 | AC-17（观感） | - | - |
| O-2 | P3 | 工艺（输入区反馈） | 在 `textarea` 连续输入接近/超过 800 字 | 接近上限有可见计数或提示，截断有反馈 | `Composer.tsx:73` 仅 `maxLength={MAX_ANSWER_CHARS}`，无计数/上限提示，超出部分被静默丢弃 | AC-17（观感） | - | - |

## 5. 架构核查（M3 质量门）

- **蓝图一致性**：融合轮把纯函数从组件文件抽到 `chatModel.ts`（气泡/题号/汇总算术）与 `setupModel.ts`（`bandOfYears`/`prefillOf`/`draftToPatch`/`previewLine`），组件文件回到「只导出组件」——正是 D-3 要求的抽取，且 `InterviewPage` 通过 import 复用（无第二份实现）。`services/rules.py` 持有枚举/默认值/闸门常量，`services/interview.py` 负责编排，路由层 49 行只做转发与错误映射。**未发现应抽取而未抽取的模块**。
- **重复实现**：`settings_or_none` 已是唯一解析实现（`history._interviews_settings_of`、`interview._settings_or_none` 均薄委托，`diagnosis` 复用 history）；`settingsLine` 单点格式化、`SETTINGS_UNKNOWN` 唯一常量；`--iq-*` token 单点定义。D-5 的漂移已消除。
- **既有结构**：`repository.py` / `db.py` / `services/ai.py` 零改动、零新表零迁移；`QuestionCard.tsx` 已删且无残留引用（`grep -rn "QuestionCard" frontend/src` 空）。
- **接口一致性（静态，309 项 0 失败）**：AST 解析 `backend/app` + `backend/tests` 每一个 import（含相对导入 → 绝对化）逐个 `hasattr`；交付面 30 个跨模块成员（`interview.create_run/score_answer/load_session/fill_settings/...`、`rules.*`、`history.list_history`、`diagnosis.interview_settings_of/build_report`、`repository.*`）逐一存在；路由 → service 三组签名兼容。前端侧由 `tsc --noEmit` 严格模式承担（import 解析 + 导出存在 + 参数形状）。检查器本身做过变异自检（注入假成员 → 被检出）。
- **交付形态契约**：无（Web 应用，非可安装插件/SDK），N/A。

## 6. 人工补测清单（环境限制或不可自动判定，非交付缺陷）

| 项 | 验收判据 | 方法 / 工具 |
|---|---|---|
| 后端 lint | `python -m ruff check app tests` 0 error | 本机 `No module named ruff`：`pip install ruff` 后复跑 |
| 真实模型端到端 | 配置 `backend/.env` 的 `AI_API_KEY` 后：上传简历 → 8 轮对话 → 报告 | 开发机手测；重点看四项设定是否真的改变题面与追问（当前只证到提示词层） |
| 单轮 15s 预算 | 真实模型下每轮 ≤15s 出分，超时 503 且答案保留 | 开发机手测 + 观察 `elapsed_s` |
| 390px 真机 / 键盘遮挡 | `document.scrollWidth ≤ 视口宽`；输入区不被软键盘遮挡（`100dvh` + `safe-area`） | iOS Safari / Android Chrome 真机 |
| 滚动锚点观感 | 新增气泡后滚到「评分区完整可见」，不整屏跳动 | 人眼看 1440 与 390 |
| 动效减弱 | `prefers-reduced-motion` 下动画消失但终值正确 | DevTools Rendering 面板 |
| 屏幕阅读器 | 气泡顺序、分数文本可读（`role="img"` + `aria-label`），不逐帧播报 | NVDA / VoiceOver |
| 窄屏右留白/宽屏观感 | DESIGN §2 几何（84/156/172、内容列 720） | 人眼看 1440 / 390 截图 |

## 7. 可复跑证据（全部为已执行命令）

| # | 命令 | 结果 |
|---|---|---|
| 1 | `cd backend && python -m pytest -p no:cacheprovider` | exit 0，`140 passed in 7.96s` |
| 2 | `cd backend && python -X utf8 ../logs/teamflow/tf-mvx9f223-m8ms9l/scripts/check_qa_r5_functional.py` | exit 0，`65 passed, 0 failed` |
| 3 | `cd backend && python -X utf8 ../logs/teamflow/tf-mvx9f223-m8ms9l/scripts/check_qa_r5_replay.py` | exit 0，`REPLAY_IDEMPOTENCY_OK` |
| 4 | `cd backend && python -X utf8 ../logs/teamflow/tf-mvx9f223-m8ms9l/scripts/check_contract_parity.py` | exit 0，17 组 / 0 失败 |
| 5 | `cd backend && python -X utf8 ../logs/teamflow/tf-mvx9f223-m8ms9l/scripts/check_interview_engine.py` | exit 0，15 PASS / 0 FAIL |
| 6 | `cd backend && python -X utf8 ../logs/teamflow/tf-mvx9f223-m8ms9l/scripts/check_t3_projection.py` | exit 0，33 PASSED / 0 FAILED |
| 7 | `cd backend && python -X utf8 ../logs/teamflow/tf-mvx9f223-m8ms9l/scripts/check_qa_r5_edges.py` | exit 0，**35 passed, 0 failed**（本轮新增） |
| 8 | `cd backend && python -X utf8 ../logs/teamflow/tf-mvx9f223-m8ms9l/scripts/check_qa_r5_interface.py` | exit 0，`{"checked":309,"failed":0}` + `INTERFACE_PARITY_OK`（本轮新增） |
| 9 | `cd frontend && npx esbuild ...check_t5_interview_chat_render.tsx --bundle ... && NODE_PATH=$PWD/node_modules node .../probe/t5_render.cjs` | exit 0，57 passed / 0 failed |
| 10 | `cd frontend && npx esbuild ...check_t6_styles_history.tsx --bundle ... && NODE_PATH=$PWD/node_modules node .../probe/t6_check.cjs` | exit 0，44 passed / 0 failed |
| 11 | `cd frontend && npm run typecheck` / `npm run lint` / `npm test` / `npm run build` | 0 / 0 error+28 warn / 65 passed / built 1.25s |
| 12 | `cd frontend && npx eslint . --max-warnings 27` | exit 1（门禁会跳，非空转） |
| 13 | `cd backend && python -m ruff check app tests` | `No module named ruff`（环境限制） |
| 14 | 真实 uvicorn + `curl -sS http://127.0.0.1:8123/health` | 200 `{"status":"ok","version":"0.1.0","ai_configured":false,"db":"sqlite"}` |
| 15 | `cd frontend && grep -riE "sk-\|api_key\|AI_API_KEY" src/ dist/` | `NO_KEY_LEAK` |
| 16 | `cd /d/work_space/code_learning && git status --porcelain=v1 -uall` | 仅源码 + 任务夹；无 dump / dist / node_modules（`git check-ignore` 逐条命中） |
| 17 | 浏览器：`/interview` 配置 → 对话 ×3 → 结束态 → 刷新 → `/history` → `/report` → 390px iframe | 见 §3 E 组（`?run_id=run-t5-2` 可复现） |
