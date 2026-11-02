"""r13 离线答案偏置修复库：选项均衡重排 + 判断题极性改写 + 解析字母引用同步。

纯离线工具（无 IO、无模块级状态），运行时**永不** import 它（见
`test_engineering_gates.py` 的反向断言）。对外契约：

- `apply(rows) -> (rows, metrics)`：唯一变换入口，由 `question_merge.build_seed()` 末尾调用；
- `classify_refs(text, valid_keys)`：解析里「哪些字母是选项引用」的唯一实现；
- `render_report(metrics)`：`SHUFFLE-REPORT.md` 正文，只吃 `apply()` 的指标；
- `check()` / `main()`：`--check`（只读比对）/ `--write`（**委托** `question_merge.write()`）/
  `--report`（打印报表）。

两条不变量（破坏任一条都会让 `question_merge --check` 恒红）：

1. **幂等**：位置分配只依赖「内容身份 + 固定 id 定序」与逐题递增的位置计数，
   与「当前答案落在哪个 key」无关；判断题用绝对映射表，重复运行不会二次翻转。
2. **`options` 数组顺序恒等于 key 位置序**：重编 key 时数组一并按 `A..D` 重建，
   判分（按 key 集合）与前端（按数组序渲染）才不会各自漂移。
"""

from __future__ import annotations

import hashlib
import re
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

#: 选项位置序（单选/多选的 key 闭集，顺序即数组序）。
KEYS: tuple[str, ...] = ("A", "B", "C", "D")

#: 哈希拼接分隔符（避免 `id` 与选项文本边界歧义）。
_HASH_SEP = "\x1f"

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
#: 打乱报表（工具产物，落本需求任务夹；任务夹建后不可变，故不再写历史夹）。
REPORT_PATH = (
    _PROJECT_ROOT
    / "docs"
    / "teamflow"
    / "20261102-r13-answer-bias-shuffle"
    / "SHUFFLE-REPORT.md"
)

#: 答案长度比的口径（「正确项平均长度 / 干扰项平均长度」）。
_LENGTH_RATIO_LONG = 3.0
_LENGTH_RATIO_WATCH = 2.0

#: 显式选项引用形式：`A 项` / `选项 A` / `选项A`。
_EXPLICIT = re.compile(r"(?:选项\s*)?([ABCD])\s*项|选项\s*([ABCD])")
#: 判角短语（字母后紧跟这些词才算「指代选项」）。
_VERDICT_TAIL = ("正确", "错误", "不正确", "不对", "误", "是", "为", "不是", "干扰项", "正解", "答案")
#: 非引用护栏：`C 语言` / `C++` / `Java/C++` / `ACID` 之类不得当选项字母。
_LANG_GUARD = re.compile(r"[ABCD](?:\s*(?:语言|编译器|标准|\+\+|#|/))|(?<=\/)[ABCD]")
#: 由「、和与或」连接的纯字母清单（`A、B、D` / `A 和 B`）。
_LIST = re.compile(r"([ABCD])(?:[、和与或]\s*([ABCD]))+")
#: 独立字母 token（两侧不能是字母数字下划线）。
_TOKEN = re.compile(r"(?<![A-Za-z0-9_])[ABCD](?![A-Za-z0-9_])")

#: 解析一致性双校验：字母后紧跟否定判定词 ⇒ 该字母**不得**在 `answer` 里
#: （`A 项错误 ⇔ A ∉ answer`）；紧跟肯定判定词 ⇒ 该字母**必须**在 `answer` 里。
#: 长词在前（`项不正确` 必须先于 `不正确` 命中），避免「不正确」被当成「正确」。
_VERDICT_NEGATIVE: tuple[str, ...] = (
    "项不正确",
    "项错误",
    "项不对",
    "项有误",
    "项不符合",
    "项是错的",
    "不正确",
    "错误",
    "不对",
    "有误",
    "不符合",
)
_VERDICT_POSITIVE: tuple[str, ...] = (
    "项正确",
    "项是对的",
    "项为正确",
    "项符合",
    "正确",
    "对的",
    "符合",
)
#: 「正确项为 A、B、D」这类显式集合句：字母集合必须等于 `answer` 集合。
_SET_PHRASE = re.compile(
    r"(?:正确项|正确选项|正确答案|正确的是)(?:为|是)?[：:]*\s*([ABCD](?:[、和与或][ABCD])*)"
)
#: 题面「选错项」的方向词：命中即该题的判定词极性**反向**（题面问「以下说法错误的是」时，
#: 解析里的「`C 错误`」恰恰是在说 C 就是应选项，`C ∈ answer` 本就自洽）。
_NEGATIVE_ASK: tuple[str, ...] = (
    "错误的是",
    "不正确的是",
    "不属于",
    "不包括",
    "不符合",
    "不正确",
    "有误",
    "以下不是",
    "下列不是",
    "哪项不是",
    "哪个不是",
    "不需要",
    "不会出现",
    "不会发生",
)
#: 已人工核对、允许留在不一致清单里的题（id -> 核对说明）。绝对白名单：
#: 只有复核过原文、确认是文案风格而非 key 错位时才可增列，且必须写清理由。
#: 当前为空：唯一命中过的 `iq380-164`（题面问「错误的是」、`C 错误` 正指 C 为应选项）
#: 已由 `_NEGATIVE_ASK` 的方向反转覆盖，不再需要白名单。
_CONSISTENCY_REVIEWED: dict[str, str] = {}

