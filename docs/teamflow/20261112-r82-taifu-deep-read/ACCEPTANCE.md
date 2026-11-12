# r82 · 验收报告：按需深读 + 页面就地发问

> 结论：PRD 中 9 条验收标准全部满足。纯增量：1 个新模块（`services/taifu/deep_read.py`，零 IO 取料层）
> + 契约 3 处可选字段 + 前端 1 个新桥（`lib/taifuBridge.ts`）与 3 处页面入口；
> 无新依赖、无新表、无额外模型调用。r77–r81 全部行为不回归。

## 1. 交付内容

| 文件 | 改动 |
| --- | --- |
| `backend/app/core/repository.py` | `get_question(question_id)`（单题读取，与 `list_questions` 同 SELECT 同投影） |
| `backend/app/services/taifu/deep_read.py` | 新建：三类焦点取料（weakness / attempt / resume），与档案段同形，零 IO（`load_question` 由调用方传入） |
| `backend/app/services/taifu/policy.py` | `FOCUS_KINDS` / `FOCUS_QUESTION_ID_MAX=64` / `FOCUS_ANCHOR_MAX=80` / `sanitize_focus()`；系统提示词新增第 8 条（明细同依据）、原第 8 条顺延为第 9 条；`USER_PROMPT_TEMPLATE` 新增 `【重点明细】` 段与 `DETAIL_NONE` 占位；`render_detail()`；`build_user_prompt(detail=)` |
| `backend/app/services/taifu/taifu.py` | `gather_sections()` → `gather_context(focus)`（返回段列表 + 明细）；`answer(detail=)`：白名单合并、`materials_used` 不含明细、响应回填 `detail` |
| `backend/app/routers/taifu.py` | `sanitize_focus(payload.focus)` → `gather_context(focus)`；空档案短路改为「段与明细都为空」 |
| `backend/app/schemas.py` | `TaifuFocus`（`kind` 故意是 `str`，非法值必须等同没传而不是 422）/ `TaifuDetailRef` / `TaifuChatRequest.focus` / `TaifuReply.detail` |
| `backend/tests/test_r82_taifu_deep_read.py` | 新建 17 条 |
| `frontend/src/api/types.ts` / `client.ts` | `TaifuFocus` / `TaifuDetailRef` / `TaifuReply.detail`；`taifuChat(question, page, focus)` |
| `frontend/src/lib/taifuBridge.ts` | 新建：`TAIFU_ASK_EVENT` / `askTaifu` / `normalizeFocus` / `onTaifuAsk`（CustomEvent 通道，浮窗在路由树之外） |
| `frontend/src/lib/taifuChat.ts` | `parseReplyBlocks()`（块级列表解析）与 `splitBold()`（行内 `**x**`） |
| `frontend/src/components/taifu/TaifuLauncher.tsx` | 焦点态（可见 / 可取消 / 路由变化清空）、「已读取明细」与「没读到」如实提示、`ReplyBody` 富文本渲染、每条回答复制按钮 |
| `frontend/src/components/report/WeaknessMap.tsx` | 每个薄弱组行内「问太傅：这条怎么补」（focus 第 N 组） |
| `frontend/src/components/report/ResumePointers.tsx` | 每条要点「问太傅」（focus 逐字原句） |
| `frontend/src/components/practice/WrongBookList.tsx` | 错题展开区「问太傅：这题为什么错」（focus 题 id） |
| `frontend/src/styles/base.css` | `.sc-taifu-focus` / `.sc-taifu-detail` / `.sc-taifu-points` / `.sc-taifu-copy` / `.sc-taifu-inline`（全部复用既有 token，无裸值，不改 DESIGN 尺寸） |
| `frontend/src/test/taifuChat.test.ts` | +5 条（parseReplyBlocks / splitBold） |
| `frontend/src/test/taifuBridge.test.ts` | 新建 5 条（node 环境下用 `EventTarget` 顶替 window） |
| `logs/teamflow/20261112-r82-taifu-deep-read/scripts/check.cjs` | 新建 8 组浏览器断言 |

## 2. 验收标准

