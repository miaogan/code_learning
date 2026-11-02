# r16 验收报告：关闭 r12 遗留 D-4 / D-6（纯文档收口）

- 任务夹：`docs/teamflow/20261102-r16-d4-d6-closure/`（基线依赖 `docs/teamflow/20261102-r12-question-bank-merge/`）
- 验收对象：工作区未提交改动 —— `docs/teamflow/architecture/ARCHITECTURE.md`（§3.4.2 新增 + §7.1 行更新）、
  `docs/question-bank-staging/PROVENANCE.md`（新增）、`docs/teamflow/memory.md`（两条更新）、本任务夹。
- 验收口径：r12 `ACCEPTANCE.md` §4 的两条 P3（D-4 / D-6）；`TECH-CHANGE.md` 声明「零代码改动、不新增功能性 AC」，
  故判据 = 两条 P3 的关闭证据 + 不回归既有约束（种子字节幂等、许可 NOTICE 门禁、契约零改动）。

## 1 判据逐条核对

| # | 判据 | 实测结果 | 结论 |
|---|---|---|---|
| 1 | D-4：架构文档给出「`source` → id 前缀」一一对应 | `ARCHITECTURE.md` §3.4.2 表：`tiji→tiji-` / `local100→l100-` / `iq380→iq380-` / `fe-interview→fei-`，含示例 id 与对应素材文件 | 通过 |
| 2 | D-4：前缀与实现逐字一致 | 与 `backend/app/services/question_merge.py:58-63` 的 `ID_PREFIX` 四键值逐字相同；id 生成规则「`ID_PREFIX[source]` + 源内原序 `%03d`」与实现一致（同文件 `_row_of`） | 通过 |
| 3 | D-4：写明 `iq380-` 规避理由 | §3.4.2 单列一条：面试发言 id 同为 `iq-{序号}`（`runs.payload.questions[].id`），同名不同域会混淆 grep / 日志 | 通过 |
| 4 | D-4：历史笔误被明确更正且 r12 夹未被改写 | §3.4.2 末条声明「r12 `TECH-CHANGE.md` §3.2 的 `iq-NNN` 与实现不符，r12 夹不可改，以实现代码与本表为准」；`git status` 中 `docs/teamflow/20261102-r12-question-bank-merge/` 零改动 | 通过 |
| 5 | D-6：自建三源有 PROVENANCE 留痕 | `docs/question-bank-staging/PROVENANCE.md` 存在，按 01/02/03 分节 | 通过 |
| 6 | D-6：条数与 r12 报表一致 | PROVENANCE §1 表 = tiji 20 / local100 100 / iq380 379（合计 499）；与 r12 合并报表 §2「读入 = 新增 = 20/100/379」逐项一致 | 通过 |
| 7 | D-6：写明来源性质、生成方式、日期 | §2：AI 生成/改写 + 按 `rules.py` 闭集归位 + r12 12 道人工抽检（每来源 3 道，<90% 整源剔除）；日期 2026-11-02（r12 提交 `eada0e3`），补记日期同日 | 通过 |
| 8 | D-6：不虚构上游 / 许可证 | §1 表「无上游，无第三方 LICENSE」；§3 把 `source_set` / `source_file` / `uid` 明确标为整理期**内部分组标记**（`03` 的 7 个 md 未随仓库提交），全文无任何外部 URL 或许可证主张 | 通过 |
| 9 | D-6：与 MIT 源边界清晰 | §5 只说明 `04-fe-interview20.json` 归 `NOTICE-fe-interview.md`，不重复其内容；PROVENANCE 只覆盖 01/02/03 | 通过 |
| 10 | 种子与素材未被改动（幂等不回归） | `question_merge --check` → 「逐字节一致：可用 779 道（幂等成立）」exit 0；`question_shuffle --check` → 「逐字节一致（幂等成立）」exit 0 | 通过 |
| 11 | 既有题库门禁不回归 | `pytest tests/test_r12_question_merge.py -q` → **39 passed**（含许可 NOTICE 门禁、冻结基线、seed 文本清理门禁） | 通过 |
| 12 | 契约与运行时零改动 | `git status --short` 只有上列文档（新增 2 个 md + 本夹 3 文件 + ARCHITECTURE / memory 修改）；`backend/**`、`frontend/**`、`seed/questions.json` 零改动 | 通过 |
| 13 | 记忆收口准确 | `memory.md` r12 条目：D-4 / D-6 由「未关闭」改为「已关闭」并指向本夹；新增 r16 约定条（前缀不得改名、staging 两类凭证、改素材须重跑 `--check`） | 通过 |

