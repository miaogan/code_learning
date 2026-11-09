# r40 · 真机测试清单（移动端可用性收口）

- 对应需求：`docs/teamflow/20261108-r40-mobile-usable/`（TECH-CHANGE / DESIGN-MOBILE / QA-REPORT）
- 覆盖改动：`index.html`（viewport、theme-color）、`tokens.css`（≤640 字号）、`base.css`（r40 段 §0–§12）、`Composer.tsx`、`UploadPage.tsx`
- 目标视口：**360 / 390 / 430**；桌面 ≥1024 本轮零改动，只需回归不进本清单
- 结论口径：本清单**只判移动端**；桌面表现请直接看 QA-REPORT §1 四道门禁

## 0. 怎么用

1. **一次只测一台设备**，每台设备从「§1.5 清零」开始，按 §2 → §3 → §4 的顺序走。
2. 每项结果只允许四种：`PASS` / `FAIL` / `BLOCKED`（环境没跑起来，测不了）/ `预期不明`（记录实际现象，不算通过也不算失败）。
3. 优先级：**P0 任何一项 FAIL 即阻塞发布**；P1 记缺陷后仍可发；P2 只做观察记录。
4. 量化项优先用 §1.6 的片段取数，**不要凭肉眼估**；取不到数（无 Mac 调试 iOS）就在该项标注「目测 + 预期不明」。
5. §6 是可直接勾选的空白清单，边测边勾；§7 记机型/系统/结果。

---

## 1. 环境与入口（一次性，约 10 分钟）

### 1.1 起服务（PC，PowerShell）

```powershell
# 终端 A：后端（backend/）
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# 自检：http://127.0.0.1:8000/health 返回 ok，且 ai_configured = true（否则画像/面试/报告都跑不出来）

# 终端 B：前端（frontend/）—— 必须带 --host
npm run dev -- --host
```

- `--host` 是必需的：Vite 默认只监听 localhost，手机访问不到。
- 后端**不需要**暴露到局域网：手机只跟 Vite 通信，`/api`、`/health` 由 Vite 代理到 `127.0.0.1:8000`（`frontend/vite.config.ts`）。
- 启动后 Vite 会打印两行地址，记下 `Network:` 那一行，形如 `http://192.168.1.23:5173/`。

### 1.2 让手机连上（三个常见坑）

| 步骤 | 操作 | 判定 |
|---|---|---|
| 1 | PC 上取局域网 IP：`ipconfig`，看「无线局域网适配器 WLAN」下的 `IPv4 地址`（形如 `192.168.x.x`） | 拿到一个非 `127.0.0.1` 的地址 |
| 2 | 手机与 PC **连同一个 Wi‑Fi**，手机浏览器打开 `http://<该 IPv4>:5173` | 出现登录页（不是浏览器错误页） |
| 3 | 打不开时先查监听：`Get-NetTCPConnection -LocalPort 5173 -State Listen` | `LocalAddress` 应为 `0.0.0.0` 或 `::`，不是 `127.0.0.1` |

- **防火墙**：首次 `--host` 启动时 Windows 会弹「是否允许 Node.js 访问网络」，必须勾**专用网络**并允许。没弹窗/误点拒绝时，管理员 PowerShell 补一条：
  ```powershell
  New-NetFirewallRule -DisplayName "Vite 5173 r40" -Direction Inbound -Protocol TCP -LocalPort 5173 -Action Allow -Profile Private
  ```
- **路由器 AP 隔离**：公司/酒店 Wi‑Fi 常开「AP 隔离/访客网络」，设备间互不可见 → 手机能上网但打不开 PC。绕法：PC 连手机热点，再用热点网段的 PC IP。
- 手机打开后卡在「正在加载…」→ 是 `/api/me` 没通：确认后端在跑、且 Vite 代理目标是 `127.0.0.1:8000`。

### 1.3 账号与数据（登录不开放自助注册）

```powershell
# backend/ 下执行；密码只打印一次，立刻记下
python -m app.admin_cli create-user --email r40-empty@local.dev --name 空态 --mode shared
python -m app.admin_cli create-user --email r40-full@local.dev  --name 有数据 --mode shared
```

- `--mode shared` 表示用服务端 `.env` 的 Key（本机 `ai_configured: true` 即满足）；若要用自己的 Key 走 `--mode own`，在「设置」页填。
- 需要**两套数据状态**：
  - **空态账号**（`r40-empty`）：不上传任何东西，用于验证空态文案 / 免简历出口 / 禁用态。
  - **有数据账号**（`r40-full`）：按 README 走一条完整链路 —— 上传 → 画像 → 面试 2–3 轮 → 笔试 → 报告 → 历史 → 润色。
- 注意 `localhost:5173`（PC）与 `192.168.x.x:5173`（手机）是**两个不同 origin**：登录态、localStorage、sessionStorage 都不共享。手机端必须**单独登录一次**，不要以为 PC 登录过手机就登上了。

### 1.4 素材准备（放在手机能选到的地方：iCloud/文件 App、Android 下载目录、微信文件传输助手）

| 文件 | 用途 | 期望结果 |
|---|---|---|
| `ok.pdf`（正常 1–2 页简历，含英文技能名） | 主路径上传 | 上传成功 → 进入生成阶段 |
| `ok.docx`（正常简历） | 验证 DOCX 走通 | 同上 |
| `ok.txt`（纯文本简历） | 验证 TXT 走通 | 同上 |
| `big.pdf`（>10MB，任意大文件改后缀即可） | 超限分支 | 「文件超过 10MB，请压缩或分卷」，**无重试入口** |
| `empty.pdf`（0 字节） | 空文件分支 | 「文件内容为空，请换一份」 |
| `bad.png` | 不支持格式 | 「仅支持 PDF / DOCX / TXT 文件」 |
| `encrypted.pdf`（加密/扫描件） | 后端解析失败分支 | 中文失败原因，不是白屏/英文报错堆栈 |
| 超长文件名（≥60 字符，含中文/空格） | 断行与卡片布局 | 文件名换行，不撑宽页面 |
| 含长 URL / 长英文标识符的简历 | `overflow-wrap: anywhere` | 长串在容器内折行，不横向溢出 |

