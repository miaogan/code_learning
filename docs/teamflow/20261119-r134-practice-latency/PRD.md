# r134：演武判分耗时波动——判一道题不再读整张题库

- 日期：2026-11-19
- 发起：用户问「演武模块 为啥后台审查回答的时候耗时波动那么大」；确认做最小修复（主键直查 + 合并重复扫描）。
- 主题：**去掉写路径上不必要的 O(N) 读**。判分逻辑本身零 AI、零改动，动的只是「为了判一道题要读多少数据」。

## 1. 定位结论

`/api/practice/answer` 不是 AI 审查：`routers/practice.py:57` 是同步 `def`，`services/assessment/practice.py:491 submit_answer()` 只调 `exam.grade_objective()` 做集合相等判定，零 AI 调用。耗时来自两处读放大 + 一处写抖动：

1. `question_bank.find_question()` 走 `load_questions()` → `repository.list_questions()` 全表读 1554 行，逐行 `_question_of()` 解码 `options` / `answer` 两个 JSON 字段，再遍历找目标 id；判一道题读了整张题库。
2. `practice.stats()` / `build_paper()` 先 `attempt_index()` 读一次全部作答，又 `proficiency.proficient_ids()` 内部再 `repository.list_attempts()` 读第二遍；`PracticePage` 最后一题结束触发 `statsPulse`，这段重活被当成「判分卡住」。
3. 每次判分都写 `question_attempts`，生产 PG 提交后还要镜像 SQLite 副本；同步端点走线程池，2 vCPU 上并发排队会放大长尾。

## 2. 实测（本地 SQLite，1554 题 / 2000 条作答，20 次均值）

| 操作 | 优化前 | 优化后 |
|---|---|---|
| `find_question()` | 19.0 ms | **3.5 ms** |
| `submit_answer()`（判分 + 写事件） | 27.7 ms | **13.7 ms** |
| `stats()`（答完顺带刷新） | 58.3 ms | **49.8 ms** |
| `wrong_book()` | 34.3 ms | 33.0 ms（未改路径，作对照） |

生产是 PostgreSQL + 副本镜像，还要叠加连接池 / 网络往返 / CPU 竞争，绝对数字会更高；`stats()` 剩余成本主要来自仍需整池题做筛选，不在本轮范围。

## 3. 改动

- `question_bank.find_question()`：改走 `repository.get_question(id)` 主键直查，命中后用同一个 `_usable()` 复核；**空库仍兜一次 `ensure_seeded()`**，与 `load_questions()` 的自举语义一致。
- `proficiency.proficient_ids(now=None, *, attempts=None)`：新增可选 `attempts`，传入时直接复用已读行，不再调用 `repository.list_attempts()`；判定公式、阈值来源与默认路径逐字一致。
- `practice.attempt_index(rows=None)`：同样支持传入已读行；`build_paper()` / `stats()` 各只读一遍作答表，索引和熟练度共用。
- 新增 5 例测试：`find_question` 命中路径不触发全表读、空库仍自动导种子、组卷/统计各只读一次作答、`proficient_ids` 传行时不查库（另有既有端到端等价用例守口径）。

## 4. 边界与未决

- **判分口径零变化**：仍是 `exam.grade_objective()` 单点判定，答题事件仍是 `source="practice"` + `run_id="practice:<session>"` 幂等写入。
- **没有加进程内题库缓存**：题库是权威库数据，启动已有 `ensure_seeded()` 全字段刷新；缓存要处理失效口径，收益不如这次的「按主键查」直接，留待真有必要时另开。
- **`stats()` 仍读整池题**：`hit` / `wrong_total` 的定义就依赖全库筛选，若要继续降需要改统计口径或加派生表，不属于本次最小修复。
- 前端最后一题后仍会刷统计；本轮不动前端，避免牵动 r129 的脉冲刷新口径。

## 5. 验证

后端专项 69 passed（练习 40+ / 熟练度 / 题库）+ 全量 pytest 无 failed + ruff 全绿；无前端与契约改动。
