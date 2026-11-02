# r17 验收报告：A 组文档回写收口（ARCHITECTURE 尾巴 + r11 三条）

- 任务夹：`docs/teamflow/20261102-r17-doc-tail-closure/`
- 验收对象：工作区未提交改动 —— `docs/teamflow/architecture/ARCHITECTURE.md`（§3.1 / §3.4.3 新增 / §7.1 / §7.2 / §8 / §8.1 新增）、
  `docs/teamflow/memory.md`（第 37 / 41 / 42 行）、`backend/app/services/exam_selector.py`（模块 docstring）、
  `frontend/src/lib/practice.ts`（`DIRECTION_LABEL`）、本任务夹。
- 验收口径：`memory.md` 第 37 行（架构文档尾巴）、第 41 行②（r8-②，① 未在本轮范围）、第 42 行（r11 C-1 / C-2 / C-3）。
  `TECH-CHANGE.md` 声明「文档回写为主，两处代码仅表述/门禁对齐，零行为改动、零契约改动、零数据改动」，
  故判据 = 三条遗留的关闭证据 + 既有门禁不回归。

## 1 判据逐条核对

| # | 判据 | 实测结果 | 结论 |
|---|---|---|---|
| 1 | 架构尾巴：§7.2 不再有过时的 r5 行 | `Select-String '待落地|进行中'` 在 `ARCHITECTURE.md` 命中 **0** 行；§7.2 现只剩 3 行（真实 PDF/DOCX、ruff、CI 实跑） | 通过 |
| 2 | 架构尾巴：§8 的 r5 条改为已交付 | §8 第 324 行写「r5 面试对话流已交付（2026-11-01）」并列出 `services/interview.py` / `rules.py` / `routers/interview.py` / 页面落点 | 通过 |
| 3 | 架构尾巴：重复「统一约束」只留一条 | `Select-String '统一约束'` 命中 **1** 行（第 325 行） | 通过 |
| 4 | §7.2 的 Docker 行与 r10 事实相反 → 移入 §7.1 | §7.1 第 306 行 = 「容器化交付（r10）」+ 5 个容器文件 + `WEB_PORT=8080` + `skillcoach-data` 卷 + 任务夹 `20261101-r10-docker-compose-deploy/DEPLOY.md`；5 个文件均实存 | 通过 |
| 5 | §7.1 测试文件数真实 | 实测 `backend/tests/*.py` 除 `conftest.py` = **31**，与 §7.1「后端测试 31 文件」一致 | 通过 |
| 6 | r8-②：3 参旧签名已在产品级文档补记 | §8.1 表首两行：`TECHNICAL.md:186` / `:302` 的 `is_follow_up_allowed(kind, follow_up_count, total_questions)` → 实现 `services/rules.py:226` 的 4 参 `(kind, follow_up_count, asked, planned_total)`；调用处 `services/interview.py:431,466` 实测传 4 参 | 通过 |
| 7 | r8-②：历史夹未被改写 | `git status --short` 不含 `docs/teamflow/20261101-r5-interview-chat-config/` | 通过 |
| 8 | r11 C-1：共享口径说明段落已存在 | `ARCHITECTURE.md` §3.4.3 七层表（数据源 / 判分 / 作答记录 / 熟练度 / 取题池 / 卷面结构 / 抽样）+ 理由段 | 通过 |
| 9 | r11 C-1：口径与 r11 约定一致 | 与 `memory.md` 第 20 行逐条对齐：`questions` 表 + seed 幂等导入、`exam.grade_objective()` 唯一判分、`question_attempts` 的 `source` 区分 + `run_id=practice:<session>`、熟练度阈值只在 `config.py`、练习池只收 single/multiple/judge、笔试受 10–12 题 / 客观 ≥8 / 挑战 ≤20% / 方向 ≥2 闸门 | 通过 |
| 10 | r11 C-2：`exam_selector.py` docstring 与实现对齐 | 模块 docstring 第 9–14 行：题型覆盖写明是取题策略 `_prefer_kind_diversity()`（定义在 `exam_selector.py:222`），并说明「不在 `build_paper()` 闸门校验项里」；闸门仍写 10–12 题 / 客观 ≥8 / 挑战 ≤20% / 方向 ≥ `require_directions`（`_fit_structure` 在 `:252`） | 通过 |
| 11 | r11 C-2：`_prefer_kind_diversity` 与 `PromptBody.tsx` 已补记 | §3.1 新增 `src/components/exam/PromptBody.tsx` 行（题面围栏唯一出口）；§8.1 第 335 行同时记两项 | 通过 |
| 12 | r11 C-3：方向闭集单一来源 | `frontend/src/lib/practice.ts:123-128` 新增 `DIRECTION_LABEL`，`directionChips()` 由 `Object.keys(DIRECTION_LABEL)` 派生；grep 确认 `前端 / 后端 / 算法与数据结构 / 计算机基础` 字面量在 `practice.ts` 只出现一次 | 通过 |
| 13 | r11 C-3：门禁可在编译期拦住漏项 | `satisfies Record<Exclude<PracticeDirectionFilter,'all'>, string>`；契约 `types.ts:533` 的 `PracticeDirectionFilter` 镜像后端 `rules.DIRECTIONS`；`npm run typecheck` 0 error | 通过 |
| 14 | r11 C-3：chip 形状与顺序不变 | 输出仍为「全部 + 前端 / 后端 / 算法与数据结构 / 计算机基础」；`vitest` 10 文件 / **133 passed** 全绿 | 通过 |
| 15 | 契约零改动 | `backend/app/schemas.py`、`frontend/src/api/types.ts` 未在 `git status` 中出现 | 通过 |
| 16 | 后端行为不回归 | `python -m pytest -p no:cacheprovider` → **534 passed, 1 skipped**，exit 0 | 通过 |
| 17 | 记忆收口准确 | `memory.md` 第 37 行标 `[x]` 并给本夹；第 41 行②标「已关闭」、①仍留；第 42 行整条标 `[x]` 并给三条落点 | 通过 |
| 18 | 改动面仅文档 + 两处表述/门禁对齐 | `git status --short`：`M backend/app/services/exam_selector.py`、`M docs/teamflow/architecture/ARCHITECTURE.md`、`M docs/teamflow/memory.md`、`M frontend/src/lib/practice.ts`、`?? docs/question-bank-staging/PROVENANCE.md`（r16 遗产）、`?? r16 夹`、`?? r17 夹` | 通过 |

