# r15 答案偏置收口报表（SHUFFLE-REPORT）

> 本文件由 `python -X utf8 -m app.services.question_shuffle --write` 生成（`question_shuffle.render_report()`），指标与 `seed/questions.json` 同源；手抄数字会在下次重算时漂移，因此不得手改。

## 1 概览

- 题库总行数：779
- 重排并重编 key 的题：505（单选 + 多选；多选 59 道）
- 判断题极性改写：38 条
- 保持原序（解析判角不可靠）：106 道

## 2 单选题答案位置分布（前 → 后）

| 阶段 | A | B | C | D |
| --- | --- | --- | --- | --- |
| 重算前（本次输入） | A 229（41.6%） | B 177（32.1%） | C 92（16.7%） | D 53（9.6%） |
| 重算后（落盘） | A 146（26.5%） | B 139（25.2%） | C 135（24.5%） | D 131（23.8%） |

按语言分桶（P3-4：轮转计数按 `language` 独立累加，子集也各自均衡）：

| 语言 | 阶段 | A | B | C | D |
| --- | --- | --- | --- | --- | --- |
| （通用） | 前 | A 88（42.3%） | B 72（34.6%） | C 34（16.3%） | D 14（6.7%） |
| （通用） | 后 | A 52（25.0%） | B 52（25.0%） | C 52（25.0%） | D 52（25.0%） |
| css | 前 | A 10（35.7%） | B 10（35.7%） | C 3（10.7%） | D 5（17.9%） |
| css | 后 | A 8（28.6%） | B 7（25.0%） | C 7（25.0%） | D 6（21.4%） |
| go | 前 | A 24（45.3%） | B 19（35.8%） | C 4（7.5%） | D 6（11.3%） |
| go | 后 | A 15（28.3%） | B 13（24.5%） | C 13（24.5%） | D 12（22.6%） |
| html | 前 | A 12（46.2%） | B 5（19.2%） | C 6（23.1%） | D 3（11.5%） |
| html | 后 | A 7（26.9%） | B 7（26.9%） | C 6（23.1%） | D 6（23.1%） |
| java | 前 | A 23（37.7%） | B 21（34.4%） | C 15（24.6%） | D 2（3.3%） |
| java | 后 | A 16（26.2%） | B 16（26.2%） | C 15（24.6%） | D 14（23.0%） |
| js | 前 | A 11（35.5%） | B 9（29.0%） | C 6（19.4%） | D 5（16.1%） |
| js | 后 | A 8（25.8%） | B 8（25.8%） | C 8（25.8%） | D 7（22.6%） |
| python | 前 | A 33（54.1%） | B 15（24.6%） | C 7（11.5%） | D 6（9.8%） |
| python | 后 | A 18（29.5%） | B 15（24.6%） | C 14（23.0%） | D 14（23.0%） |
| react | 前 | A 10（32.3%） | B 9（29.0%） | C 7（22.6%） | D 5（16.1%） |
| react | 后 | A 9（29.0%） | B 8（25.8%） | C 7（22.6%） | D 7（22.6%） |
| ts | 前 | A 6（30.0%） | B 7（35.0%） | C 3（15.0%） | D 4（20.0%） |
| ts | 后 | A 5（25.0%） | B 5（25.0%） | C 5（25.0%） | D 5（25.0%） |
| vue3 | 前 | A 12（37.5%） | B 10（31.2%） | C 7（21.9%） | D 3（9.4%） |
| vue3 | 后 | A 8（25.0%） | B 8（25.0%） | C 8（25.0%） | D 8（25.0%） |

- 口径：本表是本次 `build_seed()` 重算的**输入 / 输出**。输入 = 素材按原始顺序归一化后的行（偏置源）+ 已落盘的存量行（上一轮已打乱，因此拉低了打乱前的 A 占比）；输出 = 落盘 seed。两栏随同一份指标一起生成，干跑 `--report` 可复现同样的数字。
- 整库真·r13 前基线（r12 提交 `eada0e3` 的 seed：单选 A 323＝58.6%、判断 A 107＝68.6%）是 r13 开工时的一次性实测值，记录在技术变更单 §1/§3；复算命令：`git show eada0e3:backend/app/seed/questions.json`。
- 样本：551 道单选（含未打乱的保持原序题，因此分布由其余题补偿，这正是「轮转填最低计数位置」的作用）。

