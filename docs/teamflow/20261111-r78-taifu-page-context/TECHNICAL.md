# r78 · 技术方案：页面上下文白名单与空档案回滚

> 依据 PRD `docs/teamflow/20261111-r78-taifu-page-context/PRD.md`。纯增量：无新表、无新端点、无新依赖。

## 1. 页面上下文为什么是闭集

用户提问里的指代（「这条」「这里」「它」）只有结合当前页面才有意义。但页面路径是**客户端可控输入**，
直接拼进提示词等于开了一个任意文本注入口。因此：

```python
PAGES: dict[str, tuple[str, str]] = {
    "/report": ("医案（诊断报告）", "短板、薄弱分组、简历改进要点与 7 天计划"),
    "/practice": ("演武（专项练习）", "按方向的练习题单与错题本"),
    ...  # 15 个已登记页面
}
```

`sanitize_page(raw)`：

1. 去掉 query 与 hash（`?run_id=` / `#tutorial-s1` 不参与判定）；
2. **空串 → `None`**（旧客户端 / 未传：不猜页面，也不默认成首页）；
3. `rstrip("/")`，空结果视为 `/`；
4. `/learn/<slug>` 归到 `/learn`（唯一的子路径：教程详情不逐章登记）；
5. 命中闭集 → 返回 `{path, label, hint}`；否则 `None`。

未命中时提示词写 `【当前页面】（未识别当前页面，按问题本身回答）`，而不是「假设在首页」。

## 2. 页面不是依据

`page` **不加入** `sanitize_reply` 的白名单：

```python
allowed = {section["href"]: section["label"] for section in sections}   # 只有档案段
```

理由：档案段是「服务端这次真读到的记录」，可以支撑结论；「你正在看的页面」只是一个位置，
拿它当依据会让回答看起来有出处、实际什么都没引用。系统提示词也补了一条：页面只用于消解指代，
不要因为用户在这一页就编造该页没有的数据。

## 3. 提示词结构（r77 → r78）

```
【档案】
[1] 最近诊断（href: /report）
- 生成时间：…
【当前页面】医案（诊断报告）（/report）—— 短板、薄弱分组、简历改进要点与 7 天计划
【最近对话】
用户：…
【问题】这条短板具体差在哪
```

`build_user_prompt(sections, history, question, page=None)` 是唯一拼装点；`page` 为 `None` 时给未识别文案。

## 4. 空档案回滚（前端）

r77 的发送流程是「先乐观插入用户消息 → 请求 → 追加回答」。空档案路径服务器返回 `reply: ""` +
`notice`，r77 只做了「不追加回答」，于是留下孤儿消息。r78 改为：

```ts
const reply = await api.taifuChat(text, location.pathname)
setMeta({ materials: reply.materials_used, dropped: reply.dropped_citations })
setNotice(reply.notice)
if (!reply.reply) {
  setThread((current) => current.filter((item) => item.id !== localId))  // 收回问句
  setQuestion(text)                                                       // 放回输入框
  return
}
```

与 r77 的失败路径（`catch`）保持同一套「不留半条对话」口径：区别只是 `catch` 还会显示错误原因，
空回答显示的是服务端的 notice。

## 5. 空档案出口（前端）

```tsx
{meta !== null && meta.materials === 0 ? (
  <p className="sc-taifu-shortcuts">
    <Link to="/">去上传简历</Link>
    <Link to="/practice">先做几道练习</Link>
    <Link to="/report">去看诊断报告</Link>
  </p>
) : null}
```

只在该次回答**真实读过 0 段**时出现，且每次新提问会重置 `meta`，不会常驻。
样式沿用 r77 的 chip 语言（`--border-strong` + `--radius-pill` + `--accent`），只追加 `.sc-taifu-shortcuts` 一条规则组。

## 6. 测试

- 后端（新增到 `tests/test_r77_taifu.py`，同一模块同一能力面）：
  - `sanitize_page` 闭集：`/report?run_id=r1#weakness` → `/report`；`/learn/<slug>#…` → `/learn`；
    `/evil`、空串、`/report/../settings` → `None`；
  - 提示词：带 page 时含 `【当前页面】医案（诊断报告）（/report）`，不带时含未识别文案；
  - 端点：请求带 `page: "/report"` 时，模型收到的提示词含该行。
- 前端：无新增纯函数，靠真实浏览器脚本覆盖（页面参数、空档案回滚、快捷入口）。

## 7. 已知限制

- 页面上下文只影响「指代消解」，不改变档案内容：在报告页问「这条」仍要求报告已在档案摘要里（首段就是最新报告）。
- 引用仍到页级；要引用到具体薄弱分组需要报告页支持 `#weakness-<key>` 锚点。
- 空档案出口固定三个入口，未按缺口类型动态排序（例如只缺报告时仍显示「去上传简历」）。
