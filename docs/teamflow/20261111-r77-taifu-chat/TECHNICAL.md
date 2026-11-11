# r77 · 技术方案：太傅问答（服务端档案摘要 + 引用白名单）

> 依据 PRD `docs/teamflow/20261111-r77-taifu-chat/PRD.md`。新增 1 张表、3 个端点、1 个服务包；前端复用 r76 面板。

## 1. 与 r65 教练的差别（为什么不复用同一套）

| 维度 | r65 学习教练 | r77 太傅 |
| --- | --- | --- |
| 材料来源 | **前端**组装（教程语料只在前端） | **服务端**从库里读（画像 / 报告 / 测评 / 练习 / 学习） |
| 可信边界 | 材料由客户端上传，服务端只能做形状校验 | 材料由服务端自己查，客户端无法注入内容 |
| 引用粒度 | 教程小节 href（带 `#tutorial-` 锚点） | 站内路由（`/report` 等），不伪造锚点 |
| 交互 | 一次性生成建议卡片 | 多轮对话 + 会话落库 |
| 输出 | 结构化 JSON（blocks / actions） | 自然语言 reply + 引用数组 |

两者共用同一套思路：**模型只能引用输入里的东西，越界即丢弃并计数**。但太傅的材料是服务端真值，
所以不需要前端上传，也不能让前端上传。

## 2. 数据表

```sql
CREATE TABLE IF NOT EXISTS taifu_messages (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL DEFAULT 'default',
    role        TEXT NOT NULL,              -- 'user' | 'assistant'
    content     TEXT NOT NULL,
    citations   TEXT NOT NULL DEFAULT '[]', -- JSON 数组：[{label, href}]
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_taifu_user_created ON taifu_messages (user_id, created_at);
```

- 单线程：一个账号一条对话流，不建 session 表。PRD 明确不做多线程。
- `citations` 只在 `assistant` 行非空；用户消息恒 `[]`。
- 写入时裁剪：超过 `TAIFU_MESSAGE_LIMIT = 200` 条按 `created_at DESC` 淘汰最旧（同一事务内 `DELETE`）。
- 建表走 `R77_SCHEMA` / `R77_INDEXES`，在 `init_db()` 末尾执行；无迁移脚本（沿用「只 `CREATE TABLE IF NOT EXISTS`」约定）。

## 3. 档案摘要（`services/taifu/brief.py`）

纯函数 `build_sections(profile, report, runs, attempts, learn) -> list[Section]`，IO 全在编排层。

| 段 | href | 数据来源 | 渲染口径 |
| --- | --- | --- | --- |
| 目标与画像 | `/profile` | `repository.latest_profile()` | 目标岗位 / 经验年限 / 技术栈前 8 / 能力项数量与前 6 项 / 项目前 3（名称 · 角色 · 要点数） |
| 最近诊断 | `/report` | `repository.latest_report()` | 生成日期 / 面试均分与笔试总分 / 岗位对标与「先补 3 项」/ 薄弱分组前 5（方向 · 难度 · 错误率 a/b） |
| 测评记录 | `/history` | `repository.history_rows(limit=6)` | 最近 5 场：日期 · 类型 · 分数（复用 `history.score_of`，未计分写「未计分」） |
| 练习记录 | `/practice` | `repository.list_attempts()` | 已练题数（去重）/ 作答次数 / 正确率 / 最近一次时间 |
| 学习进度 | `/learn` | `repository.get_learn_progress()` | 有阅读记录的章节数 / 已读小节数 / 上次读到哪章 |

规则：

- **没有数据的段不进列表**——白名单只允许引用真实存在的段，避免「引用一个空报告页」。
- 每段最多 6 行、每行 ≤120 字；超出截断。摘要总长可控在 2–3KB，够模型判断又不至于烧上下文。
- 不做二次统计：分数一律 `history.score_of`，错误率一律取报告里已算好的 `rate`，服务端不重算。
- 新用户（`profile` 与 `report` 都为空、无 runs / attempts / learn）→ `sections == []` → 零成本短路。

## 4. 提示词（`services/taifu/policy.py`）

```
你是「太傅」，逃跑计划的跃迁参谋，服务对象是想转向 AI 应用 / Agent 后端的外包工程师。

硬性规则：
1. 只能使用【档案】里出现过的内容；档案没有的数字、项目、结论一律不写。
2. 引用只能从【档案】每段末尾给出的 href 里逐字挑，不得自造链接或锚点。
3. 信息不足时直接说"你的记录里还没有 X"，并指出补哪一步能让它可答。
4. 不承诺求职结果，不把模拟评测说成工作经历。
5. 只输出一个 JSON 对象：{"reply": "...", "citations": ["/report"]}
```

