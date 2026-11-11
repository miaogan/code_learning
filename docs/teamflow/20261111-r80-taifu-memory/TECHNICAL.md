# r80 · 技术方案：线程记忆（滚动摘要）

> 依据 PRD `docs/teamflow/20261111-r80-taifu-memory/PRD.md`。纯增量：无新端点、无新依赖、**无额外模型调用**。

## 1. 为什么「顺带回写」是这里的最优解

太傅的每次回答本来就是一次 JSON 输出：

```json
{"reply": "...", "citations": ["/report"]}
```

r80 只加一个字段：

```json
{"reply": "...", "citations": ["/report"], "memory": "目标是 AI 应用工程师；已建议先补部署与推理，再补缓存一致性。"}
```

- **零额外调用**：不需要第二次往返，也不会有「摘要调用失败但回答成功」这种半成品状态；
- **零额外延迟**：多写 240 字相对于一段 1200 字的回答可以忽略；
- **失败退化到现状**：模型不回 `memory`（或回了被净化掉）时，库里记忆不变，提示词与 r79 完全一致。

对比「单独调一次摘要模型」：那会把前台交互从 1 次往返变成 2 次，且要处理「摘要成功、回答失败」的回滚。

## 2. 什么时候才压缩

窗口是 `HISTORY_LIMIT = 6` 条（3 轮）。判断「有没有被挤掉」不能看取回来的条数（取 6 条永远得 6 条），所以多取一条：

```python
recent = repository.list_taifu_messages(limit=policy.HISTORY_LIMIT + 1)
overflow = len(recent) > policy.HISTORY_LIMIT
history = recent[-policy.HISTORY_LIMIT:]
```

- 6 条消息（3 轮）时 `overflow = False`：窗口装得下全部，没有东西需要压缩，提示词里让模型 `memory` 给空串；
- 8 条消息（4 轮）起 `overflow = True`：第 1 轮已被挤出窗口，这才开始压缩。

这个判断同时决定「要不要存」：短线程即使模型主动写了记忆也不落库 ——
否则提示词里会出现一条其实什么也没压缩的「记忆」，白占篇幅还容易让模型误以为有前情。

## 3. 存储：为什么单独一张表

```sql
CREATE TABLE IF NOT EXISTS taifu_threads (
    user_id     TEXT PRIMARY KEY,
    memory      TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL
);
```

不把记忆塞进 `taifu_messages` 有两种考虑：

1. **语义**：记忆是**线程级**的，不是某一条消息的属性；混进消息表会让 `GET /thread` 把它当对话渲染出来，
   而用户看到的「对话」里不该出现太傅的记事本；
2. **生命周期**：消息表按 `TAIFU_MESSAGE_LIMIT = 200` 裁剪，记忆若挂在某条消息上会随裁剪一起被删。

单行 upsert，读写各一个 repository 函数（SQL 只在这一层，符合工程门禁）：

```python
def save_taifu_memory(memory: str) -> None:
    conn.execute(
        "INSERT INTO taifu_threads (user_id, memory, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET memory = excluded.memory, "
        "updated_at = excluded.updated_at",
        (_uid(), memory, _now()),
    )
```

DDL 在 `db.py` 的 `R80_SCHEMA`，`init_db()` 第 19 步执行 —— 与 r77 一样用 `CREATE TABLE IF NOT EXISTS`，
**存量库升级不需要迁移脚本**（已验证：旧 `app.db` 重启后自动多出 `taifu_threads`）。

## 4. 净化：空值不能覆盖真记忆

```python
MEMORY_MAX = 240
MEMORY_MIN = 4

def sanitize_memory(raw: Any) -> str:
    flat = flatten(raw)
    if len(flat) < MEMORY_MIN:
        return ""
    if len(flat) <= MEMORY_MAX:
        return flat
    return flat[:MEMORY_MAX].rstrip() + "…"
```

三条口径：

- **必须单行**：记忆是提示词里的一个 `【段】`，多行会把后面的段头挤散；
- **短于 4 字视为没给**：模型常用「无」「（无）」「N/A」占位，这些不能拿去覆盖上一轮的真摘要。
  阈值刻意压到 4（初版写 8，把「第一句 第二句」这种 7 字合法摘要也丢掉了 —— 验收时改回）；
