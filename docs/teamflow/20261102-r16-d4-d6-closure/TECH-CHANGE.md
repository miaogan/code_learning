# r16 · r12 遗留 D-4 / D-6 文档收口（技术变更单）

> 本轮**只改文档，零代码改动**：D-4 在架构文档回写题库 id 前缀真相，D-6 为三份自建素材补来源留痕。
> 不改 HTTP 契约、不动 seed、不改运行时行为。

## 1 背景

r12 验收（`docs/teamflow/20261102-r12-question-bank-merge/ACCEPTANCE.md` §4）留了两条不阻断的 P3，原文口径：

- **D-4**：`TECH-CHANGE.md` §3.2 第 36 行写 id 前缀 `tiji-NNN` / `l100-NNN` / **`iq-NNN`** / `fei-NNN`，
  实现取 `iq380-`（有意避开面试 `iq-` 域）；处置「文档回写（1 行），不阻断」。
- **D-6**：`docs/question-bank-staging/` 仅 fe-interview 有 NOTICE，01/02/03 三来源无 PROVENANCE 留痕；
  建议补 `PROVENANCE.md`（自建 / AI 生成 + 方式 + 日期）。

约束：每个任务夹建后**不可变**，r12 夹不得回改（`memory.md` 说明段）；历史文档错误只能由后续需求
在产品级文档补记（先例：`memory.md` 第 40 行「r5 `TECHNICAL.md:186,302` 仍记 3 参旧签名（历史夹不可改）——由后续需求在架构文档补记」）。

## 2 改动面

| 文件 | 改动 | 说明 |
| --- | --- | --- |
| `docs/teamflow/architecture/ARCHITECTURE.md` | 新增 §3.4.2 | 四前缀与 `source` 一一对应表 + `iq380-` 规避理由 + 「r12 §3.2 为历史笔误，以实现代码与本表为准」 |
| `docs/teamflow/architecture/ARCHITECTURE.md` | 更新 §7.1 题库行 | 补素材留痕位置（`PROVENANCE.md` + `NOTICE-fe-interview.md`）与 §3.4.2 指引 |
| `docs/question-bank-staging/PROVENANCE.md` | 新增 | 01/02/03 三份自建素材的来源性质、生成方式与时间、结构实测、与 seed / 契约的对应、回滚口径 |
| `docs/teamflow/20261102-r16-d4-d6-closure/**` | 新增 | 本任务夹（`meta.json` / 本变更单 / `ACCEPTANCE.md`） |
| `docs/teamflow/memory.md` | 更新 | r12 收口条目：D-4 / D-6 标为已关闭并指向本任务夹；新增 r16 约定条 |
| `backend/**`、`frontend/**`、`backend/app/seed/questions.json` | **零改动** | 实现本身正确（`ID_PREFIX` 已是 `iq380-`），错的是历史文档 |

## 3 方案

### 3.1 D-4：架构文档回写 id 前缀真相

- **事实来源**：`backend/app/services/question_merge.py` 的 `ID_PREFIX` 与上方注释
  （四前缀避开 legacy `fe-/be-/al-/cs-` 与 r11 九个语言前缀；`iq380-` 刻意不用 `iq-`，因面试发言 id 同为 `iq-{序号}`）。
- **落点**：ARCHITECTURE §3.4.2（数据模型章内），给出一张「`source` → 前缀 → 素材 → 许可留痕」表，
  并单列三条口径：存量 260 道不写 `source`（读侧缺省 `seed`）、`source` 不进 HTTP 契约、四前缀不得改名
  （改名会让 `--rollback` 与已部署库既有行分叉）。
- **历史笔误的处理**：§3.4.2 末条明确写「r12 `TECH-CHANGE.md` §3.2 的 `iq-NNN` 与实现不符，r12 夹不可改，
  以实现代码与本表为准」，并指向本任务夹验收报告。这样既更正了认知，又不在历史产物里制造第二份真相。
- **不改代码**：`question_merge.py` 已按 `iq380-` 落盘 779 道并通过幂等门禁；改代码反而会破坏既有 id。

### 3.2 D-6：三份自建素材的来源留痕

- **单份而非三份**：三源同属团队自建、字段结构相近，一份 `PROVENANCE.md` 用「结论表 + 每份一节」即可覆盖；
  拆三份会产生大量重复叙述，并与 `NOTICE-fe-interview.md` 的边界更难对齐。
- **只写可核实事实**：条数 / 题型 / 语言 / 方向分布均按 staging 文件实测；「AI 生成 + 人工抽检」依据
  r12 `TECH-CHANGE.md` §6（「素材由 AI 改写…12 道人工抽检（每来源 3 道）」）；`source_set` / `source_file` / `uid`
  明确标注为**整理期内部分组标记**，不指向外部仓库，**不虚构上游 URL 或许可证**。
- **位置与写边界**：`docs/question-bank-staging/` 是 r12 起登记的素材输入目录（`memory.md` 题库合并约定：
  「外部素材一律先落 `docs/question-bank-staging/`（提交进仓库，作为可复现输入）」），PROVENANCE 是素材凭证、
  与 `NOTICE-fe-interview.md` 同类，不是 TeamFlow 任务产物；任务产物仍只落本任务夹。

## 4 验证计划（本轮实跑记录见 `ACCEPTANCE.md`）

1. `cd backend && python -X utf8 -m app.services.question_merge --check` → 0 差异（素材未动，seed 字节不变）。
2. `python -X utf8 -m app.services.question_shuffle --check` → 0 差异。
3. `python -X utf8 -m pytest tests/test_r12_question_merge.py -q` → 许可 NOTICE 门禁与冻结基线全绿。
4. 文档自查：`ARCHITECTURE.md` 中 `iq-NNN` 只出现在「历史笔误」声明句中；`PROVENANCE.md` 的
   tiji 20 / local100 100 / iq380 379 与 r12 合并报表 §2 逐项一致。
5. `git status --short` 只含文档改动（含新增 `PROVENANCE.md` 与本夹）。

## 5 风险与回滚

| 风险 | 处置 |
| --- | --- |
| PROVENANCE 数字与素材 / 报表不一致 | 数字逐项取自文件实测并与 r12 合并报表 §2 对齐；素材未改动由双 `--check` 兜住 |
| 素材后续更新导致 PROVENANCE 过期 | `memory.md` r16 约定：改 staging 素材必须同步 PROVENANCE 并重跑 `question_merge --check` |
| 架构文档出现第三处 id 口径 | §3.4.2 声明「以实现代码与本表为准」，r12 夹保持原文但被明确标注为笔误 |
| 回滚 | `git revert` 本轮提交；零代码、零数据变更，无库影响 |

## 6 取舍

1. **不改 r12 夹**：任务夹不可变是团队硬约定；用产品级架构文档补记可长期生效。
2. **不新增机器门禁**：D-4 属「文档与代码一致性」，无法用测试可靠断言自然语言；D-6 的回归风险
   （素材被改）已由 `question_merge --check` 全量覆盖，MIT 源许可已由既有 NOTICE 门禁覆盖。
   若后续要求「PROVENANCE 存在性」也钉成门禁，另立小需求，避免为 1 个 md 扩测试基线。
3. **单份 PROVENANCE**：见 §3.2。

## 7 交付物

- 文档：`ARCHITECTURE.md`（§3.4.2 新增 + §7.1 行更新）、`docs/question-bank-staging/PROVENANCE.md`、
  本任务夹 `meta.json` / `TECH-CHANGE.md` / `ACCEPTANCE.md`、`memory.md` 收口更新。
- 代码与数据：无。
