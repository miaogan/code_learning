# ACCEPTANCE · r51 验收清单与证据路径

> 状态：**M1 / M2 / M3 均已交付（M1 = r51，M2/M3 = r53），r53 收口批次已交付**。§3/§4 原清单是方案阶段写的验收项，
> 实际结果按 §6「r53 交付核对」与 §7「收口批次核对」核对；有意偏差逐条记在 TECHNICAL §6–§7，
> **未完成项不冒充已完成**。方案原文按「任务夹建后不可变」约定保留，不回改。
> 远端 CI：`#33` / `1c33046` 成功（1m21s），新门禁全部跑绿。
> 追加：**r54 在线评测轨道脚手架**已交付（§8），真实模型未实跑。

## 1. 验证命令（每次交付前全跑）

```bash
# backend/
python -m pytest -q
python -m ruff check app tests
python -X utf8 -m app.services.assessment.question_merge --check

# frontend/
npm run typecheck && npm run lint && npm test && npm run build

# 根
curl -sS http://127.0.0.1:8000/health
```

本机后端依赖解释器：`C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe`（默认 workbuddy python 无 pydantic）。

## 2. M1 · 交付可信度（本轮）

- [x] `.github/workflows/ci.yml` 加 `permissions` / `concurrency`
- [x] 后端 job 加题库字节门禁 `question_merge --check`
- [x] 本地实跑 `--check`：退出码 0，「题库 seed 与素材重算逐字节一致：可用 1164 道」
- [x] `README.md` 加 Actions badge 与「设计取舍」章节（4 条取舍 + 各自代价）
- [x] `AGENTS.md` 变更记录追加 r51
- [x] **CI 在 GitHub 上实跑为绿**：Actions 共 32 次运行，最近 `CI #32`（`163ebb4`，`feat/dev-skill-coach`）成功、1m6s；#21–#26 曾红灯后修复，#27–#32 连续通过。本机 `gh` 未认证，但网页公开可读；`ARCHITECTURE.md §7.1 / §7.2` 已据此更正。
- [x] **题库字节门禁经远端验证**：`Question bank byte gate` 已随 #32 在远端跑绿。
- [x] **本轮新增 4 个评测门禁经远端验证**：`CI #33`（`1c33046`）成功、1m21s，`Offline eval` / `Retrieval eval` / `Question retrieval eval` / `Reliability fault-injection` 全部跑绿。

## 3. M2 · 离线评测 Harness（待实施）

- [ ] `ai_call_logs` 表 / 索引幂等，旧库启动不炸；`db.py` 文件头「7 张表」注释更正为实际数
- [ ] 落库 best-effort：注入写库异常时 `complete_model` 仍正常返回
- [ ] 日志不含 Key / Prompt / 简历正文 / 图片（caplog 断言）
- [ ] `docs/eval/golden-v1.json` 30 例全为合成/脱敏文本，含 response_snapshot 与标注来源
- [ ] `scripts/eval_harness.py` 两条轨道分离；报告显式标注「离线回归 ≠ 模型质量」
- [ ] `--check --baseline v1` 基线未变退出 0、人为劣化退出非 0；波动带 ±2pp
- [ ] 指标分母写死、小样本给 Wilson 区间；轨迹可回放
- [ ] `EvalSummary` 双侧契约同步 + `GET /api/eval/summary` 按 user_id 隔离、越权 404
- [ ] `/eval` 看板注册到 `App.tsx` 路由与 `TOOL_ITEMS`；业务逻辑在 `lib/eval.ts` 且有测试
- [ ] 新增后端 ≥8 条、前端 ≥3 条测试，全量命令全绿
- [ ] `docs/eval/REPORT.md` 生成，数字来自命令输出而非手写

## 4. M3 · 检索增强学习计划（待实施）

- [ ] `lib/tutorialSearch.ts` + `tutorialSearch.test.ts`：bigram 分词、BM25、确定性排序、citation 锚点存在
- [ ] FTS5 探测 + 降级路径各有测试；不可用时中文 `notice` 且不 500
- [ ] `POST /api/search/questions` 不返回答案；契约双侧同步
- [ ] RRF 融合 + `StudyTask.citations?`；`PLAN_VERSION` 升 2；旧快照按版本重算
- [ ] 无命中静默回落 `pickChapter` / `practiceHref`；不检索时与 r50 行为逐字节等价
- [ ] `docs/eval/retrieval-gold.json` 20 组标注；报告给出 recall@5 / 无命中拒答率 / 引用有效率
- [ ] 命名口径核对：全文不出现「RAG」「向量检索」「多 Agent」作为已完成能力
- [ ] 新增前端纯函数测试 ≥6 条，全量命令全绿

