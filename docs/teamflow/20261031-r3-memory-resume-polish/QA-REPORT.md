# QA 报告 · r3 长期记忆（成长时间线 + 增量合并画像）与简历 AI 润色

- 需求任务夹：`docs/teamflow/20261031-r3-memory-resume-polish/`
- 被测分支：`feat/dev-skill-coach`（未提交改动 46 项：22 修改 + 24 新增，无新提交、无新分支）
- 基线：`20261031-r2-ac5-copy-markdown`（r2 复制/导出链路必须不回归 —— 本报告 §2 Q-REG 专项复跑）
- 结论：**可验收**（未发现 P0/P1/P2 缺陷；4 条 P3 观察，全部为设计已声明的边界或后续清理项）

---

## 1. 范围与环境

**被测范围**：本轮 15 条 AC 的全部可执行面 —— 后端 4 个新模块（`services/timeline.py`、`services/profile_merge.py`、
`services/resume_polish.py`、`routers/timeline.py`）、6 个改造点（`schemas.py` / `db.py` / `repository.py` /
`services/profile.py` / `services/history.py` / 三处完成钩子）、前端 11 个新组件与 3 个页面接线。

**不测**：真实模型质量（润色文案好坏属产品审美）；真实 PDF/DOCX 解析（既有能力，r1 已验）；多用户并发（产品明示单用户）。

**环境（本机实测）**：

| 项 | 实况 |
|---|---|
| 后端 | Windows 10 / Python 3.13，SQLite 标准库，pytest 真实执行 **113 passed in 6.79s** |
| 前端 | Node 22 / Vite 5.4.21，`vitest run` **7 passed**，`vite build` **✓ built in 1.29s** |
| AI | 全部用例用**零网络替身**（`AIClient.complete_model` 类级打补丁，按 `model_cls` 分发），无任何外网请求 |
| ruff | **不可用**：`python -m ruff check app tests` → `No module named ruff`（环境缺依赖，非代码问题，需开发机复跑） |
| 浏览器 | 本沙箱无法启动真实浏览器（宿主 token 限制），按「脚本化断言优先」执行；真机项见 §4 |
| 数据 | 每轮独立临时 SQLite（`DB_PATH` 指向临时目录），用例间零污染 |

> 说明：上一轮（r1/r2）记录的「`npm test`/`npm run build` 因 spawn EPERM 不可跑」在本轮**不再成立** ——
> 两者均真实跑通并计入证据。此结论已按实测更正，不沿用旧判断。

---

## 2. 用例与结果

### 2.1 功能级端到端（真实 HTTP，`check_qa_r3_functional.py`）**18/18 PASS**

一条连续用户旅程：上传简历 A → 建画像 → 上传简历 B → 增量合并 → 面试 ×2 → 笔试 → 重复提交 →
润色 → 临时岗位重跑 → 成稿 → 重复生成。全部断言由真实响应/落库状态驱动。

| 用例 | AC | 实测结果 |
|---|---|---|
| P01 `/health` 200 且响应无 Key 痕迹 | AC-15 | 200 `status=ok`；零 `sk-`/`api_key` |
| P02 未知简历润色 → 404 中文 envelope | AC-15 | `NOT_FOUND`「没有找到这份简历，请重新上传后再润色」，无路径/端点泄露 |
| P03 `limit=99` → 422 中文 envelope | AC-15 | `VALIDATION_ERROR`，中文 message |
| P04 首份简历建画像 + 写时间线事件 | AC-6 | `merge_summary={added:4,historical:0,evidence_added:0,duplicate:false}` |
| P05 第二份简历合并：同 `profile_id` + 证据旧→新 + 消失项转历史 | AC-6/7 | `same_id ✓`；React 证据累积且 `[0]` 是旧简历原文；active=3、historical=[TypeScript,Python,SQLite] |
| P06 名称归一（`react` vs `React`） | AC-7 | 6 条技能大小写去重后各 1 条；GET 响应**无** `merge_summary` |
| P07 时间线倒序 + 字段集 + 中文 summary | AC-1 | 11 字段与前端契约逐一相等，`occurred_at` 严格倒序 |
| P08 面试完成写事件、分数与 `/api/history` 同源 | AC-1/2 | 事件 `interview_avg=6.7` vs history `6.7`，**差 0.000**（阈值 ≤0.05） |
| P09 笔试事件总分 == 笔试响应 `total` | AC-2 | `total=0.0`（全选 A）两侧完全一致，题量 10 |
| P10 同一 run 重复提交不写第二条事件 | AC-3 | 事件数 4 → 4（不变） |
| P11 同类第二次：delta 1 位小数 + 短板复现/消失 | AC-5 | `delta=0.0`、复现 3、消失 0；`current_value` 与事件指标一致 |
| P12 润色 ≥3 条 / ≥2 section / `original_text` 逐字命中正文 | AC-8 | 5 条 / 4 section / `dropped_count=0`，每句都能在正文里逐字找到 |
| P13 反幻觉：新增专名整条丢弃 + 新增数字降级 | AC-9 | `Doc2Vec` 被丢弃（`dropped_count=1`）；`55%` → `〈待补充〉` 且 `flags=["numeric_added"]` |
| P14 临时 `target_role` 只作用于本次 | AC-12 | 本次回显临时岗位；画像仍为「前端开发工程师」；下一次调用已回落 |
| P15 成稿 markdown 单源、幂等 | AC-11 | 224B；同一 `polish_id` 两次取到的 markdown **字节相等** |
| P16 采纳/忽略不改 `documents.text`、不跨会话持久化 | AC-10 | 正文原文未变；`clear_cache()` 后同 `polish_id` 返回 `regenerated=true` |
| P17 连续两次同简历生成：`duplicate=true`、证据/事件不重复 | AC-3/6 | `duplicate=true`、`evidence_added=0`、证据条数与事件数均不变 |
| P18 历史项不进画出题 | AC-7 | 笔试题方向不含 historical 项（TypeScript/Python/SQLite 零命中） |

