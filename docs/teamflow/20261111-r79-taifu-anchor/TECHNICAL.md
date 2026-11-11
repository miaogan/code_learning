# r79 · 技术方案：段内锚点与报告页定位

> 依据 PRD `docs/teamflow/20261111-r79-taifu-anchor/PRD.md`。纯增量：无新表、无新端点、无新依赖、无新请求。

## 1. 锚点从哪来：服务端算，客户端抄

r77/r78 的白名单是「这次真读到了什么」的投影。锚点沿用同一口径 —— **由服务端从报告里算出来**，
不是让模型拼、也不是让前端传：

```python
def _weakness_anchors(report: Report) -> list[dict[str, str]]:
    """薄弱分组的锚点白名单（`/report#weakness-N`，N 与报告页表格行号一致）。

    只取前 `MAX_WEAK` 组：摘要里没写出来的分组，模型也不该引用。
    """
    anchors: list[dict[str, str]] = []
    for index, item in enumerate((report.weakness_map or [])[:MAX_WEAK], start=1):
        anchors.append({
            "href": f"/report#weakness-{index}",
            "label": f"最近诊断 · {clip(item.point, ANCHOR_LABEL_MAX)}",
        })
    return anchors
```

`MAX_WEAK = 5` 与摘要里写出的行数**同源**（`_report_lines` 用同一个常量枚举），
所以「能被引用的分组」严格等于「模型看到的分组」—— 不会出现「引用了档案里没写的那一条」。

`_section()` 增加可选 `anchors` 参数，段落结构从 4 键变 5 键：

```python
{"key": "report", "label": "最近诊断", "href": "/report",
 "lines": [...], "anchors": [{"href": "/report#weakness-1", "label": "..."}]}
```

## 2. 模型怎么知道有这个锚点

两处一起给：

1. **行内标注**（主要通道）：摘要每一行末尾直接写出来，模型可以逐字抄。
   ```
   薄弱：AI 工程 · 部署与推理 · 进阶 · 错误率 60%（3/5）→ /report#weakness-1
   ```
2. **系统提示词第 2 条**（消歧）：r77 原文是「只能从【档案】每段标题后给出的 href 里逐字挑选」，
   锚点出现在行内、不在标题后，模型会以为不能用。改为：

   > 引用只能从【档案】里逐字抄写出现过的 href：段标题后的页面（如 /report），
   > 或行内标注的具体位置（如 /report#weakness-2）。不得自造链接、锚点或页面。

「不得自造」保留 —— 允许抄写 ≠ 允许发明。

## 3. 白名单：段与锚点合并，段优先

```python
allowed = {section["href"]: section["label"] for section in sections}
for section in sections:
    for anchor in section.get("anchors") or []:
        href = str(anchor.get("href") or "")
        if href:
            # 段级 href 优先：同一 URL 若两者都有，保留段标签（更短、更稳）。
            allowed.setdefault(href, str(anchor.get("label") or href))
```

用 `setdefault` 而不是 `update`：万一某段的 href 恰好也是一个锚点，保留**段标签**
（「最近诊断」而不是「最近诊断 · 部署与推理」），因为用户点进去的第一落点是页面而不是某一行。

越界锚点不需要特判：`#weakness-9` 只要不在 `anchors` 里就落不进 `allowed`，
走 r77 已有的「丢弃并计数」路径（`dropped_citations`）。

## 4. 报告页定位（前端）

`WeaknessMap` 读 `location.hash`，只认 `#weakness-<n>`：

```ts
// lib/coach.ts（纯函数，可单测）
export function weaknessAnchorIndex(hash: string): number | null {
  const match = /^#weakness-(\d+)$/.exec(hash)
  if (match === null) return null
  const index = Number(match[1])
  return Number.isInteger(index) && index >= 1 ? index : null
}
```

`#weakness-0`、`#weakness-x`、`#practice`、空串一律 `null` —— **不猜、不跳到第一行**：
猜错比不跳更糟，用户会以为那条就是他问的。

定位逻辑（先展开、后滚动）：

```tsx
useEffect(() => {
  const target = weaknessAnchorIndex(location.hash)
  setAnchored(target)
  if (target === null || items === null) return
  if (!expanded && target > WEAKNESS_FOLD_LIMIT) {
    setExpanded(true)          // 目标在折叠区：先展开，下一次副作用再滚
    return
  }
  const timer = window.setTimeout(() => {
    document.getElementById(`weakness-${target}`)?.scrollIntoView({ block: 'center' })
  }, 0)
  return () => window.clearTimeout(timer)
}, [expanded, items, location.hash])
```

- 依赖 `items`：直接粘贴 URL 打开时报告还在加载（`items === null`），数据到位后副作用会再跑一遍；
- 依赖 `expanded`：展开是会引发第二轮渲染的，第一轮不滚（那时行还不存在）；
- `block: 'center'` 而不是默认的 `start`：行上方就是表头，`start` 会把行贴到视口最顶端，
  看起来像「只露了半行」。

## 5. 高亮为什么不能只靠 `:target`

`:target` 是浏览器按**地址栏 fragment** 匹配的伪类。直接粘贴 `…/report#weakness-9`
时它是生效的；但站内跳走走的是 React Router → `history.pushState`，
Chrome **不会**因此重算 `:target`（实测 `row.matches(':target') === false`，行已展开、已滚动，
只是不高亮）。

因此高亮做成两条通道，CSS 同时命中：

```css
.sc-weak-table tr:target,
.sc-weak-table tr.is-anchored { /* 淡底 + 左侧竖条 */ }
```

- `.is-anchored`：由 `WeaknessMap` 的 `anchored` 状态给出，覆盖站内跳转；
- `:target`：覆盖直接打开带锚点的 URL、以及关闭 JS 的极端情况。

## 6. 浮窗收起时机补上 hash

`TaifuLauncher` 原来的「路由变化即收起」只比 `location.pathname`。从 `/report` 点
`/report#weakness-9` 时 pathname 没变，面板不会收 —— 用户点完引用，浮窗还盖在报告上，
正好压住刚滚过去的那一行。改为比 `[location.pathname, location.hash]`。

## 7. 测试

后端（`tests/test_r77_taifu.py`，同一能力面不另开文件）：

- `test_report_section_exposes_weakness_anchors`：段里带 `#weakness-1`，且摘要行内含该 href；
- `test_sanitize_reply_accepts_anchor_but_rejects_out_of_range`：`#weakness-1` 通过、
  `#weakness-9` / `/report#evil` 丢弃。

前端（`src/test/coach.test.ts`）：

- `#weakness-1` / `#weakness-9` / `#weakness-120` → 对应数字；
- `''`、`#`、`#practice`、`#weakness-`、`#weakness-x`、`#weakness-0`、`#weakness--1`、`#weakness-1.5` → `null`。

真实浏览器（`logs/teamflow/r77-taifu-chat/scripts/check.cjs`）：
把第二轮问答切到 `mode: 'anchor'`（返回 `citations: ['/report#weakness-9']`），
断言「地址栏带 `#weakness-9` → 展开到 9 行 → 该行 `is-anchored` → 行完整在视口内」。

## 8. 已知限制

- `weakness-N` 是**表格行号**，不是稳定 ID：报告重新生成、分组重排后，同一个 N 指向的可能不是同一条。
  引用只在「当前这份报告」内有效，过期引用会指到邻近分组（不会指到不存在的行，因为越界会展开越界）。
- 只有报告页有锚点。练习、画像等页的引用仍是页级。
- 锚点粒度是分组，不是单题：摘要里没有逐题记录，模型也无法引用到具体某道错题。