#: 判断题极性改写表（**绝对映射**，不是相对取反 → 重复运行不会二次翻转）。
#: 每条：`id`（题库 id）/ `before`（基线原句，仅供报表对照）/ `statement`（改写后的错误陈述）/
#: `explanation`（该错误陈述的解析）。条数与 `29` 条达成 78 / 78 的最小翻转数一致。
JUDGE_FLIPS: tuple[dict[str, str], ...] = (
    {
        "id": "tiji-017",
        "before": "在 JavaScript 中，`==` 会比较值并允许隐式类型转换，而 `===` 要求类型与值都相等。",
        "statement": "在 JavaScript 中，`==` 只比较值且不做任何类型转换，而 `===` 允许隐式类型转换。",
        "explanation": "说反了：`==` 才做隐式类型转换（'1'==1 为 true），`===` 严格比较类型与值，"
        "不做转换（'1'===1 为 false）。",
    },
    {
        "id": "tiji-019",
        "before": "栈（stack）是一种后进先出（LIFO）的数据结构。",
        "statement": "栈（stack）是一种先进先出（FIFO）的数据结构。",
        "explanation": "栈只能在一端插入与删除，最后压入的最先弹出，是后进先出（LIFO）；"
        "先进先出（FIFO）是队列的特性。",
    },
    {
        "id": "py-q18",
        "before": "Python 的 list 与 tuple 都可以容纳不同类型的元素，tuple 创建后其元素引用不能再被替换。",
        "statement": "Python 的 tuple 创建后其元素引用仍可被任意替换，因此 tuple 与 list 一样是可变容器。",
        "explanation": "tuple 的元素引用不可替换、也不能增删，是不可变容器；"
        "只有元素本身是可变对象（如 tuple 里放 list）时其内容才可变。",
    },
    {
        "id": "py-q20",
        "before": "在 CPython 中，由于小整数缓存（-5 到 256），相同数值的两个变量用 is 比较可能返回 True。",
        "statement": "在 CPython 中，两个数值相同的 int 变量用 is 比较一定返回 False，因为小整数不会被缓存。",
        "explanation": "CPython 会缓存 -5 到 256 的小整数对象，该区间内 a is b 可能为 True；"
        "is 是身份比较，判断值相等始终应使用 ==。",
    },
    {
        "id": "java-q17",
        "before": "Java 中 int 是基本类型、Integer 是包装类，Integer 类型的变量可以为 null。",
        "statement": "Java 中 int 是基本类型、Integer 是包装类，但 Integer 类型的变量不能为 null。",
        "explanation": "Integer 是引用类型，未赋值时默认就是 null；int 才是不能为 null 的基本类型，"
        "自动拆箱遇到 null 还会抛 NullPointerException。",
    },
    {
        "id": "java-q19",
        "before": "Java 的 finally 块中出现 return 语句时，会覆盖 try 块中已经计算出的返回值。",
        "statement": "Java 的 finally 块中出现 return 语句时，不会影响 try 块中已经计算出的返回值。",
        "explanation": "finally 在方法真正返回前执行，其中的 return 会直接结束方法并覆盖 try 的返回值，"
        "同时还会吞掉异常。",
    },
    {
        "id": "go-q18",
        "before": "Go 的 map 是引用语义，把 map 传给函数后，函数内新增的键在调用方可见。",
        "statement": "Go 的 map 是值语义，把 map 传给函数后，函数内新增的键在调用方不可见。",
        "explanation": "map 变量内部是指向运行时哈希表的指针，按值传递复制的是这个指针，"
        "因此函数内增删键对调用方可见；只有函数内重新 make 才不影响调用方。",
    },
    {
        "id": "go-q19",
        "before": "在 Go 中，向已关闭的 channel 发送数据会触发 panic，而从已关闭的 channel 接收会立即返回零值。",
        "statement": "在 Go 中，向已关闭的 channel 发送数据不会触发 panic，而从已关闭的 channel 接收会一直阻塞。",
        "explanation": "向已关闭的 channel 发送会 panic（send on closed channel）；"
        "接收则立即返回剩余缓冲数据或零值，第二返回值 ok 为 false。",
    },
    {
        "id": "html-q18",
        "before": '<input type="button"> 与 <button> 都能生成可点击按钮，但 <button> 内部可以包含图标等 HTML 元素。',
        "statement": '<input type="button"> 与 <button> 都能生成可点击按钮，但 <button> 内部只能放纯文本。',
        "explanation": "input 是空元素，value 只能是纯文本；button 是容器元素，可以嵌套文本与图标。"
        '注意 button 默认 type 是 submit，在表单里需显式写 type="button"。',
    },
    {
        "id": "html-q19",
        "before": "img 是空元素（void element），没有结束标签，因此不需要写 </img>。",
        "statement": "img 元素必须写结束标签 </img>，否则浏览器会忽略这张图片。",
        "explanation": "img、br、hr、input、meta、link 等都是空元素，不能有子内容，因此没有结束标签；"
        "在 JSX 等 XML 风格语法中会写成自闭合的 <img />。",
    },
    {
        "id": "css-q18",
        "before": "box-sizing: border-box 会让 width 包含 padding 与 border，但不包含 margin。",
        "statement": "box-sizing: border-box 会让 width 包含 margin，但不包含 padding 与 border。",
        "explanation": "border-box 把 padding 与 border 计入 width，margin 始终在盒子之外，"
        "不参与 width 计算。",
    },
    {
        "id": "css-q20",
        "before": "在 CSS 层叠计算中，两条规则优先级相同时，后出现的声明会覆盖先出现的声明。",
        "statement": "在 CSS 层叠计算中，两条规则优先级相同时，先出现的声明会覆盖后出现的声明。",
        "explanation": "权重与来源都相同时，层叠的最后一道判定是书写顺序：靠后的声明胜出，"
        "因此第三方库样式应放在自己的样式之前。",
    },
    {
        "id": "js-q17",
        "before": "在 JavaScript 中，用 const 声明的对象，其内部属性仍然可以被修改。",
        "statement": "在 JavaScript 中，用 const 声明的对象，其内部属性也被冻结，不能再被修改。",
        "explanation": "const 只保证绑定不可重新赋值，对象本身的属性仍可增删改；"
        "需要不可变可配合 Object.freeze（浅冻结）或改用不可变数据结构。",
    },
    {
        "id": "js-q19",
        "before": "在 for 循环中用 var 声明的循环变量被闭包捕获时，所有回调读到的都是循环结束后的最终值。",
        "statement": "在 for 循环中用 let 声明的循环变量被闭包捕获时，所有回调读到的都是循环结束后的最终值。",
        "explanation": "let 为每次迭代创建新的绑定，各回调读到各自迭代的值；"
        "只有 var 才是函数作用域，全部回调读到循环结束后的最终值。",
    },
    {
        "id": "ts-q18",
        "before": "TypeScript 中 interface 与 type 都能描述对象形状，而 interface 支持同名声明合并。",
        "statement": "TypeScript 中 interface 与 type 都能描述对象形状，并且都能同名重复声明并自动合并。",
        "explanation": "只有 interface 支持同名声明合并；type 别名重复声明会直接编译报错。",
    },
    {
        "id": "ts-q19",
        "before": "在 TypeScript 中 any 与 unknown 都能接收任意值，但只有 any 可以在不做收窄的情况下直接访问其属性或调用。",
        "statement": "在 TypeScript 中 any 与 unknown 都能接收任意值，而且两者都可以在不收窄的情况下直接访问属性或调用。",
        "explanation": "any 完全绕过类型检查，可以直接调用；unknown 只能赋值与比较，"
        "访问成员前必须先收窄，这正是它更安全的原因。",
    },
    {
        "id": "ts-q20",
        "before": "never 是所有类型的子类型，因此可以把 never 类型的值赋给任意类型的变量。",
        "statement": "never 类型的值不能赋给任何其他类型的变量，只能用 any 接收。",
        "explanation": "never 是底类型，可以赋值给任何类型；反过来只有 never 能接收 never，"
        "它常用于穷尽性检查，让漏掉的分支在编译期暴露。",
    },
    {
        "id": "vue3-q18",
        "before": "Vue 3 的 reactive 对字符串、数字这类基本类型无效，保存基本类型状态应使用 ref。",
        "statement": "Vue 3 的 reactive 对字符串、数字这类基本类型同样有效，保存基本类型状态应使用 reactive。",
        "explanation": "reactive 基于 Proxy 代理对象，基本类型没有可代理的属性读写；"
        "基本类型状态应用 ref，模板中自动解包。",
    },
    {
        "id": "vue3-q19",
        "before": "在 Vue 3 中，给 reactive 数组按下标赋值（如 arr[0] = 1）可以触发视图更新。",
        "statement": "在 Vue 3 中，给 reactive 数组按下标赋值（如 arr[0] = 1）不会触发视图更新，必须改用 splice。",
        "explanation": "Vue 3 用 Proxy 能拦截数组索引赋值，因此 arr[0] = 1 会正常触发更新；"
        "必须用 splice 的是 Vue 2 的 defineProperty 方案。",
    },
    {
        "id": "react-q18",
        "before": "父组件重新渲染时，其子组件默认也会重新渲染，除非子组件用 React.memo 等手段做了优化。",
        "statement": "父组件重新渲染时，其子组件默认不会重新渲染，必须由子组件自己触发更新。",
        "explanation": "默认行为是父渲染带动子渲染；React.memo 对 props 做浅比较才可跳过，"
        "配合 useCallback/useMemo 保持引用稳定才真正有效。",
    },
    {
        "id": "react-q19",
        "before": "useEffect 的依赖数组若遗漏了 Effect 内使用的某个变量，可能导致回调一直读到旧的闭包值（stale closure）。",
        "statement": "useEffect 的依赖数组即使遗漏了 Effect 内使用的变量，回调也一定能读到该变量最新的值。",
        "explanation": "Effect 捕获的是创建时那次渲染的变量快照，依赖漏写就不会重新创建，"
        "可能读到过期值（stale closure）；应写全依赖或用函数式更新规避。",
    },
    {
        "id": "react-q20",
        "before": "React 18 在同一个事件处理函数中多次调用 setState 会自动批处理，只触发一次重新渲染。",
        "statement": "React 18 在同一个事件处理函数中多次调用 setState，每次调用都会各自触发一次重新渲染。",
        "explanation": "React 18 的自动批处理覆盖事件处理、Promise、setTimeout 等场景，"
        "多次更新合并为一次渲染；需要立即读取 DOM 时用 flushSync 显式同步刷新。",
    },
    {
        "id": "l100-011",
        "before": "CORS 预检请求（OPTIONS）会在请求携带 Authorization 头或 Content-Type 为 application/json 时触发。",
        "statement": "CORS 预检请求（OPTIONS）只在请求方法为 GET 时触发，携带 Authorization 头不会触发预检。",
        "explanation": "预检针对非简单请求触发：携带自定义头（如 Authorization）、"
        "Content-Type 为 application/json 等都会触发；浏览器先发 OPTIONS 询问服务端，"
        "服务端需正确响应 Access-Control-Allow-* 头。",
    },
    {
        "id": "l100-028",
        "before": "B+ 树索引因为叶子节点有序且链表相连，所以范围查询只需顺序遍历，比 HashMap 更适合范围查询。",
        "statement": "B+ 树索引的叶子节点无序且互不相连，因此范围查询必须全表扫描，不如 HashMap 适合范围查询。",
        "explanation": "B+ 树叶子节点有序且通过链表相连，范围扫描只需顺序遍历；"
        "HashMap 无序且只支持等值查询，范围查询需全扫。B+ 树高度低、IO 友好，适合数据库索引。",
    },
    {
        "id": "l100-047",
        "before": "数据库死锁的产生通常是因为两个事务以不一致的顺序加锁，导致互相等待对方持有的锁。",
        "statement": "数据库死锁只会发生在单个事务内部，与多个事务的加锁顺序无关。",
        "explanation": "死锁的典型原因是事务交叉加锁顺序不一致，形成循环等待；"
        "排查可看事务等待图，避免手段包括统一加锁顺序、缩短事务、降低隔离级别、控制批量。",
    },
    {
        "id": "l100-063",
        "before": "模型网关（LLM gateway）的主要作用之一是统一接入多种模型并屏蔽差异。",
        "statement": "模型网关（LLM gateway）的主要作用是训练大模型，无法统一接入多种模型。",
        "explanation": "模型网关的核心作用就是统一接入多种模型（OpenAI、自建、国产等）、"
        "屏蔽差异并统一 API，不负责训练。",
    },
    {
        "id": "l100-088",
        "before": "OpenTelemetry 提供厂商无关的 SDK 和 Collector，可以统一采集 logs、metrics、traces 并导出到后端。",
        "statement": "OpenTelemetry 只能采集 traces，不支持 logs 与 metrics，也不提供 Collector。",
        "explanation": "OpenTelemetry 确实提供厂商无关的 SDK 与 Collector，可统一采集 logs、metrics、traces "
        "并导出到多种后端（如 Jaeger、Tempo），三者可通过 trace_id 关联。",
    },
    {
        "id": "iq380-036",
        "before": "在 React 中，ErrorBoundary 可以捕获组件渲染期间发生的错误，并展示降级 UI。",
        "statement": "在 React 中，ErrorBoundary 可以捕获事件处理函数与异步代码中抛出的错误。",
        "explanation": "ErrorBoundary 只能捕获其子组件树在渲染期间发生的错误并展示降级 UI；"
        "事件处理、异步错误需配合 window.onerror 或 unhandledrejection 进行全局捕获。",
    },
    {
        "id": "iq380-015",
        "before": "在 SSR 中，服务端与客户端首次渲染结果不一致（如使用 Date.now 或 Math.random）可能导致 hydration mismatch。",
        "statement": "在 SSR 中，服务端与客户端首次渲染结果不一致不会造成任何问题，React 会自动把两端内容对齐。",
        "explanation": "水合不匹配的核心原因正是两端渲染出的 HTML 不同："
        "Date.now、Math.random 等非确定性值会触发文本差异告警或结构差异报错。",
    },
)