### 1.5 每轮开始前的清零动作

**要清的键**（全部是本站 origin 下的本地存储）：

| 存储 | 键 | 作用 |
|---|---|---|
| localStorage | `sc.flow`、`sc.flow.<userId>` | 五步流程完成态（决定导航 ✓ 与引导弹框） |
| localStorage | `sc.learn`、`sc.learn.<userId>` | 教程阅读进度 |
| localStorage | `weekplan:<userId>:<reportId>` | 报告周计划打卡 |
| sessionStorage | `sc.resumePrompted` | 「未上传简历」弹框只弹一次标记 |
| sessionStorage | `report:run_ids:<...>` | 报告页缓存 |

**清法（按设备选一种）**：

| 设备 | 操作 |
|---|---|
| Android Chrome | 地址栏锁形图标 → 网站设置 → **清除数据**（或 `chrome://settings/siteData` 搜 IP 后删除） |
| iOS Safari | 设置 → Safari → 高级 → 网站数据 → 搜 `192.168` → 左滑删除；或 设置 → Safari → 清除历史记录与网站数据（清全部站点） |
| 鸿蒙浏览器 | 设置 → 隐私/网站数据 → 按站点清除 |
| 微信内置 | 我 → 设置 → 通用 → 存储空间 → 清理缓存（会连登录态一起清，需重新登录；微信内按站点清数据不方便，建议优先在系统浏览器上测，微信只做兼容回归） |
| 任意设备（快捷） | 开**无痕/隐私窗口**：关闭即清；无痕下登录态只在本次会话有效 |
| 有调试线（推荐） | Android：USB + `chrome://inspect` → 选中页面 → Console 执行 `localStorage.clear(); sessionStorage.clear(); location.reload()` |

- **坑**：只清 localStorage 不清 cookie → 还是登录态，会看到上一个账号数据；只清缓存不清 localStorage → 流程 ✓ 残留，空态测不出来。**两者都要清**。
- **坑**：换了访问地址（`localhost` ↔ IP ↔ 热点新 IP）等于换了 origin，全是新数据，别误判成「数据丢了」。

### 1.6 真机取数片段（Console 直接粘贴）

**怎么打开 Console**：Android → USB 连 PC，Chrome 打开 `chrome://inspect`；iOS → Mac 上 Safari 开发菜单 → 设备 → 页面。无 Mac 时 iOS 只能截图目测，相关量化项按「预期不明」记。

**① 安全区实测**（`env()` 生效时非 0）

```js
(() => {
  const d = document.createElement('div')
  d.style.cssText = 'position:fixed;top:0;left:0;width:0;height:0;padding-top:env(safe-area-inset-top);padding-bottom:env(safe-area-inset-bottom)'
  document.body.appendChild(d)
  const cs = getComputedStyle(d)
  console.log('safeTop=', cs.paddingTop, 'safeBottom=', cs.paddingBottom)
  d.remove()
})()
```

**② 触控目标扫描**（应返回空数组）

```js
(() => {
  const sel = '.sc-btn:not(.is-sm), .sc-chip.is-clickable, .sc-lab-skill, .sc-topbar-link'
  const small = [...document.querySelectorAll(sel)]
    .map((e) => ({ cls: e.className, w: Math.round(e.getBoundingClientRect().width), h: Math.round(e.getBoundingClientRect().height) }))
    .filter((x) => x.h < 44)
  console.table(small)
  return small
})()
```

**③ 横向越界扫描**（`overflow-x: clip` 会静默裁掉越界内容，页面"不能左右滑"不等于没问题）

```js
(() => {
  const vw = document.documentElement.clientWidth
  const list = [...document.querySelectorAll('body *')]
    .filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.right > vw + 1 })
    .map((e) => ({ el: e.tagName + '.' + (e.className || ''), over: Math.round(e.getBoundingClientRect().right - vw) }))
  console.table(list)
  return list
})()
```

**④ 键盘遮挡判定**（聚焦作答框后 1 秒执行）

```js
(() => {
  const vv = window.visualViewport
  const input = document.querySelector('.sc-iq-input')
  const btn = [...document.querySelectorAll('.sc-iq-composer .sc-btn')].pop()
  const r = input.getBoundingClientRect()
  console.log({
    innerH: window.innerHeight,
    vvH: vv && Math.round(vv.height),
    vvOffsetTop: vv && Math.round(vv.offsetTop),
    inputTop: Math.round(r.top),
    inputBottom: Math.round(r.bottom),
    coveredBy: Math.round(r.bottom - ((vv?.offsetTop ?? 0) + (vv?.height ?? window.innerHeight))), // ≤0 = 未被遮挡
    btnBottom: btn ? Math.round(btn.getBoundingClientRect().bottom) : null,
  })
})()
```

**⑤ 首列标签是否被裁/换行**

```js
(() => {
  return [...document.querySelectorAll('.sc-lab-tok')].slice(0, 6).map((row) => {
    const k = row.querySelector('.sc-lab-tok-k')
    const r = k.getBoundingClientRect()
    return { text: k.textContent, w: Math.round(r.width), h: Math.round(r.height), ls: getComputedStyle(k).letterSpacing }
  })
})()
```

判定：`w ≤ 54`、`h = 16`（单行；`32` 说明换行了）、`ls = 0.44px`（11px × 0.04em）。

**⑥ 深色与裁切兜底是否生效**

```js
(() => ({
  bg: getComputedStyle(document.documentElement).backgroundColor,   // 期望 rgb(7, 8, 9)
  colorScheme: getComputedStyle(document.documentElement).colorScheme, // 期望 dark
  overflowX: getComputedStyle(document.documentElement).overflowX,  // ≤1023 期望 clip
}))()
```

---

## 2. 五个高风险项（静态推导覆盖不到，逐条展开）

