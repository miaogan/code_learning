# r111 验收报告

日期：2026-11-16 · 范围：JD 缺口驱动的定向追问（P1）+ 跃迁档案表达复盘对照（P2）

## 验收结论

全部通过（本机已知的 health 启动竞态除外，见 §4）。

## 1. 功能验收（对照 PRD 验收标准）

| # | 标准 | 结果 |
|---|---|---|
| 1 | 带缺口开局，提示词含清洗后的缺口词；technical 前几题围绕缺口 | ✅ `test_interview_chat.py` 缺口进提示词用例 |
| 2 | 清洗：空白丢弃 / 截 40 / 去重 / 最多 3；空缺口不出现提示段 | ✅ 清洗口径用例（含 `" Redis "` / 重复 / 超长 / 空串） |
| 3 | 存量 run 无 `settings.focus_gaps`：读取照旧、空列表、不产生对照行 | ✅ `test_archive_expression_gap_compare_by_run_settings` |
| 4 | 表达块逐条命中 / 未提到；`go` 不命中 `golang` | ✅ `test_term_in_text_reuses_alias_and_word_boundary` |
| 5 | `/jd` 链接 → 预填 → 开局提交全链路合法值；无缺口不下发空键 | ✅ `interviewSettings.test.ts` / `jdMatch.test.ts` |
| 6 | 契约镜像逐字段；无 `source` 字段泄漏（r12 门禁） | ✅ `test_r7_contract_mirror` + r12 门禁通过 |
| 7 | 后端 ruff / 专项、前端 typecheck / lint / build / 全量 | ✅ 见 §2 / §3 |

## 2. 后端验证

- r111 专项（r108 跃迁含 r111 节 + r110 JD + interview_chat）：**57 passed**。
- ruff（schemas / leap / jd_match / interview / 三个测试文件）：**All checks passed**。
- 全量（分四批，70 个测试文件）：**1076 tests / 2 failures / 1 skipped**。
  - 2 条失败均为 `test_health`（`test_health_returns_ok` / `test_health_reflects_live_env`），
    是 r98 依赖恢复循环在本机多容器环境的**已知启动竞态**：r110 轮已用 `git stash` 基线证明与改动无关；
    本轮**单独复跑 `test_health.py` 4 passed**；CI（Docker 环境）backend job 历来全绿。
  - 1 skipped 为既有已知跳过项。

## 3. 前端验证

- typecheck / lint：**通过**。
- build：**通过**（3.30s；chunk >500kB 警告为既有状态，非本轮引入）。
- 专项：`leapArchive` 10 条、`jdMatch` 4 条、`interviewSettings` 28 条，**全部通过**。
- 全量（45 个测试文件逐文件）：**581 tests / 0 failures**。

## 4. 已知问题与本机环境

- `test_health` 两用例在全量批跑时偶发失败（db_status=starting），单独跑必绿、CI 不复现——沿用 r110 结论，不修既有 health 逻辑。
- vitest / esbuild 在宿主 Temp 目录偶发 EPERM（宿主安全清理 hook）；本轮构建与测试均通过项目内 TEMP 重定向（`node_modules/.vitest-temp` / `.esbuild-temp`）规避，与断言无关。
- 本轮第一次 build 因未带 TEMP 重定向失败，重跑通过；不算产品问题。

## 5. 交付边界

- 未提交、未推送、未部署；生产仍为 `15bea332`（r108 + r109）。
- 改动文件清单见 TECHNICAL.md；r110 与 r111 两轮改动同在工作区，尚未分 commit。

## 6. 后续建议（不在本轮）

- 报告页回收缺口：报告若能标注「本场由 JD 对位发起、缺口为 A/B/C」，闭环可见性更好。
- `focus_gaps` 出题效果依赖模型遵循度，可在报告侧统计「缺口题占比」做只读观测（仍不评分）。
