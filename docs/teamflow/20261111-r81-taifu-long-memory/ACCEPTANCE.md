# r81 · 验收报告：长期记忆

> 结论：PRD 中 8 条验收标准全部满足。纯增量：1 张新表（`taifu_memories`）+ 3 个端点 +
> 模型输出 1 个字段；无新依赖、无额外模型调用。r80 的 `memory` 字段更名为 `summary`。
> r75–r81 七轮仍未提交。

## 1. 交付内容

| 文件 | 改动 |
| --- | --- |
| `backend/app/core/db.py` | `R81_SCHEMA`（`taifu_memories`）+ `R81_INDEXES`，`init_db()` 第 20/21 步 |
| `backend/app/core/repository.py` | `TAIFU_MEMORY_LIMIT=20`；`list_taifu_memories` / `insert_taifu_memory`（写入后裁剪）/ `delete_taifu_memory`（id+user 双条件）/ `delete_taifu_memories`；`get/save_taifu_memory` → `get/save_taifu_summary` |
| `backend/app/services/taifu/policy.py` | `SUMMARY_*` 更名；`MEMORY_ITEM_MAX=80` / `MEMORY_ITEM_MIN=6` / `MEMORY_ITEMS_PER_TURN=2`；`sanitize_memories()` / `_memory_key()` / `render_memories()`；提示词加 `【长期记忆】` 段与 `MEMORY_TASK`；系统提示词第 7 条 |
| `backend/app/services/taifu/taifu.py` | 读记忆 + 渲染进提示词；回答成功后落库新候选；`summary_used` / `memories_used` / `memories_added` |
| `backend/app/schemas.py` | `TaifuReply` 三个可观测字段；`TaifuMemoryItem` / `TaifuMemories` / `TaifuMemoryResult` |
| `backend/app/routers/taifu.py` | `GET /api/taifu/memories`、`DELETE /api/taifu/memories/{id}`、`DELETE /api/taifu/memories` |
| `backend/tests/test_r77_taifu.py` | +12 条（文件内 40 条），r80 用例同步更名 |
| `frontend/src/api/types.ts` / `client.ts` | `TaifuMemoryItem` / `TaifuMemories` / `TaifuMemoryResult` + 三个方法 |
| `frontend/src/components/taifu/TaifuLauncher.tsx` | 记忆入口（展开才读）、单条忘掉、全部忘掉两步确认、`memories_added` 当场告知 |
| `frontend/src/styles/base.css` | r81 段：`.sc-taifu-memo` / `.sc-taifu-memolist` / `.sc-taifu-memotext` |
| `logs/teamflow/r77-taifu-chat/scripts/check.cjs` | +4 组断言（共 14 组）+ 三个记忆 mock |

## 2. 验收标准

| AC | 结果 | 证据 |
| --- | --- | --- |
| AC-1 只记稳定事实 | 通过 | `MEMORY_TASK` 明确「跨对话仍成立 + 档案与记忆里都没有」；「这一轮问了什么、你的建议都不算」 |
| AC-2 与线程长度无关 | 通过 | 0 条历史的第一轮就落库（`chat_stores_long_term_memory_even_on_a_short_thread`），与摘要的「溢出才更新」门槛不同 |
| AC-3 不记重 | 通过 | 与已有/同批互相包含均丢弃；`duplicate_memory_is_not_stored_twice` 断言同一句第二次说 `memories_added == 0` |
| AC-4 有上限 | 通过 | 写 23 条后列表恰 20 条、首条为「第 3 条记忆」（最旧 3 条被淘汰）；每轮 `MEMORY_ITEMS_PER_TURN = 2` |
| AC-5 记忆不是依据 | 通过 | `memories_are_never_a_citation_source`：只在记忆里出现的 `/history` → `citations == []`、`dropped_citations == 1` |
| AC-6 可审计、可删除 | 通过 | `GET` 列出；单条删 1、重复删 0（幂等）；全部删后 `items == []`；浏览器实测三种操作 |
| AC-7 两种清空语义不同 | 通过 | `forget_all_memories_keeps_thread`（忘记忆留对话）；`delete_taifu_messages` 只清 `taifu_threads` 不碰 `taifu_memories` |
| AC-8 不回归 | 通过 | 后端 816 passed / 1 skipped（817，0 失败）；前端 36 文件 464 测试、typecheck / lint 0 warning、build 通过；浏览器 14 组断言全 PASS |

