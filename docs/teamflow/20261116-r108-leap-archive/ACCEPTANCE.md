# r108 验收报告

## 1. 功能验收（逐条对照 PRD §验收）

| # | 标准 | 结果 |
|---|---|---|
| 1 | `/api/leap-archive` 登录门禁 + 空态中文指引 | ✅ 路由带 `Depends(current_user)`；专项测试 `test_archive_empty_state_has_chinese_notices` 通过 |
| 2 | 岗位差距 = `latest_report().role_fit` 逐字段，前端零重算 | ✅ `test_archive_role_gap_reuses_report_without_recompute`；前端 `LeapPage` 直接嵌 `RoleFitCard` |
| 3 | 工程证据只列真实项目 / 行数，historical 标注 | ✅ `test_archive_engineering_projects_carry_real_evidence` + `orderedProjects` 纯函数测试 |
| 4 | 表达只收已评分发言，分数 / 点评沿用写入值；自检明说非评分 | ✅ `test_archive_expression_uses_written_score_and_skips_unanswered`（score=None 被跳过）+ hint 文案断言 |
| 5 | 数据按账号隔离 | ✅ `test_archive_is_user_isolated`（service 层切 ContextVar） |
| 6 | 太傅识别 `/leap`；教练新工具空态不编造、引用合法 | ✅ `test_sanitize_page_recognizes_leap_archive` + 教练 3 条新测试 |
| 7 | 前后端全绿 + 契约镜像 | ✅ 见 §2 |

## 2. 验证记录（2026-11-16）

后端（`.venv/Scripts/python.exe`）：

- 跃迁档案专项 `tests/test_r108_leap_archive.py`：**10 passed / 0 failed**（JUnit `junit-r108.xml`）。
- 教练 + 太傅 `test_coach_agent.py + test_r77_taifu.py`：**54 passed**；太傅补测后 41 passed。
- **后端全量**：**1063 tests / 1 failed / 1 skipped / 1061 passed**（JUnit `junit-r108-full.xml`）。
  唯一失败 `tests.test_health::test_health_returns_ok`（`assert 'degraded' == 'ok'`）。
- 前端（TEMP 重定向规避宿主 shim 的 EPERM）：**43 文件 / 542 tests passed**；
  新 `leapArchive.test.ts` 全部通过；`npm run build` 成功。
- `npm run typecheck`：通过；`npm run lint`（`--max-warnings 0`）：通过；
  `ruff check app tests`：**All checks passed**。

### 关于唯一的 health 失败（非本轮回归）

- 现象：`/health` 在 TestClient lifespan 刚启动时返回 `db_status='starting'` → `status='degraded'`，
  而 `test_health_returns_ok` 断言 `status == 'ok'`；teardown 日志随即出现 `db.recovery.ready`。
  这是 r98 依赖恢复循环的**启动竞态**（恢复周期 `DB_RECOVERY_INTERVAL_S=2`，请求发生在首个周期完成前）。
- 归因验证：用 `git stash push` 暂存**本轮全部改动**后单跑该用例，**基线同样失败**（同样的
  `startup_degraded` / `db_status=starting`），随后 `git stash pop` 恢复。故该失败与 r108 无关，
  是本机多容器环境下 PG 首次连接握手变慢暴露的既有不稳定点。
- 处置：不修改既有 health 逻辑 / 测试（超出本轮范围）；记录为本轮全量的已知环境性失败。

说明：本机 vitest / pytest 进程结束时会因宿主 fs shim 在 Temp 目录写入触发 `EPERM`，
报告已完整落盘、与断言无关（详见项目 memory 的 sticky 条）。用 `--junitxml` 读取准确计数。

## 3. 交付范围

- 代码：后端 schemas / services/leap.py / routers/leap.py / main.py / coach agent / taifu policy；
  前端 types.ts / client.ts / lib/leapArchive.ts / pages/LeapPage.tsx / App.tsx / base.css。
- 文档：本任务夹 PRD / TECHNICAL / ACCEPTANCE；`logs/teamflow/r108-*` 三份一次性结论。
- **未提交、未推送、未部署**（按用户本轮选择）。
- v0.3.0 发版仅做物料核对，tag / PR 未动，阻塞项为公网验收口令（见 logs/teamflow/r108-release-check）。

## 4. 已知边界 / 后续

- 文本自检是关键词启发式，会误判 / 漏判；界面已明示「非评分、非能力结论」。
- 雷达数据只作为「站内技术视野」事实展示，不代表个人能力（与 r67 开放项口径一致）。
- 真实浏览器 / 真机走查列入 logs 补测清单 T9，本轮未做（无公网演示账号）。
