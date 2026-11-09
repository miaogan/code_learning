# 素材来源与生成留痕（自建三源）

本文件是 `docs/question-bank-staging/` 下三份**自建素材**的来源凭证，关闭 r12 验收 P3-D-6。
第四份 `04-fe-interview20.json` 是第三方 MIT 素材，许可凭证在 `NOTICE-fe-interview.md`，不在本文件范围。

## 1 结论（一表看完）

| 文件 | `source` | 种子 id 前缀 | 条数 | 来源性质 | 上游 / LICENSE |
| --- | --- | --- | --- | --- | --- |
| `01-题集20.json` | `tiji` | `tiji-` | 20 | 自建：AI 生成 + 人工抽检 | 无上游，无第三方 LICENSE |
| `02-本地100题.json` | `local100` | `l100-` | 100 | 自建：AI 生成 + 人工抽检 | 无上游，无第三方 LICENSE |
| `03-七方向379题.json` | `iq380` | `iq380-` | 379 | 自建：AI 生成 + 人工抽检 | 无上游，无第三方 LICENSE |

- 合计 **499 道**（与 r12 合并报表「新增 519 = 499 自建 + 20 fe-interview」一致）。
- 三份文件内**没有任何 URL 字段**，`source_title` / `source_file` / `source_set` 均为整理期的**内部分组标记**，
  不指向外部仓库，因此不适用「MIT 需 `NOTICE-<source>.md`」流程（事实已记录于 r12 `TECH-CHANGE.md` §3.5 / §7-①）。

## 2 生成方式与时间

- 生成方式：由 AI 生成/改写题干、选项与解析（客观题口径，`kind ∈ {single, multiple, judge}`），
  再按 `rules.py` 的方向 / 语言闭集人工归位；r12 做 12 道人工抽检（每来源 3 道，任一来源正确率 <90% 整源剔除）。
- 落地时间：2026-11-02，随 r12 提交 `eada0e3` 进入仓库（任务夹 `docs/teamflow/20261102-r12-question-bank-merge/`）。
- 本文件补记：2026-11-02（r16 收口，任务夹 `docs/teamflow/20261102-r16-d4-d6-closure/`）。
- 三份素材**未引用任何第三方题目文本**；若后续发现某条与外部题库实质重合，按 r12 `TECH-CHANGE.md` §6
  剔除该条（数据只增不删，须走 `question_merge --rollback` 后重跑 `--write`）。

## 3 每份素材的结构（按文件实测）

### 3.1 `01-题集20.json`（`tiji`，20 道）

- 字段：`n` / `language` / `direction` / `kind` / `difficulty` / `essentiality` / `stem` / `options` / `answer` / `explanation`
- 题型：single 12 / multiple 4 / judge 4
- 方向：前端 12 / 后端 4 / 算法与数据结构 2 / 计算机基础 2
- 语言：js 5 / ts 2 / css 1 / html 1 / vue3 2 / react 1 / python 2 / java 1 / go 1 / 通用 4
- `n` 是源内原序号（1 起），与种子 id `tiji-%03d` 一一对应（`n=1` → `tiji-001`）。

### 3.2 `02-本地100题.json`（`local100`，100 道）

- 字段：`uid` / `source_set` / `source_title` / `source_difficulty` 等 staging 专有键（**不进种子**）
- 题型：single 75 / judge 25
- 方向：前端 26 / 后端 61 / 算法与数据结构 12 / 计算机基础 1（r12 按 `language` 纠正 8 条，见合并报表 §2）
- 语言：vue3 6 / ts 1 / html 2 / js 6 / react 3 / go 3 / java 3 / python 2 / css 6 / 通用 68
- `source_set` 是内部主题分组（4 组：「全栈基础与前端工程化」21 / 「多语言后端与数据库缓存」21 /
  「AI 工程化、RAG 与 Agent」10 / 「运维、DevOps 与系统设计」12，其余 36 条为空），
  **不是上游仓库名或第三方题集名**。
- `uid` 形如 `1-1`（组号-序号），仅供整理期定位；种子 id 由源内原序生成（`l100-%03d`），与 `uid` 不直接对应。

### 3.3 `03-七方向379题.json`（`iq380`，379 道）

- 字段：`uid` / `source_file` / `source_title` 等 staging 专有键（**不进种子**）
- 题型：single 288 / judge 91
- 方向：前端 62 / 后端 281 / 算法与数据结构 24 / 计算机基础 12（r12 按 `language` 纠正 1 条）
- 语言：vue3 14 / react 16 / ts 7 / html 6 / css 3 / js 2 / java 60 / python 60 / go 50 / 通用 161
- `source_file` 指向 7 个整理期的内部 markdown 分组（`01-frontend.md` 60 / `02-java.md` 60 / `03-python.md` 60 /
  `04-go.md` 50 / `05-ai.md` 69 / `06-devops.md` 40 / `07-system-design.md` 40）；**这些 md 未随仓库提交**，
  分组信息只保留在该字段，不是外部文件路径。