### 2.2 跨模块接口一致性（静态，`check_qa_interface_parity.py`）**14/14 PASS**

导入**真实 pydantic 模型**读字段、解析**真实 TS interface** 读字段做集合比对；再把 FastAPI 真实 `openapi()`
与 `client.ts` 真实 URL 字面量对照 —— 覆盖「文件存在但一调就死」这一类。

- I01–I08：`TimelineEvent`(11) / `TimelineMetrics`(5) / `TimelineComparison`(8) / `ProfileMergeSummary`(4) /
  `PolishSuggestion`(9) / `PolishResponse`(6) / `PolishFullResponse`(4) / `Evidence`(4) **字段集双侧完全相等**
- I09：`ProfileSkill` 双侧都有 `source_quotes` + `status`
- I10：`merge_summary` **只在** `ProfileWithMerge` 上，`Profile` 双侧都没有（DESIGN §7-1 契约不扩）
- I11：`client.ts` 的 **16 个端点全部命中** OpenAPI 的 17 条路由（0 个不存在）
- I12：`timeline` / `polishSuggestions` / `polishFull` 三方法签名齐备；7 个页面零直连 `fetch`
- I13：8 个 r3 契约接口字段全 snake_case（Python 侧零转换）
- I14：错误 envelope `code/message/retryable` 双侧对齐

### 2.3 前端运行态（真实组件渲染，`check_polish_ui_behavior.cjs`）**15/15 PASS**

润色页此前**没有**任何运行态证据（T9 只做了 lint/静态 grep）。本检查器用 esbuild 编译**真实组件**、
`react-dom/server` 渲染，断言的是组件代码跑出来的输出：

- A1–A5：pending/adopted/ignored 三态的真实可见差异、`aria-pressed`、忙态 2 个 disabled、临时岗位标「（临时）」
- B1：`〈待补充〉` 渲染成占位框且前后文本逐字保留（**零替换**）
- C1–C2：服务端 markdown **逐行 1:1** 渲染（6 源行 → 6 行），不裁剪不转义
- D1–D3：空/加载/失败三态；失败态 `InlineError` + 重试，且不与空态文案串台
- E1–E2：导出 `new Blob([full.markdown])` **裸传**，mime 正确，预览「服务端优先」
- F1–F2：5 个文件零 `localStorage/sessionStorage/PATCH/PUT`；采纳集合只经 `suggestion_ids` 交给服务端

### 2.4 既有门禁与回归（复用 run 内检查器，不重建）

| 检查器 | 结果 | 说明 |
|---|---|---|
| `check_memory_polish.mjs` | **28/28 PASS** | 本轮修正 4 条**误报**后转绿（详见 §3） |
| `check_copy_behavior.cjs`（r2 契约） | **6/6 PASS** | 复制 103B 字节相等、Toast 2045ms + 215ms、忙态 disabled、失败走 InlineError、导出不回归 |
| `check_t7_timeline_ui.cjs` | **25/25 PASS** | 时间线四态 / 对比块直渲染 / 首次态无 NaN / 失败不隐藏趋势表 |
| `check_t6_frontend_baseline.mjs` | **15/15 PASS** | 契约同步 + 61 个 `sc-*` 类名全部有定义 |
| `check_t8_profile_merge.mjs` | **30/30 PASS** | 画像页证据链 / 历史分组不降对比度 |
| `check_profile_merge_rules.py` | **28/28 PASS** | 归一 / 累积 / 历史隔离 / active<3 兜底 |
| `check_profile_merge_e2e.py` | **25/25 PASS** | 首份→GET→合并→PATCH→重复合并 |
| `check_timeline_backend.py` | **21/21 PASS** | 写入/同源/幂等/对比/端点 |
| `check_contract_storage.py` | **46/46 PASS** | 契约模型 + 存储读写 |