def _content_hash(*parts: str) -> str:
    """内容身份哈希：同一 `id` 与同一选项文本恒得同一序（幂等的依据）。"""
    return hashlib.sha256(_HASH_SEP.join(parts).encode("utf-8")).hexdigest()


def classify_refs(text: str, valid_keys: set[str]) -> tuple[dict[int, str], list[int]]:
    """返回（已确定的选项引用 文本位置 -> 字母, 无法判角的字母位置）。

    只认「显式形式 / 字母清单 / 字母 + 判角短语」三类；被语言名、`++`、`#`、`/`
    包裹的字母判为非引用。返回的第二个列表非空即表示该题解析判角不可靠。
    """
    known: dict[int, str] = {}
    for match in _EXPLICIT.finditer(text):
        letter = match.group(1) or match.group(2)
        start = match.start(1) if match.group(1) else match.start(2)
        if letter in valid_keys:
            known[start] = letter
    for match in _LIST.finditer(text):
        letters = re.findall(r"[ABCD]", match.group(0))
        if not all(letter in valid_keys for letter in letters):
            continue
        for token in _TOKEN.finditer(match.group(0)):
            known[match.start() + token.start()] = token.group(0)
    for token in _TOKEN.finditer(text):
        if any(abs(token.start() - pos) <= 3 for pos in known):
            continue
        if _LANG_GUARD.match(text, token.start()):
            continue
        tail = text[token.end() : token.end() + 6].lstrip()
        if tail.startswith(_VERDICT_TAIL) and token.group(0) in valid_keys:
            known[token.start()] = token.group(0)
    unknown: list[int] = []
    for token in _TOKEN.finditer(text):
        if any(abs(token.start() - pos) <= 2 for pos in known):
            continue
        if _LANG_GUARD.match(text, token.start()):
            continue
        unknown.append(token.start())
    return known, unknown


