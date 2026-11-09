# TECHNICAL · r51 简历亮点工程化技术方案

> 本文只描述**已定稿的设计与已落盘的改动**，未实施项标「待实施」。所有设计遵守 AGENTS.md §4：
> 契约双侧同步、错误 envelope 中文且脱敏、只用 token、测试按 `backend/tests/` 与 `frontend/src/**/*.test.ts` 放置。
>
> **阅读顺序（重要）**：§3–§4 是按「任务夹建后不可变」约定保留的**方案原文**，
> 实际交付以 **§6（M2/M3 实施结果）** 与 **§7（r53 收口批次）** 为准。方案里这几项均未照做，
> 且是**有意偏差**而非遗漏：`app_version` 列已去掉、评分 MAE / 轨迹 jsonl 未实现、
> `PLAN_VERSION` 保持 1、RRF 未接入计划 UI、虚表实际名 `question_search`（非 `questions_fts`）、
> 响应字段为 `mode`（非 `degraded`）、FTS 重建按行数一致跳过。偏差理由逐条见 §6 表格。

## 1. 现状接入点（本轮勘察结论）

| 能力 | 位置 | 关键约束 |
|---|---|---|
| AI 唯一出网点 | `services/ai/ai.py::_request`（L212-335） | `ai.response` L316 + 5 个 `ai.failed` 分支已有 `provider/model/status/elapsed_ms/kind`；隐私边界：不记 Key / 请求头 / Prompt / 简历正文 / 图片 |
| 调用签名 | `AIClient.complete_model(system, user, model_cls, *, timeout_s=None, retry_unavailable=False)` L84 | `test_engineering_gates.py` L73-84 钉死 `timeout_s` 必须 keyword-only，且业务模块不得覆写；**不要改签名** |
| DDL 单一出口 | `core/db.py::init_db()` L283 | 9 步定序，`CREATE ... IF NOT EXISTS` + `PRAGMA table_info` 幂等补列；当前 12 张表（文件头「7 张表」注释已过时，实施时顺手更正） |
| SQL 单一出口 | `core/repository.py` | `test_engineering_gates.py` L35-70 静态扫描：`.execute(` + SQL 关键字只允许出现在 `repository.py` / `db.py` |
| 连接 | `core/db.py::connection()` L252 | 每次新连接，无 WAL / `busy_timeout`；日志写入是高频短事务，实施时补 `PRAGMA busy_timeout=3000` |
| 测试夹具 | `tests/conftest.py` | 用 `backend/tests/.tmp` 而非 `tmp_path`；`FakeAI` / `patch_ai` / `ai_outage` 三类替身；零网络靠「替身 + 调用次数断言」 |
| 教程内容 | `frontend/src/content/tutorials/*.ts`，40 章 | 块类型 text/list/code/note/table/qa；`tutorials.test.ts` 钉死每章末节必须有 qa、table 行列一致 |
| 计划排程 | `frontend/src/lib/studyPlan.ts::buildStudyPlan` L371 | 输入只取 `report.id` + `weakness_map`；`pickChapter` L178 私有；`PLAN_VERSION=1`；两个 localStorage key |
| 题库文本列 | `questions.prompt` / `explanation` / `options`（JSON） | 现有 3 个索引全是标签列，无全文索引 |
| 路由注册 | `frontend/src/App.tsx` L124-136 + `TOOL_ITEMS` L33-39 | 新页面需同时加 `<Route>` 与工具导航项 |
| 前端测试 | `vite.config.ts` `environment: 'node'`，只收 `src/**/*.test.ts` | 无 DOM 测试库；业务逻辑必须下沉 `lib/*.ts` 纯函数 |

**环境实测**：本机 SQLite `3.50.4`，`sqlite_compileoption_used('ENABLE_FTS5') = 1`，`CREATE VIRTUAL TABLE ... USING fts5(x)` 成功。
`python -X utf8 -m app.services.assessment.question_merge --check` 退出码 0，输出「题库 seed 与素材重算逐字节一致：可用 1164 道」。

## 2. M1 · 交付可信度（本轮已落盘）

