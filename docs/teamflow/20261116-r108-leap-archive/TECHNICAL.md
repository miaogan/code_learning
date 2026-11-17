# r108 技术方案

## 1. 契约（snake_case，两侧镜像）

`backend/app/schemas.py` 末尾新增：`LeapRoleGap` / `LeapEngineeringItem` / `LeapEngineering` /
`LeapExpressionStructure` / `LeapExpressionItem` / `LeapExpression` / `LeapArchive`；
`frontend/src/api/types.ts` 逐字段镜像同名 interface。复用了既有 `RoleFit` / `RagStatus`，
没有改它们的字段（`test_r7_contract_mirror` 不受影响）。

`GET /api/leap-archive` → `LeapArchive`，`dependencies=[Depends(current_user)]`。

## 2. 服务端聚合（零 AI / 零新表 / 零重算）

`backend/app/services/leap.py`：

- `_role_gap()`：`repository.latest_report()` 的 `role_fit` 直接透传；无报告 / 无岗位给中文 notice。
- `_engineering()`：`repository.latest_profile().projects` 逐条投影（name/role/period/bullets/
  `len(source_quotes)`/status），`evidence_data_scale()` + `public_table_count()` +
  `indexer.index_status()` + `radar_latest_run()` 只报事实。
- `_expression()`：`repository.list_runs(kind="interview", limit=MAX_INTERVIEW_RUNS)`，逐条只看
  **score 为数字**的发言（与 `interview._score_of` / `history.score_of` 同口径），分数 / 点评
  取写入值；`check_expression_structure()` 做四要素关键词自检。
- 上限：`MAX_INTERVIEW_RUNS=5` / `MAX_PER_RUN=6` / `MAX_EXPRESSION_ITEMS=12`，只影响取数量。

工程门禁兼容：服务层无裸 SQL（`test_sql_only_through_repository`）、无整数 `30` 字面量
（`test_proficiency_thresholds_only_from_config`）、不复写方向 / 难度闭集
（`test_r7_closed_sets_not_duplicated` 只扫 role_fit.py / weakness.py，本模块不涉及）。

## 3. 四要素文本自检

关键词闭集在 `leap.py` 顶层（`_PROBLEM_WORDS` / `_SOLUTION_WORDS` / `_PITFALL_WORDS` /
`_TREND_WORDS` / `_FROM_TO` / `_NUMBER_WITH_UNIT`），只判措辞是否出现，不判真假。
指标命中要求「带单位的数量」或「趋势词 + 数字」或「从…到…」，避免把编号 / 纯趋势词当数据。
每条 hint 都明说「文本自检而非评分」「不构成能力结论」「不能当生产经验」。

## 4. 前端

- `lib/leapArchive.ts`：纯函数 `scaleRows` / `orderedProjects` / `structureParts` /
  `expressionSummary` / `isLeapEmpty`；页面零二次统计。
- `pages/LeapPage.tsx`：一个 `useAsync` 拉 `api.leapArchive`；三块 Card，复用 `RoleFitCard`；
  空态 `EmptyState` 带引导；错误 `InlineError` 可重试。
- `App.tsx`：`TOOL_ITEMS` 加「跃迁 /leap」，`<Routes>` 加路由。
- 样式：`base.css` 末尾 append `sc-leap-*`，全部 `var(--*)`，不改既有行
  （`test_style_baseline_append_only` 通过）。

## 5. AI 上下文

- `taifu/policy.py` `PAGES` 加 `/leap`（label + hint）。按 r81 分层，页面上下文**不进引用白名单**。
- `coach/agent.py`：`TOOL_CATALOG` + `TOOLS` 加 `read_leap_archive`；`_read_leap_archive()`
  复用 `build_leap_archive()`，产出 `ref=l1..` / `href=/leap` 的 items。引用白名单是
  `catalog.setdefault(item["ref"], item)` 动态构建，新 ref 自动进白名单，无需改校验逻辑。
  兜底计划 `_default_plan()` 不变（保留既有测试语义）。

## 6. 测试

- `tests/test_r108_leap_archive.py`（10 条）：四要素纯函数 4 条 + 路由空态 / 岗位差距复用 /
  旧报告降级 / 项目证据 / 表达取数与隔离 6 条。
- `tests/test_coach_agent.py` 追加 3 条（新工具空态、映射、闭集注册）。
- `tests/test_r77_taifu.py` 追加 1 条（`/leap` 页面识别）。
- `frontend/src/test/leapArchive.test.ts`：纯函数 9 组断言。

## 7. 工程待办结论（logs/teamflow/，不进仓库）

- 课程外链：30 门（旧待办的「25 门」过时），25 通 5 未通过，5 条均为反爬 / 限流 / 网络超时，
  **无可判定死链**，需人工浏览器复核。
- 真实环境补测清单：T1–T9（含 r108 跃迁档案真机走查）。
- 多进程限流：维持内存实现；扩容前必须先拆兜底协调器，再换 Redis 限流。