def _remap_text(text: str, refs: dict[int, str], mapping: dict[str, str]) -> str:
    """按 key 映射重写解析里的字母引用（位置逐个替换，不碰其它文本）。"""
    if not refs:
        return text
    out: list[str] = []
    last = 0
    for pos, letter in sorted(refs.items()):
        out.append(text[last:pos])
        out.append(mapping.get(letter, letter))
        last = pos + 1
    out.append(text[last:])
    return "".join(out)


def _answer_counts(rows: Sequence[dict[str, Any]], kind: str) -> dict[str, int]:
    """某一题型的答案 key 分布（单选题取唯一 key；判断题同理）。"""
    counts: Counter[str] = Counter()
    for row in rows:
        if str(row.get("kind") or "") != kind:
            continue
        answer = row.get("answer") or []
        if len(answer) == 1:
            counts[str(answer[0])] += 1
    return {key: counts.get(key, 0) for key in KEYS}


def _length_ratio(row: dict[str, Any]) -> float:
    """正确项平均长度 / 干扰项平均长度；干扰项缺失时返回 0。"""
    options = row.get("options") or []
    correct = {str(key) for key in row.get("answer") or []}
    right = [len(str(opt.get("text") or "")) for opt in options if str(opt.get("key")) in correct]
    wrong = [len(str(opt.get("text") or "")) for opt in options if str(opt.get("key")) not in correct]
    if not right or not wrong:
        return 0.0
    return (sum(right) / len(right)) / max(1, sum(wrong) / len(wrong))