1. `.github/workflows/ci.yml`
   - 顶层加 `permissions: contents: read` 与 `concurrency`（按 ref 分组、`cancel-in-progress: true`），避免同一分支重复跑。
   - 后端 job 在 `ruff` 之后新增 **题库字节门禁**：`python -X utf8 -m app.services.assessment.question_merge --check`。
     理由：这是仓库里唯一「逐字节可复算」的硬门禁，之前只在本地跑，放进 CI 才构成第三方可验证证据。
   - 不改 Python / Node 版本、不注入任何 Key，保持「零网络、零密钥」的既有口径。
2. `README.md`：顶部加 Actions badge；新增 `## 设计取舍（为什么这么做）` 一章，把 `ARCHITECTURE.md §1.1` 的四条取舍（不做 SSR / 后端选 Python / SQLite 直连不用 ORM / 手写 CSS）与**各自代价**搬到首页，便于面试官 30 秒看到判断力。
3. `AGENTS.md` 变更记录追加 r51 条目。
4. **CI 实跑已核实并更正文档**（本机 `gh` 未认证，但 Actions 页面公开可读）：共 32 次运行，最近 `CI #32` 对应 commit `163ebb4`（`feat/dev-skill-coach`）成功、耗时 1m6s；#21–#26 曾红灯、后续修复，#27–#32 连续通过。据此在 `ARCHITECTURE.md §7.1` 补 CI 实跑证据、§7.2 删除过期的「未落盘」条目，README badge 指向同一 workflow。
   **注意**：`Question bank byte gate` 已随 #32 在远端验证为绿；后续新增的 4 个评测门禁见 §7，需下一次 push 后由远端确认。

## 3. M2 · 离线评测 Harness（方案已定，待实施）

### 3.1 调用日志落库

新表 `ai_call_logs`（DDL 加 `R51_SCHEMA` 常量，插入 `init_db()` 定序末尾；索引单列）：

```sql
CREATE TABLE IF NOT EXISTS ai_call_logs (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL DEFAULT 'default',
    request_id   TEXT NOT NULL DEFAULT '-',
    provider     TEXT NOT NULL,
    model        TEXT NOT NULL,
    kind         TEXT NOT NULL,   -- success|timeout|connect|upstream|rejected|malformed|schema_invalid|skipped
    status_code  INTEGER,
    elapsed_ms   INTEGER NOT NULL,
    attempt      INTEGER NOT NULL DEFAULT 1,
    prompt_chars INTEGER NOT NULL DEFAULT 0,
    app_version  TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_call_logs_created ON ai_call_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_ai_call_logs_model_kind ON ai_call_logs(model, kind);
```

- 写入点：`ai.py::_request` 的 6 个日志分支之后 + `complete_model` 的 `schema_invalid` 分支，调用 `repository.insert_ai_call_log(...)`。
- **可靠性硬约束**：整段包 `try/except Exception` → 只 `logger.warning("ai.log.persist_failed ...")`，**日志落库失败绝不影响主链路返回**；不新增中间件、不改 `complete_model` 签名、不记任何敏感内容。
- 聚合：`GET /api/eval/summary?days=7`（登录态、按 `user_id` 隔离、只读）→ `EvalSummary`：
  `{ window_days, total, success_rate, p50_ms, p95_ms, by_kind: {k: n}, by_model: {m: {total, success_rate, p95_ms}}, trend: [{day, total, success_rate}], notice }`。
  契约双侧同步：`schemas.py::EvalSummary` ↔ `frontend/src/api/types.ts::EvalSummary`。

### 3.2 版本化金标集

`docs/eval/golden-v1.json`，30 例，**全部为合成 / 脱敏文本**，绝不入库真实简历：

```json
{
  "version": "v1",
  "created_at": "2026-11-09",
  "cases": [
    {
      "id": "g-001",
      "input": { "resume_excerpt": "...", "target_role": "高级 AI 应用工程师" },
      "expected": { "profile_fields": ["..."], "score_band": "7-8", "must_not_contain": ["..."] },
      "response_snapshot": { "...": "预录的模型响应，用于离线回放" },
      "annotation": { "source": "synthetic", "annotator": "manual", "rubric_version": "r1" }
    }
  ]
}
```

配套 `docs/eval/retrieval-gold.json`（20 组短板 → 期望章节 id，供 M3 算 recall@5）。

