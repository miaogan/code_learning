# r138：连续学习口径修正与实时刷新

- 日期：2026-11-19
- 发起：用户问「那个连续学习的逻辑是不是有问题」。
- 结论：**确实有问题**，三处：
  1. 徽章叫「连续学习」，数据源却只有 `/api/history`（已完成的面试/笔试），演武练习、学堂阅读都不算；
  2. `StreakBadge` 挂在 App 壳上，`useAsync(..., [])` 只拉一次，完成测评后不刷新；
  3. 只取最近 200 条历史，活跃日覆盖有上限，且删历史会让已过去的连续天数回退。

## 1. 新口径

「一天有效学习」= 当天至少发生一次：

| 来源 | 数据表 / 字段 | 为什么算 |
|---|---|---|
| 测评完成 | `runs`：completed 且 `kind ∈ {interview, exam}` | 原口径保留 |
| 演武作答 | `question_attempts`：`source='practice'` | 用户明确选的「测评+演武+学堂」 |
| 学堂阅读 | `learn_chapters.updated_at > 0` | 小节真的滚进视口才更新，符合「读过」定义 |

不做：镜试/讲席/雷达/简历上传等 AI 辅助行为——它们是工具调用，不代表稳定学习投入。

## 2. 服务端

- 新增 `GET /api/activity/days?tz_offset=-480&limit=400`（`app/routers/activity.py`）：
  - `tz_offset` 取浏览器 `getTimezoneOffset()`，UTC+8 = `-480`；**符号与 Python `timezone` 相反**，service 内取负，避免把东八算成西八（专项用例钉住）。
  - `repository.activity_timestamps()` 按当前账号只读三类原始时间；ISO 串和毫秒 epoch 分开回传，不在 SQL 层做跨库日期函数。
  - `services/activity.py` 按当前偏移折算 `YYYY-MM-DD`、去重、新→旧排序；脏时间静默忽略；`total` 是截断前总天数。
  - 默认 400 天、上限 1000；比旧的 200 条上限宽。
- 契约 `ActivityDays { days, total, tz_offset }`；路由带 `current_user` 鉴权，零 AI、零出网（不触 r115 出网登记制）。

## 3. 前端

- `StreakBadge` 改接 `/api/activity/days`，`computeStreakFromDays()` 直接吃服务端日键；`computeStreak(rows)` 保留为兼容包装。
- 新增 `lib/activityEvents.ts` 自定义事件 `skillcoach:activity-changed`；写侧成功后发事件：
  - 面试结束 `finishInterview`
  - 笔试提交 `submitExam`
  - 演武单题作答 `practiceAnswer`
  - 学堂进度上云 `saveLearnProgress`
  - 历史删除（战绩页 / 面试会话列表）
- 徽章同时监听窗口 `focus` 与路由 `pathname` 变化：跨天回来、切页都刷新，不必整页刷新。
- 失败/全 0 仍静默隐藏，保持 r84「锦上添花不报错」的口径。

## 4. 验证

- 后端：专项 `test_r138_activity_days.py` 4 例（三类合并去重、时区符号、账号隔离/未完成/脏值、limit 截断）；ruff 全绿；全量 pytest 通过。
- 前端：streak 12 例、activityEvents 3 例；全量 vitest 48 files / 584 tests passed（本机 EPERM 临时目录噪音，非断言失败）；typecheck / lint / build 全绿；工程门禁 41/41。
- Playwright mock：初始徽章「连续 2 天 · 本周 2/7」，首请求带 `tz_offset=-480&limit=400`；触发事件后变为「连续 3 天 · 本周 3/7」，请求数 +1。

## 5. 已知边界

- 用**当前**时区偏移折算，不还原历史 DST；徽章只看最近 400 天，影响可忽略。
- 删除历史记录仍会让对应活跃日消失——这是「删除即抹掉痕迹」的一致口径，不是回归 bug。
- 学堂进度同步是防抖上报，写完到事件触发之间有秒级延迟，正常。
