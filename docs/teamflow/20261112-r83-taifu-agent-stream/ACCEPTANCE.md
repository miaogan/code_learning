# r83 · 验收报告：太傅 agent 化（LangGraph 编排 + AI SDK 协议流式）

> 结论：PRD 中 8 条验收标准全部满足。太傅从「一次 RPC 补全」改为**图编排 + token 级流式 + 工具取料 +
> 工具调用可视化**；`/chat` 的入参出参字段零变化，唯一语义变化是**引用改由服务端取料生成**（模型不再有
> 通道编引用）。新增后端 2 个模块 + 1 个纯编码器、前端 1 个纯函数层与 2 个依赖；无新表、无新外部服务。

## 1. 交付内容

| 文件 | 改动 |
| --- | --- |
| `backend/app/services/ai/ai.py` | 新增 `stream_chat()`：SSE 逐帧解析、分片 `tool_calls` 按 `index` 累积、非 SSE 回退整包、错误映射与 `_request` 逐条对齐、**不重试**；辅助 `_is_event_stream` / `_iter_sse_json` / `_absorb_tool_delta` / `_raise_for_status` / `_message_of` |
| `backend/app/services/taifu/tools.py` | 新建：5 个工具（4 只读 + `remember`），统一 `ToolResult`（`ok/label/summary/href/content`）；`ToolContext` 懒加载简历正文并累计记忆；只读三个工具复用 r82 `deep_read.build_detail()` |
| `backend/app/services/taifu/graph.py` | 新建：`START → prepare → agent ⇄ tools → finalize → END`；`MAX_TOOL_ROUNDS=3` / `CITATION_LIMIT=5` / `TAIFU_TIMEOUT_S=120` / `SUMMARY_TIMEOUT_S=45`；两个出口 `run_events()` / `run_collect()` |
| `backend/app/services/taifu/ai_sdk.py` | 新建：纯函数编码器（内部事件 → AI SDK UI Message Stream v1 帧），`STREAM_HEADER` / `DONE_FRAME` / `headers()` |
| `backend/app/services/taifu/policy.py` | 新增 `TAIFU_AGENT_SYSTEM`（9 条规则 + 工具说明 + 「不要写链接」）、`AGENT_PROMPT_TEMPLATE`、`render_focus()`、`build_agent_prompt()`、`TaifuSummary` / `SUMMARY_SYSTEM` / `build_summary_prompt()`；旧的 `TAIFU_SYSTEM` / `build_user_prompt` / `sanitize_reply` **保留**（r65/r77 单测仍引用） |
| `backend/app/services/taifu/taifu.py` | 精简为只剩 `empty_reply()` / `missing_question_reply()`（编排搬到 graph） |
| `backend/app/routers/taifu.py` | 新增 `POST /api/taifu/chat/stream`（`_stream` / `_notice_stream` / `_has_any_record`）；`POST /api/taifu/chat` 改走 `graph.run_collect` |
| `backend/app/core/repository.py` | 新增 `list_reports(limit: int = 2)`（按 `created_at DESC`），供 `compare_reports` |
| `backend/requirements.txt` | 追加 `langgraph>=1.2` |
| `backend/tests/test_r83_taifu_agent.py` | 新建 17 条（编码器 4 / `stream_chat` 2 / 工具 4 / 图 4 / 端点 3） |
| `backend/tests/conftest.py` | `patch_ai` 增加 `fake_stream_chat`（首轮若给 `tool_calls` 则只发工具调用、不发正文） |
| `frontend/src/lib/taifuStream.ts` | 新建：`partsToView` / `textOf` / `noticeOf` / `cappedOf` / `argsLine`（组件零判断） |
| `frontend/src/components/taifu/TaifuLauncher.tsx` | 改用 `useChat` + `DefaultChatTransport`；`MessageRow` 渲染 text / tool / cites / meta；`loadThread` 转 `UIMessage[]`；发送同步化 + `sendSnapshotRef` 回滚；滚动依赖从 `messages.length` 改 `messages` |
| `frontend/src/api/client.ts` | 导出 `API_BASE` |
| `frontend/src/styles/base.css` | 追加 `.sc-tool` 系列（`is-running` / `is-miss` / `sc-tool-pulse`，含 `prefers-reduced-motion` 兜底） |
| `frontend/package.json` | 新增 `ai@^7.0.170`、`@ai-sdk/react@^4.0.174` |
| `logs/teamflow/20261112-r83-taifu-agent-stream/scripts/check.cjs` | 新建：CDP 浏览器断言（流式帧 mock / 工具卡 / `is-miss` / 引用 / 元信息） |
| `logs/teamflow/20261112-r83-taifu-agent-stream/scripts/e2e_stream.py` | 新建：假 LLM（每 80ms 一 chunk）+ 真后端，量首帧与 delta 间隔 |

