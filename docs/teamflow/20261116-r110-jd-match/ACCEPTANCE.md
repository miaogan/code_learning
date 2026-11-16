# r110 验收报告

## 1. 功能验收（逐条对照 PRD §验收）

| # | 标准 | 结果 |
|---|---|---|
| 1 | `/api/jd-match` 登录门禁 + 空白 JD 中文 400 | ✅ 路由带 `Depends(current_user)`；`test_empty_jd_is_rejected` 通过 |
| 2 | 无画像仍列技术词且全部标 missing | ✅ `test_no_profile_still_lists_jd_evidence_with_honest_notice` |
| 3 | 有画像逐条回传 JD 原句与简历引用；短别名按词边界 | ✅ `test_profile_evidence_is_quoted_not_guessed` + `test_short_ascii_alias_does_not_match_inside_word` |
| 4 | 缺口来源分离为 `origin=jd` / `origin=role_model`，无 `source` 泄漏 | ✅ `test_gaps_keep_jd_and_role_model_sources_separate` + `test_r12_source_not_in_http_contract` |
| 5 | 显式岗位优先；自动识别按模型名 / 简称 / 画像 / 报告顺序 | ✅ `test_role_is_detected_and_explicit_target_role_wins` |
| 6 | 一键链接只带闭集值；面试页带入不覆盖手改、不接旧会话 | ✅ `interviewHref` + `presetFromParams` 纯函数测试；`InterviewPage` preset 优先跳过 restore |
| 7 | 按账号隔离；响应无能力分字段 | ✅ `test_service_is_user_isolated` + `test_result_has_no_percentage_or_score_field` |
| 8 | 前后端门禁 / 测试 / 构建通过 | ✅ 见 §2 |

## 2. 验证记录（2026-11-16）

后端（`.venv/Scripts/python.exe`）：

- r110 专项 `tests/test_r110_jd_match.py`：**9 passed / 0 failed**。
- 门禁三件套（`test_style_baseline_append_only` / `test_r7_contract_mirror` /
  `test_r12_source_not_in_http_contract`）：**3 passed**。
- `ruff check`（schemas / main / routers/jd / services/jd_match / test_r110）：**All checks passed**。
- 后端全量按 4 批运行：**1072 tests / 0 failures / 1 skipped**（`.tmp/backend-r110-1b..4.xml`）。
  首批曾出现 2 条 `test_health.py` 启动竞态失败；单独复跑 `backend/tests/test_health.py` **4 passed**，
  再排除该批环境抖动后重跑首批 0 failures。该失败与 r110 无关，未改 health 逻辑。

前端（TEMP/TMP 重定向到项目内 `node_modules` 规避宿主 fs shim 的 EPERM）：

- `npm run typecheck`：通过；`npm run lint`（`--max-warnings 0`）：通过。
- `npm run build`：通过（326 modules transformed，dist 产物生成）。
- 全量 vitest：**45 文件 / 575 tests / 0 failures**（逐文件 JUnit 汇总）。
- 最终字段改名后复验：`jdMatch.test.ts` **4 passed**、`interviewSettings.test.ts` **25 passed**。

说明：本机 vitest / esbuild / pytest 进程收尾时可能因宿主安全清理 hook 在 Temp 目录写锁触发
`EPERM`；测试与构建本身已完成，计数以 JUnit / 明确成功输出为准。

## 3. 交付范围

- 后端：`schemas.py`（r110 契约）、`routers/jd.py`、`services/jd_match.py`、`main.py`、
  `tests/test_r110_jd_match.py`。
- 前端：`api/types.ts`、`api/client.ts`、`lib/jdMatch.ts`、`pages/JdPage.tsx`、`App.tsx`、
  `components/interview/setupModel.ts`、`pages/InterviewPage.tsx`、`styles/base.css`（append-only）、
  `test/jdMatch.test.ts`、`test/interviewSettings.test.ts`。
- 文档：本任务夹 PRD / TECHNICAL / ACCEPTANCE。
- **未提交、未推送、未部署**（按用户当前协作范围）。

## 4. 已知边界 / 后续

- 关键词匹配是确定性字面对照，会漏掉换义词；别名表集中在 `jd_match._ALIAS_OVERRIDES`，后续按真实 JD 增补即可。
- 不产出匹配分；这是刻意选择，避免把文本覆盖率误读成能力结论。
- 「带配置去召对」只带三个字段，经验档 / 市场 / 公司规模仍需用户在面试页确认。
- 语音表达分析、实时 copilot、投递 CRM 均未纳入本轮（见 r110 竞品路线判断）。