def _asks_negative(prompt: str) -> bool:
    """题面是否在问「哪一项是错的」（命中方向词即判定词极性反向）。"""
    return any(marker in prompt for marker in _NEGATIVE_ASK)


def _refs_consistency(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """解析字母引用与答案的双校验（`X 项错误 ⇔ X ∉ answer` / 正确项集合 == answer）。

    只校验「判角可靠」的题（`classify_refs` 报出未知字母的题整题保持原序，其原文与 key
    本来就自洽，不在此处重复判定）。题面问「错误的是」时极性反向（见 `_NEGATIVE_ASK`）。
    返回（校验对数 / 违规清单 / 已人工核对清单 / 反向题面条数）。
    """
    pairs = 0
    inverted_rows = 0
    violations: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("kind") or "") not in ("single", "multiple"):
            continue
        text = str(row.get("explanation") or "")
        valid = {str(opt.get("key") or "") for opt in row.get("options") or []}
        refs, unknown = classify_refs(text, valid)
        if unknown:
            continue
        answer = [str(key) for key in row.get("answer") or []]
        inverted = _asks_negative(str(row.get("prompt") or ""))
        if inverted:
            inverted_rows += 1
        for position, letter in sorted(refs.items()):
            tail = text[position + 1 : position + 8].lstrip()
            if tail.startswith(_VERDICT_NEGATIVE):
                expect_in_answer = False
            elif tail.startswith(_VERDICT_POSITIVE):
                expect_in_answer = True
            else:
                continue
            if inverted:
                expect_in_answer = not expect_in_answer
            pairs += 1
            if (letter in answer) != expect_in_answer:
                violations.append(
                    {
                        "id": str(row.get("id") or ""),
                        "letter": letter,
                        "expect": "in_answer" if expect_in_answer else "not_in_answer",
                        "snippet": text[max(0, position - 6) : position + 6],
                    }
                )
        expected_set = sorted(key for key in valid if key not in answer) if inverted else sorted(answer)
        for match in _SET_PHRASE.finditer(text):
            letters = sorted(re.findall(r"[ABCD]", match.group(0)))
            if not letters or not all(letter in valid for letter in letters):
                continue
            pairs += 1
            if letters != expected_set:
                violations.append(
                    {
                        "id": str(row.get("id") or ""),
                        "letter": "".join(letters),
                        "expect": "".join(expected_set),
                        "snippet": match.group(0),
                    }
                )
    reviewed = [
        {"id": item_id, "note": note}
        for item_id, note in _CONSISTENCY_REVIEWED.items()
        if any(item["id"] == item_id for item in violations)
    ]
    open_violations = [item for item in violations if item["id"] not in _CONSISTENCY_REVIEWED]
    return {
        "pairs": pairs,
        "violations": open_violations,
        "reviewed": reviewed,
        "negative_ask_rows": inverted_rows,
        "ok": not open_violations,
    }