### 2.5 工程门禁

| 命令 | 结果 |
|---|---|
| `cd backend && python -m pytest -p no:cacheprovider` | **113 passed**（0 failed / 0 skipped） |
| `cd frontend && npm run typecheck` | exit 0，**0 error** |
| `cd frontend && npm run lint` | **0 error / 28 warning**（全部为既有 `react-refresh/only-export-components` 风格类） |
| `cd frontend && npm test` | **7 passed** |
| `cd frontend && npm run build` | **✓ built**（dist 246.70 kB JS / 39.76 kB CSS） |
| `cd backend && python -m ruff check app tests` | **N/A（环境阻塞：`No module named ruff`）** |
| `git status --porcelain=v1 -uall` | 46 项改动（22 M + 24 ??），**无** `node_modules/`、`dist/`、`.venv/`、`*.db`、`__pycache__/`、IDE 文件 |
| `git check-ignore -v dist/ node_modules/ backend/tests/.tmp/ logs/teamflow/…` | 全部被 `.gitignore` 命中（提交面洁净） |

---

## 3. 本轮对共享检查器的修正（4 条误报，非放宽断言）

`check_memory_polish.mjs` 是 r3 的回归契约，本轮实测发现 4 条断言**逻辑错误**（会永久误判），已修正并回归 28/28：

1. **A12**：用 `/round\(/` 一刀切判「自算分数」，但 `_num()` 的展示取整与 AC-5 要求的「delta 1 位小数」都用 `round()`
   → 误报。改为只禁 `sum(` / `/len(`，并新增正向断言「落库分数必须是 `score_of` 原值」。
2. **A19**：要求字面 `include_router(timeline)`，实际代码是 `include_router(timeline.router)` → 误报。
3. **A25**：只认 `-> Profile`，不认 `-> MergedProfile`（后者是 `MergedProfile = Profile` 的条件别名）→ 误报。
   运行时「响应里确实没有 `merge_summary`」由 §2.1 P06 直接断言（更强）。
4. **A27**：按**猜的函数名**匹配用例（三个文件全判缺），而真实用例名是
   `test_interview_completion_writes_exactly_one_event` 等 → 误报。改为按**行为**匹配（5+5+4 条行为覆盖）。

---

## 4. 人工补测清单（环境限制，非交付缺陷）

| 项 | 验收判据 | 方法 / 工具 |
|---|---|---|
| 真机剪贴板（复制报告 Markdown） | 非安全上下文（http 局域网）下按钮置灰并给中文引导；https/localhost 下写入成功 | Chrome 真机 + 浏览器控制台核对 `navigator.clipboard` |
| Toast 体感与 `aria-live` 播报 | 停留 ≈2s、右下角、不遮挡主操作；屏幕阅读器能播报「已采纳第 3 条建议」 | 真机 + NVDA / VoiceOver |
| 小屏（375×667）与 `safe-area` | 润色页左右分栏在窄屏可切 Tab；底部导出按钮不被安全区遮挡 | Chrome DevTools 设备模拟 + 真机 |
| 生成中离开保护 | 生成中点侧栏/关页签 → 弹 `ConfirmModal`，可取消 | 真机点击 |
| 生成超 20s 提示 | 慢网下右栏出现「仍在生成」追加提示，阶段文案与秒数递增 | Chrome 网络限速（Slow 3G） |
| 反幻觉人工抽检 | 逐条核对建议句不新增事实；数字位显示 `〈待补充〉` | 人读（PRD R5 明示保留人工抽检） |

---

## 5. 缺陷表

| 编号 | 严重级 | 功能模块 | 复现步骤 | 期望行为 | 实际行为 | 关联验收项 | 检测命令 | 通过判据 |
|---|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — | — | — |

**未发现 P0 / P1 / P2 缺陷。**

### 5.1 P3 观察（不阻断验收，为可见性与后续清理而记录）