- **返回空串 = 本轮不更新**：调用方只在非空时才 `save_taifu_memory`，所以是「不覆盖」而不是「清空」。

## 5. 提示词结构（r79 → r80）

```
【档案】
[1] 最近诊断（href: /report）
- 薄弱：AI 工程 · 部署与推理 · 错误率 60%（3/5）→ /report#weakness-1
【早期对话摘要】目标是 AI 应用工程师；已建议先补部署与推理。
【当前页面】医案（诊断报告）（/report）—— 短板、薄弱分组…
【最近对话】
用户：…
太傅：…
【问题】那缓存呢

另外：把【早期对话摘要】与【最近对话】里这一轮的内容合并，用 memory 字段输出更新后的摘要…
```

无记忆时摘要段写固定占位 `MEMORY_NONE`（「无：这是本次线程的开头，或对话还短到不需要压缩」），
而不是留一个空的段头 —— 空段头会让模型以为「有摘要但没读到」。

`build_user_prompt(..., memory="", compact=False)` 两个新参数都是 keyword-only，r77–r79 的调用与测试零改动。

## 6. 记忆不是依据（与 r78 页面上下文同一条边界）

系统提示词新增第 6 条：

> 【早期对话摘要】是你自己在前几轮写下的记忆：只用来理解「上次说的那个」，**不是依据**，
> 也不能从里面挑引用。有冲突时以【档案】为准。

程序层同样不认：`sanitize_reply` 的白名单仍然只由档案段（含 r79 锚点）构成，记忆没有参与构建。
模型若从记忆里挑一个 href（例如上一轮引用过 `/history`，这一轮档案里没有历史段）→ 走既有丢弃计数。

## 7. 写入时序

```python
payload = policy.sanitize_reply(draft, sections)
payload["memory_used"] = bool(memory)
if not payload["reply"]:
    return TaifuReply(**payload)          # 空回答：消息与记忆都不写
repository.insert_taifu_message(...)      # user
repository.insert_taifu_message(...)      # assistant
if overflow:
    next_memory = policy.sanitize_memory(draft.memory)
    if next_memory:
        repository.save_taifu_memory(next_memory)
```

沿用 r77「先成功再写」：没有任何一条路径会在回答失败时留下记忆或半条对话。

`TaifuReply.memory_used` 只作可观测标记（这一轮提示词是否带了记忆），前端不消费、界面不展示。

## 8. 清空

`repository.delete_taifu_messages()` 顺带 `DELETE FROM taifu_threads`：

用户看到的「清空对话」意味着「从零开始」，模型看到的也必须是零。只清消息会让清空后第一问仍带着上一段的摘要，
这是那种「界面说干净了、实际没干净」的假象（r78 修过同类的孤儿消息问题）。

## 9. 测试（`tests/test_r77_taifu.py`，同一能力面 +7 条）

| 用例 | 锁什么 |
| --- | --- |
| `test_sanitize_memory_flattens_caps_and_rejects_placeholders` | 单行压平、截断到 240+`…`、四个占位词一律空 |
| `test_prompt_carries_memory_and_only_asks_for_it_when_overflowing` | 有/无记忆两态的段落形状；`compact` 决定是否要求回写 |
| `test_memory_is_never_a_citation_source` | 只在记忆里出现的 href 被丢弃并计数 |
| `test_short_thread_does_not_store_memory` | 短线程即使模型给了也不落库 |
| `test_overflowing_thread_stores_and_feeds_back_memory` | 8 条消息起开始压缩；下一轮 `memory_used = True` 且提示词含摘要 |
| `test_empty_answer_neither_stores_memory_nor_messages` | 空回答不写消息、不写记忆 |
| `test_clearing_thread_also_clears_memory` | 清空对话同时清记忆 |

## 10. 已知限制

- 滚动重写不可逆：某一轮摘要写得潦草，被它覆盖的旧要点就没了（没有版本、没有回滚）。
- 单段记忆不区分话题，跨话题对话会混在一起。
- 摘要内容无法程序级校验「是否忠于原文」—— 只能靠系统提示词要求「以档案为准」，以及引用白名单挡住「拿记忆当出处」。