## 2 架构一致性

| 蓝图要求 | 实测 | 结论 |
|---|---|---|
| 任务夹不可变 | r12 / r13 / r14 / r15 夹零改动；D-4 的更正落在产品级 `ARCHITECTURE.md`（与 memory 第 41 行先例同法） | 符合 |
| 产品级文档是跨需求真源 | 新增 §3.4.2 与 §7.1 行均指向实现与素材文件，不复制代码逻辑 | 符合 |
| 素材目录是输入真源 | PROVENANCE 明文「不得随手编辑」+ 双 `--check` 兜底 | 符合 |
| 契约零改动 | `schemas.py` / `types.ts` 未触碰，`source` 不进 HTTP 契约的口径保持 | 符合 |
| 无重复实现 | 文档只引用 `ID_PREFIX` / `--check` / `--rollback` 的既有事实，不新增常量或脚本 | 符合 |

## 3 复跑命令

```bash
cd backend && python -X utf8 -m app.services.question_merge --check      # exit 0：可用 779 道（幂等成立）
cd backend && python -X utf8 -m app.services.question_shuffle --check    # exit 0：打乱后逐字节一致
cd backend && python -X utf8 -m pytest tests/test_r12_question_merge.py -q -p no:cacheprovider  # 39 passed
```

文档自查：

```powershell
# ARCHITECTURE 中 iq-NNN 只应出现在「历史笔误」声明句
Select-String -Path docs/teamflow/architecture/ARCHITECTURE.md -Pattern 'iq-NNN'
# staging 凭证齐备
Get-ChildItem docs/question-bank-staging | Select-Object Name
```

## 4 遗留（P3，均不阻断）

| 编号 | 内容 | 处置建议 |
|---|---|---|
| P3-a | `ruff` 本机不可用（`No module named ruff`，无 `backend/.venv`），后端 lint 未实跑 | 与 r9/r12–r15 同口径记录；CI 或含 ruff 的环境补跑一次 |
| P3-b | PROVENANCE 的「存在性 / 章节完整」无机器门禁 | 有意取舍（见 `TECH-CHANGE.md` §6.2）：素材变更已被 `question_merge --check` 覆盖，MIT 源已有 NOTICE 门禁；如团队要求可另立小需求 |
| P3-c | r12 `TECH-CHANGE.md` §3.2 仍留 `iq-NNN` 原文（仅在产品级文档被声明为笔误） | 历史夹不可变的必然结果；读者从 ARCHITECTURE §3.4.2 与 memory 第 43 行均可获正确口径 |
| P3-d | PROVENANCE 的结构统计（题型 / 语言 / 方向）为 2026-11-02 实测快照 | 素材若更新，按 memory r16 约定同步本文件并重跑 `--check` |

## 5 验收判定说明

- 功能性：D-4（架构文档四前缀表 + 规避理由 + 历史笔误声明）、D-6（三源 PROVENANCE 留痕 + 与 NOTICE 边界）全部关闭。
- 结构性：r12 夹零改动、契约零改动、无新增代码 / 常量 / 脚本；记忆与架构文档同步指向本夹。
- 验证：双 `--check` 0 差异、定向 `pytest` 39 passed、`git status` 仅文档。
- 因此判 **通过**；4 条 P3 为环境 / 工艺留痕，不构成返工条件。

验收结论：✅ 通过
