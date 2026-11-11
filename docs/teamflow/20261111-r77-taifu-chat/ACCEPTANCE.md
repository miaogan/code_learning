# r77 · 验收报告：太傅对话

> 结论：PRD 中 11 条验收标准全部满足。新增 1 张表、3 个端点、1 个服务包；前端在 r76 面板内接上真实对话。尚未提交 / 推送。

## 1. 交付内容

| 文件 | 改动 |
| --- | --- |
| `backend/app/core/db.py` | 新增 `taifu_messages` 表与 `(user_id, created_at)` 索引（`init_db` 第 17–18 步） |
| `backend/app/core/repository.py` | 新增 `insert_taifu_message` / `list_taifu_messages` / `delete_taifu_messages`；写入时按 200 条裁剪 |
| `backend/app/schemas.py` | 新增 `TaifuCitation` / `TaifuMessage` / `TaifuThread` / `TaifuChatRequest` / `TaifuReply` / `TaifuClearResult` |
| `backend/app/services/taifu/brief.py` | 档案摘要纯函数：画像 / 诊断 / 测评 / 练习 / 学习五段，段即引用白名单 |
| `backend/app/services/taifu/policy.py` | 问句清洗、提示词、回答净化、引用白名单校验 |
| `backend/app/services/taifu/taifu.py` | 编排：读库 → 调模型 → 校验 → 落对话；空档案零调用 |
| `backend/app/routers/taifu.py` | `POST /api/taifu/chat`、`GET /api/taifu/thread`、`DELETE /api/taifu/thread` |
| `backend/app/main.py` | 注册 taifu 路由 |
| `backend/tests/test_r77_taifu.py` | 17 条：摘要投影 / 白名单 / 净化 / 短路 / 超长问句 / 会话隔离 / 清空 / 登录 |
| `frontend/src/api/types.ts` | 5 个契约类型（snake_case 与 Python 逐字对齐） |
| `frontend/src/api/client.ts` | `taifuThread` / `taifuChat` / `taifuClear` |
| `frontend/src/lib/taifuChat.ts` | 纯函数：问句清洗、发送闸门、段落切分、引用去重 |
| `frontend/src/test/taifuChat.test.ts` | 5 条前端纯函数测试 |
| `frontend/src/components/taifu/TaifuLauncher.tsx` | 面板接入对话：惰性加载线程、发送 / 失败回滚、引用链接、两步清空、读取计数 |
| `frontend/src/styles/base.css` | 追加 r77 段（消息气泡 / 引用 chip / 提示 / 清空链接 / 窄屏） |

**未改动**：r76 的位置算法与拖拽常量、既有页面、`ToolNav`、路由表、其余 AI 服务、任何业务表。

## 2. 验收标准

| AC | 结果 | 证据 |
| --- | --- | --- |
| AC-1 有据可答 | 通过 | 有画像 + 报告的账号提问，返回中文回答，`materials_used = 2`（画像 + 诊断）；浏览器实测回答分段渲染 |
| AC-2 引用可核对 | 通过 | 引用为 `/report`、`/practice`，点击跳到对应页面；越界 href（`/tmp/fake`）被丢弃，`dropped_citations = 1`，界面显示「已丢弃 1 条无依据引用」 |
| AC-3 新用户不编造 | 通过 | 无任何记录时 `materials_used = 0`、`notice` 为「站内记录还是空的…」，用抛错 responder 反向验证**未调用模型**；线程不落库 |
| AC-4 问句校验 | 通过 | 空问句 / 纯空白 → 返回 `EMPTY_QUESTION_NOTICE` 且不落库；2500 字问句**不被 422 拒绝**，入库内容截到 201 字（200 + `…`） |
| AC-5 多轮上下文 | 通过 | 提示词含最近 6 条消息（`用户：…` / `太傅：…`），单测断言；`list_taifu_messages` 按 `user_id` 过滤，换账号读不到 |
| AC-6 会话可恢复与可清空 | 通过 | 刷新后读回 2 条历史；清空后列表为空，`latest_profile()` 仍在（业务数据未动） |
| AC-7 只读承诺 | 通过 | 服务层唯一写操作是 `insert_taifu_message`；`DELETE` 只删 `taifu_messages`；无任何画像 / 报告写路径 |
| AC-8 失败可见 | 通过 | 前端 `catch` 收回乐观消息、恢复问句、面板内显示 `ApiError.message`；线程加载失败给「重试」按钮 |
| AC-9 额度与超时 | 通过 | 走 `user_ai.client_for(user, "light")`，`TAIFU_TIMEOUT_S = 120`，前台不重试；空档案在 `client_for` 之前短路（不要求配 Key） |
| AC-10 面板可用性 | 通过 | 发送中禁用输入并显示「太傅正在看你的记录…」；回答按段落渲染；引用为可点链接；390px 底部面板内完成一轮问答、无横向滚动 |
| AC-11 不回归 | 通过 | 前端 36 文件 462 测试、typecheck、lint 0 warning、build 全过；后端 793 passed / 1 skipped；r76 拖拽与位置记忆断言仍由实现保持不变（其脚本本次被 r77 脚本接替，见 §5） |

