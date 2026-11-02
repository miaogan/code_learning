# r20 · 9 题卷追问额度用满 4 次（技术变更单）

> 关闭 r8 验收 P3 D-5（`memory.md` 第 41 行 ①）：只改 `rules.max_turns()` 的派生口径，并同步两处
> 额度断言。后端业务代码仅 `rules.py` 一处算式；`interview.py`、契约两侧、前端、seed **零改动**。

## 1 背景与范围

来源（历史任务夹不可改，原文只读）：

- r8 `ACCEPTANCE.md` §59：「9 题卷的追问上限被压到 3 次（12 轮预算里 9 道正题占 9 轮），8 题卷仍 4 次。
  这是『追问不得挤占剩余正题』的必然结果，非缺陷；若产品要求『计划题量 + 4 次追问』全用满，
  需另立需求改预算并同步更新额度断言。」
- 用户本轮指令：「先处理 r8 九题卷追问额度」——即采纳后半句的产品口径，直接在本轮落地，不再挂待办。

现状（r8 D-4 之后）：

- `MAX_FOLLOW_UPS = 4`，`MAX_INTERVIEW_TURNS = MIN_INTERVIEW_QUESTIONS + MAX_FOLLOW_UPS = 12`；
- `max_turns(planned_total) = max(MAX_INTERVIEW_TURNS, planned_total)` → 9 题卷 = 12；
- `follow_ups_left = min(4 - follow_up_count, max_turns - asked - remaining_plan)` → 9 题卷开局 `spare = 12 - 1 - 8 = 3`，
  追问只能 3 次。

本轮**不含**：r5 O-4 流程留痕、r3 P3② DESIGN 回写、memory 第 45 行 QA round-2 三条、r6 390px 真机走查。

## 2 改动面

| 文件 | 改动 | 行为影响 |
| --- | --- | --- |
| `backend/app/services/rules.py` | `max_turns()` 派生口径改为 `max(MAX_INTERVIEW_TURNS, planned_total + MAX_FOLLOW_UPS)`；同步 `MAX_INTERVIEW_TURNS` 注释与 `max_turns` / `follow_ups_left` docstring | 9 题卷 12 → 13 轮，追问 3 → 4 次；8 题卷仍 12 轮；13 题卷 13 → 17 轮 |
| `backend/tests/test_interview_chat.py` | `test_turn_cap_derives_from_paper_size` 改为正面断言「发言数恰为计划题量 + 4、追问用满」；docstring 同步 | 8 / 9 / 13 三档梯子全部钉住 |
| `backend/tests/test_engineering_gates.py` | 门禁 48 增加 `opener_follow_ups == MAX_FOLLOW_UPS`（原为 `<=`） | 9 题卷开局额度掉到 3 时即红 |
| `docs/teamflow/20261102-r20-followup-quota/**` | 新增本任务夹 | — |
| `docs/teamflow/memory.md` | 第 41 行 r8 ① 标关闭 | — |

`interview.py` 仅消费 `rules.*`（`_round_input` 的 `quota` 与 `_next_question` 的守门），**零改动**；
`backend/app/schemas.py` / `frontend/src/api/types.ts` 零改动（`turns_left` / `follow_ups_left` / `allow_follow_up`
从不进 HTTP 契约，前端也零消费，见 `grep frontend/src` 无结果）。

## 3 方案

### 3.1 派生口径：计划题量 + 完整追问预算

```python
def max_turns(planned_total: int) -> int:
    return max(MAX_INTERVIEW_TURNS, planned_total + MAX_FOLLOW_UPS)
```

- 8 题卷：`max(12, 12) = 12`（与 r8 前完全一致）；
- 9 题卷：`max(12, 13) = 13`（新增的 1 轮正好容纳第 4 次追问）；
- 13 题卷：`max(12, 17) = 17`（题量越长，上限随计划题量线性增长）。

保留 `max(..., MAX_INTERVIEW_TURNS)` 下限而不是直接写 `planned_total + MAX_FOLLOW_UPS`：低于 8 题的脏计划
（结构闸门本会 502 拦掉）也不至于得到比标准卷更小的上限，语义上「标准卷预算」始终是最低承诺。

### 3.2 `follow_ups_left()` 不再压缩额度

新口径下 `spare = (planned_total + 4) - asked - remaining_plan`，而 `asked - asked_plan = follow_up_count`、
`asked_plan + remaining_plan = planned_total`（计划未超量时），代入即：

```
spare = planned_total + 4 - asked - (planned_total - asked_plan)
      = 4 - (asked - asked_plan)
      = MAX_FOLLOW_UPS - follow_up_count
```

因此返回值恒等于「配额余量」，`min()` 的第二项不会再截断它。公式本身**不动**：`min(配额余量, 机动轮次)`
仍是唯一守门点，既保证追问不挤占剩余正题，也保证挑战题（另由 `is_follow_up_allowed` 一律拒绝）不越界。

### 3.3 不给「9 题卷」写特例

备选方案是 `max(12, 9 + 4 if planned_total == 9 else planned_total)` 之类的题量分支——**否决**：
`rules.py` 是面试 / 笔试 / 报告共用的唯一出处，按具体题量开洞会让第 10、11 题卷再次回到压缩额度；
「计划题量 + 追问上限」是唯一对任意题量都自洽的派生式。

### 3.4 存量 v1 长卷的可见变化（可接受）

v1 payload 预载整卷、没有 `plan`，`_planned_total()` 取 `len(entries) - follow_up_count`（原卷计划题量）。
13 题 v1 卷此前 `turns_left = 13 - 13 = 0`、`allow_follow_up = False`；新口径下变为 `17 - 13 = 4` 与允许追问，
且追问只追加到 `questions` 末尾，**原卷未答条目的投放顺序不受影响**（`_next_question` ③ 分支按原顺序取未答条目）。
该字段前端零消费，语义从「预算已被预载占满、0 机动」修正为「还剩 4 次追问额度」，属同向改进。

## 4 测试同步

| 用例 | 原断言 | 新断言 |
| --- | --- | --- |
| `test_turn_cap_derives_from_paper_size`（8 / 9 / 13 三档梯子） | `len(turns) <= max_turns`、`follow_ups <= MAX_FOLLOW_UPS` | `len(turns) == plan_total + MAX_FOLLOW_UPS`、`follow_ups == MAX_FOLLOW_UPS`（保持 `<= max_turns` 作上界复核） |
| 门禁 48 `test_interview_prompt_paper_feasible` | `opener_follow_ups <= MAX_FOLLOW_UPS` | `opener_follow_ups == MAX_FOLLOW_UPS` |
| `test_follow_up_gated_by_quota`（8 题卷） | 12 条 = 8 正题 + 4 追问 | **不变**（新口径下 8 题卷仍是 12 轮） |

## 5 验证计划

- 定向：`python -m pytest tests/test_interview_chat.py tests/test_engineering_gates.py -q`（63 passed）。
- 全量：`python -m pytest -q`（结果见 `ACCEPTANCE.md` §3）。
- 前端零改动，不重复跑 typecheck / lint / vitest；`ruff` 本机不可用（与历史同口径）。

## 6 风险与回滚

- 风险低：只改一条纯函数派生式，无状态机、无契约、无落库、无网络行为变化。
- 唯一可见变化是 9 题卷在「模型每轮都建议追问」时可多问 1 轮（13 轮），是否真用满仍由模型的
  `allow_follow_up` 决策与守门共同决定。
- 回滚：`rules.py` 单函数改回 `max(MAX_INTERVIEW_TURNS, planned_total)` 并还原两处断言即可，无数据副作用。