def _length_metrics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """答案长度比分布：>3x 清单（id + 比值）、2-3x 条数、全量中位数。"""
    ratios = [
        (str(row.get("id") or ""), _length_ratio(row))
        for row in rows
        if str(row.get("kind") or "") in ("single", "multiple")
    ]
    ratios = [item for item in ratios if item[1] > 0]
    long_items = sorted((item for item in ratios if item[1] > _LENGTH_RATIO_LONG), key=lambda x: -x[1])
    watch_items = [item for item in ratios if _LENGTH_RATIO_WATCH < item[1] <= _LENGTH_RATIO_LONG]
    values = sorted(ratio for _id, ratio in ratios)
    middle = values[len(values) // 2] if values else 0.0
    return {
        "sample": len(ratios),
        "long": [{"id": item_id, "ratio": round(ratio, 2)} for item_id, ratio in long_items],
        "watch_count": len(watch_items),
        "median": round(middle, 2),
    }


def apply(rows: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """按内容定序重排选项并重编 key、按绝对表改写判断题陈述，返回（新行, 指标）。

    不改入参、无 IO、幂等；解析判角不可靠（`classify_refs` 报出未知字母）或选项数不是
    四道的题**保持原序**（计入 `skipped`），不猜。重写后的字母引用由 `_refs_consistency()`
    按「`X 项错误 ⇔ X ∉ answer`」与「正确项集合 == answer」双校验，结果进 `metrics`。
    """
    original = [dict(row) for row in rows]
    before_single = _answer_counts(original, "single")
    before_judge = _answer_counts(original, "judge")

    counters: dict[str, int] = {key: 0 for key in KEYS}
    skipped: list[str] = []
    multi_shuffled = 0
    replace: dict[str, dict[str, Any]] = {}

    movable = sorted(
        (row for row in original if str(row.get("kind") or "") in ("single", "multiple")),
        key=lambda row: (_content_hash(str(row.get("id") or ""), "order"), str(row.get("id") or "")),
    )
    for row in movable:
        options = row.get("options") or []
        valid = {str(opt.get("key") or "") for opt in options}
        refs, unknown = classify_refs(str(row.get("explanation") or ""), valid)
        if len(valid) != len(KEYS) or unknown or not valid <= set(KEYS):
            if str(row.get("kind") or "") == "single":
                answer = row.get("answer") or []
                if len(answer) == 1:
                    counters[str(answer[0])] += 1
            skipped.append(str(row.get("id") or ""))
            continue
        ordered = sorted(
            options,
            key=lambda opt: (
                _content_hash(str(row.get("id") or ""), str(opt.get("text") or "")),
                str(opt.get("text") or ""),
            ),
        )
        if str(row.get("kind") or "") == "single":
            answer_key = str((row.get("answer") or [""])[0])
            distractors = [opt for opt in ordered if str(opt["key"]) != answer_key]
            position = min(KEYS, key=lambda key: counters[key])
            slots = [key for key in KEYS if key != position]
            mapping: dict[str, str] = {answer_key: position}
            for slot, opt in zip(slots, distractors):
                mapping[str(opt["key"])] = slot
            counters[position] += 1
        else:
            mapping = {str(opt["key"]): KEYS[index] for index, opt in enumerate(ordered)}
            multi_shuffled += 1
        updated = dict(row)
        placed = {mapping[str(opt["key"])]: str(opt.get("text") or "") for opt in ordered}
        updated["options"] = [{"key": key, "text": placed[key]} for key in KEYS]
        updated["answer"] = sorted(mapping[str(key)] for key in row.get("answer") or [])
        updated["explanation"] = _remap_text(
            str(row.get("explanation") or ""), refs, mapping
        )
        replace[str(row.get("id") or "")] = updated

    flips = {str(item["id"]): item for item in JUDGE_FLIPS}
    for row in original:
        if str(row.get("kind") or "") != "judge":
            continue
        item = flips.get(str(row.get("id") or ""))
        if item is None:
            continue
        updated = dict(row)
        updated["prompt"] = item["statement"]
        updated["answer"] = ["B"]
        updated["explanation"] = item["explanation"]
        replace[str(row.get("id") or "")] = updated

    result = [replace.get(str(row.get("id") or ""), row) for row in original]
    after_single = _answer_counts(result, "single")
    after_judge = _answer_counts(result, "judge")
    metrics: dict[str, Any] = {
        "total": len(result),
        "single": {
            "count": sum(after_single.values()),
            "before": before_single,
            "after": after_single,
        },
        "judge": {
            "count": sum(after_judge.values()),
            "before": before_judge,
            "after": after_judge,
            "flipped": len(JUDGE_FLIPS),
            "rows": [
                {
                    "id": str(item["id"]),
                    "before": str(item["before"]),
                    "statement": str(item["statement"]),
                    "explanation": str(item["explanation"]),
                }
                for item in JUDGE_FLIPS
            ],
        },
        "multiple": {"shuffled": multi_shuffled},
        "shuffled": len(replace) - len(JUDGE_FLIPS),
        "skipped": {"count": len(skipped), "ids": skipped},
        "length_ratio": _length_metrics(result),
        # 双校验：重写后的字母引用必须仍与 answer 自洽（错位=解析指向错项，必须红）。
        "refs_consistency": _refs_consistency(result),
    }
    return result, metrics


def _percentages(counts: dict[str, int]) -> str:
    """把位置计数渲染成 `A 138（25.0%）` 这样的表格行单元格。"""
    total = sum(counts.values()) or 1
    return " | ".join(f"{key} {counts[key]}（{counts[key] / total * 100:.1f}%）" for key in KEYS)


def _refs_section(metrics: dict[str, Any]) -> list[str]:
    """第 6 节：解析字母引用双校验（对数 / 违规清单 / 人工核对说明）。"""
    refs = metrics.get("refs_consistency") or {}
    pairs = int(refs.get("pairs") or 0)
    violations = refs.get("violations") or []
    reviewed = refs.get("reviewed") or []
    lines = [
        "## 6 解析字母引用一致性（双校验）",
        "",
        "重编 key 后，解析里的字母引用按同一映射重写；再用两条口径复算，"
        "任一不成立即视为「解析指向错项」：",
        "",
        "- `X 项错误 ⇔ X ∉ answer`（同理「`X 项正确` ⇒ `X ∈ answer`」）；"
        "题面问「以下说法错误的是」时极性反向（`_NEGATIVE_ASK`）；",
        "- 「正确项为 A、B、D」这类集合句的字母集合 == `answer`。",
        "",
        f"- 校验对：{pairs} 处",
        f"- 反向题面（问「错误的是」）：{int(refs.get('negative_ask_rows') or 0)} 道，已按反向极性复算",
        f"- 违规：{len(violations)} 处" + ("（**必须修到 0**）" if violations else ""),
        "",
    ]
    if violations:
        lines.append("| id | 字母 | 期望 | 上下文 |")
        lines.append("| --- | --- | --- | --- |")
        cell = _cell
        for item in violations:
            lines.append(
                f"| {cell(str(item.get('id') or ''))} | {cell(str(item.get('letter') or ''))} "
                f"| {cell(str(item.get('expect') or ''))} | {cell(str(item.get('snippet') or ''))} |"
            )
        lines.append("")
    if reviewed:
        lines.append("已人工核对（不计入违规，理由逐条写明）：")
        lines.append("")
        for item in reviewed:
            lines.append(f"- `{item.get('id')}`：{item.get('note')}")
        lines.append("")
    else:
        lines.append(
            "已人工核对清单为空：唯一被判定词误伤的 `iq380-164`（题面「以下说法错误的是」、"
            "解析「因此 C 错误」正指 C 为应选项）已由方向反转复算覆盖，无需白名单。"
        )
        lines.append("")
    return lines


def render_report(metrics: dict[str, Any]) -> str:
    """`SHUFFLE-REPORT.md` 正文：只吃 `apply()` 的指标，不手抄任何数字。"""
    total = int(metrics.get("total") or 0)
    single = metrics.get("single") or {}
    judge = metrics.get("judge") or {}
    multiple = metrics.get("multiple") or {}
    skipped = metrics.get("skipped") or {}
    ratio = metrics.get("length_ratio") or {}
    single_after = single.get("after") or {}
    single_before = single.get("before") or {}
    judge_after = judge.get("after") or {}
    judge_before = judge.get("before") or {}
    skipped_ids = list(skipped.get("ids") or [])
    lines: list[str] = [
        "# r13 答案位置偏置修复报表（SHUFFLE-REPORT）",
        "",
        "> 本文件由 `python -X utf8 -m app.services.question_shuffle --write` 生成（"
        "`question_shuffle.render_report()`），"
        "指标与 `seed/questions.json` 同源；手抄数字会在下次重算时漂移，因此不得手改。",
        "",
        "## 1 概览",
        "",
        f"- 题库总行数：{total}",
        f"- 重排并重编 key 的题：{int(metrics.get('shuffled') or 0)}"
        f"（单选 + 多选；多选 {int(multiple.get('shuffled') or 0)} 道）",
        f"- 判断题极性改写：{int(judge.get('flipped') or 0)} 条",
        f"- 保持原序（解析判角不可靠）：{int(skipped.get('count') or 0)} 道",
        "",
        "## 2 单选题答案位置分布（前 → 后）",
        "",
        "| 阶段 | " + " | ".join(KEYS) + " |",
        "| --- | " + " | ".join("---" for _ in KEYS) + " |",
        f"| 重算前（本次输入） | {_percentages(single_before)} |",
        f"| 重算后（落盘） | {_percentages(single_after)} |",
        "",
        "- 口径：本表是本次 `build_seed()` 重算的**输入 / 输出**。输入 = 素材按原始顺序归一化后的"
        "行（偏置源）+ 已落盘的存量行（上一轮已打乱，因此拉低了打乱前的 A 占比）；输出 = 落盘 seed。"
        "两栏随同一份指标一起生成，干跑 `--report` 可复现同样的数字。",
        "- 整库真·r13 前基线（r12 提交 `eada0e3` 的 seed：单选 A 323＝58.6%、判断 A 107＝68.6%）"
        "是 r13 开工时的一次性实测值，记录在技术变更单 §1/§3；复算命令："
        "`git show eada0e3:backend/app/seed/questions.json`。",
        f"- 样本：{int(single.get('count') or 0)} 道单选（含未打乱的保持原序题，"
        "因此分布由其余题补偿，这正是「轮转填最低计数位置」的作用）。",
        "",
        "## 3 判断题极性分布（前 → 后）",
        "",
        "| 阶段 | " + " | ".join(KEYS) + " |",
        "| --- | " + " | ".join("---" for _ in KEYS) + " |",
        f"| 重算前（本次输入） | {_percentages(judge_before)} |",
        f"| 重算后（落盘） | {_percentages(judge_after)} |",
        "",
        "判断题**只改陈述、不动选项**（选项恒为 `A. 正确 / B. 错误`，顺序固定），"
        "极性靠下半张表里的绝对映射达成。本节「重算前」同样是本次流水线的输入"
        "（素材原序的判断题 + 已落盘存量），整库原始基线 A 107＝68.6% 见 §2 口径说明。",
        "",
        "## 4 判断题极性改写对照（原句 → 新句）",
        "",
        "| # | id | 原句（基线，答案为「正确」） | 新句（改写后答案为「错误」） | 解析 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for index, item in enumerate(judge.get("rows") or [], start=1):
        cell = _cell
        lines.append(
            f"| {index} | {cell(str(item.get('id') or ''))} | {cell(str(item.get('before') or ''))} "
            f"| {cell(str(item.get('statement') or ''))} | {cell(str(item.get('explanation') or ''))} |"
        )
    lines += [
        "",
        "## 5 答案长度比（正确项平均长度 / 干扰项平均长度）",
        "",
        f"- 样本：{int(ratio.get('sample') or 0)} 道（单选 + 多选）",
        f"- 中位比值：{ratio.get('median')}",
        f"- 2–3x 抽检清单：{int(ratio.get('watch_count') or 0)} 道",
        f"- >3x 清单：{len(ratio.get('long') or [])} 道（**只出裁剪建议，不自动改写语义**）",
        "",
    ]
    long_items = ratio.get("long") or []
    if long_items:
        lines.append("| id | 比值 |")
        lines.append("| --- | --- |")
        for item in long_items:
            lines.append(f"| {_cell(str(item.get('id') or ''))} | {item.get('ratio')} |")
        lines.append("")
    lines += _refs_section(metrics)
    lines += [
        "## 7 保持原序的题（解析字母引用判角不可靠）",
        "",
        f"共 {int(skipped.get('count') or 0)} 道：这些题的解析里出现了无法确定指向的字母"
        "（如 `C 语言`、`C++`、`ACID` 等结构性误伤），按安全优先**不打乱**，"
        "原文与 key 保持自洽，交人工评审后再改写解析。",
        "",
    ]
    if skipped_ids:
        lines.append("```text")
        lines.append(" ".join(skipped_ids))
        lines.append("```")
        lines.append("")
    lines += [
        "## 8 幂等与门禁（可复跑的证据）",
        "",
        "```bash",
        "cd backend && python -X utf8 -m app.services.question_shuffle --check   # 0 差异（只读）",
        "cd backend && python -X utf8 -m app.services.question_merge --check      # 0 差异（打乱已并入重算）",
        "cd backend && python -X utf8 -m app.services.question_shuffle --write    # 再次写盘后 seed 逐字节不变",
        "cd backend && python -X utf8 -m pytest -q -p no:cacheprovider tests/test_r13_question_shuffle.py",
        "```",
        "",
        "变红方向（常驻门禁 `test_r13_question_shuffle.py` 覆盖）：把全部单选答案改成 A、"
        "清空 `JUDGE_FLIPS`、把 `answer` 挪出 `options` —— 位置分布 / 极性 / key 闭集三条断言各红。",
        "",
        "## 9 运行时不受影响",
        "",
        "本模块是**离线工具**：运行时（`question_bank` / `exam` / `practice` / `proficiency`）"
        "永不 import 它；变换只落在被 git 追踪的 `seed/questions.json` 上，"
        "序列化仍只经 `question_merge.dumps()` 一处。存量 `app.db` 因 `ON CONFLICT DO NOTHING` "
        "不刷新（本需求已显式接受，见技术变更单 §4/§7）。",
        "",
    ]
    return "\n".join(lines)


def _cell(value: str) -> str:
    """Markdown 表格单元格转义：竖线与换行不得破坏表格。"""
    return value.replace("|", "\\|").replace("\n", " ")


def check(seed_path: Path | None = None, staging_dir: Path | None = None) -> bool:
    """重算到字节比对（只读）：打乱后 `seed` 应与「素材重算 + apply」逐字节一致。"""
    from app.services import question_merge

    target = Path(seed_path) if seed_path is not None else question_merge.SEED_PATH
    staging = Path(staging_dir) if staging_dir is not None else question_merge.STAGING_DIR
    rows, _stats = question_merge.build_seed(staging, target)
    expected = question_merge.dumps(rows).encode("utf-8")
    return target.read_bytes() == expected


def main(argv: list[str] | None = None) -> int:
    """离线入口：`--check` / `--write`（委托 `question_merge.write`）/ `--report`。"""
    args = list(sys.argv[1:] if argv is None else argv)
    if "--check" in args:
        if check():
            print("打乱后的 seed 与素材重算逐字节一致（幂等成立）")
            return 0
        print("打乱后的 seed 与素材重算不一致：请重跑 --write 后提交 seed 与报表")
        return 1
    if "--write" in args:
        from app.services import question_merge

        result = question_merge.write()
        print(f"已写入 {result['total']} 条（{result['bytes']} 字节）；报表 {result['shuffle_report_path']}")
        return 0
    if "--report" in args:
        from app.services import question_merge

        # 干跑必须与 `--write` 同一条流水线（`build_seed` 的 `apply()` 指标），
        # 否则「素材原序 + 已是固定点的磁盘 seed」两种输入会让报表数字对不上交付物。
        _rows, stats = question_merge.build_seed()
        print(render_report(stats.get("shuffle") or {}))
        return 0
    print("用法：python -X utf8 -m app.services.question_shuffle --check | --write | --report")
    return 2


if __name__ == "__main__":  # pragma: no cover - 手工离线入口
    raise SystemExit(main())
