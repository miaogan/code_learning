# r43 自检迭代 · 技术变更单

- 任务夹：`docs/teamflow/20261108-r43-self-audit/`
- 性质：**不开新功能**，只清理技术债与用户可感知的小缺陷。
- 约束：契约两侧同步、`snake_case`、错误 envelope 与闭集不破、业务在 `services/`、样式只用 token、窄屏 360–430 可用；不提交、不合并。

## 1. 本轮实际改动

### 1.1 熟练度说明合并成一处（第 3 项）

r6 遗留三条是同一个信息缺口，本轮合并成**同一行说明**，不再拆成三个分散标签：

| 位置 | 说明内容 |
| --- | --- |
| 卷面首行 | 过滤事实（`本次已过滤 N 道你已熟练掌握的题`）+ 回流规则 + 兜底回流计数 |
| 结果面板 | 复显本卷过滤事实，L2 兜底回流计数拼在同一行 |

回流规则文案（带「默认」限定，真实阈值仍在后端 `config.Settings`）：

> 默认 30 天内答对 2 次及以上、且最近一次答对才计为熟练；超过 30 天或最近一次答错会自动回流到题池。另有 N 道因保持卷面结构被重新纳入。

**契约新增字段**（两侧同步）：

- `backend/app/schemas.py`：`ExamRun.reintroduced_count: int = 0`
- `frontend/src/api/types.ts`：`reintroduced_count: number`
- 语义：`reintroduced_count = |熟练 ∩ 本卷|`，与 `filtered_count` 满足
  `filtered_count + reintroduced_count = |熟练 ∩ 可用|`。
- 旧 payload 缺字段按 0 处理；页面在两个计数都为 0 时不挂任何节点（零占位）。
- 服务端同时写进 `exams` 的 payload（供 QA 断言），读侧一律 `.get()` 兜底。

**显示口径**：

- `filtered_count = 0` 但 `reintroduced_count > 0`（L2 把全部熟练题放回卷面）时**仍然显示**，
  这是本轮修掉的真实信息缺口（r19 的「N=0 不解释」会漏掉这一场景）。
- 结果面板不重复长规则句，只复显事实；兜底回流句与事实用 ` · ` 拼在同一行。

**涉及文件**：

- `backend/app/services/assessment/exam_selector.py`（`Paper.reintroduced_count` + `attempt()` 计算）
- `backend/app/services/assessment/exam.py`（响应与 payload 写入）
- `backend/app/schemas.py`、`frontend/src/api/types.ts`（双侧契约）
- `frontend/src/lib/examNotice.ts`（`proficiencyRuleHint(count, reintroduced)`、`backfillNotice(n)`）
- `frontend/src/pages/ExamPage.tsx`（首行与结果面板）
- 测试：`backend/tests/test_exam_filter.py`、`backend/tests/test_engineering_gates.py`、`frontend/src/test/examNotice.test.ts`

### 1.2 上传上限校验收敛到 `services/parser.py` 单一出处（第 4 项）

r42 新增图片入口后，单张 / 合计体积判断又散回路由层。本轮把阈值判断收进
`services/resume/parser.py::ensure_upload_size(size, message)`：

- 文档上传、单张图片、图片合计三条路径都只经过这一个判断点；
- `{mb}` 占位符在该函数内按 `max_upload_bytes()` 替换，路由不再各自拼阈值数字；
- 错误码仍是 `FILE_TOO_LARGE`（413），错误码闭集未变。

`backend/app/routers/resume.py::_read_images` 只保留「读取上限 + 空文件 + 格式/HEIC 嗅探」，
体积判断改为调用 `ensure_upload_size`。前端 `UploadPage.tsx` 的 `10MB` 由 `MAX_UPLOAD_MB`
单点派生，避免文件与图片两条提示各写一份数字。

### 1.3 第 4 项其余两条：核对结论为**已交付**，本轮不改

| 项 | 证据 | 结论 |
| --- | --- | --- |
| 面试 `Composer` 字数计数与上限提示 | `frontend/src/components/interview/Composer.tsx`：`已用 Xs · N/MAX 字`，`chars >= MAX_ANSWER_CHARS` 时追加「（已达上限）」（r5 O-2 已实现） | 已闭环，无改动 |
| 框架级 405 中文化 | `backend/app/main.py` 的 `StarletteHTTPException` handler：405 → `METHOD_NOT_ALLOWED` +「该接口不支持此请求方法」 | 已闭环，无改动 |

### 1.5 全量基线暴露的契约漂移（首轮 1 例失败，已修）

