# r20 验收报告：9 题卷追问额度用满 4 次

- 任务夹：`docs/teamflow/20261102-r20-followup-quota/`
- 验收对象（工作区未提交改动）：`backend/app/services/rules.py`、`backend/tests/test_interview_chat.py`、
  `backend/tests/test_engineering_gates.py`、本任务夹、`docs/teamflow/memory.md`。
- 验收口径：r8 `ACCEPTANCE.md` §59（D-5/P3）「若产品要求『计划题量 + 4 次追问』全用满，需另立需求改预算
  并同步更新额度断言」；用户本轮明确要求处理 9 题卷追问额度。r5 O-4 / r3 P3② / memory 第 45 行 / r6 390px 不在范围。

## 1 判据逐条核对

| # | 判据 | 实测结果 | 结论 |
|---|---|---|---|
| 1 | 9 题卷能用满 4 次追问 | `rules.max_turns(9) = max(12, 13) = 13`；`follow_ups_left(9, 1, 0) = 4` | 通过 |
| 2 | 8 题卷维持 12 轮 / 4 次追问 | `rules.max_turns(8) = 12`；`test_follow_up_gated_by_quota` 原断言（12 条 = 8 正题 + 4 追问）未改且通过 | 通过 |
| 3 | 长卷同步线性增长 | `rules.max_turns(13) = max(12, 17) = 17`；13 题梯子用例 17 条发言 | 通过 |
| 4 | 计划正题一题不落 | 三档梯子均断言计划题干集合是实际发言的子集，且发言数恰为 `计划题量 + 4` | 通过 |
| 5 | 追问额度不再被压缩 | 新口径下 `spare = MAX_FOLLOW_UPS - follow_up_count`（恒等于配额余量）；三档梯子均 `follow_ups == rules.MAX_FOLLOW_UPS` | 通过 |
| 6 | 轮次上限仍由计划题量派生、无第二份算术 | `grep MAX_INTERVIEW_TURNS backend/app` 只剩 `rules.py` 定义与注释；`interview.py` 仅调用 `rules.max_turns` / `follow_ups_left` / `is_follow_up_allowed` | 通过 |
| 7 | 挑战题仍不给追问 | `is_follow_up_allowed` 的 `challenge` 早退分支未动；9 题梯子（末位 challenge）仍正常结束 | 通过 |
| 8 | 契约零改动 | `backend/app/schemas.py` / `frontend/src/api/types.ts` 零改动；`turns_left` / `follow_ups_left` / `allow_follow_up` 不进 HTTP 契约 | 通过 |
| 9 | 前端零改动 | 前端无轮次 / 12 / 4 的硬编码，且不消费上述配额字段；未重复跑前端门禁（无文件变更） | 通过 |
| 10 | 门禁同步更严 | `test_turn_cap_derives_from_paper_size` 由 `<=` 改 `==`；门禁 48 由 `opener_follow_ups <= 4` 改 `== 4`（退回压缩额度即红） | 通过 |
| 11 | 存量 v1 长卷行为可解释 | 13 题 v1 卷 `turns_left` 0 → 4、允许追问，原卷未答条目投放顺序不变；见 `TECH-CHANGE.md` §3.4 | 通过（同向改进） |
| 12 | 定向用例全绿 | `python -m pytest tests/test_interview_chat.py tests/test_engineering_gates.py -q` → exit 0，100% 通过 | 通过 |
| 13 | 全量不回归 | `python -m pytest -q` → exit 0，仅 1 skipped（与 r18 基线同口径） | 通过 |
| 14 | 记忆收口准确 | `memory.md` 第 41 行 r8 ①（连同已关闭的 ②）整条标 `[x]` 并指向本报告 | 通过 |
| 15 | 任务夹自包含 | `meta.json` / `TECH-CHANGE.md` / `ACCEPTANCE.md` 齐备 | 通过 |

## 2 架构一致性

| 蓝图要求 | 实测 | 结论 |
|---|---|---|
| 配额 / 轮次口径单点 | 派生式只在 `rules.max_turns()`；`interview.py` 两处调用点（`_round_input`、`_next_question`）全部走派生值 | 符合 |
| 闭集与阈值分工 | 本轮不动 `MAX_FOLLOW_UPS` / `MIN_INTERVIEW_QUESTIONS` 等闭集常量，只改派生函数 | 符合 |
| 契约两侧同步 | 未触碰契约（无新字段） | 符合 |
| 任务夹不可变 | r8 验收报告零改动；D-5 的关闭证据落本夹 + `memory.md` | 符合 |
| 无第二份算术 | `grep MAX_INTERVIEW_TURNS backend/app` 仅定义与注释；无 `12 - asked` 类硬编码 | 符合 |

## 3 复跑命令与实测

```powershell
cd backend
python -m pytest tests/test_interview_chat.py tests/test_engineering_gates.py -q   # exit 0
python -m pytest -q                                                                # exit 0，1 skipped
```

- 前端：本轮零文件变更，未重复跑 typecheck / lint / vitest（沿用 r19 基线 136 passed）。
- `ruff`：本机不可用（与历史同口径，未记为通过）。

## 4 偏离与遗留（均不阻断）

| 编号 | 内容 | 处置 |
|---|---|---|
| 说明-1 | 存量 v1 长卷的 `turns_left` / `allow_follow_up` 数值变化 | 属同向改进且字段前端零消费；`TECH-CHANGE.md` §3.4 留痕 |
| P3-a | 9 题卷「用满 4 次追问」依赖模型每轮都建议追问，真实体验需端到端冒烟 | 并入 `memory.md` 第 38 行真实环境补测（多轮追问措辞抽查） |
| P3-b | `ruff` 本机不可用 | 与历史同口径；CI 或含 ruff 的环境补跑 |

## 5 验收判定

D-5 的两条要求全部落地：上限按「计划题量 + 追问上限」派生（9 题卷 13 轮、4 次追问用满），
8 题卷与 13 题卷各自维持/扩展到自洽轮次，原「追问不得挤占剩余正题」的守门语义保持不变；
额度断言由「≤」收紧为「==」，退回旧口径即红。契约、前端、`interview.py` 零改动。

验收结论：✅ 通过
