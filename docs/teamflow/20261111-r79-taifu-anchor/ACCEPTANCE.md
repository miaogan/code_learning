# r79 · 验收报告：引用指到报告里的具体那一条

> 结论：PRD 中 6 条验收标准全部满足。纯增量（无新表、无新端点、无新依赖、无新请求）：
> 后端 1 个纯函数 + 白名单合并 + 2 条测试，前端 1 个纯函数 + 1 段定位副作用 + 1 条样式组。
> r75–r79 五轮**仍未提交**，等提交指令。

## 1. 交付内容

| 文件 | 改动 |
| --- | --- |
| `backend/app/services/taifu/brief.py` | `ANCHOR_LABEL_MAX = 40`、`_weakness_anchors()`、`_section(anchors=...)`；薄弱行末尾写 `→ /report#weakness-N`；`build_sections` 把锚点挂到报告段 |
| `backend/app/services/taifu/policy.py` | `sanitize_reply` 白名单并入段内锚点（`setdefault`，段标签优先）；系统提示词第 2 条改为「段标题或行内标注的 href 都可逐字抄写」 |
| `backend/tests/test_r77_taifu.py` | +2（`test_report_section_exposes_weakness_anchors`、`test_sanitize_reply_accepts_anchor_but_rejects_out_of_range`），文件内 21 条 |
| `frontend/src/lib/coach.ts` | `weaknessAnchorIndex(hash)`（`#weakness-<n>` → n，其余 `null`） |
| `frontend/src/components/report/WeaknessMap.tsx` | 行 `id="weakness-N"`；读 hash → 折叠区先展开 → `scrollIntoView({block:'center'})`；`is-anchored` 行高亮 |
| `frontend/src/components/taifu/TaifuLauncher.tsx` | 收起依赖改为 `[location.pathname, location.hash]` |
| `frontend/src/styles/base.css` | `.sc-weak-table tr:target, tr.is-anchored` 一组规则（r79 段） |
| `frontend/src/test/coach.test.ts` | +2（锚点解析：合法形状 / 8 种非法形状一律 `null`） |
| `logs/teamflow/r77-taifu-chat/scripts/check.cjs` | 新增 `mode: 'anchor'` 场景与两条断言（同页锚点、跨折叠定位） |

## 2. 验收标准

| AC | 结果 | 证据 |
| --- | --- | --- |
| AC-1 引用能落到行 | 通过 | 报告段 `anchors == [{"href": "/report#weakness-1", "label": "最近诊断 · AI 工程 · 部署与推理"}]`，摘要行含同一 href（`test_report_section_exposes_weakness_anchors`） |
| AC-2 只白名单内的锚点有效 | 通过 | `#weakness-1` 通过；`#weakness-9`（摘要只写 1 组）与 `/report#evil` 均被丢弃并计 `dropped_citations`（`test_sanitize_reply_accepts_anchor_but_rejects_out_of_range`） |
| AC-3 段级引用不回归 | 通过 | 白名单先写入段 href 再 `setdefault` 锚点：`/report` 仍是「最近诊断」；r77 的丢弃计数用例断言值未变 |
| AC-4 跨折叠也能看见 | 通过 | 浏览器实测：从 `/report` 点引用 → 表格从 8 行变 9 行（自动展开）→ `#weakness-9` 行的 `top/bottom` 落在 `[0, innerHeight]` 内 |
| AC-5 用户认得出是哪条 | 通过 | 同一行 `classList.contains('is-anchored') === true`；截图（`report-anchor.png`）可见淡底 + 左侧竖条 |
| AC-6 不回归 | 通过 | 后端 797 passed / 1 skipped（798）、前端 36 文件 464 测试、typecheck / lint 0 warning、build 通过；浏览器 10 组断言全 PASS（含 r77 两步清空、引用跳转、刷新恢复、390px 无横向滚动，r78 空档案回滚与三个出口） |

## 3. 验证命令与结果

```text
backend: ruff check app tests   → All checks passed
backend: pytest -q              → 797 passed / 1 skipped（798 条，0 失败；见 §4.4 关于 exit code 的说明）
backend: pytest tests/test_r77_taifu.py -q → 21 passed，exit 0
frontend: typecheck / lint      → passed，0 warning
frontend: npm test              → 36 test files / 464 tests passed（r78 时为 462，+2）
frontend: npm run build         → passed，index.js 580.45 kB（gzip 236.61 kB）/ index.css 170.20 kB（gzip 23.99 kB）
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
RESULT: PASS
```

## 4. 验收中发现并修复的问题

1. **`:target` 在站内跳转下不生效**。初版只靠 `tr:target` 做高亮，直接粘贴 URL 没问题；
   但引用点进来是路由跳转（`pushState`），Chrome 不重算 `:target` ——
   于是「行展开了、也滚过去了，就是没有高亮」，看起来像定位失败。
   改为双通道：显式 `is-anchored` 状态类承担站内跳转，`:target` 保留给直链。
2. **浮窗在同页锚点跳转后不收起**。原收起逻辑只比 `pathname`，`/report` → `/report#weakness-9`
   不算变化，面板继续盖住刚滚到的那一行。依赖里补 `location.hash`。
3. **系统提示词把锚点挡在门外**。r77 第 2 条写「只能从每段标题后的 href 里挑」，
   而锚点给在行内 —— 模型按字面理解就不会用。改成「段标题后的页面，或行内标注的具体位置」，
   同时保留「不得自造链接、锚点或页面」。
4. **后端全量的 exit code 受沙箱清理钩子影响**。最后一轮 `pytest -q` 结束时
   `[safe-delete] SAFE_DELETE_BULK_GUARD_ERROR`（`EPERM mkdir …\.lock`）让进程以 1 退出，
   并把汇总行顶掉。按符号统计为 797 点 + 1 `s`、无 `F`/`E`；单独跑 `tests/test_r77_taifu.py`
   仍是 `exit=0`、21 passed。这是环境问题，不是用例失败。
5. **CDP 脚本里 `.pop()` 改过头**。为断言锚点取「最后一条引用」，连带把更早的
   「点第一条引用跳 `/report`」改成取最后一条（拿到 `/practice`）而误红。
   已收敛为：只有锚点场景用 `.pop()`，页级跳转仍取 `.querySelector('.sc-taifu-cite')`。

## 5. 顺带修正

- **后端进程跑的是旧代码**：本轮开始时 `8000` 上的 uvicorn 早于 r77 启动，
  `/openapi.json` 里没有 `taifu` 路由（`/api/taifu/thread` 返回 `NOT_FOUND`）。
  已用 `backend/.venv` 重启并确认 `['/api/taifu/chat', '/api/taifu/thread']` 已注册。
  浏览器脚本本身 mock 了 `/api/*`，不受影响，但手工联调会被这个假象误导。

## 6. 已知限制

- `weakness-N` 是表格行号而非稳定 ID：报告重新生成、分组重排后同一 N 可能指向邻近分组（不会指向空行）。
- 只有报告页有锚点；练习、画像等页的引用仍是页级。
- 锚点粒度是分组，无法引用到某道具体错题（摘要里没有逐题记录）。
- 长线程仍只取最近 6 条原句进提示词，十几轮之后上下文会漂（r78 已列为后续项，尚未处理）。
