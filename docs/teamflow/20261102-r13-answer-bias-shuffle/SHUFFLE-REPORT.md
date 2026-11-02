# r13 答案位置偏置修复报表（SHUFFLE-REPORT）

> 本文件由 `python -X utf8 -m app.services.question_shuffle --write` 生成（`question_shuffle.render_report()`），指标与 `seed/questions.json` 同源；手抄数字会在下次重算时漂移，因此不得手改。

## 1 概览

- 题库总行数：779
- 重排并重编 key 的题：505（单选 + 多选；多选 59 道）
- 判断题极性改写：29 条
- 保持原序（解析判角不可靠）：106 道

## 2 单选题答案位置分布（前 → 后）

| 阶段 | A | B | C | D |
| --- | --- | --- | --- | --- |
| 重算前（本次输入） | A 236（42.8%） | B 172（31.2%） | C 87（15.8%） | D 56（10.2%） |
| 重算后（落盘） | A 139（25.2%） | B 138（25.0%） | C 137（24.9%） | D 137（24.9%） |

- 口径：本表是本次 `build_seed()` 重算的**输入 / 输出**。输入 = 素材按原始顺序归一化后的行（偏置源）+ 已落盘的存量行（上一轮已打乱，因此拉低了打乱前的 A 占比）；输出 = 落盘 seed。两栏随同一份指标一起生成，干跑 `--report` 可复现同样的数字。
- 整库真·r13 前基线（r12 提交 `eada0e3` 的 seed：单选 A 323＝58.6%、判断 A 107＝68.6%）是 r13 开工时的一次性实测值，记录在技术变更单 §1/§3；复算命令：`git show eada0e3:backend/app/seed/questions.json`。
- 样本：551 道单选（含未打乱的保持原序题，因此分布由其余题补偿，这正是「轮转填最低计数位置」的作用）。

## 3 判断题极性分布（前 → 后）

| 阶段 | A | B | C | D |
| --- | --- | --- | --- | --- |
| 重算前（本次输入） | A 87（55.8%） | B 69（44.2%） | C 0（0.0%） | D 0（0.0%） |
| 重算后（落盘） | A 78（50.0%） | B 78（50.0%） | C 0（0.0%） | D 0（0.0%） |

判断题**只改陈述、不动选项**（选项恒为 `A. 正确 / B. 错误`，顺序固定），极性靠下半张表里的绝对映射达成。本节「重算前」同样是本次流水线的输入（素材原序的判断题 + 已落盘存量），整库原始基线 A 107＝68.6% 见 §2 口径说明。

## 4 判断题极性改写对照（原句 → 新句）

