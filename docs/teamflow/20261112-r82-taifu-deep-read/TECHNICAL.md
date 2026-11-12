# r82 · 技术方案：按需深读 + 页面就地发问

## 1. 设计要点

一句话：**focus 是「用户点了哪一条」的声明，明细是服务端对这条的重新取料，白名单跟着本次取料走。**

三条硬边界不变，只做加法：

1. 材料仍由服务端读库（`deep_read` 与 `brief` 同为「投影层」，零统计、零改写）；
2. 明细段的 `href` 就是它的引用白名单，且只在本次真读到它时才存在；
3. 太傅仍不写任何业务表。

新增的一条边界：**focus 不参与「该不该读」的判断，只参与「读哪一条」**。没传就完全走老路，
不做问句猜测——这是 AC-5 的实现前提。

## 2. 契约

### 2.1 请求

```python
class TaifuFocus(BaseModel):
    kind: str = ""            # 故意不是 Literal：非法值要「等同没传」，不能被 422 挡在门外
    index: int = 0            # weakness：1 起
    question_id: str = ""     # attempt
    anchor: str = ""          # resume：简历正文里的逐字原句

class TaifuChatRequest(BaseModel):
    question: str = ""
    page: str = ""
    focus: TaifuFocus | None = None
```

`kind` 用 `str` 而不是 `Literal`：pydantic 对 `Literal` 非法值抛 422，而 AC-1 要求
「kind 非法 = 没传」。闭集校验放在 `policy.sanitize_focus()`，与 `sanitize_page()` 同一手法。

### 2.2 响应

```python
class TaifuDetailRef(BaseModel):
    kind: str = ""     # weakness | attempt | resume
    label: str = ""    # 界面显示用，如「薄弱明细 · 事件循环 · 进阶」
    href: str = ""     # 与明细段同一 href

class TaifuReply(BaseModel):
    ...
    detail: TaifuDetailRef | None = None   # 没读明细时为 None（含 focus 越界被忽略）
```

## 3. 后端

### 3.1 `services/taifu/deep_read.py`

```python
MAX_DETAIL_LINES = 8
DETAIL_LINE_MAX = 160
MAX_SAMPLES = 3          # 与 WeaknessItem.samples 上限同源
RESUME_CONTEXT = 180     # 原句前后各 180 字

def build_detail(
    focus: dict[str, Any],
    *,
    profile: Profile | None,
    report: Report | None,
    attempts: list[dict[str, Any]],
    document_text: str | None,
) -> dict[str, Any] | None
```

返回与 `brief._section()` **同形**的段（`key/label/href/lines/anchors`），
因此 `sanitize_reply()` 不用改一行就能把它纳入白名单。

三类取料：

| kind | 校验顺序 | 行 |
| --- | --- | --- |
| `weakness` | report 非空 → `weakness_map` 是 list → `1 ≤ index ≤ len` → 组内 samples 非空 | 分组行 + 每题两行（题面/结果、解析） |
| `attempt` | `question_id` 在题库 → 本账号有该题的作答 | 题面、选项、答案与结果、解析 |
| `resume` | `document_text` 非空 → `anchor` 在正文里 `find` 到 | 位置与问题、原句、前后文窗口 |

任一校验不过 → `None`（调用方据此当成没传）。

题目读取：新增 `repository.get_question(question_id)`（单条，不扫全表）。
`questions.answer` / `options` 是 JSON 文本列，复用 `repository._json_list` 同款解析（模块内自带小工具，
不跨模块借私有函数）。

### 3.2 编排（`services/taifu/taifu.py`）

```python
def gather_context(focus) -> tuple[list[dict], dict | None]:
    profile = repository.latest_profile()
    report = repository.latest_report()
    attempts = repository.list_attempts()
    sections = brief.build_sections(...)
    document_text = (
        repository.get_document_text(profile.resume_id)
        if focus and focus["kind"] == "resume" and profile is not None
        else None
    )
    detail = deep_read.build_detail(focus, profile=..., report=..., attempts=..., document_text=...)
    return sections, detail
```

明细**不 append 进 sections**，单独作为 `build_user_prompt(..., detail=...)` 的参数：
提示词里它是独立的一段（`【重点明细】`），但 `sanitize_reply()` 的白名单要把两者合并。