## 2. 验收标准

| AC | 结果 | 证据 |
| --- | --- | --- |
| AC-1 真流式（token 级、无攒批） | 通过 | 假 LLM 每 80ms 吐一 chunk → 首帧（正文）**0.20s**、总 **1.00s**，10 个 delta 间隔 **0.082–0.095s**，与上游节奏一比一，无攒批（`e2e_stream.py`） |
| AC-2 协议合法 | 通过 | 帧序列 `start → data-meta → text-start → text-delta×10 → data-citations → data-done → text-end → finish → [DONE]`；`text-start` 只出现一次（重复会让 `useChat` 切成两段）；`finish()` 幂等、`[DONE]` 之后事件一律丢弃（`test_encoder_*` 4 条） |
| AC-3 编排用框架 | 通过 | `StateGraph` + 条件边 `agent → tools`，工具轮次上限 3；连续要工具被截断并标 `capped`（`test_graph_stops_after_the_tool_round_cap`） |
| AC-4 出网单一出口 | 通过 | 节点里只调 `AIClient.stream_chat`，无 `ChatOpenAI` / `langchain_openai`；`stream_chat` 复用 `runtime.ready`、`_persist_call_log`、错误映射 |
| AC-5 工具真的读库 | 通过 | 命中 / 未命中两条路：`read_weakness_detail` 读不到分组时 `ok=False` 且 `href=None`（不猜）；`read_resume_anchor` 逐字定位到 `documents.text` 才返回 `/polish`；未知工具名直接拒（`test_tool_*` 4 条） |
| AC-6 引用只来自取料 | 通过 | `citations` 只由 `_tools` 节点在 `href` 非空时追加、按 href 去重、上限 5；模型正文里写的链接一律不进（`test_graph_cites_only_what_the_tool_actually_read`） |
| AC-7 工具调用可见 | 通过 | `tool-input-start` / `tool-input-available` / `tool-output-available` 三帧 → 前端工具卡（运行中脉冲 / 完成摘要 / `is-miss` 未读到），浏览器断言 PASS |
| AC-8 不回归 | 通过 | 后端 **851 条 0 失败**（`--junitxml` 统计）；`/chat` 字段与 r82 一致，r77/r82 引用断言按新语义修正后全过；前端 38 文件 **484 测试**、typecheck / lint 0 warning、build 通过 |

## 3. 验证命令与结果

```text
backend: ruff check app tests            → All checks passed
backend: pytest -q --junitxml=r83.xml    → 851 tests / 0 failures / 0 errors / 1 skipped
backend: pytest tests/test_r83_taifu_agent.py -q → 17 passed
frontend: npm run typecheck / lint       → 通过，0 warning
frontend: npm test                       → 38 test files / 484 tests passed
frontend: npm run build                  → 通过
```

真实端到端（`python logs/teamflow/20261112-r83-taifu-agent-stream/scripts/e2e_stream.py`，假 LLM + 真后端）：

```text
首帧（第一段正文）: 0.20s
总耗时:             1.00s
delta 数:           10，间隔 0.082 / 0.085 / 0.088 / 0.091 / 0.095 ...（无攒批）
帧序列: start → data-meta → text-start → text-delta×10 → data-citations → data-done → text-end → finish → [DONE]
RESULT: PASS
```