| # | id | 原句（基线，答案为「正确」） | 新句（改写后答案为「错误」） | 解析 |
| --- | --- | --- | --- | --- |
| 1 | tiji-017 | 在 JavaScript 中，`==` 会比较值并允许隐式类型转换，而 `===` 要求类型与值都相等。 | 在 JavaScript 中，`==` 只比较值且不做任何类型转换，而 `===` 允许隐式类型转换。 | 说反了：`==` 才做隐式类型转换（'1'==1 为 true），`===` 严格比较类型与值，不做转换（'1'===1 为 false）。 |
| 2 | tiji-019 | 栈（stack）是一种后进先出（LIFO）的数据结构。 | 栈（stack）是一种先进先出（FIFO）的数据结构。 | 栈只能在一端插入与删除，最后压入的最先弹出，是后进先出（LIFO）；先进先出（FIFO）是队列的特性。 |
| 3 | py-q18 | Python 的 list 与 tuple 都可以容纳不同类型的元素，tuple 创建后其元素引用不能再被替换。 | Python 的 tuple 创建后其元素引用仍可被任意替换，因此 tuple 与 list 一样是可变容器。 | tuple 的元素引用不可替换、也不能增删，是不可变容器；只有元素本身是可变对象（如 tuple 里放 list）时其内容才可变。 |
| 4 | py-q20 | 在 CPython 中，由于小整数缓存（-5 到 256），相同数值的两个变量用 is 比较可能返回 True。 | 在 CPython 中，两个数值相同的 int 变量用 is 比较一定返回 False，因为小整数不会被缓存。 | CPython 会缓存 -5 到 256 的小整数对象，该区间内 a is b 可能为 True；is 是身份比较，判断值相等始终应使用 ==。 |
| 5 | java-q17 | Java 中 int 是基本类型、Integer 是包装类，Integer 类型的变量可以为 null。 | Java 中 int 是基本类型、Integer 是包装类，但 Integer 类型的变量不能为 null。 | Integer 是引用类型，未赋值时默认就是 null；int 才是不能为 null 的基本类型，自动拆箱遇到 null 还会抛 NullPointerException。 |
| 6 | java-q19 | Java 的 finally 块中出现 return 语句时，会覆盖 try 块中已经计算出的返回值。 | Java 的 finally 块中出现 return 语句时，不会影响 try 块中已经计算出的返回值。 | finally 在方法真正返回前执行，其中的 return 会直接结束方法并覆盖 try 的返回值，同时还会吞掉异常。 |
| 7 | go-q18 | Go 的 map 是引用语义，把 map 传给函数后，函数内新增的键在调用方可见。 | Go 的 map 是值语义，把 map 传给函数后，函数内新增的键在调用方不可见。 | map 变量内部是指向运行时哈希表的指针，按值传递复制的是这个指针，因此函数内增删键对调用方可见；只有函数内重新 make 才不影响调用方。 |
| 8 | go-q19 | 在 Go 中，向已关闭的 channel 发送数据会触发 panic，而从已关闭的 channel 接收会立即返回零值。 | 在 Go 中，向已关闭的 channel 发送数据不会触发 panic，而从已关闭的 channel 接收会一直阻塞。 | 向已关闭的 channel 发送会 panic（send on closed channel）；接收则立即返回剩余缓冲数据或零值，第二返回值 ok 为 false。 |
| 9 | html-q18 | <input type="button"> 与 <button> 都能生成可点击按钮，但 <button> 内部可以包含图标等 HTML 元素。 | <input type="button"> 与 <button> 都能生成可点击按钮，但 <button> 内部只能放纯文本。 | input 是空元素，value 只能是纯文本；button 是容器元素，可以嵌套文本与图标。注意 button 默认 type 是 submit，在表单里需显式写 type="button"。 |
| 10 | html-q19 | img 是空元素（void element），没有结束标签，因此不需要写 </img>。 | img 元素必须写结束标签 </img>，否则浏览器会忽略这张图片。 | img、br、hr、input、meta、link 等都是空元素，不能有子内容，因此没有结束标签；在 JSX 等 XML 风格语法中会写成自闭合的 <img />。 |
| 11 | css-q18 | box-sizing: border-box 会让 width 包含 padding 与 border，但不包含 margin。 | box-sizing: border-box 会让 width 包含 margin，但不包含 padding 与 border。 | border-box 把 padding 与 border 计入 width，margin 始终在盒子之外，不参与 width 计算。 |
| 12 | css-q20 | 在 CSS 层叠计算中，两条规则优先级相同时，后出现的声明会覆盖先出现的声明。 | 在 CSS 层叠计算中，两条规则优先级相同时，先出现的声明会覆盖后出现的声明。 | 权重与来源都相同时，层叠的最后一道判定是书写顺序：靠后的声明胜出，因此第三方库样式应放在自己的样式之前。 |
| 13 | js-q17 | 在 JavaScript 中，用 const 声明的对象，其内部属性仍然可以被修改。 | 在 JavaScript 中，用 const 声明的对象，其内部属性也被冻结，不能再被修改。 | const 只保证绑定不可重新赋值，对象本身的属性仍可增删改；需要不可变可配合 Object.freeze（浅冻结）或改用不可变数据结构。 |
| 14 | js-q19 | 在 for 循环中用 var 声明的循环变量被闭包捕获时，所有回调读到的都是循环结束后的最终值。 | 在 for 循环中用 let 声明的循环变量被闭包捕获时，所有回调读到的都是循环结束后的最终值。 | let 为每次迭代创建新的绑定，各回调读到各自迭代的值；只有 var 才是函数作用域，全部回调读到循环结束后的最终值。 |
| 15 | ts-q18 | TypeScript 中 interface 与 type 都能描述对象形状，而 interface 支持同名声明合并。 | TypeScript 中 interface 与 type 都能描述对象形状，并且都能同名重复声明并自动合并。 | 只有 interface 支持同名声明合并；type 别名重复声明会直接编译报错。 |
| 16 | ts-q19 | 在 TypeScript 中 any 与 unknown 都能接收任意值，但只有 any 可以在不做收窄的情况下直接访问其属性或调用。 | 在 TypeScript 中 any 与 unknown 都能接收任意值，而且两者都可以在不收窄的情况下直接访问属性或调用。 | any 完全绕过类型检查，可以直接调用；unknown 只能赋值与比较，访问成员前必须先收窄，这正是它更安全的原因。 |
| 17 | ts-q20 | never 是所有类型的子类型，因此可以把 never 类型的值赋给任意类型的变量。 | never 类型的值不能赋给任何其他类型的变量，只能用 any 接收。 | never 是底类型，可以赋值给任何类型；反过来只有 never 能接收 never，它常用于穷尽性检查，让漏掉的分支在编译期暴露。 |
| 18 | vue3-q18 | Vue 3 的 reactive 对字符串、数字这类基本类型无效，保存基本类型状态应使用 ref。 | Vue 3 的 reactive 对字符串、数字这类基本类型同样有效，保存基本类型状态应使用 reactive。 | reactive 基于 Proxy 代理对象，基本类型没有可代理的属性读写；基本类型状态应用 ref，模板中自动解包。 |
| 19 | vue3-q19 | 在 Vue 3 中，给 reactive 数组按下标赋值（如 arr[0] = 1）可以触发视图更新。 | 在 Vue 3 中，给 reactive 数组按下标赋值（如 arr[0] = 1）不会触发视图更新，必须改用 splice。 | Vue 3 用 Proxy 能拦截数组索引赋值，因此 arr[0] = 1 会正常触发更新；必须用 splice 的是 Vue 2 的 defineProperty 方案。 |
| 20 | react-q18 | 父组件重新渲染时，其子组件默认也会重新渲染，除非子组件用 React.memo 等手段做了优化。 | 父组件重新渲染时，其子组件默认不会重新渲染，必须由子组件自己触发更新。 | 默认行为是父渲染带动子渲染；React.memo 对 props 做浅比较才可跳过，配合 useCallback/useMemo 保持引用稳定才真正有效。 |
| 21 | react-q19 | useEffect 的依赖数组若遗漏了 Effect 内使用的某个变量，可能导致回调一直读到旧的闭包值（stale closure）。 | useEffect 的依赖数组即使遗漏了 Effect 内使用的变量，回调也一定能读到该变量最新的值。 | Effect 捕获的是创建时那次渲染的变量快照，依赖漏写就不会重新创建，可能读到过期值（stale closure）；应写全依赖或用函数式更新规避。 |
| 22 | react-q20 | React 18 在同一个事件处理函数中多次调用 setState 会自动批处理，只触发一次重新渲染。 | React 18 在同一个事件处理函数中多次调用 setState，每次调用都会各自触发一次重新渲染。 | React 18 的自动批处理覆盖事件处理、Promise、setTimeout 等场景，多次更新合并为一次渲染；需要立即读取 DOM 时用 flushSync 显式同步刷新。 |
| 23 | l100-011 | CORS 预检请求（OPTIONS）会在请求携带 Authorization 头或 Content-Type 为 application/json 时触发。 | CORS 预检请求（OPTIONS）只在请求方法为 GET 时触发，携带 Authorization 头不会触发预检。 | 预检针对非简单请求触发：携带自定义头（如 Authorization）、Content-Type 为 application/json 等都会触发；浏览器先发 OPTIONS 询问服务端，服务端需正确响应 Access-Control-Allow-* 头。 |
| 24 | l100-028 | B+ 树索引因为叶子节点有序且链表相连，所以范围查询只需顺序遍历，比 HashMap 更适合范围查询。 | B+ 树索引的叶子节点无序且互不相连，因此范围查询必须全表扫描，不如 HashMap 适合范围查询。 | B+ 树叶子节点有序且通过链表相连，范围扫描只需顺序遍历；HashMap 无序且只支持等值查询，范围查询需全扫。B+ 树高度低、IO 友好，适合数据库索引。 |
| 25 | l100-047 | 数据库死锁的产生通常是因为两个事务以不一致的顺序加锁，导致互相等待对方持有的锁。 | 数据库死锁只会发生在单个事务内部，与多个事务的加锁顺序无关。 | 死锁的典型原因是事务交叉加锁顺序不一致，形成循环等待；排查可看事务等待图，避免手段包括统一加锁顺序、缩短事务、降低隔离级别、控制批量。 |
| 26 | l100-063 | 模型网关（LLM gateway）的主要作用之一是统一接入多种模型并屏蔽差异。 | 模型网关（LLM gateway）的主要作用是训练大模型，无法统一接入多种模型。 | 模型网关的核心作用就是统一接入多种模型（OpenAI、自建、国产等）、屏蔽差异并统一 API，不负责训练。 |
| 27 | l100-088 | OpenTelemetry 提供厂商无关的 SDK 和 Collector，可以统一采集 logs、metrics、traces 并导出到后端。 | OpenTelemetry 只能采集 traces，不支持 logs 与 metrics，也不提供 Collector。 | OpenTelemetry 确实提供厂商无关的 SDK 与 Collector，可统一采集 logs、metrics、traces 并导出到多种后端（如 Jaeger、Tempo），三者可通过 trace_id 关联。 |
| 28 | iq380-036 | 在 React 中，ErrorBoundary 可以捕获组件渲染期间发生的错误，并展示降级 UI。 | 在 React 中，ErrorBoundary 可以捕获事件处理函数与异步代码中抛出的错误。 | ErrorBoundary 只能捕获其子组件树在渲染期间发生的错误并展示降级 UI；事件处理、异步错误需配合 window.onerror 或 unhandledrejection 进行全局捕获。 |
| 29 | iq380-015 | 在 SSR 中，服务端与客户端首次渲染结果不一致（如使用 Date.now 或 Math.random）可能导致 hydration mismatch。 | 在 SSR 中，服务端与客户端首次渲染结果不一致不会造成任何问题，React 会自动把两端内容对齐。 | 水合不匹配的核心原因正是两端渲染出的 HTML 不同：Date.now、Math.random 等非确定性值会触发文本差异告警或结构差异报错。 |