### RC-01 · 软键盘避让时序（P0，阻塞发布）

- 依据：`index.html` 加了 `interactive-widget=resizes-content`（Chromium/ArkWeb 收缩布局视口）；iOS Safari 不认该值，由 `Composer.tsx` 的 `visualViewport` 遮挡判定兜底（只在被遮挡时 `scrollBy` 一次，260ms 后执行）。
- 前置：`r40-full` 账号已进入面试页，有一轮可作答；手机**关闭**自动旋转锁定（竖屏）。

| 步骤 | 操作 | 预期结果 |
|---|---|---|
| 1 | 面试页点作答框，等键盘完全弹出（约 1s） | 键盘不覆盖作答框；「提交回答」按钮完整可见 |
| 2 | 执行片段 ④ | `coveredBy ≤ 0`；`btnBottom ≤ innerH`（iOS 上以 `vvOffsetTop + vvH` 为准） |
| 3 | 保持键盘弹出，往下滑页面 | 能滑到页面底部；吸底输入区不跳动、不与键盘重叠 |
| 4 | 滚到最后一轮，看该轮评分区 | 评分区（分数 + 点评）完整出现在输入区上方，不被粘性区压住（`--iq-scroll-pad` 172 vs 实际输入区 160） |
| 5 | 键盘弹出状态下点「提交回答」 | 点击生效，评分开始；键盘收起后视口恢复正常高度 |
| 6 | 收起键盘再聚焦一次 | **不出现**无谓的整页跳动（兜底只在被遮挡时才滚动） |

失败时先查什么：

1. 确认 meta 真的生效：`document.querySelector('meta[name=viewport]').content` 里有 `interactive-widget=resizes-content`。
2. 看 `window.visualViewport` 是否存在（iOS 12+ 有）；`coveredBy` 为正但页面没滚 → 兜底可能被 `matchMedia('(max-width: 1023px)')` 判为非移动（横屏/大屏平板会走到这）。
3. 整页跳动而非"贴上去" → 检查是否有别的元素在键盘弹出时改变高度（吸底区 min-height 固定 156，实际 160）。
4. 键盘盖住「提交回答」但作答框可见 → 看 `.sc-iq-composer` 的 `padding-bottom` 是否含 `env(safe-area-inset-bottom)`（base.css 约 L2836）。
5. 微信内置浏览器（X5/XWeb）对 `interactive-widget` 的支持**未知**，按实际记录；只要片段 ④ 的 `coveredBy ≤ 0` 就算通过。

### RC-02 · 安全区实际像素（P0）

- 依据：`viewport-fit=cover` 由 r21 引入；顶栏高度 = `--topbar-h + env(safe-area-inset-top)`，吸底输入区底部 padding 含 `env(safe-area-inset-bottom)`。

| 步骤 | 操作 | 预期结果 |
|---|---|---|
| 1 | 在**有刘海/灵动岛**的 iPhone 打开首页，执行片段 ① | `safeTop` 明显非 0（按机型记实际值） |
| 2 | 看顶栏 | 品牌名与右侧账号不被刘海/状态栏遮住；顶栏底边发丝线完整 |
| 3 | 进面试页滑到底 | 吸底输入区不被手势条压住；输入区内部仍留约 12 的呼吸（safe-area 只加在底部 padding） |
| 4 | 横屏一次（若体验允许） | 左右安全区由浏览器自身处理；顶栏不压刘海；此项**预期不明，按实际记录** |
| 5 | 在无刘海小屏（iPhone SE / 老 Android）执行片段 ① | 两项均为 `0px`；顶栏与输入区外观与设计基线一致（不能因为 env=0 就少一截留白） |

失败时先查什么：

1. `safeTop` 恒为 0 但有刘海 → 先确认 `meta[name=viewport]` 含 `viewport-fit=cover`（缺它 `env()` 直接为 0）。
2. 顶栏高度对但内容被遮 → 检查是 `height` 与 `padding-top` 是否**同时**让位（只加高度不加 padding 会把内容顶进刘海）。
3. 手势条压住输入区 → `.sc-iq-composer` 的 `padding-bottom` 是否被后续规则覆盖（用 Console 看 computed `padding-bottom`）。
4. Android 手势条机型 `safeBottom` 可能为 0（系统自绘）→ 这属平台差异，按实际记录，不判 FAIL。

### RC-03 · 360 宽 `PRIMARY` 首列是否被裁（P0，仅在 360 设备上可判）

- 依据：`tokens.css` 把 ≤640 的 `--fs-nano` 抬到 11px（原 9.5），等宽下 `"PRIMARY"` 7 字符 ≈ 46.2；原字距 0.12em 会到 55.4 顶破 `.sc-lab-tok` 首列 54，故 `base.css` r40 §12 把 ≤1023 的 `.sc-lab-tok-k` 字距放宽到 0.04em（49.3）。

| 步骤 | 操作 | 预期结果 |
|---|---|---|
| 1 | 视口宽 **360**（设备或 DevTools 360×800）打开有连续 5 段流程/指标条的页面（首页流程条、报告指标、画像读数） | 每行首列标签完整显示，不贴边、不截断 |
| 2 | 执行片段 ⑤ | 每项 `w ≤ 54`、`h = 16`、`ls = 0.44px` |
| 3 | 看中文标签（如「方向」「掌握」） | 同样单行；中文字距被放宽后仍居中不歪 |
| 4 | 换成 390 / 430 再看一遍 | 表现不退化（列宽不变，标签更宽松） |

失败时先查什么：