### 3.3 两条轨道（**最重要的诚实边界**）

| 轨道 | 输入 | 评测对象 | 指标 | 是否进 CI |
|---|---|---|---|---|
| **离线回归门禁** | 固定响应快照 + 人工标注 | 解析 / 校验 / 评分 / 降级**管线** | schema 通过率、字段级 P/R、评分 MAE、失败分类正确率、纯函数处理耗时 p95 | 是，零网络 |
| **在线质量评测** | 同一金标集打真实模型 | 模型 + 提示词版本 | 真实 p50/p95 延迟、token 成本、失败率、多次采样 pass@k | 否，`AI_LIVE=1` 手动跑 |

**离线轨道不能声称「模型准确率提升」**——响应快照固定，管线跑得再稳也不代表模型变好。
报告与简历话术必须分别写：「管线回归门禁通过率 X%」与「在线评测（v1 提示词 → v2 提示词）字段 P/R 由 A 提升到 B」。
后者只有真跑过真实模型、留存 prompt/model 版本与轨迹，才能写进简历。

### 3.4 指标定义（分母写死，避免面试被问穿）

- `schema 通过率 = model_validate 成功数 / 响应总数`。
- `字段级 micro-P = TP / (TP+FP)`、`micro-R = TP / (TP+FN)`，逐字段比对画像 5 维度；`F1 = 2PR/(P+R)`。
- `评分 MAE = Σ|pred − human| / n`，`human` 来自金标标注，不用被测模型自评。
- `失败分类正确率 = 分类与注入故障一致数 / 注入故障数`（`ai_outage` / 超时 / 429 / 5xx 各注入一组）。
- `p95` 取排序后 `ceil(0.95*n)-1` 位置，**离线轨道标注为「本地处理耗时」**。
- 小样本比例一律给 **Wilson 95% 区间**，不写裸百分比；门禁用波动带 ±2pp 防 flaky（呼应 r48「持续集成门禁波动带」题）。

### 3.5 评测脚本与门禁

`scripts/eval_harness.py`（CLI，独立于 FastAPI 进程，零网络）：

```bash
python -X utf8 scripts/eval_harness.py --golden docs/eval/golden-v1.json --report docs/eval/REPORT.md
python -X utf8 scripts/eval_harness.py --check --baseline v1     # 跌破基线 → 非零退出码，供 CI 使用
```

- 版本锁定：脚本记录 `prompt_version` / `model` / `rubric_version` / 输入文件 sha256；轨迹写 `docs/eval/traces/<run>.jsonl` 可回放。
- 评分器隔离：评分逻辑是纯函数 / 规则，**不调用被测模型打分**，防「同源自评偏差」（r48 题库同题）。
- 报告：Markdown 表格给出每个指标 + 与基线差值 + 是否过门禁 + 样本量与区间；只读聚合 `/api/eval/summary` 供前端 `/eval` 看板展示趋势（业务逻辑下沉 `lib/eval.ts` + 同名测试）。

### 3.6 M2 验收清单

- [ ] 旧库启动 `init_db()` 不炸、新表幂等；`test_engineering_gates.py` SQL 出口门禁仍绿。
- [ ] 注入「落库抛异常」时 `complete_model` 仍正常返回（best-effort 有测试）。
- [ ] `caplog` 断言不出现 Key / Prompt / 简历正文（扩展 `test_observability.py` 模板）。
- [ ] `--check` 在基线未变时退出 0、人为劣化基线后退出非 0。
- [ ] `EvalSummary` 双侧字段同步，越权读取返回 404（沿用 r23 隔离口径）。
- [ ] 新增后端 ≥8 条、前端 ≥3 条测试；`pytest` / `ruff` / `typecheck` / `lint` / `test` / `build` 全绿。

## 4. M3 · 检索增强学习计划（方案已定，待实施）

### 4.1 核心取舍：不做「把教程导出成后端 JSON」

教程正文在前端 TS、题库在后端 DB。若统一到后端 FTS5，就要把 40 章导出成 seed JSON，产生**双份真源**——题库已经为字节级一致性付出过门禁代价，不再重蹈覆辙。
改为**两路检索、前端融合**：