真实浏览器（`node logs/teamflow/20261112-r83-taifu-agent-stream/scripts/check.cjs`，Edge headless CDP + mock 帧）：

```text
PASS 流式帧按序渲染成一段连续正文（不是等结束后一次性出现）
PASS 工具卡：运行中显示「正在读…」+ 脉冲
PASS 工具卡：完成显示结果摘要
PASS 工具卡：未读到（is-miss）如实标注，不伪装成成功
PASS 引用列表来自 data-citations，可点击跳转
PASS 元信息行显示「读了 N 段档案记录」
RESULT: PASS
```

## 4. 验收中发现并修复的问题

1. **LangGraph 不接受 coroutine**。`add_conditional_edges` 用 `lambda state: _agent(state)` 时抛
   `InvalidUpdateError: Expected dict, got <coroutine object _agent>`——lambda 返回协程，框架不认。
   改为显式 `async def agent_node(state, client)` / `finalize_node(state, client)` 闭包（`build(client)` 里绑定）。
2. **原本想用装饰器注入 client**。`_bind_client` 包裹层会把图的 context 覆盖掉、client 反而丢了。
   改成「节点签名 `(state, client)` + 闭包绑定」，出网对象不进 state（state 要可序列化）。
3. **`run_collect` 的 reply 必须以 `done.reply` 为准**。流式累积出来的 token 可能是 `'   '`（模型只吐空白），
   若直接用累积值，`reply == ''` 的断言会变成 `'   '`。改为 `done.reply` 无条件覆盖。
4. **上游忽略 `stream: true`**。自建端点常见：返回整包 JSON。`_is_event_stream()` 判 `content-type`，
   非 SSE 时把 `message.content` 当一个 `text` 事件、`message.tool_calls` 当 `tool_call` 事件产出，
   否则这条链路在本地档上会直接空响应。
5. **前端滚动不跟随流式内容**。滚动 `useEffect` 原本依赖 `messages.length`，流式时长度不变、内容在变，
   结果只滚一次。改依赖 `messages`（引用变化即重跑）。
6. **测试用例污染了开发库**。`test_tool_reads_resume_anchor_from_the_document` 用了 `profile_factory`
   （纯内存造对象、不碰库），于是 `insert_document` 落到了默认 `DB_PATH` 的开发库，首跑写入 `res-r83`、
   之后每次重跑都撞 `UNIQUE constraint failed: documents.id`。改为显式注入 `tmp_db`，用例回到一次性临时库。

## 5. 与前几轮的关系

- **r65 / r77 的「引用白名单」从「模型给的过滤」变成「服务端生成」**：之前是模型输出 `citations`、
  服务端按本次真读到的段过滤（r65 教练、r77 太傅）；r83 起太傅的模型**根本没有 citations 字段**——
  引用由工具结果产生，模型没有通道可编。这是本轮的**唯一语义变化**，也是 r82「引用必须是真读到的」
  的终点形态。
- **r82 的 focus 降级为提示**：以前 focus 直接带明细进提示词；现在 focus 只告诉模型「用户正看着什么」，
  明细必须经 `read_*` 工具取——这样「读到了」与「没读到」在界面上可区分（r82 无法区分）。
- **r80/r81 的记忆语义未动**：`remember` 工具套用 `sanitize_memories`（长度闭区间、字面包含去重、
  每轮 ≤2 条），`href=None`——记忆照旧不是依据。
- **r76-r82 的前端行为全部保留**：拖动与位置记忆、焦点条与取消、复制回答、记忆面板、清空对话、
  引用跳转与锚点高亮都不动，只换渲染源（`message.parts`）与请求方式（`useChat`）。

## 6. 已知限制

- **配额按「一次问答扣一次」**，但工具轮次会让上游实际调用次数 = 1 + 工具轮次（最多 4 次）。
  成本口径与账单不齐，本轮不改配额模型（改需要动 `user_ai` 的计数语义）。