`test_exam_service.py::test_paper_never_leaks_answers` 断言笔试题面**恰好** 5 个字段，
而 `schemas.ExamQuestion` 里多出一个前端从未使用的 `sub_direction`；同一轮里
`test_routes.py:296` 又断言它**存在**，两个用例互相矛盾（单独跑都绿、全量跑必红）。
前端 `types.ts::ExamQuestion` 从来没有该字段，按 AGENTS「契约两侧同步」判定为后端单侧多字段：

- `backend/app/schemas.py`：删除 `ExamQuestion.sub_direction`（`_public()` 本就没传，行为零变化）；
- `backend/tests/test_routes.py`：题面白名单同步为 5 字段。

这不是本轮功能引入的失败，是 r11/r19 之后一直没被全量运行照出来的存量漂移；
基线价值即在此。

### 1.6 文档收尾（第 5 项）

`docs/teamflow/architecture/ARCHITECTURE.md`：

- §7.2「未落盘」删除两条**已过期**条目（`pypdf`/`python-docx` 缺失、全局无 `ruff`），
  并在 §7.1 补一条「本地工程验证（r43 补记）」作为已落盘证据；
- 仅保留真实未完成项：CI 实跑、iOS 真机 HEIC 补测；
- §7.1 后端测试文件数由 31 修正为 38；
- §7.2 的「缺 r5 行」与 §8「待落地 / 进行中」「重复统一约束」三条：**核对后确认已在 r17 清理**，
  当前文本无该内容，本轮不回改（避免把已清理的旧口径又写回去）。

### 1.7 测试基础设施加速（`TEST-BASELINE.md` §3 方案 A，已确认执行）

基线定位到瓶颈：`client` 每次 `with TestClient(app)` 触发 lifespan，`ensure_seeded()` 里
`import_seed()` 逐行调 `repository.insert_question()` —— 1088 题 = 1088 次开连接 + 1088 个事务，
实测 **11.26s**，占了单例 setup 的绝大部分。

改动（只换写入方式，不改数据语义）：

| 文件 | 改动 |
| --- | --- |
| `backend/app/core/repository.py` | 新增 `_question_insert_row()`（单条/批量共用的参数元组构造）与 `insert_questions(questions) -> int`：单连接、单事务 `executemany`，`total_changes` 差值即新增数（冲突行不产生变更） |
| `backend/app/services/assessment/question_bank.py` | `import_seed()` 改调 `repository.insert_questions()`，返回值语义不变（本次新增行数，重复导入恒 0） |
| `backend/tests/test_r11_data_layer.py` | 新增 `test_insert_questions_batch_matches_single_row_semantics`：空批 0、首批 = 行数、全量重复 0、混合批只计新增、既有行不被覆盖 |

口径不变（逐条核对）：

- 幂等仍是 `questions.id` 主键 + `ON CONFLICT(id) DO NOTHING`（AC-1「只增不覆盖」不回退）；
- `import_seed()` 返回值仍是「本次新增数」，`ensure_seeded()` / `refresh_from_seed()` 未动；
- `refresh_from_seed()` 仍是唯一的覆写路径（批量导入不参与覆写，r14 语义不变）。

副作用（可接受）：逐条写入时单行失败可被隔离，批量后整批同一事务；但 `_question_insert_row()`
对 NOT NULL 列（`options`/`answer`/`language`/`explanation`）都给了确定值（空集合写 `"[]"`、
字符串缺省写 `""`），不存在会触发约束失败的输入，`_usable()` 仍在上游过滤。

### 1.8 未采纳的叠加方案

`TEST-BASELINE.md` §3 的 B（session 级模板库 + 每例拷贝）与 C（`pytest-xdist`）本轮不做：
A 之后每例 setup 已降到亚秒级，B 的边际收益（每例 ~0.2s）与「多一份模板库生命周期要维护」不划算；
C 会引入新开发依赖且并行下的日志/相位需要重新确认，留作后续按需开启。

## 2. 未改动（明确不出手）

- 题库种子、选池阶梯、熟练度判定算法（`proficiency.py`）与阈值配置均未动；
- 前端样式尺寸未新增 token（本轮没有新尺寸）。

## 3. 验证命令

```powershell
# 后端（受影响文件 + 全量基线）
cd backend
python -m ruff check app tests
python -m pytest tests/test_exam_filter.py tests/test_engineering_gates.py tests/test_r41_image_resume.py tests/test_resume_guard.py -q
# 批量导入（r43 §1.7）
python -m pytest tests/test_r11_data_layer.py tests/test_question_bank.py tests/test_question_bank_quality.py tests/test_seed_roundtrip.py -q
# 全量回归
python -m pytest -q --durations=0

# 前端四道门禁
cd frontend
npm run typecheck
npm run lint
npm test -- --run
npm run build
```

结果见 `QA-REPORT.md`。