## 5 答案长度比（正确项平均长度 / 干扰项平均长度）

- 样本：611 道（单选 + 多选）
- 中位比值：1.46
- 2–3x 抽检清单：106 道
- >3x 清单：40 道（**只出裁剪建议，不自动改写语义**）

| id | 比值 |
| --- | --- |
| iq380-047 | 7.61 |
| css-q5 | 6.46 |
| html-q2 | 4.8 |
| iq380-310 | 4.71 |
| iq380-131 | 4.65 |
| css-q7 | 4.6 |
| js-q7 | 4.56 |
| ts-q3 | 4.26 |
| java-q8 | 4.17 |
| vue3-q2 | 3.97 |
| iq380-299 | 3.79 |
| java-q7 | 3.73 |
| react-q4 | 3.71 |
| js-q10 | 3.67 |
| react-q5 | 3.67 |
| css-q2 | 3.62 |
| iq380-132 | 3.58 |
| iq380-296 | 3.51 |
| iq380-373 | 3.49 |
| iq380-297 | 3.48 |
| iq380-060 | 3.43 |
| iq380-352 | 3.41 |
| react-q6 | 3.4 |
| cs-q11 | 3.35 |
| react-q2 | 3.34 |
| html-q11 | 3.3 |
| ts-q5 | 3.3 |
| java-q9 | 3.28 |
| l100-019 | 3.28 |
| ts-q7 | 3.22 |
| l100-018 | 3.18 |
| iq380-264 | 3.18 |
| l100-072 | 3.16 |
| vue3-q6 | 3.16 |
| iq380-330 | 3.16 |
| iq380-042 | 3.15 |
| cs-q13 | 3.1 |
| fe-q15 | 3.09 |
| java-q4 | 3.08 |
| iq380-294 | 3.04 |