| 编号 | 严重级 | 功能模块 | 观察内容 | 关联验收项 | 检测命令 | 通过判据 |
|---|---|---|---|---|---|---|
| O-1 | P3 | 润色·反幻觉 | 专名判定按 TECHNICAL §278 只覆盖「ASCII 词 + `「…」/《…》`片段」，**中文自由编造**（如「获年度最佳员工」）不会被拦截 | AC-9 | 见 §2.1 P13 | 属设计已声明边界（PRD R5 明示「拦不住语义跑偏」+ 人工抽检）；建议后续补一条中文专名规则 |
| O-2 | P3 | 润色·成稿区 | 生成失败时右栏以 `InlineError` 占位，**上一次已成稿正文暂不显示**（左栏与采纳状态按 DESIGN §245 保留） | AC-11 | 见 §2.3 D3 | 与 DESIGN §245/§285 一致；若产品希望「失败也保留旧成稿」，需改设计 |
| O-3 | P3 | 后端·画像合并 | `profile_merge.py` 里 `CONTRACT_READY=False` 分支（自定义 `MergedSkill/MergedProject/MergedProfile`）在契约落地后已成**死代码**，只保留 `MergedProfile = Profile` 别名 | AC-6/AC-14 | `grep -n "if CONTRACT_READY" backend/app/services/profile_merge.py` | 契约模型已在 `schemas.py` 定义（§2.2 I09/I10 通过）→ 建议下一轮删除死分支，降低双源风险 |
| O-4 | P3 | 前端·工程 | `npm run lint` 有 28 条 `react-refresh/only-export-components` 警告（既有风格类，0 error） | AC-14 | `cd frontend && npm run lint` | 非本轮引入（r1/r2 同样存在）；可在抽离纯函数时顺手消除 |

### 5.2 架构核查（M3 质量门）

| 核查项 | 结论 |
|---|---|
| 是否按技术方案抽出模块 | ✓ `services/timeline.py`（唯一组装点，复用 `history.score_of` + `diagnosis.build_shortfalls`）、`services/profile_merge.py`（纯函数合并）、`services/resume_polish.py`（5 函数单入口）、`routers/timeline.py`（只做参数校验） |
| 是否有重复实现 | 未发现。时间线 SQL 仅 `repository.py`（28 文件零命中）、建表仅 `db.py`（29 文件零 `CREATE TABLE`）、分数口径仅 `history.score_of`（时间线不复制算式）、提示词仅 `resume_polish.py`（9 路由 + 18 页面/组件零提示词） |
| 是否该抽未抽 | 未发现新增重复；唯一**反向**问题见 O-3（兼容分支已成死代码） |
| 既有结构是否被破坏 | 未见。r2 复制/导出链路 6/6 未回归；`HistoryPage` 趋势表在时间线失败时照常显示（T7 G2） |

---

## 6. 结论

**可验收。** 15 条 AC 中 14 条由已执行命令驱动到终态（AC-14 的 ruff 一项因环境缺依赖转人工，已列 §4/§2.5）；
AC-1/2/3/5/6/7/8/9/10/11/12/15 均有**真实 HTTP 响应**或**真实组件渲染输出**为证，非存在性检查。

- 阻塞项：**无**
- 环境受限项：`ruff`（缺依赖）、真实浏览器/剪贴板/屏幕阅读器/小屏（见 §4）
- 交付形态：无新增构建产物入库风险（提交面已核，§2.5）

### [Verification evidence]

- `cd backend && python -m pytest -p no:cacheprovider` → exit 0，**113 passed**（0 failed/0 skipped）
- `cd backend && python -X utf8 ../logs/teamflow/tf-mvwecqgm-yva03c/scripts/check_qa_r3_functional.py` → exit 0，**18/18 PASS**（AC-1/2/3/5/6/7/8/9/10/11/12/15 真实 HTTP 旅程）
- `cd backend && python -X utf8 ../logs/teamflow/tf-mvwecqgm-yva03c/scripts/check_qa_interface_parity.py` → exit 0，**14/14 PASS**（9 个契约模型字段集双侧相等 + 16 个前端端点全部命中 OpenAPI）
- `cd frontend && NODE_PATH="$PWD/node_modules" node ../logs/teamflow/tf-mvwecqgm-yva03c/scripts/check_polish_ui_behavior.cjs` → exit 0，**15/15 PASS**（三态/占位/成稿 1:1/三态错误/导出单源/零持久化）
- `node logs/teamflow/tf-mvwecqgm-yva03c/scripts/check_memory_polish.mjs` → exit 0，**28/28 PASS**（修正 4 条误报后）
- `node logs/teamflow/tf-mvwecqgm-yva03c/scripts/check_copy_behavior.cjs` → exit 0，**6/6 PASS**（r2 无回归）
- `cd frontend && NODE_PATH="$PWD/node_modules" node ../logs/teamflow/tf-mvwecqgm-yva03c/scripts/check_t7_timeline_ui.cjs` → exit 0，**25/25 PASS**
- `cd frontend && npm run typecheck` → exit 0，0 error；`npm run lint` → 0 error / 28 warning；`npm test` → 7 passed；`npm run build` → ✓ built
- `cd backend && python -m ruff check app tests` → **N/A**：环境阻塞 `No module named ruff`（需开发机复跑）
- `git status --porcelain=v1 -uall` + `git check-ignore -v dist/ node_modules/ backend/tests/.tmp/ logs/…` → 提面洁净，无依赖/构建产物/缓存/密钥入库