## 3 判断题极性分布（前 → 后）

| 阶段 | A | B | C | D |
| --- | --- | --- | --- | --- |
| 重算前（本次输入） | A 95（60.9%） | B 61（39.1%） | C 0（0.0%） | D 0（0.0%） |
| 重算后（落盘） | A 85（54.5%） | B 71（45.5%） | C 0（0.0%） | D 0（0.0%） |

按语言分桶（P3-3/P3-4：双向翻转后，每种语言的判断题极性也各自落在 40%–60%）：

| 语言 | 阶段 | A | B | C | D |
| --- | --- | --- | --- | --- | --- |
| （通用） | 前 | A 38（65.5%） | B 20（34.5%） | C 0（0.0%） | D 0（0.0%） |
| （通用） | 后 | A 34（58.6%） | B 24（41.4%） | C 0（0.0%） | D 0（0.0%） |
| css | 前 | A 3（42.9%） | B 4（57.1%） | C 0（0.0%） | D 0（0.0%） |
| css | 后 | A 3（42.9%） | B 4（57.1%） | C 0（0.0%） | D 0（0.0%） |
| go | 前 | A 12（70.6%） | B 5（29.4%） | C 0（0.0%） | D 0（0.0%） |
| go | 后 | A 10（58.8%） | B 7（41.2%） | C 0（0.0%） | D 0（0.0%） |
| html | 前 | A 3（50.0%） | B 3（50.0%） | C 0（0.0%） | D 0（0.0%） |
| html | 后 | A 3（50.0%） | B 3（50.0%） | C 0（0.0%） | D 0（0.0%） |
| java | 前 | A 11（57.9%） | B 8（42.1%） | C 0（0.0%） | D 0（0.0%） |
| java | 后 | A 10（52.6%） | B 9（47.4%） | C 0（0.0%） | D 0（0.0%） |
| js | 前 | A 5（71.4%） | B 2（28.6%） | C 0（0.0%） | D 0（0.0%） |
| js | 后 | A 3（42.9%） | B 4（57.1%） | C 0（0.0%） | D 0（0.0%） |
| python | 前 | A 11（55.0%） | B 9（45.0%） | C 0（0.0%） | D 0（0.0%） |
| python | 后 | A 11（55.0%） | B 9（45.0%） | C 0（0.0%） | D 0（0.0%） |
| react | 前 | A 5（62.5%） | B 3（37.5%） | C 0（0.0%） | D 0（0.0%） |
| react | 后 | A 4（50.0%） | B 4（50.0%） | C 0（0.0%） | D 0（0.0%） |
| ts | 前 | A 4（50.0%） | B 4（50.0%） | C 0（0.0%） | D 0（0.0%） |
| ts | 后 | A 4（50.0%） | B 4（50.0%） | C 0（0.0%） | D 0（0.0%） |
| vue3 | 前 | A 3（50.0%） | B 3（50.0%） | C 0（0.0%） | D 0（0.0%） |
| vue3 | 后 | A 3（50.0%） | B 3（50.0%） | C 0（0.0%） | D 0（0.0%） |

判断题**只改陈述、不动选项**（选项恒为 `A. 正确 / B. 错误`，顺序固定），极性靠下半张表里的绝对映射达成。本节「重算前」同样是本次流水线的输入（素材原序的判断题 + 已落盘存量），整库原始基线 A 107＝68.6% 见 §2 口径说明。

## 4 判断题极性改写对照（原句 → 新句）

