# r83 技术方案 · 太傅 agent 化

## 1. 分层边界

新增的两层不能碰到既有三层的东西：

```
routers/taifu.py        HTTP：契约、鉴权、SSE 响应
  ├─ services/taifu/graph.py     【新】编排：LangGraph 图、状态、事件
  │    ├─ services/taifu/tools.py   【新】取料：只读工具 + remember
  │    └─ services/taifu/policy.py  既有：提示词、清洗、白名单
  └─ services/ai/ai.py           既有 + 【改】：新增 stream_chat
```

**铁律：图节点里只允许通过 `AIClient` 出网。** 不引入 `langchain-openai`、不用 `ChatOpenAI`。
原因见 PRD「关键决策」：配额扣减、调用日志、隐私边界、退避、`json_mode` 都长在 `AIClient` 里。

LangGraph 的依赖边界也守住：只用 `langgraph.graph`（`StateGraph` / `START` / `END`）与
`langgraph.config.get_stream_writer`，不用 `langgraph.prebuilt` 的 `ToolNode`、
不用 `langchain_core` 的 message 类型。所有消息仍是 OpenAI 的 dict 形状（与 `_request` 一致）。

## 2. 出网层：`AIClient.stream_chat`

```python
async def stream_chat(
    self,
    system: str,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    timeout_s: float | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """产出三类事件：
    {"kind": "text",      "text": "..."}
    {"kind": "tool_call", "index": 0, "id": "call_x", "name": "read_question_detail", "arguments": "..."}
    {"kind": "done",      "finish_reason": "stop"}
    """
```

要点：

| 事项 | 做法 |
| --- | --- |
| 就绪检查 | 与 `_request` 同一套：`runtime.ready` 为假 → `AppError(AI_UNAVAILABLE, 503)`，并 `_persist_call_log(kind="skipped")` |
| 请求体 | `{"model", "messages": [system] + messages, "temperature": 0.2, "stream": True}`；有 `tools` 时附 `"tools": [...]` + `"tool_choice": "auto"` |
| `response_format` | **流式不带**。流式产出的是自然语言正文，JSON mode 只对结构化补全有意义；`runtime.json_mode` 在此路径忽略 |
| 传输 | `_shared_client().stream("POST", url, ...)`，`aiter_lines()` 逐行；`data: ` 前缀，`[DONE]` 终止 |
| tool_calls 累积 | delta 里 `tool_calls[i].function.arguments` 是**分片字符串**，按 `index` 累积拼接；`id` / `name` 只在首片出现，取第一个非空值 |
| 上游不支持流式 | 若 `content-type` 不是 `text/event-stream`，退回读整包 JSON，把 `message.content` 作为单个 `text` 事件、`message.tool_calls` 作为 `tool_call` 事件产出。自建端点常见，必须有这条路 |
| 错误映射 | 与 `_request` 逐条对齐：超时 → `503 retryable`、429/5xx → `503 retryable`、4xx → `502 不可重试`、解析失败 → `502 retryable` |
| 日志 | 首字到达时记 `elapsed_ms`（首 token 延迟），结束时记 `kind="success"`；prompt 正文一律不记 |
| 重试 | **不重试**。已经流出正文再重试会让用户看到重复内容；流式调用的失败一律交给上层提示重问 |

`_persist_call_log` 的 `prompt_chars` 仍按 system + messages 文本长度估算，口径与 `_request` 一致。

## 3. 工具层：`services/taifu/tools.py`

统一的返回形状，让图节点不必区分工具：

```python
class ToolResult(TypedDict):
    ok: bool            # False 表示没读到（找不到 / 越界 / 参数非法）
    label: str          # 界面卡片标题，如「错题明细 · 事件循环与微任务」
    summary: str        # 一行结果摘要，进界面卡片
    href: str | None    # 有具体指向时给引用 href；None 表示不进引用
    content: list[str]  # 回灌给模型的行（受预算约束）
```

| 工具 | 参数 | 数据来源 | 预算 |
| --- | --- | --- | --- |
| `read_weakness_detail` | `point: str`（分组名，模糊匹配） | `latest_report().weaknesses` + 题库 + 作答 | ≤8 行 × 160 字 |
| `read_question_detail` | `question_id: str` | `repository.get_question` + `list_attempts` | ≤8 行 × 160 字 |
| `read_resume_anchor` | `anchor_text: str` | `get_document_text(profile.resume_id)` 定位 + 前后文窗口 | ≤8 行 × 160 字 |
| `compare_reports` | 无 | 新增 `repository.list_reports(limit=2)` | ≤8 行 × 160 字 |
| `remember` | `content: str` | `insert_taifu_memory` | 单条 ≤80 字，每轮 ≤2 条 |