```python
detail_ref = deep_read.to_ref(detail)      # None 或 TaifuDetailRef
payload = policy.sanitize_reply(draft, [*sections, *([detail] if detail else [])])
```

空档案短路顺序不变：`sections == []` 时明细必为 `None`（三类明细分别依赖 report / attempts / profile，
这三者任一存在就会产出对应段），所以先短路仍等价、仍零成本。

### 3.3 提示词

系统提示词新增第 9 条：

> 【重点明细】是用户刚从页面上点开的那一条的原始记录，比【档案】更细，**同样是依据**，
> 可以引用它的 href；回答「这条 / 这题 / 这段」时优先用它。

`USER_PROMPT_TEMPLATE` 在【档案】之后插入：

```
【重点明细】（用户刚点开的那一条；与【档案】同等有效，优先用它回答「这条 / 这题 / 这段」）
[1] 薄弱明细：事件循环 · 进阶 · 错误率 75%（href: /report#weakness-3）
- 分组：事件循环 · 进阶 · 错误率 75%（3/4）
- 题面：以下哪个操作不会阻塞事件循环…… · 你的结果：答错
...
```

明细段只有一段，编号固定 `[1]`，避免与档案段编号混排。

### 3.4 白名单

`policy.sanitize_reply(draft, sections)` 完全不动：allowed = 所有段的 href + anchors。
明细段按同形结构传入即可。因此：

- 有明细 → `/polish`（resume）或 `/practice` 可能首次进入白名单；
- 无明细 → 与 r81 完全一致的 allowed 集合（AC-5）。

## 4. 前端

### 4.1 `lib/taifuBridge.ts`（跨组件唤起）

```ts
export const TAIFU_ASK_EVENT = 'sc:taifu-ask'
export interface TaifuAsk { question: string; focus: TaifuFocus; label: string }
export function askTaifu(ask: TaifuAsk): void            // window.dispatchEvent(CustomEvent)
export function onTaifuAsk(handler: (ask: TaifuAsk) => void): () => void
export function safeAsk(ask: TaifuAsk | null): boolean   // 纯校验：focus 不合法就不发
```

不用 Context：浮窗挂在 `App` 的兄弟位置，页面组件在路由树里，`CustomEvent` 是唯一不动
组件树结构的通道；且它是同步的，点完立刻开面板。

`safeAsk` 做前端侧的同一套闭集校验（index ≥ 1、question_id / anchor 非空），
避免页面传半个对象过去、服务端又静默忽略（用户会以为「问了但没读明细」）。

### 4.2 浮窗状态

新增：

```ts
const [focus, setFocus] = useState<{ value: TaifuFocus; label: string } | null>(null)
```

生命周期：

| 事件 | 行为 |
| --- | --- |
| 收到 `TaifuAsk` | `setOpen(true)` + `setQuestion(q)` + `setFocus(...)` + 聚焦输入框 |
| 用户点「× 取消」 | `setFocus(null)`，问题文本保留 |
| 路由变化 | `setFocus(null)`（与既有「路由变化收起」同一 effect） |
| 发送 | 请求体带 `focus?.value`；成功后**不清空**（同一话题可连续追问） |
| 服务端忽略焦点 | 响应的 `detail === null` → 界面不显示「已读取」，焦点 chip 也撤掉（诚实告知没读到） |

### 4.3 回答渲染（`lib/taifuChat.ts`）

两个纯函数，先测后用：

```ts
export interface ReplyBlock { kind: 'p' | 'list'; ordered?: boolean; text?: string; items?: string[] }
export function parseReplyBlocks(text: string): ReplyBlock[]
export interface InlineSpan { text: string; bold: boolean }
export function splitBold(text: string): InlineSpan[]
```

规则：

| 输入 | 输出 |
| --- | --- |
| `- x` / `* x` / `· x` | 无序 list item |
| `1. x` / `1、x` / `1) x` | 有序 list item（连续同类合并成一个 block） |
| 空行 | 结束当前 list |
| 其他非空行 | paragraph |
| `**x**` | `splitBold` 切成 `{text, bold}` 段（未闭合时按普通文本处理） |

