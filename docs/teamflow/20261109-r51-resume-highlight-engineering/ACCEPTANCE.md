# ACCEPTANCE · r51 验收清单与证据路径

> 状态：**M1 已交付；M2 / M3 方案已定，未实施**。未完成项一律不勾选，避免把「计划」写成「已完成」。

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
- [x] **CI 在 GitHub 上实跑为绿**：Actions 共 31 次运行，最近 `CI #31`（`a54e4be`，`feat/dev-skill-coach`）成功、1m6s；#21–#26 曾红灯后修复，#27–#31 连续通过。本机 `gh` 未认证，但网页公开可读；`ARCHITECTURE.md §7.1 / §7.2` 已据此更正。
- [ ] **新增门禁经远端验证**：`Question bank byte gate` 尚未推送，下一次 push 后需在 Actions 页面确认该步骤为绿（本地 `--check` 已退出 0）。

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