1. `h = 32` → 换行了：先看实际 `font-size` 是否真为 11px（≤640 的 token 是否被后续规则覆盖）。
2. `ls` 不是 `0.44px` → r40 §12 没落在生效范围（该段在 `max-width: 1023px` 内，桌面视口看不到）。
3. 被截断（`w` 接近 54 但文字缺笔画）→ 量父容器 `.sc-lab-tok` 的首列 `grid-template-columns` 是否为 `54px minmax(0,1fr) …`；若某页把列写死更窄，属该模块问题，不是 token 问题。
4. 首列没破但**其他列**挤爆 → 检查 `.sc-lab-tok` 的 `58px / 34px` 两列内容是否超长（本清单不覆盖新内容，按实际记录）。
5. **手头没有 360dp 真机**时：用桌面 DevTools 360×800 验收排版，并标注「非真机」；不要用「改系统显示大小」代替，它不改 CSS 视口宽。

### RC-04 · 画像 / 报告有真实数据时的窄屏（P0，需 `r40-full` 账号）

- 依据：QA-REPORT 明确未覆盖「有数据的长文本、表格、课程卡」——本地验证只跑了空态与结构规则。

| 步骤 | 操作 | 预期结果 |
|---|---|---|
| 1 | 用 `r40-full` 登录手机端，进画像页 | 维度卡单列；每卡的长 `sourceQuote` 正常折行，无横向溢出（片段 ③ 空数组） |
| 2 | 画滚到技能标签区 | 每个标签高度 ≥44；长英文技能名折行；点选反馈正常 |
| 3 | 看「本次合并」摘要条 | 360 下不被挤压成两行，信息完整 |
| 4 | 进报告页，滚过指标条 / 弱项表 / 提升路线 / 课程卡 | 单列排布；弱项表在 ≤640 已重排；长文本与数字不撑宽 |
| 5 | 在报告页长按选中一段文本、滚动 | 选中与滚动互不打架；不会因长按触发链接跳转 |
| 6 | 报告页滚到底，点周计划某一天打卡 | 点击生效，刷新后仍保留（`weekplan:<userId>:<reportId>`） |
| 7 | 切到后台再回来（不刷新） | 报告仍在（sessionStorage 缓存按账号分区） |

失败时先查什么：

1. 溢出（片段 ③ 有结果）→ 先定位到具体元素，再看该模块自身有没有 `white-space: nowrap`、固定 `width`、`min-width`、`grid` 写死列宽；**不要**因此去掉 `overflow-x: clip` 兜底。
2. 长串不断行 → 确认它是否在 `.sc-page` 之外（兜底只作用于 `.sc-page` 子树）。
3. 表格列被压成 1 字宽 → 该表在 ≤640 应已"卡片化"，检查对应断点规则是否被新类名绕过。
4. 打卡不持久 → 无痕窗口 / 隐私模式下 localStorage 会被禁；换普通窗口复测。
5. 数据生成失败 → 先看 `/health` 的 `ai_configured`，以及设置页 My Key 是否为空（`--mode shared` 才走服务端 Key）。

### RC-05 · `overflow-x: clip` 静默裁切的排查（P0，方法项）

- 依据：`html, body { overflow-x: clip }`（≤1023）**不再有横向滚动条**，越界内容会被直接裁掉——这正是它的副作用。判据必须从「能不能滑」改成「有没有元素越界」。

| 步骤 | 操作 | 预期结果 |
|---|---|---|
| 1 | 对 8 个页面各执行一次片段 ③ | 每页都返回**空数组** |
| 2 | 有结果时，看 `over` 值 | 通常 1–2px 属亚像素误差（可忽略，记 P2）；> 4px 必须定位 |
| 3 | 对越界元素检查 computed 样式 | 找出 `nowrap` / 固定宽 / `min-width` / `grid` 死列宽中的真凶 |
| 4 | 定位后临时在 Console 给该元素加 `outline: 1px solid red`，截图 | 截图能证明"被裁的是谁"，附进缺陷单 |
| 5 | 同时确认页面确实不能横向拖动 | 手指横向拖 → 页面不左右移动（这是 clip 的目的） |

失败时先查什么：

1. 片段 ③ 报错 → 页面里可能有跨域 iframe 之类，忽略并改用「逐页人工扫右边缘」。
2. 全部元素都不越界但视觉上仍有内容缺失 → 检查是不是 `overflow: hidden` 在某个祖先上裁的，不是 clip。
3. 修完越界后 `sticky` 失效 → 说明有人把 clip 换成了 `hidden`/`auto`（会建立滚动容器），必须回 `clip`。
4. `document.documentElement.scrollWidth > clientWidth` 但元素级扫描为空 → **不同内核对 clip 的 `scrollWidth` 返回值不一致**，以元素级扫描为准，此处按实际记录，不判 FAIL。
5. 长 `pre` / 代码块只在块内横向滚动、页面不动 → 正确（`overscroll-behavior-x: contain`），不要误判为溢出。

---

## 3. 八个页面窄屏要点

> 每页先跑 4 个通用判定：片段 ②（触控为空）、片段 ③（无越界）、片段 ⑥（`bg=rgb(7,8,9)`、`colorScheme=dark`）、顶部吸顶栏滚动不抖。下面只写各页特有的。

### 3.1 上传 `/`（本轮新改多）

