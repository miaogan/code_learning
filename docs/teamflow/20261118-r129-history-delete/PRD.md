# r129 历史记录删除能力补齐（PRD）

## 背景

用户提问「和历史记录相关的大部分功能都没有设计删除功能，是故意的还是漏了」。盘点结论：**大部分是漏了**。

- 故意做了删除的（3 处）：太傅对话 / 长期记忆（可审计、可反悔是设计目标）、雷达样例草稿 discard、自带 AI Key 清除。
- 漏了删除的（6 处）：镜试复盘卡、面试场次（召对）、考工答卷（exam runs）、错题本 / 练习记录、历史画像、简历版本。`history.py` 文档原句「无新建、无删除——历史是 runs/reports 的投影」是早期只读投影设计，删除能力后来一直没排进范围。
- 更底层的缺口：账号本身也没有删除入口（本轮不做，见「未决」）。

## 决策（用户选定）

全站统一补齐：单条删除 + 列表清空 + 统一二次确认交互。

## 删除口径（数据层）

| 对象 | 端点 | 级联范围 | 明确不删 |
|---|---|---|---|
| 镜试复盘卡 | `DELETE /api/mirror/cards/{id}`、`DELETE /api/mirror/cards` | 无（旁路数据） | — |
| 测评场次（面试/笔试） | `DELETE /api/history/{run_id}` | `runs` + 成长时间线事件（type∈interview/exam, ref_id=run_id）+ 该场次 `question_attempts` | reports（快照） |
| 错题本 | `DELETE /api/practice/wrong-book/{qid}`、`DELETE /api/practice/wrong-book` | 只写 `wrong_book_dismissals` 移出标记（新表） | **作答事件**（统计 / 熟练度口径不变） |
| 简历版本 | `DELETE /api/resumes/{resume_id}` | `documents` + 该版本 profiles + profile_jobs + 简历时间线事件（type=resume） | 历史成绩 runs（快照） |
| 历史画像 | （无独立列表 UI） | 随简历版本删除级联清 | — |

关键口径：

1. **删场次不留幽灵**：统计 / 错题本 / 时间线都由 runs + timeline_events + question_attempts 派生，只删 run 会留下幽灵错题 / 孤儿时间线，所以三表同事务级联。runs 表是共享承载，repository 层带 `kinds` 白名单防误删。
2. **错题本「移出」≠ 删除事实**：不动作答事件（练习统计、熟练度窗口口径不变）。`dismissed_at` 只掩盖**不早于它**的错——之后再答错是新事实，会重新进错题本（移出不是永久拉黑）。`wrong_total` 与错题本同一口径同步过滤，两边数字不打架。
3. **删简历 = 连画像一起清**：简历正文是最敏感的个人数据。若删的是当前最新画像的来源，latest 画像随之消失，全站自然回到「先上传简历」的门禁态（前端确认文案明说）。画像没有独立历史列表 UI，故不提供单独删除入口。
4. **账号隔离**：全部删除按 id + user_id 双条件（repository 层 `_uid()`），跨账号删除一律 404 且不落痕迹。

## 交互

统一两次点击式确认按钮 `ConfirmButton`（不用 `window.confirm`，不引入模态框）：第一次点击变「确认？」态，再点执行；失焦 / 4 秒自动退回。删除失败走各页面既有 InlineError 通道。

入口分布：镜试右栏（每条删除 + 头部清空）、召对 SessionList（每场删除）、战绩页 TrendTable（每行删除 + 「操作」列）、错题本（每题移出 + 头部清空）、校勘页（每版本删除 + 说明文案）。

## 验证

- 后端：`tests/test_r129_deletes.py` 9 例（镜像单删/清空/隔离、场次级联/白名单、错题本移出/再错重现/清空、简历级联/快照保留），全量 pytest 无 failed、ruff 全绿。
- 前端：typecheck / lint / build 全绿，vitest 全部通过（本机 EPERM 噪音与改动无关，以 CI 为准）。

## 未决（本轮不做）

- 账号级「注销 / 一键清空我的数据」。
- 测评场次暂不做「一键清空全部」（单条删除已覆盖；批量删误触代价高，等真实需求再议）。