- **流式不重试**。已经吐出正文再重试会让用户看到重复内容；流式中途失败只能提示重问，
  与 `_request` 的退避策略刻意不同。
- **工具并发但无超时隔离**：`asyncio.gather` 里任一工具卡住会拖住整轮，只能靠外层
  `TAIFU_TIMEOUT_S=120` 兜底。
- **`/chat` 与 `/chat/stream` 走的是同一个图**，语义一致；但 `/chat` 不再有「模型编引用被丢弃计数」
  这个概念，`dropped_citations` 恒 0（字段保留以兼容契约）。
- **历史线程没有工具记录**：`/thread` 只存问答文本，转 `UIMessage[]` 时只造 `text` part，
  刷新后旧回答看不到当轮的工具卡（有意为之：不为可观测性扩表）。

## 7. 交付后修复（2026-11-12）

用户反馈「前端多条回答错乱/重复」。定位到**一个根因 + 一处防御**：

| 项 | 内容 |
| --- | --- |
| 根因 | `ai_sdk.StreamEncoder` 的 `message_id` 默认值是常量 `"msg_taifu"`，每次流式回答都往 `start` 帧里写同一个 id |
| 为什么致命 | `start.messageId` 会成为助手消息的 id，而 `useChat` 收到新消息是**按 id 归位**的：`messages.findLastIndex(m => m.id === 新id)` 命中就 `replaceMessage`、不命中才追加（见 `ai/dist/index.js` 的 `runUpdateMessageJob`）。于是第二问的第二条回答**原地顶掉第一条**——不是「显示两条」，而是「第一条没了」 |
| 连带症状 | 两处 `key={message.id}` 撞车（React duplicate key），`copiedId === message.id` 让两条的「复制」一起变「已复制」 |
| 修复 | `ai_sdk.new_message_id()` 生成 `msg_<uuid16>`，`StreamEncoder(message_id=None)` 默认逐次唯一；显式传值仍生效（续流 / 重放要复用同一个 id） |
| 防御 | `lib/taifuStream.ts` 新增 `rowKeysOf(messages)`：同一列里重复 id 追加序号（`msg` / `msg#2`），组件用它做 React key 与「已复制」的键——退一步说，id 再撞也是「显示两条」，不会塌成一条 |

### 验证

```text
backend: pytest tests/test_r83_taifu_agent.py -q → 19 passed（新增 2 条）
backend: pytest -q --junitxml                   → 853 tests / 0 failures / 0 errors / 1 skipped
backend: ruff check app tests                   → All checks passed
frontend: vitest run                            → 38 files / 487 tests passed（新增 3 条）
frontend: typecheck / eslint --max-warnings 0   → 通过
```

真实浏览器（`node logs/teamflow/20261112-r83-taifu-agent-stream/scripts/check-two-replies.cjs`）：

```text
PASS 连问两次得到两条独立回答，第一条没有被顶掉
PASS 复制状态按行隔离，点第一条不影响第二条
RESULT: PASS

# 负向自检（SAME_ID=1，故意让两次流共用 msg_taifu）
PASS 负向自检：共用同一 messageId 时第二条顶掉第一条（旧 bug 已复现）
     实际列表：["第 2 条回答。"]
RESULT: REPRODUCED
```

负向自检是这条修复的关键证据：断言在旧行为下**必然失败**，说明它真的在防这件事，而不是碰巧通过。

### 新增两条测试

- `test_encoder_gives_each_stream_its_own_message_id`：两个编码器给出不同 id、前缀是 `msg_`、显式指定仍生效。
- `test_stream_endpoint_gives_each_reply_a_distinct_message_id`：同一个端点连问两次，两个 `start` 帧的 `messageId` 必须不同（端到端锁住这条契约）。
- `rowKeysOf` 3 条：唯一 id 原样用、重复 id 追加序号且整列无重复、空列表给空数组。