`read_weakness_detail` / `read_question_detail` / `read_resume_anchor` 复用 r82 `deep_read.py`
的取料函数（它们已经处理了「题目被删」「选项缺失」「锚点定位失败」这些边界），
只是把入口从 `focus.kind` 改成工具入参。

`remember` 的写入约束沿用 `policy.sanitize_memories`：长度闭区间、与已有条目互相包含即去重、
每轮上限 2 条。写成功后 `href=None`（记忆不是站内依据）。

**新增仓储函数**：`list_reports(limit: int = 2) -> list[Report]`，按 `created_at DESC`。
`compare_reports` 靠它拿相邻两份做对比；`brief` 仍只读 `latest_report()`，不改。

## 4. 图：`services/taifu/graph.py`

```python
class TaifuState(TypedDict, total=False):
    question: str
    page: dict[str, str] | None
    focus: dict[str, Any] | None
    sections: list[dict[str, Any]]        # prepare 注入的摘要段（含 href）
    dialogue: list[dict[str, Any]]        # OpenAI messages，逐轮累积
    citations: list[dict[str, str]]       # 只由工具结果追加
    rounds: int
    reply: str
    memories_added: int
    error: str
```

```
START → prepare → agent ──(有 tool_calls 且 rounds < 3)──→ tools ──→ agent
                     └──(无 tool_calls 或 rounds ≥ 3)──→ finalize → END
```

- **prepare**：`brief.build_sections` + 历史 + 摘要 + 记忆，拼成首条 user message；发 `meta` 事件。
  带 `focus` 时在提示词里注明「用户正看着：<label>」，但**不给明细** —— 明细必须经工具取，
  这样「读到了」与「没读到」在界面上可区分（r82 的行为变化点）。
- **agent**：`client.stream_chat(...)`，边流边把 `text` 事件用 `get_stream_writer()` 转发，
  同时累积 `tool_calls`。有 tool_calls → 返回 `{"rounds": rounds + 1}` 走 tools 边。
- **tools**：并发执行本轮全部 tool_calls（`asyncio.gather`），逐个发 `tool_start` / `tool_end`，
  结果按 OpenAI 的 `role="tool"` 消息回灌，`href` 非空的追加进 `citations`（按 href 去重，上限 5）。
- **finalize**：`reply` 为空时给中文 notice，不写历史；否则写 user + assistant 两条消息，
  窗口溢出时更新摘要（沿用 r80 的 `overflow` 判定），发 `done` 事件。

**轮次硬上限**：`MAX_TOOL_ROUNDS = 3`。达到上限后即使模型还要调工具也强制走 finalize，
并在 `meta` 里标 `capped=True`（界面提示「已达取料上限」）。

**为什么不用 `ToolNode`**：`ToolNode` 依赖 `langchain_core.messages` 类型，会把整条链路
拖进 langchain 的消息抽象；自写 20 行 `asyncio.gather` 更短，也便于逐条发事件。

## 5. 内部事件 → AI SDK 协议

内部事件（图发出，与前端解耦）：

| 事件 | 载荷 |
| --- | --- |
| `meta` | `materials`, `focus`, `memories_used`, `capped` |
| `tool_start` | `id`, `name`, `label`, `input`（已脱敏摘要） |
| `tool_end` | `id`, `ok`, `label`, `summary` |
| `token` | `delta` |
| `citations` | `items: [{label, href}]` |
| `done` | `reply`, `memories_added`, `created_at` |
| `error` | `message` |

`services/taifu/ai_sdk.py` 负责编码成 `text/event-stream`：

```
data: {"type":"start","messageId":"msg_x"}
data: {"type":"data-meta","data":{"materials":8,...}}
data: {"type":"tool-input-start","toolCallId":"call_x","toolName":"read_question_detail"}
data: {"type":"tool-input-available","toolCallId":"call_x","toolName":"read_question_detail","input":{...}}
data: {"type":"tool-output-available","toolCallId":"call_x","output":{"ok":true,"summary":"..."}}
data: {"type":"text-start","id":"txt_x"}
data: {"type":"text-delta","id":"txt_x","delta":"这道题"}
data: {"type":"text-end","id":"txt_x"}
data: {"type":"data-citations","data":{"items":[...]}}
data: {"type":"finish"}
data: [DONE]
```