| # | id | 原句（改写前） | 新句（改写后） | 新句答案 | 解析 |
| --- | --- | --- | --- | --- | --- |
| 1 | tiji-017 | 在 JavaScript 中，`==` 会比较值并允许隐式类型转换，而 `===` 要求类型与值都相等。 | 在 JavaScript 中，`==` 只比较值且不做任何类型转换，而 `===` 允许隐式类型转换。 | 错误（B） | 说反了：`==` 才做隐式类型转换（'1'==1 为 true），`===` 严格比较类型与值，不做转换（'1'===1 为 false）。 |
| 2 | tiji-019 | 栈（stack）是一种后进先出（LIFO）的数据结构。 | 栈（stack）是一种先进先出（FIFO）的数据结构。 | 错误（B） | 栈只能在一端插入与删除，最后压入的最先弹出，是后进先出（LIFO）；先进先出（FIFO）是队列的特性。 |
| 3 | py-q18 | Python 的 list 与 tuple 都可以容纳不同类型的元素，tuple 创建后其元素引用不能再被替换。 | Python 的 tuple 创建后其元素引用仍可被任意替换，因此 tuple 与 list 一样是可变容器。 | 错误（B） | tuple 的元素引用不可替换、也不能增删，是不可变容器；只有元素本身是可变对象（如 tuple 里放 list）时其内容才可变。 |
| 4 | py-q20 | 在 CPython 中，由于小整数缓存（-5 到 256），相同数值的两个变量用 is 比较可能返回 True。 | 在 CPython 中，两个数值相同的 int 变量用 is 比较一定返回 False，因为小整数不会被缓存。 | 错误（B） | CPython 会缓存 -5 到 256 的小整数对象，该区间内 a is b 可能为 True；is 是身份比较，判断值相等始终应使用 ==。 |
| 5 | java-q17 | Java 中 int 是基本类型、Integer 是包装类，Integer 类型的变量可以为 null。 | Java 中 int 是基本类型、Integer 是包装类，但 Integer 类型的变量不能为 null。 | 错误（B） | Integer 是引用类型，未赋值时默认就是 null；int 才是不能为 null 的基本类型，自动拆箱遇到 null 还会抛 NullPointerException。 |
| 6 | java-q19 | Java 的 finally 块中出现 return 语句时，会覆盖 try 块中已经计算出的返回值。 | Java 的 finally 块中出现 return 语句时，不会影响 try 块中已经计算出的返回值。 | 错误（B） | finally 在方法真正返回前执行，其中的 return 会直接结束方法并覆盖 try 的返回值，同时还会吞掉异常。 |
| 7 | go-q18 | Go 的 map 是引用语义，把 map 传给函数后，函数内新增的键在调用方可见。 | Go 的 map 是值语义，把 map 传给函数后，函数内新增的键在调用方不可见。 | 错误（B） | map 变量内部是指向运行时哈希表的指针，按值传递复制的是这个指针，因此函数内增删键对调用方可见；只有函数内重新 make 才不影响调用方。 |
| 8 | go-q19 | 在 Go 中，向已关闭的 channel 发送数据会触发 panic，而从已关闭的 channel 接收会立即返回零值。 | 在 Go 中，向已关闭的 channel 发送数据不会触发 panic，而从已关闭的 channel 接收会一直阻塞。 | 错误（B） | 向已关闭的 channel 发送会 panic（send on closed channel）；接收则立即返回剩余缓冲数据或零值，第二返回值 ok 为 false。 |
| 9 | html-q18 | <input type="button"> 与 <button> 都能生成可点击按钮，但 <button> 内部可以包含图标等 HTML 元素。 | <input type="button"> 与 <button> 都能生成可点击按钮，但 <button> 内部只能放纯文本。 | 错误（B） | input 是空元素，value 只能是纯文本；button 是容器元素，可以嵌套文本与图标。注意 button 默认 type 是 submit，在表单里需显式写 type="button"。 |
| 10 | html-q19 | img 是空元素（void element），没有结束标签，因此不需要写 </img>。 | img 元素必须写结束标签 </img>，否则浏览器会忽略这张图片。 | 错误（B） | img、br、hr、input、meta、link 等都是空元素，不能有子内容，因此没有结束标签；在 JSX 等 XML 风格语法中会写成自闭合的 <img />。 |
| 11 | css-q18 | box-sizing: border-box 会让 width 包含 padding 与 border，但不包含 margin。 | box-sizing: border-box 会让 width 包含 margin，但不包含 padding 与 border。 | 错误（B） | border-box 把 padding 与 border 计入 width，margin 始终在盒子之外，不参与 width 计算。 |
| 12 | css-q20 | 在 CSS 层叠计算中，两条规则优先级相同时，后出现的声明会覆盖先出现的声明。 | 在 CSS 层叠计算中，两条规则优先级相同时，先出现的声明会覆盖后出现的声明。 | 错误（B） | 权重与来源都相同时，层叠的最后一道判定是书写顺序：靠后的声明胜出，因此第三方库样式应放在自己的样式之前。 |
| 13 | js-q17 | 在 JavaScript 中，用 const 声明的对象，其内部属性仍然可以被修改。 | 在 JavaScript 中，用 const 声明的对象，其内部属性也被冻结，不能再被修改。 | 错误（B） | const 只保证绑定不可重新赋值，对象本身的属性仍可增删改；需要不可变可配合 Object.freeze（浅冻结）或改用不可变数据结构。 |
| 14 | js-q19 | 在 for 循环中用 var 声明的循环变量被闭包捕获时，所有回调读到的都是循环结束后的最终值。 | 在 for 循环中用 let 声明的循环变量被闭包捕获时，所有回调读到的都是循环结束后的最终值。 | 错误（B） | let 为每次迭代创建新的绑定，各回调读到各自迭代的值；只有 var 才是函数作用域，全部回调读到循环结束后的最终值。 |
| 15 | ts-q18 | TypeScript 中 interface 与 type 都能描述对象形状，而 interface 支持同名声明合并。 | TypeScript 中 interface 与 type 都能描述对象形状，并且都能同名重复声明并自动合并。 | 错误（B） | 只有 interface 支持同名声明合并；type 别名重复声明会直接编译报错。 |
| 16 | ts-q19 | 在 TypeScript 中 any 与 unknown 都能接收任意值，但只有 any 可以在不做收窄的情况下直接访问其属性或调用。 | 在 TypeScript 中 any 与 unknown 都能接收任意值，而且两者都可以在不收窄的情况下直接访问属性或调用。 | 错误（B） | any 完全绕过类型检查，可以直接调用；unknown 只能赋值与比较，访问成员前必须先收窄，这正是它更安全的原因。 |
| 17 | ts-q20 | never 是所有类型的子类型，因此可以把 never 类型的值赋给任意类型的变量。 | never 类型的值不能赋给任何其他类型的变量，只能用 any 接收。 | 错误（B） | never 是底类型，可以赋值给任何类型；反过来只有 never 能接收 never，它常用于穷尽性检查，让漏掉的分支在编译期暴露。 |
| 18 | vue3-q18 | Vue 3 的 reactive 对字符串、数字这类基本类型无效，保存基本类型状态应使用 ref。 | Vue 3 的 reactive 对字符串、数字这类基本类型同样有效，保存基本类型状态应使用 reactive。 | 错误（B） | reactive 基于 Proxy 代理对象，基本类型没有可代理的属性读写；基本类型状态应用 ref，模板中自动解包。 |
| 19 | vue3-q19 | 在 Vue 3 中，给 reactive 数组按下标赋值（如 arr[0] = 1）可以触发视图更新。 | 在 Vue 3 中，给 reactive 数组按下标赋值（如 arr[0] = 1）不会触发视图更新，必须改用 splice。 | 错误（B） | Vue 3 用 Proxy 能拦截数组索引赋值，因此 arr[0] = 1 会正常触发更新；必须用 splice 的是 Vue 2 的 defineProperty 方案。 |
| 20 | react-q18 | 父组件重新渲染时，其子组件默认也会重新渲染，除非子组件用 React.memo 等手段做了优化。 | 父组件重新渲染时，其子组件默认不会重新渲染，必须由子组件自己触发更新。 | 错误（B） | 默认行为是父渲染带动子渲染；React.memo 对 props 做浅比较才可跳过，配合 useCallback/useMemo 保持引用稳定才真正有效。 |
| 21 | react-q19 | useEffect 的依赖数组若遗漏了 Effect 内使用的某个变量，可能导致回调一直读到旧的闭包值（stale closure）。 | useEffect 的依赖数组即使遗漏了 Effect 内使用的变量，回调也一定能读到该变量最新的值。 | 错误（B） | Effect 捕获的是创建时那次渲染的变量快照，依赖漏写就不会重新创建，可能读到过期值（stale closure）；应写全依赖或用函数式更新规避。 |
| 22 | react-q20 | React 18 在同一个事件处理函数中多次调用 setState 会自动批处理，只触发一次重新渲染。 | React 18 在同一个事件处理函数中多次调用 setState，每次调用都会各自触发一次重新渲染。 | 错误（B） | React 18 的自动批处理覆盖事件处理、Promise、setTimeout 等场景，多次更新合并为一次渲染；需要立即读取 DOM 时用 flushSync 显式同步刷新。 |
| 23 | l100-011 | CORS 预检请求（OPTIONS）会在请求携带 Authorization 头或 Content-Type 为 application/json 时触发。 | CORS 预检请求（OPTIONS）只在请求方法为 GET 时触发，携带 Authorization 头不会触发预检。 | 错误（B） | 预检针对非简单请求触发：携带自定义头（如 Authorization）、Content-Type 为 application/json 等都会触发；浏览器先发 OPTIONS 询问服务端，服务端需正确响应 Access-Control-Allow-* 头。 |
| 24 | l100-028 | B+ 树索引因为叶子节点有序且链表相连，所以范围查询只需顺序遍历，比 HashMap 更适合范围查询。 | B+ 树索引的叶子节点无序且互不相连，因此范围查询必须全表扫描，不如 HashMap 适合范围查询。 | 错误（B） | B+ 树叶子节点有序且通过链表相连，范围扫描只需顺序遍历；HashMap 无序且只支持等值查询，范围查询需全扫。B+ 树高度低、IO 友好，适合数据库索引。 |
| 25 | l100-047 | 数据库死锁的产生通常是因为两个事务以不一致的顺序加锁，导致互相等待对方持有的锁。 | 数据库死锁只会发生在单个事务内部，与多个事务的加锁顺序无关。 | 错误（B） | 死锁的典型原因是事务交叉加锁顺序不一致，形成循环等待；排查可看事务等待图，避免手段包括统一加锁顺序、缩短事务、降低隔离级别、控制批量。 |
| 26 | l100-063 | 模型网关（LLM gateway）的主要作用之一是统一接入多种模型并屏蔽差异。 | 模型网关（LLM gateway）的主要作用是训练大模型，无法统一接入多种模型。 | 错误（B） | 模型网关的核心作用就是统一接入多种模型（OpenAI、自建、国产等）、屏蔽差异并统一 API，不负责训练。 |
| 27 | l100-088 | OpenTelemetry 提供厂商无关的 SDK 和 Collector，可以统一采集 logs、metrics、traces 并导出到后端。 | OpenTelemetry 只能采集 traces，不支持 logs 与 metrics，也不提供 Collector。 | 错误（B） | OpenTelemetry 确实提供厂商无关的 SDK 与 Collector，可统一采集 logs、metrics、traces 并导出到多种后端（如 Jaeger、Tempo），三者可通过 trace_id 关联。 |
| 28 | iq380-015 | 在 SSR 中，服务端与客户端首次渲染结果不一致（如使用 Date.now 或 Math.random）可能导致 hydration mismatch。 | 在 SSR 中，服务端与客户端首次渲染结果不一致不会造成任何问题，React 会自动把两端内容对齐。 | 错误（B） | 水合不匹配的核心原因正是两端渲染出的 HTML 不同：Date.now、Math.random 等非确定性值会触发文本差异告警或结构差异报错。 |
| 29 | iq380-215 | Go 的 sync.Cond 的 Broadcast 方法会唤醒所有等待者，而 Signal 只唤醒一个等待者。 | Go 的 sync.Cond 的 Broadcast 与 Signal 都只唤醒一个等待者，无法唤醒全部等待者。 | 错误（B） | 说反了：Broadcast 唤醒所有等待者，只有 Signal 只唤醒一个等待者；条件变化需要通知全部时用 Broadcast。 |
| 30 | iq380-230 | 在 Go 中，只有发送方应关闭 channel，接收方不应关闭发送方的 channel。 | 在 Go 中，接收方应主动关闭发送方的 channel，发送方不应关闭 channel。 | 错误（B） | 说反了：channel 应由发送方关闭；接收方关闭后再发送会 panic，多发送方时用额外 done channel 加 WaitGroup 协作关闭。 |
| 31 | ts-q17 | TypeScript 的类型标注会被保留在编译产出的 JavaScript 中，并在运行时对变量做类型校验。 | TypeScript 的类型标注在编译后会被完全擦除，运行时不做任何类型校验。 | 正确（A） | 类型标注、接口、泛型在编译后全部擦除，运行时不校验类型；来自外部的数据仍需运行时校验（如 zod 或手写类型守卫）。 |
| 32 | react-q17 | 在 React 中直接修改 state 对象（例如 state.count++）也能可靠触发界面更新。 | 在 React 中直接修改 state 对象不会触发界面更新，必须用 setState 传入新对象。 | 正确（A） | React 通过引用是否变化判断更新，直接修改同一对象不会触发渲染；应传新对象（展开运算符或不可变更新库）。 |
| 33 | js-q18 | setTimeout(fn, 0) 注册的回调会在当前同步代码执行完之前就运行。 | setTimeout(fn, 0) 注册的回调会等当前同步代码与微任务队列清空后才运行。 | 正确（A） | setTimeout 回调是宏任务，必须等当前同步代码与微任务队列清空后才执行，因此一定晚于后续同步语句。 |
| 34 | js-q20 | Object.freeze() 会递归冻结对象的全部嵌套属性，使对象彻底不可变。 | Object.freeze() 是浅冻结，只冻结对象自身的直接属性，嵌套对象仍可修改。 | 正确（A） | Object.freeze 只冻结对象自身的直接属性，嵌套对象仍可修改；需要彻底不可变时要递归冻结或使用不可变库。 |
| 35 | html-q17 | 在同一个 HTML 页面中，id 属性可以重复出现多次，用来给同类元素分组。 | 在同一个 HTML 页面中，id 属性必须全页唯一，同类元素分组应使用 class。 | 正确（A） | id 必须全页唯一：label 的 for、锚点跳转、document.getElementById 都依赖唯一性；需要分组复用样式应使用 class。 |
| 36 | html-q20 | 把重要提示放在 <marquee> 标签里滚动展示是 HTML5 推荐的强调方式，读屏软件也能正确朗读滚动内容。 | marquee 已从 HTML 标准中废弃，滚动内容会干扰阅读，重要提示应使用静态文本并配合 aria-live 播报。 | 正确（A） | marquee 已从标准中废弃，滚动内容不利于无障碍与性能；重要提示应使用静态高对比文本并配合 aria-live 播报。 |
| 37 | vue3-q17 | 在 Vue 3 中把 v-if 与 v-for 写在同一个元素上是推荐做法，v-if 可以直接使用 v-for 的循环变量。 | 在 Vue 3 中 v-if 的优先级高于 v-for，把两者写在同一元素上时 v-if 拿不到循环变量。 | 正确（A） | Vue 3 中 v-if 的优先级高于 v-for，因此 v-if 拿不到循环变量；应把 v-if 移到外层 template 或用 computed 先过滤列表。 |
| 38 | vue3-q20 | Vue 3 的 computed 每次被访问时都会重新执行计算函数，不做任何缓存。 | Vue 3 的 computed 会缓存计算结果，只有依赖的响应式数据变化时才重新求值。 | 正确（A） | computed 会缓存计算结果，只有依赖变化时才重新求值；因此计算函数里不应写副作用，副作用应放进 watch。 |