| # | 检查项 | 类型 | 操作 | 预期 | 失败先查 |
|---|---|---|---|---|---|
| 1 | 触屏文案 | 新改 | 390 宽打开首页，看上传区主文案 | 只显示「点击选择文件」，**不出现**「拖入或点击」 | `.is-tap`/`.is-drag` 两个节点是否都存在、`.is-tap` 是否 `display: inline` |
| 2 | 桌面反证 | 回归 | PC 上把窗口拉到 ≥1024 | 显示「拖入或点击选择文件」，可拖拽 | `base.css` §11 默认 `.is-tap { display: none }` 是否被覆盖 |
| 3 | file input 行为 | 回归 | 点上传区任意位置（不是只点 CTA） | 系统文件选择器弹出（iOS 一般直接进「文件」/ iCloud Drive；若出现来源菜单，选「选取文件」；Android 进系统「文档」选择器） | 整块是不是 `<button>` + `inputRef.current.click()`；`input` 是否 `hidden` 但仍在 DOM |
| 4 | 单文件 | 回归 | 在选择器里多选 | 系统只允许选 1 个（`multiple` 不存在） | DOM 里 `input` 是否被误加 `multiple` |
| 5 | `accept` 过滤 | 回归 | 选择器里看可选文件 | 只有 `.pdf/.docx/.txt` 可选（部分内核不严格过滤 → 见 §5.4 第 3 条） | `accept` 是否仍为 `.pdf,.docx,.txt` |
| 6 | 超限/空文件/格式 | 回归 | 依次选 `big.pdf` / `empty.pdf` / `bad.png` | 三种中文提示各就各位；均**无重试入口** | `validateLocally` 的三条分支 |
| 7 | 长文件名 | 新改 | 上传超长文件名样本 | 文件名折行，卡片不撑宽（片段 ③ 空） | `overflow-wrap: anywhere` 是否落在 `.sc-page` 内 |
| 8 | CTA 独占行 | 新改 | 360 宽看上传区底部 | 「选择文件 ↗」独占一行、上方有发丝线、整行可点 | ≤430 §9 是否生效（`grid-column: 1 / -1`） |
| 9 | 进度卡布局 | 回归 | 上传 1–2 次，观察进度阶段 | 环形进度在左、阶段文字在右，窄屏不竖挤、不重叠 | `.sc-upload-progress` 是否包裹了两种进度卡 |
| 10 | 吸底/粘性不冲突 | 新改 | 上传中上下滚动 | 顶栏与吸顶步骤条保持粘性（clip 未破坏 sticky） | `overflow-x` 是否被改成 `hidden/auto` |
| 11 | 切后台 | 预期不明 | 生成中切到别的 App 再回来（不刷新） | 进度继续推进或回到最新状态；**预期不明，按实际记录** | 回来若停在旧秒数，看 2s 轮询是否因页面隐藏被节流 |

### 3.2 画像 `/profile`

| # | 检查项 | 类型 | 操作 | 预期 | 失败先查 |
|---|---|---|---|---|---|
| 1 | 维度卡单列 | 回归 | 390 宽看画像主体 | 维度卡单列，卡间距一致 | ≤640 单列规则是否被新类名绕过 |
| 2 | 长 `sourceQuote` | 回归 | 找最长的一条溯源引文 | 正常折行，右边缘不越界 | 引文容器是否 `nowrap` |
| 3 | 技能标签触控 | 新改 | 点技能标签 | 高度 ≥44（片段 ② 不含 `.sc-lab-skill`），点按反馈可见 | `base.css` §4 的三条选择器 |
| 4 | 长英文技能名 | 新改 | 看含长英文名的标签 | 标签内折行，不撑破卡片 | `overflow-wrap` 只在 `.sc-page`；标签自身是否需要 `min-width: 0` |
| 5 | 合并摘要条 | 回归 | 刚合并完的账号看摘要条 | 360 下信息完整、高度不塌 | 是否被 `flex` 压成两行 |
| 6 | 空态 | 回归 | `r40-empty` 账号打开 | 空态文案 + 去上传的入口可点 ≥44 | 空态是否复用了 `.sc-btn`（不是裸 `<a>`） |

### 3.3 面试 `/interview`

| # | 检查项 | 类型 | 操作 | 预期 | 失败先查 |
|---|---|---|---|---|---|
| 1 | 键盘避让 | 新改 | 见 **RC-01** | 同 RC-01 | 同 RC-01 |
| 2 | 快捷键提示隐藏 | 新改 | 窄屏看输入区信息行 | 只有「已用 Xs · Y/800 字」，**无**「Ctrl/Cmd + Enter」 | `.sc-iq-meta-key` 的 `display: none` 是否只在 ≤1023 |
| 3 | 桌面反证 | 回归 | PC ≥1024 | 提示重新出现 | 同上，规则是否被写进无断点区 |
| 4 | 输入区长回答 | 回归 | 粘贴 800 字 | 框内滚动（最高 128），不顶破吸底区 | `max-height: --textarea-min-h` |
| 5 | 达到上限 | 回归 | 写满 800 字 | 出现「（已达上限）」且无法再输入 | `maxlength` 与提示文案 |
| 6 | 气泡宽度 | 回归 | 390 宽看多轮气泡 | 气泡占满可用宽、不溢出；身份缩进在窄屏收窄 | `--iq-bubble-max` 是否在 ≤1023 被覆盖 |
| 7 | 滚动留白 | 回归 | 滚到最后一轮 | 评分区可完整滚出粘性区（RC-01 步骤 4） | `--iq-scroll-pad` 172 是否仍大于实际输入区 160 |
| 8 | 只读态 | 回归 | 看已结束的会话 | 输入框只读、无提交入口、提示是「本场面试已结束」 | `readonly` 分支 |
| 9 | 中文输入法 | 回归 | 用拼音输入未上屏直接点提交 | 不误提交（组合态不应触发） | 是否需要 `compositionstart` 保护（若误提交，记 P1） |

### 3.4 笔试 `/exam`

| # | 检查项 | 类型 | 操作 | 预期 | 失败先查 |
|---|---|---|---|---|---|
| 1 | 筛选 chip | 新改 | 390 宽看筛选行 | 每个 chip 高 ≥44；换行整齐不溢出 | `.sc-chip.is-clickable` 的 `height:auto + min-height` |
| 2 | 题卡与选项 | 回归 | 进入一套题 | 单列；选项整行可点，点按命中不偏 | 选项是否为 `<label>` 包 `<input>` 整行 |
| 3 | 计时读数 | 回归 | 观察计时 | 数字/环形不被裁、不抖动 | 数字容器固定宽是否被抬字号挤破 |
| 4 | 结果块 | 回归 | 提交后看结果 | 长解析文本折行，不横向溢出 | 片段 ③ |
| 5 | 禁用态 | 回归 | 未选就点提交 | 禁用样式可见且点不动；无 hover-only 依赖 | `:disabled` 是否有独立视觉 |

### 3.5 报告 `/report`

