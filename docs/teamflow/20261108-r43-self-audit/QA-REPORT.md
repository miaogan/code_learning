# r43 自检迭代 · QA 报告

- 任务夹：`docs/teamflow/20261108-r43-self-audit/`
- 基线结果与瘦身分析另见 `TEST-BASELINE.md`。
- 本轮未提交、未合并。

## 1. 验证结果

### 1.1 后端

| 命令 | 结果 |
| --- | --- |
| `python -m ruff check app tests` | ✅ All checks passed |
| `python -m pytest tests/test_exam_service.py::test_paper_never_leaks_answers "tests/test_routes.py::test_exam_create_submit_and_resubmit_400" tests/test_engineering_gates.py tests/test_exam_filter.py -q` | ✅ 72 passed |
| `python -m pytest -q --durations=0`（全量基线） | ✅ 次轮 **615 例全绿、exit=0**，逐用例聚合 2591.5s（≈43 分钟）；首轮 613 passed / 1 skipped / 1 failed 的失败项已在本轮修掉。明细见 `TEST-BASELINE.md` §1 |

### 1.2 前端四道门禁

| 命令 | 结果 |
| --- | --- |
| `npm run typecheck` | ✅ 通过 |
| `npm run lint` | ✅ 通过（0 warning） |
| `npm test -- --run` | ✅ 19 files / 222 tests passed |
| `npm run build` | ✅ 141 modules，3.23s |

## 2. 第 3 项：熟练度说明合并成一处

| 验收点 | 落点 | 结论 |
| --- | --- | --- |
| 过滤结果行说明「题怎么才会回流」 | `frontend/src/lib/examNotice.ts::proficiencyRuleHint()`；`ExamPage.tsx` 卷面首行 | ✅ 写明「默认 30 天内答对 2 次及以上、且最近一次答对才计为熟练；超过 30 天或最近一次答错自动回流」 |
| 结果面板复显本卷过滤事实 | `ExamPage.tsx` 提交态 `.sc-meta-line`（`filteredNotice` + `backfillNotice` 同行拼接） | ✅ |
| L2 兜底回流提示「另有 N 道…」 | 后端 `reintroduced_count`（`ExamRun` / payload）+ 前端 `backfillNotice()` | ✅ |
| 合并成一处（不是三个标签） | 首行一个 `.sc-meta-line`：事实 · 规则 · 兜底计数 | ✅ 单节点、单行 |
| 净过滤 0 但确有回流 | `proficiencyRuleHint(0, 4)` 仍返回说明（r19 的 N=0 静默缺口已补） | ✅ 单测锁定 |
| 契约两侧同步 | `backend/app/schemas.py` ↔ `frontend/src/api/types.ts`，`snake_case`，默认 0 | ✅ 工程门禁锁定字段集与默认值 |
| 360–430 窄屏 | `.sc-meta-line` 为 `flex-wrap: wrap`，长句换行、无横向溢出（无新增尺寸 / token） | ✅ 静态核对（未实机走查） |

## 3. 第 4 项：零散缺陷核对

| 项 | 证据 | 结论 |
| --- | --- | --- |
| 面试 `Composer` 字数计数与超限提示 | `frontend/src/components/interview/Composer.tsx`：`已用 Xs · N/MAX 字`，达上限追加「（已达上限）」 | ✅ 已交付（r5 O-2），本轮不改 |
| 框架级 405 中文化 | `backend/app/main.py:173` → `METHOD_NOT_ALLOWED` +「该接口不支持此请求方法」；`test_routes.py:84` 锁定 | ✅ 已交付（2026-11-03），本轮不改 |
| 上传上限校验收敛到 `services/parser.py` 单一出处 | 新增 `ensure_upload_size()`；文档 / 单张图片 / 图片合计三条路径共用；错误码仍 `FILE_TOO_LARGE` | ✅ 本轮补齐（r42 图片路径曾绕过单源） |

## 4. 第 5 项：文档收尾

| 项 | 处理 |
| --- | --- |
| `ARCHITECTURE.md` §7.2 过期条目 | 删除「缺 `pypdf`/`python-docx`」「全局无 `ruff`」两条（均已可实跑），§7.1 补「本地工程验证（r43 补记）」 |
| §7.2 缺 r5 行 / §8 待落地 / 重复统一约束 | 核对确认已在 r17 清理，当前文本无该内容，不回改 |
| §7.1 测试文件数 | 31 → 38（实测） |

## 5. 风险与遗留

- 本轮**没有**改动测试基础设施；测试瘦身只出方案（`TEST-BASELINE.md` §3），等确认后再动手。
- 规则文案含「默认 30 天 / 答对 2 次」：阈值仍住后端 `config.Settings`，若运维用环境变量覆盖，文案只能以「默认」限定（已留痕，不做接口下发）。
- 未做浏览器端 360–430 实机走查；`ExamPage` 的说明行为单行长句，靠 `.sc-meta-line` 的 `flex-wrap` 换行，未新增视觉尺寸。
- iOS 真机 HEIC 补测仍是 r42 遗留，不在本轮范围。
