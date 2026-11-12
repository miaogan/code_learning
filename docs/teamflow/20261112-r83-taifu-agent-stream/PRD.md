# r83 · 太傅：从单次补全改成 agent（LangGraph 编排 + 流式 + 工具可见）

## 背景

r77–r82 把太傅的「问 / 引 / 记 / 深读」做齐了，但底层始终是**一次 RPC 式补全**：

```
页面点击 → gather_context()（if kind 分支） → /chat/completions（非流式，JSON mode）
        → sanitize_reply() 白名单 → 落库 → 整体返回
```

这套结构有三个绕不开的上限：

1. **不可见**。全程一个请求对一个响应，用户等 120s 只看得到转圈。读了几段、要查什么，界面上没有任何位置能显示。
2. **不自决**。读什么材料由服务端的 `if focus["kind"]` 决定，模型从头到尾不知道"可以自己去看某道题的解析"。r82 的「深读」是页面点了才有，点不到就没有。
3. **不可拓**。每加一类材料就要加一个 `kind` 分支、改一次 `deep_read`。材料种类涨到六七类时，这个 if 链会变成第二个需要维护的提示词。

同时 `ai.py` 里那套自研的 retry / 退避 / JSON 修复 / 连接池，是"一次补全"的工具箱，不是编排层。
它把出网做对了，但没有地方放"多步"。

## 目标

> 把编排从「Python 函数顺序调用」换成「图 + 事件流」：模型自己决定要不要读料、读哪一条，
> 用户能看着它读、看着它写；出网仍然只有一条路，配额、日志、隐私边界一个不丢。

## 范围

| 改动 | 说明 |
| --- | --- |
| 编排层 | 新 `services/taifu/graph.py`：`StateGraph` + `agent ⇄ tools` 循环（硬上限 3 轮）+ 后置 `finalize` |
| 出网层 | `AIClient` 新增 `stream_chat()`：SSE 解析、`tool_calls` 分片累积；**配额扣减 / 调用日志 / 隐私边界 / 退避 / `json_mode` 全部沿用原实现** |
| 工具层 | 新 `services/taifu/tools.py`：4 个只读工具（薄弱明细 / 错题明细 / 简历锚点 / 历史报告对比）+ 1 个写入工具（`remember`，只写记忆表） |
| 流式端点 | 新增 `POST /api/taifu/chat/stream`，按 AI SDK UI Message Stream v1 协议输出 |
| 旧端点 | `POST /api/taifu/chat` 保留，改为**聚合同一张图**的事件 —— 一个图两个出口，旧契约不破 |
| 前端 | 接入 `ai@7` + `@ai-sdk/react@4` 的 `useChat`；正文增量渲染、工具卡（进行中 / 完成）、引用、元信息 |
| 引用语义 | **引用 = 本轮工具真正读到的明细段**，模型不再有通道去编引用；`dropped_citations` 恒为 0 |
| 记忆 | 长期记忆由 `remember` 工具写入（模型自主决定），不再靠 replies 里的字段回传 |

### 引用语义的变更（会影响既有行为）

r79 的语义是「模型挑它认为相关的段来引」，靠白名单丢弃幻觉。流式下正文没有 JSON 通道，
让模型再单独吐一次 citations 要多一次结构化调用、且要先等正文结束。

改为：**本轮读过什么，就引什么**。具体口径：

- 工具读到的明细段 → 逐条列出（最多 5 条），这是有具体指向的引用；
- `prepare` 注入的摘要段 → 不进引用列表，只计入「本次读了 N 段档案」的元信息；
- 没有工具调用 → 引用为空，界面只显示元信息。

代价：模型失去了"挑重点引"的选择权，`dropped_citations` 失去意义（恒 0）。
`test_r77_taifu.py` 里依赖模型吐引用的 6 处断言按新语义重写。

## 明确不做

- **不改业务边界**。「参谋不是执行器」仍然成立：写入只碰 `taifu_memories` 一张表，
  不改画像、不改计划、不投递、不删数据。
- **不做多 agent / 子图**。一个 agent 节点 + 一个工具节点足够；多 agent 会把这个问答场景的成本翻倍，
  而问题是"我这条该怎么补"，不是"帮我做完整个项目"。
- **不做工具审批流**。全部工具只读（除 `remember` 写自己的记忆表），没有需要人工确认的操作。
- **不迁移其他模块**。画像、报告、润色仍走 `complete_model`，本轮只动太傅。
- **不换出网实现**。不引入 `langchain-openai` 的 `ChatOpenAI`，见下。

## 关键决策

### 为什么不用 `ChatOpenAI`

`AIClient` 里绑着四样丢不起的东西：`consume_shared_quota()`（内置 Key 配额）、
`_persist_call_log()`（调用计数）、隐私边界（日志不记 prompt / 简历正文）、
重试退避 + `json_mode` 分支。换 `ChatOpenAI` 等于把这四样重写一遍或直接绕过。

**LangGraph 只做编排，出网仍走 `AIClient`。** 图节点是普通 async 函数，不依赖 langchain 的模型抽象。
langgraph 的核心依赖很轻（`langgraph` + `langgraph-checkpoint`），不拖 langchain 全家桶。

### 为什么 token 级流式必须靠出网层

LangGraph 的 `astream` 能流「节点级」事件，但流不出 token —— token 来自 HTTP 响应的字节流。
所以 `AIClient.stream_chat()` 必须是 async generator，图节点里消费它、把每个 delta 用
`get_stream_writer()` 转发出去。少这一层，前端就只能看到"生成中 / 生成完"。

### 为什么不保留旧的 gather 分支

`gather_context()` 的 `if kind` 分支被工具层取代：`prepare` 只注入摘要投影（和 r82 一样），
明细一律走工具。r82 的页面入口（focus）保留，但退化为**提示**——告诉模型"用户正看着这一条"，
模型仍需调工具才拿得到明细（这样"读到了"和"没读到"在界面上是可区分的）。

## 验收标准

1. 问一句能流式看到正文，首字延迟显著低于整段等待（同条件下首 token 到达时间 < 总时长的 1/3）。
2. 界面上能看到工具调用：名称、入参摘要、状态（进行中 / 完成）、结果摘要。
3. 工具轮次受硬上限约束：模型连续要求调工具时不无限循环，达到上限后强制生成。
4. 引用只可能指向本轮真读到的明细；构造"模型想引一段没读过的材料"场景时，引用列表里不出现它。
5. `POST /api/taifu/chat` 的行为与 r82 一致（除引用语义变更），旧前端不崩。
6. 流中断（用户取消 / 上游超时）时：已流出的正文不回滚、不写半条历史、给出中文提示。
7. 配额扣减仍按"一次问答 = 一次配额"计，不随工具轮次翻倍。
8. `materials_used` / `memories_added` 语义不变，界面文案不变。

## 交付物

- `docs/teamflow/20261112-r83-taifu-agent-stream/PRD.md`（本文）
- `docs/teamflow/20261112-r83-taifu-agent-stream/TECHNICAL.md`
- `docs/teamflow/20261112-r83-taifu-agent-stream/ACCEPTANCE.md`
