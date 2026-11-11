# 技术方案与变更记录

## 数据设计

- 素材：`docs/question-bank-staging/13-system-architecture-scenarios.json`，60 条原创记录。
- `source="sys-arch"`，ID 前缀 `sysarch-`；`question_merge.py` 在 `SOURCES` / `STAGING_FILES` / `ID_PREFIX` 三处登记，合并优先级继续由 `SOURCES` 单点派生。
- 所有行显式声明 `direction="研发工程实践"`、`sub_direction="架构设计"`、`language=""`；该二级方向已存在于 `rules.SUBDIRECTIONS`，无需扩展前后端闭集。
- 题型：single 40 / multiple 11 / judge 9；难度：basic 12 / intermediate 33 / challenge 15；必备度：must_know 29 / advanced 31。判断题正确 6 / 错误 3。

## 链路复用

沿用 `normalize_record()`、归一化字面查重、字符 2-gram Jaccard 0.62 门禁、`question_shuffle.apply()` 和 `question_bank.ensure_seeded()`。`practice_pool()` 只收客观题，`exam_pool()` 只排除 `source="radar"`，所以人工复核的 `sys-arch` 题可进入练习与笔试。筛选继续走 `practice._resolve_focus()` 和 `_filtered()`，判分仍只有 `exam.grade_objective()` 一份；无运行时服务、SQL、HTTP schema 或前端改动。

合并器自动更新历史 `QUESTION-BANK-MERGE-REPORT.md` 与 `SHUFFLE-REPORT.md`，不改历史任务夹其他文件。新增素材的来源性质与查重结果追加至 `PROVENANCE.md`，当前题量与来源表同步至 ARCHITECTURE。

## 选项轮转与冻结基线

新增 60 道通用语言题进入 `language=""` 桶，按既有内容哈希定序和最低计数位置轮转规则改变部分旧题选项 key／位置；多选也按内容哈希重排。旧 1224 道 ID、题干、选项文本及正确答案文本均保留，73 道旧题解析中的选项字母引用由重排器同步更新，字母一致性违规 0。前 260 行块仍为 **199377 字节**，SHA-256 按实际重排结果更新为：

```text
dd96b8bfe242cd724ade875c14b91cec1bf0e8e7ea3fe95ff4521085cd6baadb
```

这是全局位置均衡的确定性副作用，不是答案语义或判分规则变更。

## 回归网

- `test_question_bank_quality.py`：总量 1284、来源 `sys-arch=60`，固定本批题型／难度／必备度／分类／判断题分布；同一断言跑 seed 与导入后的库。
- `test_r12_question_merge.py`：总量 1284、素材 1024、前 260 行冻结 SHA-256、双次重算及回滚计数。
- `test_r11_practice_service.py`：真实 seed 在临时库中首次导入 1284，重复 `import_seed()` / `refresh_from_seed()` 均为 0；架构设计精确筛选 60、`limit=0` 无补位、`stats.hit=60`；单选／多选／判断标准答案判 True，错误／少选判 False，题单不泄露答案和解析，且本批进入笔试题池。
- 全库近重复门禁、选项引用一致性、答案长度比与代码规范继续复用既有测试。

## 验证环境

使用仓库已有 `backend/.venv`（Python 3.13.14），统一 `-X utf8`，并显式传入 `PYTHONPATH=backend` 与 `backend/pyproject.toml`。仓库根的 pytest 会找根目录配置；只传 `tests/...` 相对路径会收集 0 项，因此专项和全量均使用绝对测试路径。ruff 同样传后端绝对路径。临时 SQLite 由 `tmp_db` fixture 放在 `backend/tests/.tmp` 并自动清理，不读取或写入用户开发数据库。

## 回滚与部署

代码回退后，通过既有 `question_merge --rollback` 删除全部已登记素材来源，保留 260 道存量；该操作包含本批，不是只删 `sys-arch` 的专用回滚。不要手工删 seed 或数据库行。正式 seed 已生成，本轮未主动写用户开发数据库；后端下次启动由 `ensure_seeded()` 幂等补入新题并刷新同 ID 行，历史作答与卷面快照不因选项刷新而重算。