- `uid` 形如 `01-1`；种子 id 按源内原序生成（`iq380-%03d`）。

## 4 与种子 / 契约的关系

- `source` 只写进 `backend/app/seed/questions.json` 与 `questions.source` 列，**不进 HTTP 契约**
  （`backend/app/schemas.py` / `frontend/src/api/types.ts` 零改动）。
- 三源全部并入且未被去重丢弃（r12 合并报表 §2：读入 = 新增 = 20/100/379，越界 0、字面重复 0、近重复 0）。
- 可复现：`cd backend && python -X utf8 -m app.services.question_merge --check` 必须 0 差异；
  素材被改动会让该命令变红，故本目录是**输入真源**，不得随手编辑。
- 回滚：`python -X utf8 -m app.services.question_merge --rollback` 按 `tiji-` / `l100-` / `iq380-` / `fei-`
  四个前缀删库内本批行（存量 260 行不受影响）。

## 5 与 fe-interview 的边界

`04-fe-interview20.json`（20 道）是唯一第三方素材（上游 `haizlin/fe-interview`，MIT），
上游 URL、LICENSE 全文与 AI 改写说明在 `NOTICE-fe-interview.md`；
`backend/tests/test_r12_question_merge.py::test_license_notice_present_when_third_party_source_in_seed`
把它钉成机器门槛。本文件只覆盖 01/02/03 三份自建素材，不与 NOTICE 重复叙述。

## 6 追加素材 `10-ai-engineering-advanced.json`（r47，2026-11-09）

| 文件 | `source` | 种子 id 前缀 | 条数 | 来源性质 | 上游 / LICENSE |
| --- | --- | --- | --- | --- | --- |
| `10-ai-engineering-advanced.json` | `ai-adv` | `aiadv-` | 40 | 自建：AI 生成 + 人工逐条复核 | 无上游，无第三方 LICENSE |

- 面向「高级 AI 应用工程师」，全部为 AI 工程方向、`language=""` 的通用题；
  子方向分布：部署与推理 12 / LLM 与 RAG 12 / Agent 7 / Prompt 工程 6 / 通用 AI 3；
  难度：challenge 30 / intermediate 10；题型：single 24 / multiple 11 / judge 5。
- 与 01/02/03 的差异：**素材显式声明 `sub_direction`**（合法值由 `rules.SUBDIRECTIONS` 校验后随行落盘，
  非法值不猜、回落方向通用兜底），因此新题不会被统一标成「通用 AI」；老素材不带该键，键序断言不变。
- 题干与既有全库做过 2-gram Jaccard 查重（阈值 0.62，实测最高相似度 < 0.40），
  `--write` 报表确认读入 40 / 新增 40 / 越界 0 / 字面重复 0 / 近重复 0。
- 未引用任何第三方题目文本；`--check` 逐字节 0 差异是唯一幂等判据，
  回滚按 `question_merge.SOURCES` 全量删本批行（含 `aiadv-`），存量 260 行不受影响。

## 7 追加素材 `11-ai-engineering-systems.json`（r48，2026-11-09）

| 文件 | `source` | 种子 id 前缀 | 条数 | 来源性质 | 上游 / LICENSE |
| --- | --- | --- | --- | --- | --- |
| `11-ai-engineering-systems.json` | `ai-sys` | `aisys-` | 36 | 自建：AI 生成 + 人工逐条复核 | 无上游，无第三方 LICENSE |

- 承接 r47，继续面向「高级 AI 应用工程师」，但主题收敛到**系统设计与评测基础设施**，
  三组各 12 道：多 Agent 编排（`Agent`）、RAG 评审（`LLM 与 RAG`）、harness / 评测流水线工程（`通用 AI`）。
- 全部为 `difficulty=challenge`、`essentiality=advanced`、`language=""` 的 AI 工程通用题；
  题型：单选 18 / 多选 14 / 判断 4（判断「正确」「错误」各 2，避免扰动判定题极性分布）。
- 沿用 r47 的显式 `sub_direction` 通道（合法值随行落盘），三组分别落在 `Agent` / `LLM 与 RAG` / `通用 AI`；
  与 01/02/03 老素材的键序互不干扰。
- 与全库逐条做过题干 2-gram Jaccard 查重（阈值 0.62，实测 ≥0.40 的配对为 0）；
  解析不含孤立字母引用、正确项长度比均 ≤3、越界丢弃 0。
- `--write` 报表确认读入 36 / 新增 36 / 字面重复 0 / 近重复 0；
  `--check` 逐字节 0 差异是唯一幂等判据，回滚按 `question_merge.SOURCES` 全量删本批行（含 `aisys-`），
  存量 260 行不受影响。