| # | 检查项 | 类型 | 操作 | 预期 | 失败先查 |
|---|---|---|---|---|---|
| 1 | 单列布局 | 回归 | 390 宽看报告 | 指标条 / 弱项 / 路线 / 课程卡全部单列 | ≤1023 的 `--lab-report-cols` 覆盖 |
| 2 | 长文本 | 新改 | 看最长的一段诊断文字 | 折行，右边缘不越界 | 片段 ③ |
| 3 | 复制按钮 | 新改（44） | 手机（`http://IP`）点「复制 Markdown」 | **预期：出现中文失败提示**「当前浏览器不支持剪贴板复制，请改用「导出 .md」手动保存」——**这是非安全上下文的正确行为，不是缺陷** | 若按钮无反应/无提示 → 看 `navigator.clipboard` 分支 |
| 4 | 复制（对照） | 回归 | PC `http://localhost:5173` 点复制 | 成功 toast | `navigator.clipboard` 是否可用（localhost 属安全上下文） |
| 5 | 导出 `.md` | 回归 | 手机点「导出 .md」 | 触发下载；iOS 落到「文件」App，Android 落到「下载」 | 导出是 `Blob + <a download>`；微信内可能被拦（见 §5） |
| 6 | `<pre>` 代码块 | 新改 | 找含代码/命令的报告段落 | 块内横向滚动，页面不动；不撑宽 | `.sc-page pre` 的 `max-width/overflow-x/overscroll-behavior-x` |
| 7 | 周计划打卡 | 回归 | 点某天，刷新 | 状态保留；换账号后不串 | `weekplan:<userId>:<reportId>` |
| 8 | 空态 | 回归 | 无报告账号打开 | 空态 + 去面试/笔试的入口可点 | — |

### 3.6 历史 `/history`

| # | 检查项 | 类型 | 操作 | 预期 | 失败先查 |
|---|---|---|---|---|---|
| 1 | 时间线卡片化 | 回归 | 390 宽看时间线 | 每事件一张卡（r22 规则），时间不挤成竖排 | ≤640 时间线规则 |
| 2 | 趋势表卡片化 | 回归 | 看成绩趋势表 | ≤640 转卡片，不出现需要横滑的表格 | 趋势表断点规则 |
| 3 | 长标识 | 新改 | 找最长的事件标题/技能名 | 折行 | 片段 ③ |
| 4 | 可点行 | 新改（44） | 点任一时间线卡 | 整卡 ≥44，命中区域与视觉一致 | `.sc-btn` / 卡内按钮选择器 |
| 5 | 空态 | 回归 | 空账号 | 文案 + 免简历出口 | — |

### 3.7 练习 `/practice`

| # | 检查项 | 类型 | 操作 | 预期 | 失败先查 |
|---|---|---|---|---|---|
| 1 | 筛选 chip | 新改 | 390 宽看筛选 | 高 ≥44；不换行错位 | 同 3.4-1 |
| 2 | 代码块横滑 | 新改 | 找最长代码行，横向拖 | 只有代码块内部滚动，页面不横移 | `overscroll-behavior-x: contain` |
| 3 | 错题行 | 回归 | 点错题行展开/收起 | 展开动画不跳；行高 ≥44 可点 | `--qa-row-min-h` |
| 4 | 选项单列 | 回归 | 看选择题 | 每项独占一行，长选项折行 | — |
| 5 | 标签列对齐 | 回归 | 看 6 行筛选标签 | 左缘对齐（`--qa-label-w` 96） | 是否被窄屏覆盖破坏 |

### 3.8 润色 `/polish`

| # | 检查项 | 类型 | 操作 | 预期 | 失败先查 |
|---|---|---|---|---|---|
| 1 | 单栏 | 回归 | 390 宽打开 | 双栏在 ≤1319 收单栏，无并排挤压 | 单栏断点 |
| 2 | 成稿 Tab | 回归 | 切「原版 / 润色版」 | Tab 可点、命中准，切换不跳位 | `--sev-tab-h` 与按钮选择器 |
| 3 | 建议卡按钮 | 新改（44） | 点采纳/忽略 | 高 ≥44；连续快速点不重复提交 | 是否有 submitting 守卫 |
| 4 | 长文本 | 新改 | 找最长改写段落 | 折行、不横向溢出 | 片段 ③ |
| 5 | 编辑器滚动 | 回归 | 粘贴长内容 | 框内滚动，页面不整体跳动 | `max-height` / `overflow` |

---

## 4. 横切项（每台设备、每轮都要过）

| ID | 检查项 | 操作 | 预期（量化） |
|---|---|---|---|
| X-01 | 元素级越界 | 每页跑片段 ③ | 返回空数组；允许 ≤2px 亚像素，记 P2 |
| X-02 | 触控目标 | 每页跑片段 ② | 返回空数组（全部 ≥44 高） |
| X-03 | 吸顶不抖 | 任意页上下滚动 | 顶栏（56 + safeTop）与吸顶步骤条（44 项 + 8 内边距 + 1 发丝线 = 53）不跳动、不闪；内容不被两栏永久遮挡 |
| X-04 | 深色兜底 | 系统切到**浅色**，重开页面 | 页面仍深色；过滚回弹区为 `#070809`；首帧不闪白；片段 ⑥ 三项符合 |
| X-05 | 输入防放大 | 聚焦任意 `input`/`textarea` | 聚焦瞬间**页面不放大**（英文/数字输入框 computed `font-size` ≥16；`.sc-iq-input` 应为 16px） |
| X-06 | 页内锚点 | 进 `/learn/<章>`，点目录跳到某一小节 | 跳转后小节标题**完整可见**，不被「顶栏 56 + 吸顶 53」压住（`scroll-padding-top = 112 + safeTop`） |
| X-07 | 禁用态不靠 hover | 找禁用按钮 | 禁用有独立配色且点击无效；触屏上无「只有 hover 才看得出可点」的元素 |
| X-08 | 误触 | 在下拉/上滑区间来回滑 | 不触发意外跳转/提交；链接不做整页可点 |
| X-09 | 弹窗按钮 | 触发任一确认弹窗 | ≤430 两个按钮铺满一行（`flex: 1 1 auto`），拇指可达 |
| X-10 | 五段流程条 | 首页 360 宽看流程条 | ≤430 为单列，标题不断成三行 |