## 5. 简历口径终检（写完简历前逐条打勾）

- [ ] 所有数字都能指向一条可复跑命令或其产物文件
- [ ] 离线指标与在线指标分开表述，未混同
- [ ] 未出现「自研模型 / RAG 系统 / 多 Agent 平台」等与代码不符的词
- [ ] `RESUME.md §4` 五个追问能脱口而出，答案能在仓库里指到文件
- [ ] 演示脚本第 3–5 步对应的功能确已上线（未上线不演示）

## 6. r53 交付核对（M2 / M3）

**已完成**

- [x] `ai_call_logs` 表 / 索引幂等，旧库启动不炸；`db.py` 文件头注释更正为 13 张业务表 + 1 张可选虚表
- [x] 落库 best-effort：注入写库异常时 `_persist_call_log` 只记 warning、不抛（13 条后端测试全过）
- [x] 日志不含 Key / Prompt / 正文（`_persist_call_log` 只传元数据）
- [x] `docs/eval/golden-v1.json` 30 例全合成脱敏；`retrieval-gold.json` 20 组，8 方向 / AI 5 子方向全覆盖
- [x] `scripts/eval_harness.py` 两轨分离，报告显式标注「离线回归 ≠ 模型质量」、`--check` 对比基线 ±2pp
- [x] 指标分母写死 + Wilson 区间；`docs/eval/REPORT.md` / `baseline-v1.json` 由命令生成
- [x] `EvalSummary` 双侧契约同步；`GET /api/eval/summary` 登录态、越权 401；`/eval` 看板注册到路由与工具导航
- [x] `lib/tutorialSearch.ts` + `tutorialSearch.test.ts`：bigram / BM25 / 确定性 / RRF / 8 条测试
- [x] FTS5 探测 + 降级（短查询、无虚表）都有测试，`notice` 中文且不 500
- [x] `POST /api/search/questions` 不返回答案；契约双侧同步，脏值静默忽略
- [x] `StudyTask.citations?` 可点击且 section 真实存在；不开启检索时与 r50 逐字节等价（新增 5 条测试）
- [x] 检索无命中静默回落；`docs/eval/RETRIEVAL-REPORT.md` 给出 recall@5 / 拒答率 / 引用有效率 + Wilson 区间 + 解读限制
- [x] 全文不出现「RAG / 向量检索 / 多 Agent」作为已完成能力；命名统一「检索增强 + 引用归因」
- [x] 后端 646 passed / 1 skipped、前端 268 passed，全量命令全绿

**明确未完成 / 待验证（不冒充完成）**

- [ ] 评分 MAE 与轨迹 jsonl：金标缺逐例人工打分，未实现（报告已说明「未计入」）
- [ ] RRF 融合接入计划 UI：融合纯函数已实现并单测，计划页只展示教程侧 citation
- [ ] `PLAN_VERSION` 升 2：有意保持 1（纯附加字段，旧快照零占位）
- [ ] 题目侧 FTS5 的端到端召回评估：当前只评估教程侧 BM25
- [ ] CI 的 `Question bank byte gate` 与 `Offline eval gate` 经远端验证：需下一次 push，本地均已实跑通过
- [ ] 在线质量评测轨道（`AI_LIVE=1` 打真实模型）：需真实 Key 与人工标注，本轮未跑

## 7. r53 收口批次核对

> §6 中「题目侧 FTS5 端到端召回评估」「CI 门禁经远端验证（题库字节部分）」两项已在本批次完成 / 部分完成；
> 按「任务夹建后不可变」约定保留 §6 原文，以本节为最新状态。

**已完成**

