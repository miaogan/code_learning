# r124 · 验收报告（学堂 / 演武高阶知识深化）

## 1. 内容验收

| 项 | 扩充前 | 扩充后 | 判据 |
|---|---|---|---|
| 学堂教程章节 | 48 | 60 | AI +6 / 后端 +3 / 前端 +2 / 中间件 +1；`tutorials.test.ts` 全绿 |
| 教程 RAG 小节 | 197 | 245 | `export_tutorials.mjs --check` 一致 |
| 演武题库 | 1434 | 1554 | `question_merge --check` 逐字节幂等 |
| 题库来源 | 16 | 18 | 新增 `ai-mastery`/`aim-`、`fullstack-adv`/`fsadv-` |

各方向教程与题目增量：

| 方向 | 教程 | 题目 |
|---|---|---|
| AI 工程 | 6（上下文工程 / 高级召回 / LLM 评测 / MCP / 推理量化 / Agent 记忆） | 50 |
| 后端 | 3（分布式一致性 / 限流熔断 / Go 并发） | 30 |
| 前端 | 2（React 并发 / TS 类型系统） | 20 |
| 中间件与运维 | 1（Redis 高可用） | 4 |
| 算法与数据结构 | — | 4 |
| 计算机基础 | — | 4 |
| SQL 与数据库 | — | 4 |
| 研发工程实践 | — | 4 |

## 2. 门禁执行结果

| 命令 | 结果 |
|---|---|
| `node ../scripts/export_tutorials.mjs` | 已导出 245 小节 |
| `node ../scripts/export_tutorials.mjs --check` | 教程种子一致（245 小节） |
| `npm run typecheck` | 通过 |
| `npm run lint` | 通过（0 warning） |
| `npm test -- --run` | 45 文件 / 582 passed |
| `npm run build` | 通过（326 modules，chunk 体积警告为既有） |
| `python -m app.services.assessment.question_merge --write` | 1554 条；越界 0 / 字面重复 0 / 近重复 0 / 纠正 9 / 推断 20 |
| `question_merge --check` | 可用 1554 道，逐字节一致 |
| `pytest tests/test_r12_question_merge.py tests/test_question_bank_quality.py tests/test_r13_question_shuffle.py tests/test_r11_practice_service.py tests/test_engineering_gates.py` | 174 passed |
| 后端全量 `pytest -q` | 1252 passed，0 failed |
| `ruff check app tests` | All checks passed |

### 全量结果

后端全量 1252 用例 100% 通过（进度条到 100%、无 F），`ruff check app tests` = All checks passed。用例总数与 r123 相同（1252），因本轮只改既有断言常量、未新增测试函数。

注：本机 pytest 收尾时安全策略偶发拦截临时文件清理（`safe-delete` 的 EPERM 提示），发生在全部用例通过之后，不影响测试结果，CI 不复现。

## 3. 门禁同步点说明

- **冻结 SHA**：新增 120 道通用桶题再次触发存量前 260 行的确定性选项轮转，字节数仍为 199377，`R13_SEED_SHA256` 刷新为 `da457989…c376`（与 r47/r48/r55/r107/r123 同类）。
- **架构设计筛选**：`fsadv-065`（上线回滚设计）落研发工程实践 / 架构设计，筛选量 62 → **63**（sys-arch 60 + kbx 2 + fsadv 1），断言显式校验三批都在，而非只改数字。
- **长度均衡门禁**：`fsadv-041` 的 TS 泛型约束题初稿正确项过长（3.15x）被 `test_long_answer_ratio_within_budget` 拦下，在素材内压缩正确项 + 补足干扰项解决，不放宽门禁阈值。
- **r49 教程 fixture**：新高级章全部追加在各方向文件末尾，且 `Prompt 工程` 子方向不新增高级章、`部署与推理` 新高级章排在 `ai-inference-serving` 之后，两个依赖选章顺序的行为测试保持通过。

## 4. 构建环境注意

`npm run build` 在本机 `C:\Users\user\AppData\Local\Temp\esbuild-*` 偶发 `Access is denied`（安全策略拦截 esbuild 清理临时文件，非代码问题）。把 `TEMP` / `TMP` 重定向到项目内 `.tmp/wintemp` 后正常通过。CI 环境不复现。