| 路 | 语料 | 实现 | 理由 |
|---|---|---|---|
| 教程 | 40 章 → 小节粒度文档 | `frontend/src/lib/tutorialSearch.ts` 纯函数 BM25 | 内容同源、零网络、可单测、无需同步 |
| 题目 | `questions.prompt` / `explanation` | 后端 `CREATE VIRTUAL TABLE ... USING fts5(...)` + `POST /api/search/questions` | 数据本来就在 DB；FTS5 本机已验证 |

### 4.2 教程检索

- `buildSectionDocs(chapters)`：每小节拍平为 `{chapter_id, section_id, title, direction, sub_direction, level, text}`，text 汇总该节全部 block（qa 的 question/answer、table 的单元格一并纳入）。
- 中文分词取舍：**不引分词库**（保持前端 3 个运行时依赖不变），用「二元字组 bigram + 英文/数字连续词」构造 term；文档里写明这是精度与依赖的交换。
- `bm25Score(query, docs, k1=1.5, b=0.75)` → `searchTutorials(query, {direction, sub_direction, level})` → `Citation[]`：
  `{chapter_id, section_id, title, snippet, score, href}`，`href` 直接指向 `/learn/<chapterId>#tutorial-<sectionId>`（复用 r25 断点续读锚点）。
- 纯函数 + `src/test/tutorialSearch.test.ts`：确定性排序、无命中返回空、越界筛选回落、citation 指向的 section 必须真实存在。

### 4.3 题目检索与降级

- 启动时探测 `SELECT sqlite_compileoption_used('ENABLE_FTS5')`；可用则建 `questions_fts`（`prompt`, `explanation`），随题库幂等导入重建；不可用则不建虚表，端点降级为现有闭集筛选并回中文 `notice`。
- `POST /api/search/questions`：`{query, direction?, sub_direction?, limit=5}` → `{items:[{question_id, prompt, direction, sub_direction, score}], degraded, notice}`。
  **不返回 `answer` / `explanation` 原文中的答案信息**，沿用「答案只服务端可见」口径。契约双侧同步。

### 4.4 融合与兼容

- 查询构造：`WeaknessItem.point + summary + samples[].question_id`（按 id 回捞题干，报告本身不含题干原文）。
- 融合排序用 RRF：`score = Σ 1/(60 + rank_i)`，避免两路分数量纲不同；取 top-3 citation 挂到 `StudyTask.citations?: Citation[]`。
- `PLAN_VERSION` 1 → 2（新增可选字段，旧快照按版本失效重算，沿用 `WeekPlan.tsx` 的版本校验）。
- **静默回落**：检索无命中 / 端点失败 / FTS5 不可用时，退回 r49 的 `pickChapter` 与 r50 的 `practiceHref`，计划仍确定性可复算；不新增空态页、不改分组 key 与排序。
- 报告页 `WeekPlan` 任务卡显示「依据：章名 · 小节」，点击直达锚点。

### 4.5 指标与命名诚实

- `recall@5 = 命中期望章节的查询数 / 20`（用 `docs/eval/retrieval-gold.json` 人工标注）。
- `无命中拒答率`、`引用有效率`（citation 的 section 真实存在 / 全部 citation）。
- 与硬编码基线做配对比较，报告写清「提升来自召回覆盖，不是模型能力」。
- **不用 embedding，就命名「检索增强 + 引用归因」，禁止写 RAG**。要写 RAG 必须补向量检索、chunk 策略评估与金标上下文上界归因（即 r49 `ai-eval-harness` 章的内容），属于另一个量级的工作量。

### 4.6 M3 验收清单

- [ ] FTS5 可用 / 不可用两条路径都有测试；降级时 `notice` 为中文且不 500。
- [ ] 全部 citation 可点击且锚点存在；旧报告（`weakness_map: null`）、旧 localStorage 快照不崩。
- [ ] `buildStudyPlan` 在「不检索」输入下与 r50 行为逐字节等价（回归断言）。
- [ ] `recall@5` / 无命中拒答率写进 `docs/eval/REPORT.md`，标注样本量与区间。
- [ ] 前端纯函数测试 ≥6 条；全量验证命令全绿。

## 5. 里程碑依赖与「可独立交付」口径