## 3. 验证命令与结果

```text
backend: python -m ruff check app tests      → All checks passed
backend: python -m pytest -q                 → 794 tests / 0 failures / 1 skipped（JUnit 统计，247s）
frontend: npm run typecheck                  → passed（双 tsconfig）
frontend: npm run lint                       → passed，--max-warnings 0
frontend: npm test -- --no-file-parallelism  → 36 test files / 462 tests passed
frontend: npm run build                      → passed，174 modules
                                              dist/assets/index-*.js 579.65 kB（gzip 236.36 kB）
```

真实 Chromium（CDP，`logs/teamflow/r77-taifu-chat/scripts/check.cjs`；接口用 `Fetch.enable` 合成，零外网、零 Key）：

```text
PASS 首次打开是空态：3 条示例、输入可用、空问句不可发送
PASS 点示例填入问句，发送按钮随问句解禁
PASS 一轮问答：分段渲染、引用可点、读取与丢弃计数可见
PASS 点引用跳转站内页面，浮窗随路由变化收起
PASS 刷新后读回历史对话（服务端线程）
PASS 清空为两步确认，确认后回到空态
PASS 390px 底部面板内完成一轮问答且无横向滚动
RESULT: PASS
```

截图：`desktop-empty.png` / `desktop-chat.png` / `mobile-chat.png`（同目录）。已人工查看：气泡宽度贴合内容、引用 chip 与正文可读、无重叠或裁切。

## 4. 验收中发现并修复的问题

1. **用户气泡占满整行**：块级 `div` 即使 `max-width: 88%` 也会撑满容器，`margin-left: auto` 看不出「靠右」。改为 `width: fit-content` 后气泡贴合内容，截图复核通过。
2. **CDP mock 报 `Invalid InterceptionId`**：页面导航 / StrictMode 重挂载会取消在途请求，此时回填拦截结果必然失败。脚本改为把该错误识别为「请求已被页面自己取消」，只对真正的 mock 异常报错（否则校验会随机红）。
3. **测试构造漏字段**：`WeaknessItem` 的 `summary` 为必填，最初构造报告时漏写导致 `ValidationError`；补齐后与真实报告结构一致。
4. **对 `sanitize_question` 的期望写错**：空白压平是「多空格 → 单空格」，不是删除空格（`我 先补什么`），改成与实现一致的断言，避免把正确行为测成缺陷。

## 5. 与 r76 的关系（口径变更留痕）

- r76 的「入口预览」态在本轮被取代：输入框与发送按钮从 `disabled` 变为可用，徽标从「入口预览」改为「你的跃迁参谋 · 只读」。
  任务夹建后不可变，故此处留痕而不回改 r76 文档。
- r76 的浏览器脚本 `logs/teamflow/r76-taifu-launcher/scripts/check.cjs` 断言「占位符 = 问答接口接入中」「输入 disabled」「文本含入口预览」，
  这些断言在 r77 后**必然失效**，属于预期演进；r76 脚本由 r77 脚本接替，拖拽 / 位置记忆的实现未改动且仍被 r77 脚本的打开面板路径覆盖。

## 6. 已知限制

- 引用只能到页级：报告页内还要自己找对应薄弱分组（分组名与摘要里一致，能对上）。
- 教程正文只在前端，太傅无法引用到小节；问「给我讲一下 X」只能给方向与章节入口。
- 回答质量取决于用户配置的 light 档模型；离线或无 Key 给中文说明，不降级成假回答。
- 会话单线程、不可导出、清空不可恢复；超过 200 条按时间淘汰最旧。
- iOS Safari 触屏与软键盘遮挡未真机验证（桌面触屏模拟通过）。

## 7. 后续可做（不在本轮）

- 把「当前页」作为对话上下文的一部分注入提示词（面板已显示页名，但尚未进 prompt）。
- 引用到具体薄弱分组锚点（需要报告页支持 `#weakness-<key>` 定位）。
- 对话摘要压缩（长线程按轮次总结，替代简单截断到 6 条）。