| AC | 结果 | 证据 |
| --- | --- | --- |
| AC-1 焦点是闭集 | 通过 | `sanitize_focus` 拒绝未知 kind / 0 与负数 / `index=True`（bool 排除）/ 字符串序号 / 空·超长·含空格的题号 / 空·超长原句；`kind` 用 `str` 避免 422（`test_sanitize_focus_accepts_only_closed_shapes`） |
| AC-2 明细内容正确 | 通过 | weakness 明细含分组信息 / 题面 / 正确答案 / 你的结果 / 解析；attempt 强制要求有作答记录；resume 原句必须逐字命中正文（找不到即 `None`，不拿相似句硬凑）（`test_weakness_detail_*` / `test_attempt_detail_*` / `test_resume_detail_*`） |
| AC-3 有预算 | 通过 | 行数 ≤ 8、整行（含「· 你的结果」等后缀与省略号）≤ 160 字：`_fit()` 按整行预算截断，`clip()` 收紧到含省略号 ≤ limit（`test_detail_respects_line_and_row_budget`） |
| AC-4 白名单只扩到本次读到的 | 通过 | 有 resume 明细时 `/polish` 可引用；没读到时 `/polish` 被丢弃并计 `dropped_citations == 1`（`test_polish_is_only_citable_when_the_resume_detail_was_read`） |
| AC-5 无 focus 零变化 | 通过 | r77 浏览器断言 14 组全 PASS；无 focus 时提示词含 `DETAIL_NONE` 占位、`detail` 为 `null`、`materials_used` 不变（`test_chat_without_focus_is_unchanged`） |
| AC-6 三处入口可用 | 通过 | 医案薄弱组 / 医案简历要点 / 错题本展开行各能唤起并带对焦点（浏览器断言 3 组） |
| AC-7 焦点透明 | 通过 | 焦点条「正在问 · ×取消」；取消后请求 `focus === null`；同页锚点跳转后浮窗收起且焦点清空（浏览器断言 2 组） |
| AC-8 回答可读 | 通过 | `-` / `1.` 渲染成真实列表（`.sc-taifu-points li`），`**x**` 渲染成 `<strong>`；复制按钮存在（浏览器断言 1 组 + `test_r82` 渲染纯函数 5 条） |
| AC-9 不回归 | 通过 | 后端 834 条（833 passed / 1 skipped，0 失败）；前端 37 文件 474 测试、typecheck / lint 0 warning、build 通过；r77 浏览器断言全 PASS |

## 3. 验证命令与结果

```text
backend: ruff check app tests     → All checks passed
backend: pytest -q --junitxml     → 834 tests / 0 failures / 0 errors / 1 skipped（live smoke，恒 skip）
backend: pytest tests/test_r82_taifu_deep_read.py -q → 17 passed
frontend: typecheck / lint        → 通过，0 warning
frontend: npm test                → 37 test files / 474 tests passed
frontend: npm run build           → 通过（586.53 kB / gzip 238.57 kB）
```

真实浏览器（`node logs/teamflow/20261112-r82-taifu-deep-read/scripts/check.cjs`，Edge headless CDP + mock）：

```text
PASS 医案每一行薄弱组都有「问太傅」入口
PASS 点入口唤起浮窗：问题已填、焦点可见（事件循环）
PASS 请求带上焦点第 1 组；回答上方如实显示「已读取明细」
PASS 回答渲染成真实列表 + 粗体；每条回答有复制入口
PASS 取消焦点后这一问不带 focus（回到摘要问答）
PASS 简历改进要点也能唤起，焦点是那条原句所在位置
PASS 简历焦点的原句逐字送达（服务端据此在正文里定位）
PASS 同页锚点跳转后浮窗收起、焦点清空（不会带到下一条）
RESULT: PASS
```

回归：r77 的 14 组浏览器断言全 PASS。

## 4. 验收中发现并修复的问题

1. **「单行 160」差点是假的**。`brief.clip()` 的语义是「截到 limit 再加省略号」，最长 limit+1；
   且题面行要拼「· 你的结果：答错」后缀，只截内容再拼尾巴会顶到 170。新增 `deep_read.clip()`
   （含省略号 ≤ limit）与 `_fit()`（按整行预算截断），并用测试钉死。
2. **「已不在题库」的题不能编造**。薄弱组的样例题若被题库刷新删掉，明细只保留报告里的原始证据行
   （「题目 xxx 已不在题库 · Q1 · 2/10」），不回退成「题目不存在」整条丢弃 —— 组本身还有诊断价值。
3. **截图时机**。入口唤起后面板有 180ms 展开动画，动画中间截屏会拍到半透明面板
   （透出页面内容，看起来像布局 bug）；断言后补 350ms 再截，确认稳定帧无遮挡。
4. **本轮环境注意**：CI 沙箱的清理钩子会往 pytest stdout 注入错误并污染退出码，
   统计一律以 `--junitxml` 解析为准（见 §3），已记录进已知限制。

## 5. 与前几轮的关系

- **r79 锚点的反向**：r79 让太傅能指到报告某一行；r82 让页面能把「我在看这一行」告诉太傅。
  两个方向共用同一组锚点（`#weakness-N`），没有发明第二套编号。
- **白名单语义只做加法**：明细段与档案段同形，`sanitize_reply()` 一行没改 —— 「引用必须是本次真读到的」
  这条边界从 r77 一路守到 r82，只是「真读到的」多了一个按需取的明细段。
- **r81 的记忆边界未动**：焦点/明细只影响「读什么」，与长期记忆、线程摘要的「不是依据」分层无关。

## 6. 已知限制

- `question_attempts` 不存用户选项：错题明细只能说「你答错了、正确答案是 B」，说不出「你选了 C」。
- 明细只覆盖三类；教程正文在前端 TS、历史报告对比需要新查询口径，都不在本轮。
- 焦点是前端传的，服务端只校验闭集与数据归属，不保证用户「真的在看那一页」——但明细本身仍是服务端真值，
  不产生引用面扩大。
- 一次只读一条明细；提示词预算固定（明细 ≤8 行 / 1.5KB），不能靠传焦点塞更多材料。
