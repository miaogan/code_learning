# r43 · 后端测试基线与瘦身结论

> 结论先说：**慢不在 AI、不在 sleep，在「每个用例都新建库 + 启动时 1088 条单行 INSERT」**。
> 单次 `TestClient` 启动实测 **11.27s**，其中 `import_seed` 独占 **11.26s**（1088 条单行事务）。
> 全量 615 例里约 90+ 例会拉起 `TestClient`，所以 30+ 分钟的墙钟时间大半花在重复灌种子。
> **本轮只出结论与方案，未改任何测试基础设施**（按约定等确认）。

## 1. 基线

### 1.1 首轮全量（2026-11-08 23:51 起，约 36 分钟）

命令（`backend/`）：

```powershell
python -m pytest -q --durations=30
```

| 指标 | 结果 |
| --- | --- |
| 收集 | **615** 例（38 个 `test_*.py`） |
| 结果 | **613 passed / 1 skipped / 1 failed** |
| 失败 | `tests/test_exam_service.py::test_paper_never_leaks_answers` |
| 失败原因 | 题面多出 `sub_direction`：与 `test_routes.py:296` 的白名单**互相矛盾**（合同漂移，见下） |

失败项**已在同轮修掉**（`schemas.ExamQuestion` 删除前端从未使用的 `sub_direction`，
`test_routes.py` 白名单同步 5 字段），并用受影响文件复核 72 passed。

**第二轮全量（修复后）**：命令 `python -m pytest -q --durations=0`，输出留档到
`$env:TEMP/r43_pytest_full.txt`。

| 指标 | 结果 |
| --- | --- |
| 收集 | **615** 例（38 个 `test_*.py`） |
| 退出码 | **0** |
| 结果 | **615 全绿**（含 1 例 skip 保持原状） |
| 墙钟 | 日志 00:36:43 → 01:20:12，约 **43 分钟** |
| 逐用例耗时聚合 | **2591.5s**（≈43.2 分钟，与墙钟吻合） |

> 首轮 36 分钟是事后回看的粗估（未单独计时）；两轮机器负载不同，差异不是回归。
> 下文 §1.2 的 Top30 与 §1.3 的分文件表都来自这两轮的实测输出。

### 1.2 首轮 Top 30 耗时（`--durations=30` 原样）

| 耗时 | 阶段 | 用例 |
| --- | --- | --- |
| 38.58s | call | `test_question_bank.py::test_stored_rows_keep_closed_set_labels[direction]` |
| 33.92s | setup | `test_auth.py::test_cross_user_resources_are_404` |
| 30.18s | setup | `test_r11_practice_api.py::test_paper_empty_result_is_200` |
| 29.17s | setup | `test_resume_polish.py::test_polish_endpoint_returns_suggestions_and_does_not_touch_text` |
| 28.70s | setup | `test_observability.py::test_every_response_carries_request_id` |
| 28.65s | setup | `test_r42_jobs.py::test_image_job_completes_and_stores_resume` |
| 25.62s | setup | `test_r11_practice_api.py::test_paper_invalid_enum_is_422` |
| 24.72s | setup | `test_resume_polish.py::test_polish_response_carries_verbatim_resume_text` |
| 24.67s | setup | `test_r42_jobs.py::test_stale_resume_job_is_failed_on_read` |
| 23.31s | setup | `test_observability.py::test_error_response_keeps_same_request_id` |
| 21.64s | setup | `test_timeline.py::test_interview_event_matches_history_and_diagnosis` |
| 18.56s | setup | `test_profile_merge.py::test_post_returns_merge_summary_but_get_does_not` |
| 17.09s | setup | `test_routes.py::test_report_generate_without_runs_rejected` |
| 17.00s | setup | `test_auth.py::test_secret_key_missing_blocks_key_storage` |
| 16.74s | setup | `test_routes.py::test_report_generate_latest_and_markdown` |
| 16.33s | setup | `test_routes.py::test_history_sorted_desc_and_limited` |
| 16.21s | setup | `test_routes.py::test_exam_create_submit_and_resubmit_400` |
| 15.99s | setup | `test_routes.py::test_interview_finish_early_is_idempotent` |
| 15.72s | setup | `test_timeline.py::test_exam_event_has_no_comparison_when_previous_is_interview` |
| 15.69s | setup | `test_routes.py::test_interview_bad_paper_maps_to_502` |
| 15.57s | call | `test_question_bank.py::test_ensure_seeded_refreshes_stale_rows_on_startup` |
| 15.54s | setup | `test_routes.py::test_patch_rejects_empty_quote` |
| 15.51s | setup | `test_routes.py::test_interview_create_unknown_profile_404` |
| 15.46s | call | `test_question_bank.py::test_ensure_seeded_imports_every_time_and_stays_idempotent` |
| 15.43s | setup | `test_r42_jobs.py::test_profile_job_reuses_running_job` |
| 15.42s | setup | `test_routes.py::test_full_flow_reaches_terminal_report` |
| 15.41s | setup | `test_routes.py::test_ai_outage_maps_to_503` |
| 15.38s | setup | `test_routes.py::test_profile_generate_then_patch_roundtrip` |
| 15.38s | setup | `test_routes.py::test_latest_profile_404_when_empty` |
| 15.37s | call | `test_question_bank.py::test_import_seed_is_idempotent` |