用户消息结构：`【档案】<逐段编号 + href + 行> 【最近对话】<最近 6 条截断> 【问题】<问句>`。

JSON 输出（而不是自由文本）是为了让引用可校验：模型给 `citations` 数组，服务端对照白名单过滤。
`reply` 里的换行保留（前端按段落渲染）。

## 5. 回复净化（`policy.sanitize_reply`）

```python
allowed = {section["href"]: section["label"] for section in sections}
```

- `citations`：非字符串丢弃；不在 `allowed` 的丢弃并 `dropped_citations += 1`；去重保序；最多 4 条。
- `reply`：`\r\n → \n`、连续 3+ 换行压成 2、首尾 strip、超 1200 字截断加 `…`。
- `reply` 为空 → 返回 `notice = EMPTY_REPLY_NOTICE`（中文：模型这次没给出可用回答，可以再问一次），**不抛 500**。
- 返回 `materials_used = len(sections)`，让界面能显示「本次读取了 N 段站内记录」。

## 6. 端点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/taifu/chat` | 请求 `{question}`；返回 `TaifuReply`；持久化用户消息 + 回答 |
| `GET` | `/api/taifu/thread?limit=20` | 最近消息（时间升序），供打开面板恢复 |
| `DELETE` | `/api/taifu/thread` | 清空本账号对话，返回 `{deleted: n}` |

口径：

- 全部走 `Depends(current_user)`，未登录 401；跨账号不可见（`repository` 按 `user_id` 过滤）。
- `client = user_ai.client_for(user, "light")`；`TAIFU_TIMEOUT_S = 120`，前台 `retry_unavailable` 默认 False。
- **空档案短路在 `client_for` 之前**：没数据的用户不消耗额度、不要求配 Key。
- 空问句在路由层直接返回提示，不发请求、不落库。
- 会话写入在模型成功之后：失败不留半条对话（避免「有问无答」的历史）。

## 7. 前端

- `api/types.ts` 新增 `TaifuCitation` / `TaifuMessage` / `TaifuThread` / `TaifuReply` / `TaifuClearResult`，snake_case 与 Python 逐字对齐。
- `api/client.ts` 新增 `taifuThread()` / `taifuChat(question)` / `taifuClear()`，仍走唯一出口 `request()`。
- `lib/taifuChat.ts` 纯函数层（可单测）：
  - `clampQuestion(raw)`：压平空白、去首尾、截 200 字；
  - `canSend(question, pending)`；
  - `paragraphsOf(text)`：按空行 / 换行切段，丢空段。
- `TaifuLauncher` 打开时惰性加载线程（收起状态零请求）；发送后本地追加问句与回答，`pending` 期间禁用输入；
  失败走面板内 `InlineError` 风格（中文原因 + 重试）；引用渲染成 `<Link>`，点击跳转并因路由变化自动收起面板。
- 清空为两步确认（先「清空」，按钮变「再点一次」）。
- 样式只在 `base.css` 追加 r77 段，沿用 r76 的 token，零裸色值裸尺寸。

## 8. 测试

- 后端 `tests/test_r77_taifu.py`：
  1. 摘要只包含有数据的段；空档案 → `sections == []`；
  2. 引用白名单：合法通过、越界丢弃并计数、重复去重；
  3. `reply` 清洗：换行保留、超长截断、空回答给 notice；
  4. 空问句 / 纯空白 → 提示且不落库；
  5. 空档案端点 → 不调用模型（用抛错的 responder 反向验证）；
  6. 会话：发送两轮 → `GET thread` 顺序正确；换账号读不到；
  7. `DELETE` 清空后 `GET` 为空，且画像 / 报告数据不受影响；
  8. 未登录 401；无 Key 走既有中文错误码。
- 前端 `test/taifuChat.test.ts`：`clampQuestion` 空白 / 超长 / 换行，`canSend` 三态，`paragraphsOf` 空文本与多段。

## 9. 已知限制

- 引用只能到页级，用户点进去还要自己找对应卡片（报告页有薄弱分组，能对上）。
- 教程正文在前端，太傅无法引用到小节；问「给我讲一下 X」这类问题只能给方向与章节入口。
- 对话不跨账号迁移、不做导出；清空不可恢复。
- 回答质量取决于用户配置的 light 档模型；离线或无 Key 时功能不可用（给中文说明，不降级成假回答）。