---

## 5. 设备矩阵与优先级

### 5.1 最小必测集（P0，不做完不能发）

| 设备 | 视口 | 浏览器 | 必测原因 |
|---|---|---|---|
| iPhone（有刘海/灵动岛，如 13/14/15） | 390/393 | Safari | `interactive-widget` 不被支持，全靠 `visualViewport` 兜底；safe-area 非 0 |
| Android（360dp 小屏或 390） | 360/390 | Chrome | `interactive-widget` 生效路径；小屏最窄列与字号 |
| 桌面 Chrome DevTools | 360×800 / 390×844 | 设备模拟 | 辅助项：能覆盖 360 排版与片段 ②③⑤，**不替代真机键盘与安全区** |

> 若手头没有 360dp 真机：360 用 DevTools 验收并标「非真机」，同时把 RC-03 降级为 P1 观察 —— 但 390 真机的 RC-03 仍必须 PASS。

### 5.2 扩展集（发现问题记 P1，不阻塞发布）

| 设备 | 重点 | 备注 |
|---|---|---|
| iPhone SE（375，无刘海） | safe-area 应为 0 的分支；最窄 iPhone 宽 | 无刘海下顶栏/输入区**不应**少留白 |
| 微信内置浏览器（iOS + Android 各一） | 文件选择器、键盘行为、`.md` 下载、复制 | X5/XWeb 行为差异大，见 §5.4 |
| 鸿蒙浏览器（ArkWeb） | `interactive-widget` 是否生效、系统字体缩放 | 用户主目标机型，务必至少跑一次全流程 |
| Android 平板 / 手机横屏 | 布局是否仍单列、safeLeft/Right | 横屏不是本轮验收目标，按实际记录 |

### 5.3 阻塞规则

- **阻塞发布（P0）**：RC-01～RC-05 任一 FAIL；5.1 三台设备上的 X-01/X-02/X-05 任一 FAIL；上传页主路径（PDF 上传成功 → 进入生成）FAIL。
- **记缺陷可发（P1）**：X-06/X-07/X-09/X-10 FAIL；扩展集设备的键盘/下载/复制异常；360 首列换行但仅表现为"多占一行"。
- **观察（P2）**：≤2px 亚像素越界；横屏 safe-area 异常；微信内 `.md` 下载被拦；`scrollWidth` 与内核相关的不一致。

### 5.4 明确「预期不明，按实际记录」的项

1. 微信内置浏览器对 `interactive-widget=resizes-content` 的支持（X5/XWeb 未知）——只看片段 ④ 的 `coveredBy ≤ 0`。
2. 鸿蒙 ArkWeb 是否解析该值，以及系统「字体大小」设置对 `rem/px` 的影响（本项目全用 px，理论上不随系统字号变）。
3. 微信/iOS 的文件选择器是否严格按 `accept` 过滤（很多内核只做弱过滤，仍可选到 `.png`，此时应由前端本地校验兜底报错）。
4. iOS Safari 点「导出 .md」的落点（文件 App / 下载项 / 仅预览）。
5. 生成阶段切后台再回来，画像轮询是否恢复。
6. 桌面窗口缩到 ≤640 时的 hover 交互（本轮用视口宽度切文案，窄桌面仍能拖拽）。
7. `overflow-x: clip` 下 `documentElement.scrollWidth` 的返回值（内核差异，以元素级扫描为准）。

---

## 6. 可直接勾选的测试清单

> 每台设备复制一份下面的区块；括号内填机型/系统/结果。

**设备信息**：机型 `____________` / 系统版本 `____________` / 浏览器 `____________` / 视口宽 `____` / 是否刘海或手势条 `______`

### 环境

- [ ] ENV-1 后端 `/health` 返回 ok 且 `ai_configured=true`（记录：____）
- [ ] ENV-2 手机能打开 `http://<IP>:5173` 并看到登录页（IP：____________）
- [ ] ENV-3 手机端单独登录 `r40-full` 成功（账号：____________）
- [ ] ENV-4 已清除该 origin 的 localStorage + sessionStorage + cookie（清法：____________）
- [ ] ENV-5 素材已就位：ok.pdf / ok.docx / ok.txt / big.pdf / empty.pdf / bad.png / 加密 PDF / 超长文件名 / 含长 URL 样本

### 高风险项

- [ ] RC-01 键盘避让：`coveredBy ≤ 0`、提交按钮可见、最后一条评分区可完整滚出（记录：coveredBy=____）
- [ ] RC-01b 键盘弹出后页面能滑到底、输入区不跳动
- [ ] RC-01c 收起键盘再聚焦一次，无无谓整页跳动
- [ ] RC-02 安全区：`safeTop=____` / `safeBottom=____`；顶栏与输入区均不被遮挡
- [ ] RC-02b 无刘海设备：`safeTop=0` 且留白与设计基线一致
- [ ] RC-03 首列：`w≤54`、`h=16`、`ls=0.44px`（记录：w=____ / h=____）
- [ ] RC-04 画像有数据：维度卡单列、长引文折行、技能标签 ≥44、摘要条完整
- [ ] RC-04b 报告有数据：单列、弱项表重排、课程卡完整、打卡持久
- [ ] RC-05 越界扫描：8 页片段 ③ 均返回空数组（有结果页：____________）
- [ ] RC-05b 页面确实不能横向拖动（clip 生效）

### 八页