特征：**几乎全是 setup**，不是用例本体慢；`call` 慢的三条也都直接调 `import_seed`。

### 1.3 各测试文件耗时分布（第二轮 `--durations=0` 逐用例聚合）

按「文件内所有 `setup` + `call` + `teardown` 求和」的口径统计，38 个文件合计 **2591.5s**：

| 文件 | 例数 | 合计(s) | 单例均(s) |
| --- | --- | --- | --- |
| `test_question_bank_quality.py` | 80 | 299.7 | 3.7 |
| `test_routes.py` | 47 | 247.4 | 5.3 |
| `test_r11_practice_api.py` | 42 | 219.2 | 5.2 |
| `test_question_bank.py` | 38 | 206.6 | 5.4 |
| `test_auth.py` | 49 | 197.7 | 4.0 |
| `test_resume_polish.py` | 30 | 160.2 | 5.3 |
| `test_report_coach.py` | 29 | 147.8 | 5.1 |
| `test_r42_jobs.py` | 24 | 147.5 | 6.1 |
| `test_r41_image_resume.py` | 24 | 123.4 | 5.1 |
| `test_exam_service.py` | 24 | 111.0 | 4.6 |
| `test_profile_job.py` | 21 | 105.8 | 5.0 |
| `test_exam_filter.py` | 23 | 101.0 | 4.4 |
| `test_report_service.py` | 26 | 98.4 | 3.8 |
| `test_resume_guard.py` | 12 | 88.0 | 7.3 |
| `test_timeline.py` | 39 | 82.7 | 2.1 |
| `test_observability.py` | 10 | 45.7 | 4.6 |
| `test_health.py` | 9 | 33.4 | 3.7 |
| `test_seed_roundtrip.py` | 6 | 33.4 | 5.6 |
| `test_interview_chat.py` | 76 | 26.8 | 0.4 |
| `test_r11_practice_service.py` | 60 | 26.0 | 0.4 |
| `test_r12_question_merge.py` | 14 | 21.4 | 1.5 |
| `test_profile_merge.py` | 26 | 18.8 | 0.7 |
| `test_report_markdown.py` | 3 | 16.3 | 5.4 |
| `test_profile_null_contract.py` | 6 | 15.6 | 2.6 |
| `test_r11_data_layer.py` | 38 | 5.4 | 0.1 |
| `test_engineering_gates.py` | 34 | 4.0 | 0.1 |
| `test_interview_service.py` | 18 | 2.6 | 0.1 |
| `test_r13_question_shuffle.py` | 17 | 2.3 | 0.1 |
| `test_proficiency.py` | 10 | 1.3 | 0.1 |
| `test_profile_service.py` | 8 | 1.2 | 0.2 |
| `test_weakness.py` | 14 | 0.4 | 0.03 |
| `test_ai_provider.py` | 16 | 0.2 | 0.01 |
| `test_role_fit.py` | 15 | 0.2 | 0.01 |
| `test_r11_contract.py` | 12 | 0.1 | 0.01 |
| `test_ai_timeout_retry.py` | 3 | 0.0 | 0.00 |
| `test_courses.py` | 1 | 0.0 | 0.00 |
| `test_question_backfill.py` | 3 | 0.0 | 0.00 |
| `test_resume_hints.py` | 4 | 0.0 | 0.00 |

读法（关键证据）：

- 耗时 Top 15 个文件合计 **2336.4s（90.2%）**，这 15 个无一例外都会拉起 `TestClient`（或直接调 `import_seed`，
  如 `test_question_bank*`）；反过来，单例均 <0.5s 的 16 个文件合计只有 **70.5s（2.7%）**，全是纯服务层/纯函数调用。
- 极端对照：`test_interview_chat.py` 76 例只要 26.8s（0.4s/例，纯服务层直调）；
  `test_routes.py` 47 例要 247.4s（5.3s/例，每例一次 `client`）。**用例数不是慢的原因，fixture 才是。**
- 报告组（`test_report_service` 98.4 + `test_report_markdown` 16.3 + `test_report_coach` 147.8 = **262.5s**，
  107 例）≈ 4.4 分钟——与「约 8 分钟」的体感差异来自单文件独立跑时无同轮缓存预热，但结论不变：
  这 107 例几乎全是 `client` 启动开销，报告计算本身是毫秒级。
- 结论可直接量化：把 1088 题的灌库成本从 11.26s 压到 0.1–0.3s，Top 15 那 2336s 能砍掉约 **85%**。

## 2. 慢在哪（实测归因）

### 2.1 单次 `TestClient` 启动 11.27s