## 2 架构一致性

| 蓝图要求 | 实测 | 结论 |
|---|---|---|
| 任务夹不可变 | r5 / r11 / r12–r16 夹零改动；r11 三条与 r8-② 全部落在产品级 `ARCHITECTURE.md`（§3.4.3 / §8.1），先例与 r16 §3.4.2 一致 | 符合 |
| 产品级文档是跨需求真源 | §3.4.3 给「共享 / 刻意不同」判定与事实，不复制代码；§8.1 每行都指向实现位置，可在实现变动时就地更新 | 符合 |
| 方向闭集单源 | 后端 `rules.DIRECTIONS` → 契约 `PracticeDirectionFilter` → 前端 `DIRECTION_LABEL`（`satisfies` 保证完整性），前端不再有第二份字面量 | 符合 |
| 结构闸门单源 | `build_paper()` / `_fit_structure()` 仍是唯一结构闸门；docstring 只更正「题型覆盖」的归属（取题策略），不改取题顺序与行为 | 符合 |
| 契约零改动 | 两侧契约文件未触碰；无新字段、无 snake_case 变化 | 符合 |
| 无重复实现 | 未新增常量表 / 脚本 / 测试夹具；`DIRECTION_LABEL` 是消费契约而非第二份闭集 | 符合 |

## 3 复跑命令

```bash
# 后端全量（本轮实测 534 passed, 1 skipped / exit 0；单跑约 2–3 分钟，本机因并发旧进程耗时 26 分钟）
cd backend && python -m pytest -p no:cacheprovider

# 前端三门禁
cd frontend && npm run typecheck        # 0 error
cd frontend && npm run lint             # 0 error / 28 warnings（既有基线，--max-warnings 28）
cd frontend && npm test -- --run        # 10 files / 133 passed
```

文档自查：

```powershell
Select-String -Path docs/teamflow/architecture/ARCHITECTURE.md -Pattern '待落地|进行中'   # 0 命中
Select-String -Path docs/teamflow/architecture/ARCHITECTURE.md -Pattern '统一约束'        # 1 命中
Select-String -Path docs/teamflow/architecture/ARCHITECTURE.md -Pattern '^#### 3.4.3|^### 8.1'  # 两节存在
(Get-ChildItem -Path backend\tests -Filter *.py | Where-Object { $_.Name -ne 'conftest.py' }).Count  # 31
```

## 4 遗留（P3，均不阻断）

| 编号 | 内容 | 处置建议 |
|---|---|---|
| P3-a | `ruff` 本机不可用（`No module named ruff`，无 `backend/.venv`），后端 lint 未实跑 | 与 r9/r12–r16 同口径记录；CI 或含 ruff 的环境补跑 |
| P3-b | `directionChips()` 只有 typecheck 保障，`src/test/practice.test.ts` 无 chip 顺序断言 | 本轮目标（消除第二来源）已由编译期门禁达成；顺序回归属可选增强，如需要另立小需求 |
| P3-c | 后端全量套件本机耗时 26 分钟（因同时有一个 20:03 起的孤儿 pytest 进程并发抢 CPU，已停止；套件本身无慢用例失败） | 后续跑全量前先 `Get-Process python` 确认无并发实例 |
| P3-d | §7.2 删除「Docker 未做」行属超出待办原文的同类比邻修正 | 已记 `TECH-CHANGE.md` §6.2；历史「README 三步手动流程」口径仍可从 §7.1 r10 行追溯 |
| P3-e | r8 ①（9 题卷追问上限被压到 3 次）仍在 `memory.md` 第 41 行，未动 | 属产品口径决策，需另立需求改预算并同步额度断言 |

## 5 验收判定说明

- 功能性：架构文档尾巴（§7.2 两行 / §8 三条）收干净；r8-② 的 3 参旧签名在 §8.1 回写；r11 C-1（§3.4.3）、
  C-2（docstring + §3.1/§8.1 补记）、C-3（`DIRECTION_LABEL` + `satisfies` 门禁）全部关闭。
- 结构性：任务夹零改写、契约零改动、无新增数据与运行时行为；`DIRECTION_LABEL` 与 §3.4.3 都是「消费既有真源」而非新副本。
- 验证：后端 534 passed / 1 skipped（exit 0）；前端 typecheck / lint 0 error、vitest 133 passed；`git status` 仅上述 4 个修改 + 3 个新增目录（含 r16 遗产）。
- 因此判 **通过**；5 条 P3 为环境 / 工艺留痕，不构成返工条件。

验收结论：✅ 通过