- [ ] P-UP-1 触屏只显示「点击选择文件」（桌面反证：显示拖入）
- [ ] P-UP-2 点整块上传区唤出系统选择器；只能选 1 个文件
- [ ] P-UP-3 超 10MB / 空文件 / 不支持格式三种中文提示正确且无重试
- [ ] P-UP-4 超长文件名折行、不撑宽
- [ ] P-UP-5 CTA「选择文件 ↗」独占一行、有发丝线、整行可点
- [ ] P-UP-6 进度卡环形在左、文字在右，窄屏不竖挤
- [ ] P-PR-1 维度卡单列 + 长引文折行
- [ ] P-PR-2 技能标签 ≥44 且长英文名折行
- [ ] P-PR-3 合并摘要条 360 下信息完整
- [ ] P-PR-4 空态入口可点 ≥44
- [ ] P-IQ-1 窄屏无「Ctrl/Cmd + Enter」提示（桌面反证：有）
- [ ] P-IQ-2 800 字回答框内滚动，不顶破吸底区
- [ ] P-IQ-3 气泡不溢出；身份缩进收窄合理
- [ ] P-IQ-4 只读态无提交入口
- [ ] P-IQ-5 中文输入法组合态点提交不误发（若误发记 P1）
- [ ] P-EX-1 筛选 chip ≥44、换行整齐
- [ ] P-EX-2 题卡与选项单列、整行可点
- [ ] P-EX-3 计时读数不裁、不抖
- [ ] P-EX-4 结果长解析折行
- [ ] P-EX-5 禁用态可见且点不动
- [ ] P-RP-1 全部单列、长文本不越界
- [ ] P-RP-2 手机复制 → **预期为中文失败提示**（非缺陷）；桌面 localhost 复制 → 成功
- [ ] P-RP-3 导出 `.md` 触发下载（记录落点：____________）
- [ ] P-RP-4 代码块块内横滑、页面不动
- [ ] P-RP-5 周计划打卡持久、换账号不串
- [ ] P-HS-1 时间线卡片化、时间不竖排
- [ ] P-HS-2 趋势表卡片化、无需横滑
- [ ] P-HS-3 时间线卡可点 ≥44
- [ ] P-QA-1 筛选 chip ≥44
- [ ] P-QA-2 代码块横滑时页面不横移
- [ ] P-QA-3 错题行展开/收起可点
- [ ] P-QA-4 标签列左缘对齐
- [ ] P-PL-1 单栏布局、无并排挤压
- [ ] P-PL-2 成稿 Tab 可点、切换不跳位
- [ ] P-PL-3 建议卡按钮 ≥44、连点不重复提交
- [ ] P-PL-4 长段落折行、编辑器框内滚动

### 横切

- [ ] X-01 每页片段 ③ 空数组
- [ ] X-02 每页片段 ② 空数组
- [ ] X-03 顶栏 + 吸顶步骤条滚动不抖、不遮内容
- [ ] X-04 系统浅色下仍深色、回弹区 #070809、无首帧白闪
- [ ] X-05 聚焦输入框页面不放大
- [ ] X-06 `/learn` 锚点跳转后标题不被吸顶栏压住
- [ ] X-07 禁用态有独立视觉、无 hover-only 依赖
- [ ] X-08 横向滑动筛选条不触发整页横移
- [ ] X-09 弹窗两按钮 ≤430 铺满一行
- [ ] X-10 首页流程条 ≤430 单列

### 结果汇总

- P0 通过：`__/__`；P1 缺陷：`__` 条；P2 观察：`__` 条
- 是否可发布：`PASS / 需修复后复测`
- 备注：`________________________________________________`

---

## 7. 结果记录表

| # | 机型 | 系统版本 | 浏览器/内核 | 视口宽 | 刘海/手势条 | P0 结果 | P1 缺陷数 | 备注（含截图链接） |
|---|---|---|---|---|---|---|---|---|
| 1 |  |  |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |  |  |
| 4 |  |  |  |  |  |  |  |  |
| 5 |  |  |  |  |  |  |  |  |

**FAIL 条目登记**（按 ID 记，便于回填缺陷单）

| 条目 ID | 现象（一句） | 期望（引用本清单条款） | 截图/录屏 | 初判归属（哪条 CSS/组件） | 严重度 |
|---|---|---|---|---|---|
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |

---

## 8. 与本次改动的关系（便于失败时快速定位）

| 现象 | 大概率来源 | 位置 |
|---|---|---|
| 页面能左右拖 / 越界被裁 | `overflow-x: clip` 与 sticky 的取舍 | `frontend/src/styles/base.css` r40 §1 |
| 长英文名/URL 断行 | `.sc-page { overflow-wrap: anywhere }` | 同上 §2 |
| 锚点跳转被吸顶栏压住 | `scroll-padding-top` | 同上 §3 |
| 按钮/chip 仍点不准 | 44 触控选择器覆盖范围 | 同上 §4 |
| 键盘盖住输入区 | viewport meta / `Composer` 兜底 | `frontend/index.html`、`frontend/src/components/interview/Composer.tsx` |
| 输入区莫名跳动 | `scroll-margin-bottom` + 兜底 `scrollBy` | 同上 §5 |
| 手机上还显示 Ctrl/Cmd 提示 | `.sc-iq-meta-key` 断点 | 同上 §5 |
| 上传文案仍说「拖入」 | `.is-tap` / `.is-drag` 切换 | 同上 §11、`frontend/src/pages/UploadPage.tsx` |
| 360 首列换行/截断 | 字号 11 与字距 0.04em 的组合 | `frontend/src/styles/tokens.css` r40、`base.css` §12 |
| 360 下 CTA 挤在主文案旁 | ≤430 CTA 独占行 | `base.css` §9 |
| 流程条三行换行 | ≤430 单列 | `base.css` §8 |
| 弹窗按钮挤在右下 | ≤430 按钮铺满 | `base.css` §10 |
| 浅色系统下闪白 / 回弹区白 | `color-scheme`、`html` 底色、`theme-color` | `base.css` §0、`index.html` |
| 地址栏颜色不对 | `theme-color` 与 `--bg-canvas` 不同步 | `index.html`（改色需两处同步） |

- 回滚口径见 TECH-CHANGE §5：r40 全部 append-only，单点可回滚。
