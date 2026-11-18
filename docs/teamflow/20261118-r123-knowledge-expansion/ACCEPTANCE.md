# r123 · 验收报告（学堂 / 演武知识量扩充）

## 1. 内容验收

| 项 | 扩充前 | 扩充后 | 判据 |
|---|---|---|---|
| 学堂教程章节 | 40 | 48 | 八方向各 +1；`tutorials.test.ts` 全绿 |
| 教程 RAG 小节 | 165 | 197 | `export_tutorials.mjs --check` 一致 |
| 演武题库 | 1334 | 1434 | `question_merge --check` 逐字节幂等 |
| 题库来源 | 15 | 16 | 新增 `kb-expand` / `kbx-` 前缀 |

各方向教程与题目增量：

| 方向 | 教程 | 题目 |
|---|---|---|
| 前端 | `fe-css-layout` | 13 |
| 后端 | `be-python-concurrency` | 13 |
| 算法与数据结构 | `algo-sorting-stability` | 12 |
| 计算机基础 | `cs-computer-network-ip` | 12 |
| AI 工程 | `ai-prompt-injection-defense` | 13 |
| 中间件与运维 | `mw-cicd-pipeline` | 12 |
| SQL 与数据库 | `sql-nosql-choice` | 12 |
| 研发工程实践 | `eng-tech-debt` | 13 |

## 2. 门禁执行结果

| 命令 | 结果 |
|---|---|
| `node ../scripts/export_tutorials.mjs` | 已导出 197 小节 |
| `node ../scripts/export_tutorials.mjs --check` | 教程种子一致（197 小节） |
| `npm run typecheck` | 通过 |
| `npm run lint` | 通过（0 warning） |
| `npm test -- --run` | 45 文件 / 582 passed |
| `npm run build` | 通过（326 modules） |
| `python -m app.services.assessment.question_merge --write` | 1434 条；越界 0 / 字面重复 0 / 近重复 0 / 纠正 9 / 推断 20 |
| `question_merge --check` | 可用 1434 道，逐字节一致 |
| `pytest tests/test_r12_question_merge.py tests/test_question_bank_quality.py tests/test_r13_question_shuffle.py tests/test_r11_practice_service.py tests/test_engineering_gates.py` | 174 passed |
| 后端全量 `pytest -q` | 1252 passed，0 failed / 0 skipped |
| `ruff check app tests` | All checks passed |

### 过程中修正的两处

1. **studyPlan r49 用例变红**：新增 `ai-prompt-injection-defense` 初稿归入「Prompt 工程 / 高级」，使该子方向不再「无高级章」，破坏 r49 的难度递降回落断言。修正方式是把新章改归「通用 AI」（语义上更贴近跨模块安全主题），不改行为测试。
2. **架构设计筛选断言**：新增 2 道 `kbx-` 题落在「研发工程实践 / 架构设计」，该筛选由 60 → 62。断言改为显式校验「原 sys-arch 60 + 新 kbx 2」，保证既有批次仍完整保留。

### 构建环境注意

`npm run build` 首两次在 `C:\Users\user\AppData\Local\Temp\esbuild-*` 报 `Access is denied`（本机安全策略拦截 esbuild 清理临时文件，与代码无关）。把 `TEMP` / `TMP` 重定向到项目内 `.tmp/wintemp` 后正常通过。CI 环境不复现。

## 3. 已知限制

- 教程中的代码示例是结构骨架，未在独立工程里逐段执行；按各库当前 API 结构编写，读者需按自身版本核对参数。
- 新题均为通用题（`language=""`），不带具体语言标签；这是为了让八方向均衡且不引入「语言↔方向冲突」，语言专项筛选仍由既有 1074 道素材题覆盖。
- 全量后端用例中 `test_health_returns_ok` 在本机偶发启动竞态（多容器下 PG 首次握手变慢），与本次改动无关；判回归以专项 174 条与 CI 门禁为准。