```
M1（本轮） ──> M2（日志落库 → 金标集 → 脚本/门禁 → 看板）
           └─> M3（教程 BM25 → 题目 FTS5 → 融合 → citation → 评估）
```

M2 与 M3 互不阻塞，任一单独完成即可独立写进简历；`docs/eval/` 是两者共享的评测产物目录。
每一项交付前必须跑：`backend/` 的 `pytest -q` + `ruff check app tests`、`frontend/` 的 `typecheck && lint && test && build`、根目录 `question_merge --check`。

## 6. 实施结果（r53，2026-11-09）

M2 / M3 已落盘。以下 5 处是**有意偏差**，按「任务夹建后不可变」约定补记于此，不回改 §3–§4 原方案：

| 项 | 原方案 | 实施 | 理由 |
|---|---|---|---|
| `app_version` 列 | 记应用版本 | 去掉该列 | 避免与 `main.APP_VERSION` 形成双份真源；日志只留元数据 |
| 评分 MAE / 轨迹 jsonl | 列入指标与产物 | **未实现** | 金标只标 `score_band` 区间、无逐例人工打分，缺少可复算的 `human` 标签；不编造指标。报告里显式写明「未计入」 |
| `PLAN_VERSION` | 升 2 | **保持 1** | `citations` 是纯附加可选字段，`buildStudyPlan` 默认不产出（与 r50 逐字节等价），旧快照缺字段零占位，无需失效重算 |
| RRF 融合 | 两路检索融合进计划 | `reciprocalRankFusion` 已实现并单测，**未接入计划 UI** | `buildStudyPlan` 是同步纯函数，题目检索需异步 API；强接会破坏确定性排程。计划页只展示教程侧 citation，题目侧以独立端点提供 |
| FTS5 重建 | 每次导入重建 | 行数一致即跳过 | 题库导入幂等（只增不改），避免每次启动重写 1164 行 |

**实测（命令输出，非手写）**

- `python -X utf8 scripts/eval_harness.py --check`：30 例，schema 通过率 93.3%、micro-P 98.0% / R 99.0% / F1 98.5%、负向 `hallucination_rate` 13.3%、p50/p95 本地处理耗时 3/19 微秒。基线 `docs/eval/baseline-v1.json`，波动带 ±2pp，已接入 CI `Offline eval gate`。
- `node scripts/eval_retrieval.mjs`：20 组标注，recall@5 100%、无命中拒答率 0%、引用有效率 100%（90/90），Wilson 95% 区间 [83.9%, 100%]。
- **两组数字都只证明实现可用**：金标 30 例为合成数据、响应快照与标注同源；检索标注 20 组由同一批章节标题启发写成，存在标注泄漏风险。用途是**回归检测**，不是能力宣传，报告内已写「解读限制」。

**新增**：`ai_call_logs` 表、`question_search` FTS5 虚表（可选能力，缺失降级 LIKE）、`GET /api/eval/summary`、`POST /api/search/questions`、`/eval` 看板、`lib/tutorialSearch.ts` / `lib/eval.ts`、`scripts/eval_harness.py` / `scripts/eval_retrieval.mjs`、`docs/eval/` 五份产物、`backend/tests/test_r51_eval_harness.py`（13 条）与前端 3 个测试文件（18 条）。

**验证**：后端 646 passed / 1 skipped、前端 268 passed；`typecheck` / `lint` / `build` / `ruff` / `question_merge --check` 全绿。CI 新增的 `Offline eval gate` 与题库字节门禁需下一次 push 后由远端验证。

## 7. 收口批次（r53 续，2026-11-09）

与 §6 同属**一个未提交变更集**，最终一次性提交。目标是消除「文档说的 ≠ 代码里有的」，并补齐 §6 明确记档的未完成项里能零网络落地的部分。

### 7.1 交付内容