```powershell
python -c "import os,tempfile,time; os.environ['DB_PATH']=tempfile.mktemp(suffix='.db'); from fastapi.testclient import TestClient; from app.main import app; t0=time.perf_counter(); c=TestClient(app); c.__enter__(); t1=time.perf_counter(); c.__exit__(None,None,None); print('lifespan_s=%.2f'%(t1-t0))"
# lifespan_s=11.27
```

拆开同一流程：

```text
init_db=0.26  import_seed=11.26(+1088)  refresh=0.05(+0)
```

- **`import_seed` 是唯一大头**：1088 行，每行一次 `repository.insert_question` → 各自开连接 / 各自一个事务；
  行数越多越线性膨胀（题库 1088 题以后每加题都变慢）。
- `refresh_from_seed` 在已经一致的库上 0.05s，不是问题。
- `init_db()` 建表 + 9 步迁移 0.26s，也不是问题。

### 2.2 逐项回答「是不是 AI / 是不是 sleep / 是不是 fixture」

| 假设 | 实测 | 结论 |
| --- | --- | --- |
| 报告组真的在调 AI | `test_report_service.py` / `test_report_markdown.py` 全程无 `AIClient` / `monkeypatch`；全部确定性计算 | ❌ 不成立 |
| 有真实 `time.sleep` / 重试等待 | `app/` 内无 `sleep`/backoff；测试里只有 `test_profile_job.py:55`、`test_r42_jobs.py:87` 两处 **0.05s** 轮询 | ❌ 不成立（合计 <0.1s） |
| fixture 每次重建库 | `tmp_db` 是 function 级：新临时文件 + `init_db()`；`client` 再叠加 `with TestClient(app)` 触发 lifespan → **每次都重新灌 1088 题** | ✅ **成立，就是它** |
| 有网络请求 | `conftest` 全量 `FakeAI` / `reset_ai_pool`，用例零外网 | ❌ 不成立 |

补充：`client` fixture 还顺带建 user + session（毫秒级），可忽略。

### 2.3 各测试文件耗时分布

完整 38 行见 §1.3。一句话：Top 15 文件吃掉 90.2% 的墙钟，它们每例都要么重启 `TestClient`（≈11s 灌种子），
要么直接调 `import_seed`；Top 15 之外的其他 23 个文件合计只有 255.1s（9.8%）。

## 3. 瘦身方案（**未实施，等确认**）

### 方案 A（推荐，先做）：把 `import_seed` 改成单事务批量写入（生产同样受益）

- 位置：`app/core/repository.py` 新增 `insert_questions(rows) -> int`（`executemany` + `INSERT OR IGNORE`，
  用 `conn.total_changes` 差值返回新增数），`question_bank.import_seed()` 改调它。
- 语义不变：仍「只增不覆盖」、仍返回新增行数、仍幂等；`refresh_from_seed` 不动。
- 预期收益（按实测折算）：
  - 单次启动 **11.3s → 0.1–0.3s**；
  - 单例 `client` setup **11–30s → 0.4–0.6s**；
  - 全量 **43 分钟 → 约 10 分钟**（Top 15 砍 85% + 其余 255.1s 不变 ≈ 605s）。
- 风险：低（只改写入方式，不改数据语义）；需要补一条 `executemany` 幂等/新增数用例。

### 方案 B（叠加）：预置种子模板库 + 每例拷文件

- 做法：session 级 fixture 建一次「已灌种子」的模板 `.db`；`tmp_db` 改为 `shutil.copyfile` 模板 → 临时路径，
  再跑 `init_db()`（`CREATE IF NOT EXISTS` 天然幂等）。
- 前提：方案 A 之后 lifespan 的重复导入已接近免费，否则模板库会被 lifespan 再灌一遍。
- 预期：在 A 之上再省 `init_db` 与空库建表的时间（每例 ~0.2s），收益边际。

### 方案 C（可选）：`pytest-xdist` 并行

- 每例独立临时库，天然可并行；加 `pytest-xdist` 后 `-n auto`。
- 预期：A 之后 10 分钟 → **2 分钟左右**（4–8 核）。
- 代价：多一个开发依赖 + CI 需要装；并行下日志/临时文件冲突需确认（目前用 `uuid4` 文件名，安全）。

### 不建议

- 全局 session 级 `client`（会破坏用例间数据隔离，大量用例直接写库）；
- 缩小测试种子到「够用就行」（组卷结构闸门依赖 1088 题的方向/难度分布，回归风险高）。

## 4. 本轮结论

1. 基线已建立并可复现（§1.1 两轮：首轮 613/1 skip/1 failed，失败项本轮修掉；次轮 **615 全绿、exit=0、43.2 分钟**）。
2. 慢的根因是 **重复灌种子 + 单行事务**，不是 AI、不是等待、不是报告组本身；
   报告组 107 例本身只占 262.5s，其余是逐例 `client` 启动（§1.3）。
3. 优先方案 A（生产与测试双收益），预估全量 43 分钟 → 约 10 分钟；方案 B/C 可按需叠加。
4. **本轮不改测试基础设施**，等确认后再动手。
