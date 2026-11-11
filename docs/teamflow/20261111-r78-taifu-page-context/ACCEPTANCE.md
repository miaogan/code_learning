# r78 · 验收报告：页面上下文与空档案出口

> 结论：PRD 中 6 条验收标准全部满足。纯增量（无新表、无新端点、无新依赖）：后端 2 条新测试 + 提示词与 schema 各加一个字段，前端 1 个参数 + 1 段回滚 + 1 组出口链接。尚未提交 / 推送。

## 1. 交付内容

| 文件 | 改动 |
| --- | --- |
| `backend/app/schemas.py` | `TaifuChatRequest` 增 `page`（默认空串） |
| `backend/app/services/taifu/policy.py` | `PAGES` 闭集（15 页）+ `sanitize_page()`；提示词增 `【当前页面】` 段；系统提示词增一条「页面只用于消解指代」 |
| `backend/app/services/taifu/taifu.py` | `answer(..., page=None)` 透传 |
| `backend/app/routers/taifu.py` | 闭集归一后传入服务层 |
| `backend/tests/test_r77_taifu.py` | +2 条（页面闭集 / 提示词页面段），端点用例补 `page` 断言 |
| `frontend/src/api/client.ts` | `taifuChat(question, page)` |
| `frontend/src/components/taifu/TaifuLauncher.tsx` | 提问带 `location.pathname`；空回答收回问句并恢复输入；`materials_used = 0` 时给三个入口 |
| `frontend/src/styles/base.css` | 追加 `.sc-taifu-shortcuts`（r78 段） |

## 2. 验收标准

| AC | 结果 | 证据 |
| --- | --- | --- |
| AC-1 指代可解 | 通过 | 首页提问时请求体 `page = "/"`；在 `/report` 提问时 `page = "/report"`，服务端提示词含 `【当前页面】医案（诊断报告）（/report）`（后端用例断言 + 浏览器断言两次提问的 `page` 值） |
| AC-2 页面不污染引用 | 通过 | 白名单仍只由档案段构成；r77 的「越界 href 丢弃并计数」用例不受影响（`dropped_citations = 1` 仍成立） |
| AC-3 不可注入 | 通过 | `/evil`、空串、`/report/../settings` 一律 `None`；`/learn/<slug>#tutorial-s1` 归到 `/learn`；`/report?run_id=r1#weakness` 归到 `/report` |
| AC-4 空档案不留假消息 | 通过 | 浏览器实测：空档案回答后消息气泡数回到 0、输入框恢复原问句、notice 文案可见 |
| AC-5 空档案有出路 | 通过 | 出现 3 个链接，`href` 依次为 `/`、`/practice`、`/report`；下一次正常回答后该组消失 |
| AC-6 不回归 | 通过 | 后端 796 passed / 1 skipped；前端 36 文件 462 测试、typecheck、lint 0 warning、build 全过；浏览器 9 组断言全 PASS（含 r77 的两步清空、引用跳转、刷新恢复、390px） |

## 3. 验证命令与结果

```text
backend: ruff check app tests   → All checks passed
backend: pytest -q              → 796 tests / 0 failures / 1 skipped（JUnit 统计，227s）
frontend: typecheck / lint       → passed，0 warning
frontend: npm test               → 36 test files / 462 tests passed
frontend: npm run build          → passed，174 modules，579.94 kB（gzip 236.43 kB）
```

真实 Chromium（`logs/teamflow/r77-taifu-chat/scripts/check.cjs`，同一套脚本持续覆盖两轮能力）：

```text
PASS 首次打开是空态：3 条示例、输入可用、空问句不可发送
PASS 点示例填入问句，发送按钮随问句解禁
PASS 空档案：收回问句、给中文说明与三个可点出口
PASS 一轮问答：分段渲染、引用可点、读取与丢弃计数可见
PASS 点引用跳转站内页面，浮窗随路由变化收起
PASS 刷新后读回历史对话（服务端线程）
PASS 清空为两步确认，确认后回到空态
PASS 390px 底部面板内完成一轮问答且无横向滚动
PASS 非首页同样带上当前页面（/report）
RESULT: PASS
```

## 4. 验收中发现并修复的问题

1. **空串被当成首页**：`sanitize_page("")` 初版按 `rstrip("/") or "/"` 兜底，把「前端没传」误判成「用户在投卷」，等于替用户猜了一个页面。改为空串直接返回 `None`，由提示词写「未识别」。
2. **`meta` 不重置会让出口常驻**：`materials_used = 0` 的快捷入口按 `meta` 渲染，若下一次回答仍为 0 会一直留着；已在每次发送时重置 `meta`（置 `null` 后再按回答写入），浏览器断言「正常回答后快捷入口消失」。
3. **CDP 脚本的计数基线要跟着改**：新增的空档案一次发送会让 `chatCalls` 从 1 变 2，原断言写死 1 会误红；改成按场景计数并显式断言两次调用的 `page`。

## 5. 与 r77 的关系

- 测试沿用 `tests/test_r77_taifu.py`：同一能力面（太傅问答）不另开文件，r78 只新增 2 条用例并在端点用例里补断言。
- r77 的 `answer(question, sections, *, client)` 签名增加 keyword-only 的 `page`，旧调用方零改动。
- r77 ACCEPTANCE 里「页面上下文尚未进提示词」已列为后续项，本轮完成，口径以本夹为准。

## 6. 已知限制

- 页面上下文只用于消解指代，不改变档案内容：在报告页问「这条」仍要求最新报告已在档案摘要里。
- 快捷入口固定三个，不按缺口类型动态排序（只缺报告时也会出现「去上传简历」）。
- 引用仍到页级，未支持 `#weakness-<key>` 锚点。