响应头：`Content-Type: text/event-stream; charset=utf-8`、`Cache-Control: no-cache`、
`x-vercel-ai-ui-message-stream: v1`、`X-Accel-Buffering: no`。

编码器是纯函数（事件 → 字符串列表），可单测，不需要起服务。
出错时发 `{"type":"error","errorText":"..."}` 后照常 `[DONE]`，前端 `useChat` 会把它挂到 `error` 上。

## 6. 一个图，两个出口

| 端点 | 实现 |
| --- | --- |
| `POST /api/taifu/chat/stream` | 消费内部事件 → 编码成 AI SDK 协议 → `StreamingResponse` |
| `POST /api/taifu/chat` | 消费同一个事件流，聚合 token 成 `reply`，取 `citations` / `meta` / `done`，拼 `TaifuReply` |

`/chat` 的入参、出参字段不变，唯一语义变化是引用来源（见 PRD）。
这样 834 条存量测试的回归面收敛到「引用相关断言」，而不是「整个太傅重写」。

`/chat` 走流式出网后，上游账单口径不变（仍是一次补全），但**工具轮次会让实际调用次数 = 1 + 工具轮次**。
配额按「一次问答扣一次」计，在路由层扣（`client_for` 里已有），不随轮次累加。

## 7. 前端

新增依赖：`ai@7`、`@ai-sdk/react@4`（v7 对应 react 包 4.x，锁小版本）。

```
TaifuLauncher
  useChat({
    transport: new DefaultChatTransport({
      api: '/api/taifu/chat/stream',
      body: () => ({ page, focus }),        // 每次请求现取，避免闭包旧值
    }),
    messages: seeded,                        // 由 /thread 构造的 UIMessage[]
    onError, onFinish,
  })
```

**消息渲染**改为遍历 `message.parts`：

| part | 渲染 |
| --- | --- |
| `text` | 复用 r82 的段落 / 列表 / 粗体渲染 |
| `tool-<name>` | 工具卡：`input-available` 时显示「正在读…」，`output-available` 时显示结果摘要 |
| `data-meta` | 底部元信息行（读了 N 段 / 已达上限） |
| `data-citations` | 引用列表（保留 r79 的 hover 锚点行为） |

纯函数抽到 `src/lib/taifuStream.ts`（`partsToView`、`toolLabel`、`toolStateOf`），便于 vitest 覆盖。
组件只做布局，判断逻辑全在纯函数里 —— 与 r82 拆 `taifuChat.ts` 同一手法。

**保留不动**：焦点条、取消（`useChat` 的 `stop()`）、复制回答（从文本 part 拼）、记忆面板、清空对话、拖动与位置记忆。

**初始消息**：`/thread` 返回的历史没有工具记录，转成 `UIMessage[]` 时只造 `text` part，
`id` 用服务端消息 id，保证 React key 稳定。

## 8. 测试策略

| 层 | 覆盖 |
| --- | --- |
| 编码器 | 每种内部事件都产出合法 SSE 行；`[DONE]` 只出现一次；`data-meta` 的 JSON 可解析 |
| `stream_chat` | 假 SSE 文本（含分片 tool_calls、`[DONE]`、空行、错误帧）→ 断言累积结果；上游非 SSE 时回退整包解析 |
| 工具 | 四类只读工具的命中 / 未命中（不编造）；`remember` 的长度与去重；预算截断 |
| 图 | 无工具直达 finalize；一轮工具后生成；连续要工具被 3 轮截断；引用只来自工具结果 |
| 端点 | `/chat/stream` 的响应头、首帧是 `start`、末帧是 `[DONE]`；`/chat` 字段与 r82 一致 |
| 前端 | `partsToView` 对 text / tool / data 的映射；工具卡状态机；空 parts 不崩 |

存量测试修正范围：`test_r77_taifu.py` 中 6 处 `dropped_citations` 断言改为
「引用只来自取料，模型无法注入引用」；`test_r80` / `test_r81` 的 `summary_used` / `memories_added`
断言保留（语义不变）。