## 3. 验证命令与结果

```text
backend: ruff check app tests              → All checks passed
backend: pytest tests/test_r77_taifu.py -q  → 40 passed，exit 0
backend: pytest -q                          → 816 passed / 1 skipped（817 条，0 失败）
frontend: typecheck / lint                  → 通过，0 warning
frontend: npm test                          → 36 test files / 464 tests passed
frontend: npm run build                     → 通过（580.45 kB / gzip 236.61 kB）
```

真实 Chromium（`node logs/teamflow/r77-taifu-chat/scripts/check.cjs`）：

```text
PASS 首次打开是空态：3 条示例、输入可用、空问句不可发送
PASS 点示例填入问句，发送按钮随问句解禁
PASS 空档案：收回问句、给中文说明与三个可点出口
PASS 一轮问答：分段渲染、引用可点、读取与丢弃计数可见
PASS 点引用跳转站内页面，浮窗随路由变化收起
PASS 刷新后读回历史对话（服务端线程）
PASS 清空为两步确认，确认后回到空态
PASS 390px 底部面板内完成一轮问答且无横向滚动
PASS 非首页同样带上当前页面（/report），引用带具体锚点
PASS 点引用直达第 9 条：自动展开、滚动到视口、该行高亮
PASS 展开记忆才读，列出已记住的事实
PASS 新回答记住 1 条事实：当场告知并刷新记忆列表
PASS 单条「忘掉」只删这一条
PASS 全部忘掉为两步确认，确认后回到空记忆
RESULT: PASS
```

## 4. 验收中发现并修复的问题

1. **`memory` 与 `memories` 只差一个字母**。r80 的 `memory: str` 与 r81 要加的 `memories: list`
   放在同一个 JSON 里，模型把数组塞进 `memory` 会让 pydantic 校验失败 → 整次回答失败
   （用户看到报错而不是回答）。先把 r80 字段更名为 `summary`（数据库列名保留 `memory`，
   列名不参与模型交互，不为它做迁移）。
2. **记忆列表嵌套滚动把内容藏了**。初版给 `.sc-taifu-memolist` 加 `max-height: 104px` + 内部滚动，
   实测截图里第 3 条被自己的滚动条切掉、「全部忘掉」按钮被挤出面板可视区。
   改为：去掉内滚动（面板主体已经会滚，两个滚动条比一个难用），并把 `memoriesOpen` /
   `memories.length` 加进「滚到底」effect 的依赖，展开时自动把列表带到视野里。
3. **CDP 断言写死了消息绝对条数**。新加的「记住一条」场景用 `msg.length === 2` 等回答，
   但进入该节时线程里已有上一段测试留下的 2 条消息，等值永远不成立（看起来像功能没生效）。
   改为先读基线再断言 `before + 2`。
4. **`MEMORY_ITEM_MIN` 初值偏严**（继承 r80 的教训）：中文一句七八个字就够，阈值定高会把合法短句
   当占位丢掉且失败无声，定在 6。

## 5. 与前几轮的关系

- **r80 → r81 分层**：摘要管「这次聊了什么」（随对话清空），长期记忆管「你是谁」（跨对话留存）。
  两者都进提示词、都不是依据、都不进白名单。
- **r78 的同一条边界第三次出现**：页面上下文（前端给）、线程摘要（模型给）、长期记忆（模型给）
  —— 三者都只能用来「理解」，只有服务端重读的档案才是依据。这条边界现在写在系统提示词第 5/6/7 条，
  并且在 `sanitize_reply` 里由代码兜底（白名单只由档案段构建）。
- **r81 是唯一一个用户可写的面**：忘掉记忆是用户对太傅数据唯一的主动写操作（除了清空对话）。

## 6. 已知限制

- 记忆质量靠模型自觉：漏记、记错程序都发现不了，只能靠用户看列表时自己删。
- 去重是字面包含，不做语义：「我只有周末有空」与「工作日完全没时间」会存成两条。
- 20 条按时间淘汰而非重要性：早期的重要约束可能被后来的琐事挤掉。
- 不可编辑，只能忘掉重记；也没有「这条记忆是从哪一轮提炼的」这类溯源。