- [x] **简历口径纠偏**：`RESUME.md` 删除全部 `<...>` 占位符与「轨迹回放 / RRF 融合 / 自动降级 / MAE / 补 busy_timeout」等不实表述，改为 12 条实测事实 + 6 条可直接复制的 bullet + 7 个必答追问；`§2` 新增 4 条「不建议这样写」
- [x] **文档数字统一**：测试数 883 → 935（667 + 268）、CI 31 次 → 32 次，同步 README / AGENTS / PRD / ARCHITECTURE / RESUME / TECHNICAL；`TECHNICAL.md` 顶部加「以 §6–§7 为准」指引，`PRD §1.1` 标注为方案阶段基线
- [x] **并发写锁**：`PRAGMA busy_timeout = 3000` 双保险，8 线程 × 50 次并发写 100% 成功、0 次锁失败
- [x] **日志保留期**：`prune_ai_call_logs()` 90 天，随 `create_session()` 收口；脏参数夹紧、不误删今天
- [x] **LLM 可靠性治理**：`services/ai/reliability.py`（退避 / 熔断 / 输出修复 / 幂等键 / 影子对比），默认接入修复兜底与后台重试退避，12 条测试
- [x] **检索评估补完**：教程侧 `--check` 只读门禁、题目侧 20 组标注 + 独立零网络评估脚本，两路 recall@5 均 100%
- [x] **演示数据**：`seed_eval_demo.py` 合成 120 条 / 7 天 / 2 模型，幂等且默认不写开发库
- [x] **性能基准**：`benchmark.py` → `PERF-REPORT.md`，并发写 / 导入幂等 / FTS5 检索三组 p50/p95/p99
- [x] **CI 门禁**：backend 加 `Question retrieval eval` / `Reliability fault-injection`，frontend 加 `Retrieval eval`；YAML 解析通过，全部步骤在等价工作目录下本地退出 0
- [x] **全量验证**：后端 667 passed / 1 skipped、前端 268 passed；`ruff`（app/tests 与新增脚本）/ `typecheck` / `lint` / `build` / `question_merge --check` / 5 个评测门禁全绿；`eval_reliability.py` 报告两次生成 sha256 一致
- [x] **远端 CI**：`CI #33`（`1c33046`）成功、1m21s，4 个新门禁与题库字节门禁全部跑绿

**明确未完成 / 待验证（不冒充完成）**

- [ ] 在线质量评测**真实模型实跑**与评分 MAE：仍需用户同意消耗配额与逐例人工打分；轨迹 jsonl 与版本锁定脚手架已于 §8 落地（`docs/eval/traces/dry-run.jsonl`）
- [ ] RRF 融合接入计划 UI、`PLAN_VERSION` 升 2：有意不做（TECHNICAL §6 偏差表）
- [ ] 熔断自动短路、影子对比、幂等缓存接入主链路：可注入组件已实现并单测，默认只观测（§7.2）
- [ ] WAL：有意不启用，基准显示 `busy_timeout` 已消除写失败
- [ ] `benchmark.py` 进 CI：有意不进，跨机器分位不稳定会 flaky

## 8. r54 在线评测轨道核对

**已完成**

- [x] `services/eval/live.py` 纯函数层：版本锁定、轨迹白名单、混淆矩阵、Wilson 区间、双轨对比、双开关判定
- [x] `scripts/eval_live.py` CLI：默认 dry-run / `--check` 只读门禁 / `--live` 真跑 / `--limit`
- [x] 复用产品真实链路 `PROFILE_SYSTEM` + `ProfileDraft` + `AIClient.complete_model`，不另写客户端
- [x] 脱敏轨迹 `docs/eval/traces/dry-run.jsonl`（21 个白名单键）+ `LIVE-REPORT.md`（版本锁定 / 指标分母 / 双轨不可比较 / 解读限制）
- [x] 真跑双开关：`--live` + `AI_LIVE=1` + 运行时就绪；不满足退出码 2、零出网；真跑日志写临时库不污染开发库
- [x] CI 新增 `Live eval dry-run gate`（仅 dry-run，`--check` 只读）；在线真跑刻意不进 CI
- [x] 后端新增 10 条测试（版本锁定 / 脱敏 / 分母 / 双开关 / CLI 只读与拒绝出网），`ruff check app tests` 全过

**明确未完成 / 待用户确认（不冒充完成）**

- [ ] **真实模型实跑**：`AI_LIVE=1 python -X utf8 scripts/eval_live.py --live` 需用户明确同意消耗第三方 API 配额，本轮未执行
- [ ] 提示词 v1 → v2 的因果对比：需至少两个版本的真跑轨迹
- [ ] 评分 MAE：仍需逐例人工打分
- [ ] token 成本采集、多次采样 pass@k、`verify_quotes()` 纳入在线链路（逐条理由见 `TECHNICAL.md §8.3`）
- [ ] 远端 CI 验证 `Live eval dry-run gate`：需下一次 push 后确认

> 当前 `LIVE-REPORT.md` 标注为 **DRY-RUN**，延迟恒为 0；只能证明脚手架可复跑，不能写进简历当模型质量指标。