## 6 解析字母引用一致性（双校验）

重编 key 后，解析里的字母引用按同一映射重写；再用两条口径复算，任一不成立即视为「解析指向错项」：

- `X 项错误 ⇔ X ∉ answer`（同理「`X 项正确` ⇒ `X ∈ answer`」）；题面问「以下说法错误的是」时极性反向（`_NEGATIVE_ASK`）；
- 「正确项为 A、B、D」这类集合句的字母集合 == `answer`。

- 校验对：406 处
- 反向题面（问「错误的是」）：6 道，已按反向极性复算
- 违规：0 处

已人工核对清单为空：唯一被判定词误伤的 `iq380-164`（题面「以下说法错误的是」、解析「因此 C 错误」正指 C 为应选项）已由方向反转复算覆盖，无需白名单。

## 7 保持原序的题（解析字母引用判角不可靠）

共 106 道：这些题的解析里出现了无法确定指向的字母（如 `C 语言`、`C++`、`ACID` 等结构性误伤），按安全优先**不打乱**，原文与 key 保持自洽，交人工评审后再改写解析。

```text
iq380-281 iq380-184 iq380-280 iq380-129 l100-095 iq380-321 iq380-249 iq380-161 l100-066 l100-094 iq380-037 cs-q17 iq380-179 iq380-220 iq380-344 l100-032 l100-065 l100-034 iq380-180 iq380-252 iq380-087 l100-035 iq380-345 iq380-311 iq380-158 l100-086 l100-081 iq380-310 l100-087 l100-045 iq380-054 fei-005 l100-003 iq380-103 iq380-029 iq380-168 al-q16 iq380-188 iq380-139 iq380-038 iq380-242 l100-018 fei-015 l100-068 l100-093 iq380-297 iq380-116 iq380-096 iq380-113 iq380-001 l100-002 iq380-361 iq380-299 iq380-086 iq380-186 iq380-225 iq380-260 l100-069 l100-017 l100-033 l100-009 iq380-209 iq380-166 l100-084 fei-008 iq380-185 l100-048 l100-012 iq380-134 iq380-211 l100-064 iq380-257 l100-046 iq380-040 fei-007 iq380-131 iq380-341 iq380-132 fei-011 iq380-193 iq380-196 iq380-181 iq380-177 iq380-101 iq380-160 iq380-308 l100-082 l100-019 iq380-324 iq380-277 iq380-002 iq380-114 iq380-182 l100-072 l100-007 iq380-136 iq380-170 iq380-133 iq380-347 l100-010 iq380-227 iq380-085 iq380-278 iq380-138 iq380-020 iq380-212
```

## 8 幂等与门禁（可复跑的证据）

```bash
cd backend && python -X utf8 -m app.services.question_shuffle --check   # 0 差异（只读）
cd backend && python -X utf8 -m app.services.question_merge --check      # 0 差异（打乱已并入重算）
cd backend && python -X utf8 -m app.services.question_shuffle --write    # 再次写盘后 seed 逐字节不变
cd backend && python -X utf8 -m pytest -q -p no:cacheprovider tests/test_r13_question_shuffle.py
```

变红方向（常驻门禁 `test_r13_question_shuffle.py` 覆盖）：把全部单选答案改成 A、清空 `JUDGE_FLIPS`、把 `answer` 挪出 `options` —— 位置分布 / 极性 / key 闭集三条断言各红。

## 9 运行时不受影响

本模块是**离线工具**：运行时（`question_bank` / `exam` / `practice` / `proficiency`）永不 import 它；变换只落在被 git 追踪的 `seed/questions.json` 上，序列化仍只经 `question_merge.dumps()` 一处。存量 `app.db` 因 `ON CONFLICT DO NOTHING` 不刷新（本需求已显式接受，见技术变更单 §4/§7）。