复制按钮：`navigator.clipboard.writeText(content)`，失败给「复制失败，请手动选中」，
不做 `execCommand` 降级（已废弃，且本项目只支持现代浏览器）。

### 4.4 三处页面入口

| 位置 | 组件 | 文案 | focus |
| --- | --- | --- | --- |
| 医案 · 薄弱组行 | `components/report/WeaknessMap.tsx` | 问太傅：这条怎么补 | `{kind:'weakness', index: index+1, label: item.point}` |
| 医案 · 简历改进要点 | `components/report/ResumePointers.tsx` | 问太傅：这句怎么写 | `{kind:'resume', anchor: pointer.anchor_text, label: pointer.location}` |
| 演武 · 错题展开 | `components/practice/WrongBookList.tsx` | 问太傅：这题为什么错 | `{kind:'attempt', question_id: item.question_id, label: 题面前 20 字}` |

按钮形态：`sc-taifu-inline`（无边框小按钮，hover 变强调色）。不放在 `<a>` 里、不拦冒泡地
破坏既有交互（错题本的展开按钮独立）。

### 4.5 样式

只加类、不加裸值，全部走 tokens：

- `.sc-taifu-focus`（焦点 chip + 取消）、`.sc-taifu-detail`（已读取提示）
- `.sc-taifu-points` / `.sc-taifu-points li`（回答列表，区别于示例问题用的 `.sc-taifu-list`）
- `.sc-taifu-copy`（消息头右侧复制按钮）
- `.sc-taifu-inline`（页面内入口按钮）

不新增 token：以上全部复用 `--sp-*` / `--fs-*` / `--radius-*` / 既有语义色，
因此不用回写 DESIGN 的尺寸推导。

## 5. 测试

后端 `tests/test_r82_taifu_deep_read.py`：

- `sanitize_focus`：缺省 / kind 非法 / index 为 0 / index 为 bool / 字段超长 → `None` 或归一；
- `build_detail` 三类正常路径 + 越界（index 超长、题号不存在、无作答、anchor 不在正文）→ `None`；
- 预算：行数 ≤ 8、单行 ≤ 160；
- 白名单：有明细时明细 href 可引，无明细时 `/polish` 被丢弃；
- 编排：`gather_context` 无 focus 时与 `gather_sections` 等价。

前端：

- `taifuChat.test.ts`：`parseReplyBlocks`（列表 / 编号 / 空行 / 混排）、`splitBold`（成对 / 未闭合 / 多个）；
- `taifuBridge.test.ts`：`safeAsk` 三类非法输入不发事件、合法输入能收到；
- 既有 36 个测试文件不回归。

## 6. 落地清单

| 文件 | 改动 |
| --- | --- |
| `backend/app/schemas.py` | `TaifuFocus` / `TaifuDetailRef` / `TaifuChatRequest.focus` / `TaifuReply.detail` |
| `backend/app/core/repository.py` | `get_question(question_id)` |
| `backend/app/services/taifu/deep_read.py` | 新建 |
| `backend/app/services/taifu/policy.py` | `sanitize_focus` / 系统提示词第 9 条 / `build_user_prompt(detail=)` |
| `backend/app/services/taifu/taifu.py` | `gather_context` / `answer(detail=)` / `detail` 回填 |
| `backend/app/routers/taifu.py` | 传 `payload.focus` |
| `backend/tests/test_r82_taifu_deep_read.py` | 新建 |
| `frontend/src/api/types.ts` / `client.ts` | `TaifuFocus` / `TaifuDetailRef` / `taifuChat(question, page, focus)` |
| `frontend/src/lib/taifuBridge.ts` | 新建 |
| `frontend/src/lib/taifuChat.ts` | `parseReplyBlocks` / `splitBold` |
| `frontend/src/components/taifu/TaifuLauncher.tsx` | 焦点态 / 明细标记 / 富文本 / 复制 |
| `frontend/src/components/report/WeaknessMap.tsx` | 入口按钮 |
| `frontend/src/components/report/ResumePointers.tsx` | 入口按钮 |
| `frontend/src/components/practice/WrongBookList.tsx` | 入口按钮 |
| `frontend/src/styles/base.css` | 5 个新类 |
| `frontend/src/test/taifuChat.test.ts` / `taifuBridge.test.ts` | 追加用例 |
