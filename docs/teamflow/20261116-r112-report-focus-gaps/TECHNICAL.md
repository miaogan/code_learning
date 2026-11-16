# r112 技术方案

## 改动点

`frontend/src/components/interview/chatModel.ts` → `settingsLine()`

```ts
const gaps = (settings.focus_gaps ?? [])
  .filter((gap): gap is string => typeof gap === 'string' && gap.trim().length > 0)
  .slice(0, 3)
if (gaps.length > 0) parts.push(`缺口：${gaps.join(' / ')}`)
```

- `focus_gaps` 在 `InterviewSettings` 里是可选字段（`focus_gaps?: string[]`），旧 run 反序列化后为 `undefined`，`?? []` 兜住。
- 展示侧再截前 3 项：写入侧 `_focus_gaps_of` 已限制 3 项，这里只防御手工 payload / 旧数据。
- 位置在「方向 · 二级方向」之后：先回答「按什么岗位 / 什么方向」，再回答「本场重点追问什么」。

## 为什么不需要后端改动

| 数据 | 来源 |
|---|---|
| `Report.interview_settings` | `diagnosis.interview_settings_of()` → `history._interviews_settings_of()` → `rules.settings_or_none()` → `InterviewSettings.model_validate(raw)` |
| `RunSummary.interview_settings`（历史行） | 同上投影 |

`InterviewSettings` 在 r111 已含 `focus_gaps`（默认 `[]`），因此 r111 之后写入的 run 天然带出；r111 之前的 payload 缺键 → 默认空列表 → 文案不变。三处「本场设定」本来就是同一解析器 + 同一格式化函数，无需新增分支。

## 测试

`frontend/src/test/interviewChat.test.ts` 新增一例覆盖四态：

- 有缺口 → `… · 缺口：Redis / RAG`
- 空数组 → 与四项文案一致
- 全空白项 → 不产生 `缺口：`
- 超过 3 项 → 只显示前 3 项

## 风险

- 无接口变化、无迁移、无缓存影响：纯展示层格式化，回滚即恢复。

## 验证

- typecheck / lint 通过；`interviewChat.test.ts` 24 passed（新增 1 例）。
- 全量前端测试与构建见 ACCEPTANCE.md。