## 5 答案长度比（正确项平均长度 / 干扰项平均长度）

- 样本：611 道（单选 + 多选）
- 中位比值：1.46
- 2–3x 抽检清单：129 道
- >3x 清单：0 道（P3-2 起由 `LENGTH_REWRITES` 自动压缩，门禁 `MAX_LONG_ANSWER_COUNT` 要求为 0）

### 5.1 正确项压缩改写（P3-2：只动正确项文本，不动选项顺序 / key / 解析）

- 表内条目：40 条；本次改写 17 条、已是改写态 23 条、基线不符（stale）0 条

| id | 原文（压缩前） | 改写后 |
| --- | --- | --- |
| cs-q11 | 请求并保持（持有资源的同时等待新资源） | 请求并保持（占有并等待） |
| cs-q13 | CPU 寄存器、程序计数器等执行现场，以及进程地址空间相关状态 | CPU 寄存器、程序计数器与地址空间等状态 |
| css-q2 | 最近的非 static 定位祖先元素，没有则相对初始包含块 | 最近的非 static 定位祖先 |
| css-q5 | rem 相对根元素 html 的 font-size；em 相对当前元素（或父元素）计算出的 font-size | rem 相对根字号，em 相对当前元素字号 |
| css-q7 | 伪类选择元素的某个状态（如 :hover），伪元素创建元素的特定部分（如 ::before） | 伪类选择元素状态，伪元素创建元素的特定部分 |
| fe-q15 | 取外层词法作用域中的 this，且 call/apply 无法改变 | 取外层词法 this，call/apply 无法改变 |
| html-q11 | 块级元素独占一行且可设置宽高，行内元素随文本流排列、宽高不直接生效 | 块级独占一行可设宽高，行内随文本流排列 |
| html-q2 | 让视口宽度等于设备宽度并按 1:1 缩放，移动端按响应式布局渲染 | 视口宽度等于设备宽度 |
| iq380-042 | 解决组件渲染到 DOM 树其他位置（如 body）以避免 overflow 或层级问题 | 渲染到 DOM 树其他位置（如 body）以避开层级限制 |
| iq380-047 | 使用 rollup-plugin-visualizer 或 webpack-bundle-analyzer 分析体积分布，查重复依赖并按需引入，开启 gzip/brotli 压缩，配置 CDN 缓存与长效 hash 名，进行路由/组件级 code splitting 并单独分包大依赖 | 可视化分析体积分布，排查重复依赖并按需引入，开启 gzip/brotli，按路由/组件分包 |
| iq380-060 | 使用 SSE/fetch-stream 累积 tokens，并节流 setState 渲染；用 AbortController 中断并保留已生成部分；维护消息状态机处理重新生成 | SSE/fetch-stream 累积 tokens 节流渲染，AbortController 中断保留已生成部分，状态机管理 |
| iq380-131 | 用 @app.exception_handler 注册自定义异常处理，定义统一错误结构 {error:{code,message,retryable}}，并分别处理 HTTPException、Pydantic ValidationError 与业务异常 | 用 @app.exception_handler 统一处理 HTTPException、ValidationError 与业务异常 |
| iq380-132 | 用 PyJWT 签发 access/refresh token 并设 exp 与自定义 claims，用 Depends 做鉴权依赖校验签名与过期，refresh 端点用 refresh token 换新 access，密钥放环境变量且固定 alg | 用 PyJWT 签发带 exp 的 access/refresh token，Depends 校验签名与过期，密钥放环境变量且固定 alg |
| iq380-264 | 护栏在输入/输出两端做约束：输入侧做敏感词/注入检测、超长截断、意图白名单；输出侧做结构化校验、PII 脱敏、拒绝违规请求；可用规则+分类模型+LLM judge 组合实现。 | 输入端做注入检测与截断，输出端做结构化校验、PII 脱敏与违规拦截，规则+分类模型+LLM judge |
| iq380-294 | 用显式状态（PLANNING/ACTING/REFLECTING/DONE）驱动循环，每步结果持久化以支持崩溃恢复与人工介入，状态转移条件明确避免死循环 | 用显式状态（规划/执行/反思/完成）驱动循环，每步持久化支持恢复与人工介入，转移条件明确避免死循环 |
| iq380-296 | 采用多层防御：输入过滤 + 系统指令约束 + 输出护栏 + 分类拦截，并检测常见越狱模板，输出前做合规与敏感内容分类，违规直接拦截，日志留痕持续对抗升级 | 多层防御：输入过滤、指令约束、输出护栏与分类拦截，检测越狱模板并留痕 |
| iq380-297 | 直接用 JSON Schema 或结构化输出约束格式，后端再做校验，缺失字段给默认值或带反馈重试补全，类型错误做转换校验，失败进入有限次修复循环 | 用 JSON Schema 约束格式并由后端校验，缺失字段给默认值或带反馈重试，失败进入有限次修复 |
| iq380-299 | 按模型、用户、功能、租户维度统计 token 与费用，定位长 context、贵模型滥用、重复调用、无缓存等高成本来源，设预算告警与单请求上限，并结合采纳率看每有效回答成本 | 按模型、用户、功能、租户维度统计 token 与费用，定位高成本来源并设预算告警与单请求上限 |
| iq380-310 | 使用 kubectl logs 和 describe 查看退出原因与 Events，检查是否 OOM、启动失败、依赖未就绪或 liveness 探针误杀，必要时调高 initialDelaySeconds | 用 kubectl logs 与 describe 查退出原因，排查 OOM、依赖未就绪与探针误杀 |
| iq380-330 | 使用 p95/p99 延迟监控长尾恶化，并基于 SLO（如 99% 请求 < 300ms）的 burn rate 告警。 | 用 p95/p99 延迟监控长尾，并按 SLO burn rate 告警 |
| iq380-352 | OT（操作变换）或 CRDT（无冲突复制数据类型） | OT 或 CRDT 解决并发冲突 |
| iq380-373 | 使用API Key/Secret或OAuth2 client_credentials鉴权，并对请求签名（timestamp+nonce防重放） | 用 API Key/Secret 或 OAuth2 鉴权，并对请求签名防重放 |
| java-q4 | == 比较引用（基本类型比较值），equals 默认比较引用，可被重写为比较内容 | == 比较对象地址，equals 默认为地址比较、可重写比较内容 |
| java-q7 | int 是基本类型、不能为 null；Integer 是包装类、可为 null 并可放进集合 | int 为基本类型，Integer 为可空包装类 |
| java-q8 | 链表转换为红黑树，把极端查找从 O(n) 降到 O(log n) | 链表转为红黑树，避免查找退化 |
| java-q9 | Error 表示 JVM 层面的严重问题，通常不应捕获；Exception 是应用可处理的异常 | Error 属 JVM 严重问题不宜捕获，Exception 可处理 |
| js-q10 | 防抖在停止触发一段时间后才执行一次；节流按固定时间间隔最多执行一次 | 防抖在停止触发后执行，节流按固定间隔执行 |
| js-q7 | 会丢失函数与 undefined、Date 变成字符串、遇到循环引用直接抛错 | 会丢失函数与 undefined 等 |
| l100-018 | 核心逻辑用框架无关的 TS 编写，React/Vue 仅提供薄适配层（hook/composable），上报走 sendBeacon 或 requestIdleCallback，重计算放 Web Worker | 核心用框架无关 TS，React/Vue 只做薄适配层，上报用 sendBeacon，重计算放 Web Worker |
| l100-019 | 采用命令模式记录每步操作的 inverse（反向命令），或使用快照+结构共享（如 Immer produce 的 patch），并限制历史栈深度、对大文档用 diff/patch 而非整树 | 命令模式记录反向命令，或快照加结构共享（Immer patch），并限制历史深度、大文档用 diff/patch |
| l100-072 | 离线使用固定数据集和自动指标（如 Ragas/准确率）做回归对比；在线通过 A/B 测试不同 prompt/模型，关注采纳率、满意度、token 成本；闭环收集难例、人工标注后加入回归集迭代。 | 离线固定数据集加自动指标做回归，在线 A/B 看采纳率、满意度与 token 成本，难例标注后入回归集 |
| react-q2 | props 由父组件传入且只读；state 由组件自身维护，更新会触发重新渲染 | props 传入后只读；state 由自身维护并驱动渲染 |
| react-q4 | 受控组件的值由 state 驱动；非受控组件由 DOM 自己保存，通过 ref 读取 | 受控值由 state 驱动，非受控用 ref 读取 |
| react-q5 | 更新前的旧值，因为状态更新是批处理且异步生效 | 更新前的旧值 |
| react-q6 | 读取最近的 Provider 提供的上下文值，避免逐层传 props | 读取最近 Provider 的上下文值 |
| ts-q3 | x 的类型是 number \| undefined，直接调用 toFixed 会编译报错 | 可选参数 x 可能为 undefined，编译报错 |
| ts-q5 | 一次性启用 noImplicitAny、strictNullChecks 等一组严格检查 | 一次性开启一组严格检查（含 strictNullChecks） |
| ts-q7 | 永远不会正常返回的值，例如总是抛异常或死循环的函数返回类型 | 永不正常返回的值，如总是抛错或死循环 |
| vue3-q2 | ref 可包装任意类型并需 .value 读写；reactive 只对对象/数组生效，直接访问属性 | ref 用 .value 读写；reactive 仅支持对象 |
| vue3-q6 | v-if 会销毁/重建元素与组件，v-show 只切换 CSS display | v-if 销毁重建元素，v-show 只切换 display |

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

变红方向（常驻门禁 `test_r13_question_shuffle.py` 覆盖）：把全部单选答案改成 A、清空 `JUDGE_FLIPS`、把 `answer` 挪出 `options`、把某道题的正确答案项改回超长原文 ——位置分布 / 极性 / key 闭集 / 长度比 / 按语言分桶五组断言各红。

## 9 运行时不受影响

本模块是**离线工具**：运行时（`question_bank` / `exam` / `practice` / `proficiency`）永不 import 它；变换只落在被 git 追踪的 `seed/questions.json` 上，序列化仍只经 `question_merge.dumps()` 一处。r14（P3-1）起 `question_bank.ensure_seeded()` 在启动时用 `repository.refresh_questions()` 把种子覆写到已存在的同 id 行，因此已部署的旧 `app.db` 也会收敛到本报表的分布；历史 `question_attempts` / `runs.payload` 不受影响（判分只存 `correct`，卷面快照在 payload 里）。