| 项 | 落盘 | 实测证据 |
|---|---|---|
| 并发写锁 | `db.py::connection()` 加 `PRAGMA busy_timeout = 3000`（驱动参数 + PRAGMA 双保险）；`repository.prune_ai_call_logs()` 按 90 天保留期随 `create_session()` 收口 | 8 线程 × 50 次并发写 100% 成功、0 次锁失败；`test_r53_concurrency.py` 5 条 |
| LLM 可靠性治理 | `services/ai/reliability.py`：指数退避+抖动、三态熔断器、结构化输出修复、幂等键、影子对比；`ai.py` 默认接入「修复兜底」与「后台重试退避」 | `scripts/eval_reliability.py` 故障注入：55.5%→84.0%（+28.5pp）、修复救回 34 次、熔断减少 80% 无效上游调用 |
| 检索评估补完 | `eval_retrieval.mjs` 加只读 `--check`；新增 `scripts/eval_question_retrieval.py` + 20 组题目侧标注 | 教程侧 / 题目侧 recall@5 均 100%（20/20），题目侧 Wilson 95% `[83.9%, 100%]`、FTS5 命中占比 80%（4 组短查询降级 LIKE） |
| 性能基准 | `scripts/benchmark.py` → `docs/eval/PERF-REPORT.md`（临时库，零网络） | 并发写 `no_timeout` 28.2%（287 次锁失败）→ `with_timeout` 100%；题库导入 8.78ms / 幂等二次 1.58ms；FTS5 检索 p50/p95/p99 = 72/107/238 us |
| 演示数据 | `scripts/seed_eval_demo.py`，`provider='demo'`，重复运行幂等 | dry-run：120 条 / 7 天 / 2 模型，成功率 74.2%、p50 793ms、p95 3942ms；**默认不写开发库** |
| CI 门禁 | backend 加 `Question retrieval eval` / `Reliability fault-injection`，frontend 加 `Retrieval eval` | 4 个新门禁在各自 `working-directory` 下本地实跑退出 0；`node ../scripts/eval_retrieval.mjs --check` 在 `frontend/` 下可跑（esbuild 从 frontend/node_modules 解析） |

### 7.2 有意偏差（继续补记，不回改方案正文）

| 项 | 方案 / 承诺 | 实施 | 理由 |
|---|---|---|---|
| WAL | §1 表格写「必要时评估 WAL」 | **不启用** | 基准显示 `busy_timeout` 已消除写失败；WAL 引入 -wal/-shm 文件与备份复杂度，单进程本地库收益不成立 |
| 熔断短路 | PRD 加分项「熔断降级」 | 可注入状态机，**默认只观测不自动短路** | 避免把全局状态塞进 646+ 条既有测试的调用链；故障注入脚本验证策略效果，线上开关需显式注入 `allow()` |
| 影子对比 / 幂等键 | PRD 加分项 | 纯函数已实现并单测，**未接主链路** | 接影子模型需第二份 Key 与配额，幂等缓存需定义失效语义，属于另一个变更集 |
| benchmark 进 CI | — | **刻意不进** | 磁盘 / CPU 差异会让 p95/p99 跨机器抖动，制造 flaky；只作为本地可复跑报告 |
| 在线评测 / 轨迹 / MAE / RRF 接入 | §3.3 / §4.4 | **仍未实现** | 需真实 Key、逐例人工打分与异步排程改造；`RESUME.md §2` 已列为「不建议写」，不冒充完成 |

### 7.3 诚实边界（写简历前必读）

- **故障注入 55.5%→84.0% 是模拟函数 + 虚拟时钟**，不是线上可用性；虚拟 p95 不能与 `PERF-REPORT.md` 的真实基准混用。
- 题目侧 / 教程侧标注各 20 组，由同一批标题与题目关键词启发写成，**存在标注泄漏**；100% 只证明实现可用，不证明检索质量。
- `busy_timeout` 的 28.2%→100% 是**同一基准的两组配置对照**，不是项目上线前后的演进数据。
- `docs/eval/traces/` 不存在；评分 MAE 因缺逐例人工打分未计入，报告里显式写「未计入」。

### 7.4 验证

**后端 667 passed / 1 skipped、前端 268 passed**；`ruff check app tests` / `typecheck` / `lint` / `build` / `question_merge --check` 全绿。
新增脚本单独 `ruff check` 全过；`eval_reliability.py` 连跑两次报告 sha256 一致（注入固定 seed 的随机源，保证可复算）。
CI 的 4 个新门禁需下一次 push 后由远端确认；`Question bank byte gate` 已随 #32 验证为绿。
