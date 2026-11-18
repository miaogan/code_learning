import type { TutorialChapter } from '../../lib/tutorialTypes'

/** 前端方向：事件循环与异步、React 状态与渲染、渲染性能、TypeScript 类型系统。 */
export const FRONTEND_CHAPTERS: TutorialChapter[] = [
  {
    id: 'fe-event-loop',
    title: 'JavaScript 事件循环与异步',
    direction: '前端',
    sub_direction: 'js',
    level: '进阶',
    summary: '一张调用栈、微任务队列、宏任务队列的调度图，讲清 setTimeout 与 Promise 的执行顺序。',
    sections: [
      {
        id: 'why',
        title: '为什么需要事件循环',
        blocks: [
          {
            kind: 'text',
            text: 'JavaScript 在浏览器里只有一个主线程执行脚本。如果一段代码长时间占用主线程，页面就无法响应点击、滚动与渲染。事件循环（Event Loop）就是「单线程 + 任务队列」的调度机制：主线程永远只做一件事，做完就去看队列里下一个该执行的任务。',
          },
          {
            kind: 'list',
            items: [
              '调用栈（Call Stack）：正在执行的同步代码，后进先出。',
              '微任务队列（Microtask Queue）：Promise.then、queueMicrotask、MutationObserver 回调。',
              '宏任务队列（Macrotask Queue）：setTimeout、setInterval、I/O 回调、用户交互回调。',
              '渲染：浏览器在两次宏任务之间有机会绘制页面，因此「让出主线程」才会看到界面更新。',
            ],
          },
        ],
      },
      {
        id: 'order',
        title: '执行顺序规则',
        blocks: [
          {
            kind: 'text',
            text: '每轮事件循环的口诀：先清空调用栈，再把微任务队列全部清空，然后取一个宏任务执行，接着再清空微任务，之后才可能渲染。微任务会在当前宏任务结束后立刻执行，而不是等下一个宏任务。',
          },
          {
            kind: 'table',
            headers: ['阶段', '处理内容', '典型 API'],
            rows: [
              ['同步代码', '调用栈里逐行执行', '普通函数调用'],
              ['微任务', '本轮清空、优先级高于宏任务', 'Promise.then / queueMicrotask'],
              ['宏任务', '每轮只取一个', 'setTimeout / 事件回调'],
              ['渲染', '宏任务之间择机执行', '样式计算、布局、绘制'],
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: '记忆点',
            text: '微任务插队：任何微任务都会排在「下一个宏任务」之前。所以 Promise 链通常比 setTimeout 先执行。',
          },
        ],
      },
      {
        id: 'example',
        title: '一段可预测的输出',
        blocks: [
          {
            kind: 'text',
            text: '下面的输出顺序是：script start → script end → promise1 → promise2 → timeout。理解它就能应对大多数面试手写题。',
          },
          {
            kind: 'code',
            language: 'javascript',
            caption: 'Promise 与 setTimeout 的混排',
            code: [
              "console.log('script start')",
              '',
              'setTimeout(() => {',
              "  console.log('timeout')",
              '}, 0)',
              '',
              'Promise.resolve()',
              '  .then(() => {',
              "    console.log('promise1')",
              '  })',
              '  .then(() => {',
              "    console.log('promise2')",
              '  })',
              '',
              "console.log('script end')",
            ].join('\n'),
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              '同步代码先执行：script start、script end。',
              '同步代码结束后清空微任务：promise1、promise2。',
              '微任务清空后取宏任务：timeout。',
            ],
          },
        ],
      },
      {
        id: 'pitfalls',
        title: '常见坑与自测',
        blocks: [
          {
            kind: 'note',
            tone: 'warn',
            title: '不要在微任务里无限递归',
            text: 'Promise.then 里再排 Promise.then 会不断产生微任务，微任务队列不清空就不会进入宏任务，页面会一直卡住。需要让出主线程时用 setTimeout 或 requestAnimationFrame。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: 'async 函数里的 await 之后的代码，是微任务还是宏任务？',
                answer: 'await 会把后续代码挂到当前 Promise 的 then 上，属于微任务；它会在当前同步代码结束后、下一个宏任务之前执行。',
              },
              {
                question: 'setTimeout(fn, 0) 会立刻执行吗？',
                answer: '不会。它至少要把回调排进宏任务队列，等本轮微任务清空后才执行；浏览器还有最小延迟与节流，实际不会严格为 0。',
              },
              {
                question: '为什么长循环会卡住页面？',
                answer: '同步循环一直占用调用栈，微任务与渲染都没有机会执行。可以拆成分片任务，或放到 Web Worker。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'fe-react-render',
    title: 'React 状态与渲染',
    direction: '前端',
    sub_direction: 'react',
    level: '基础',
    summary: '从「状态变化 → 重新渲染」讲清 useState、useEffect 与受控组件的边界，避免把状态写成副作用。',
    sections: [
      {
        id: 'model',
        title: '状态驱动的渲染模型',
        blocks: [
          {
            kind: 'text',
            text: 'React 页面不是「改 DOM」，而是「描述某个状态下的 UI」。状态变化后，React 重新执行组件函数，得到新的元素树，再与上一次的结果比较，最后只把差异写进 DOM。理解这一点，就能解释为什么直接修改变量不会触发更新。',
          },
          {
            kind: 'list',
            items: [
              '组件函数在每次渲染时都会重新执行，函数内声明的普通变量只是这一次渲染的局部值。',
              '只有通过 setState 更新状态，React 才会安排下一次渲染。',
              '状态更新是异步批处理的：同一事件里的多次 setState 可能合并成一次渲染。',
              '不要依赖「上一次渲染的变量」保存跨渲染数据，应该用状态或 ref。',
            ],
          },
        ],
      },
      {
        id: 'rules',
        title: 'useState 与 useEffect 的职责',
        blocks: [
          {
            kind: 'table',
            headers: ['写法', '适合存放', '不该做什么'],
            rows: [
              ['useState', '会影响 UI 的数据', '不要存可以通过 props 推导出的值'],
              ['useRef', '跨渲染但不需要触发 UI 的数据', '不要在渲染阶段读写它'],
              ['useEffect', '与外部系统同步（请求、订阅、定时器）', '不要用它派生纯计算状态'],
            ],
          },
          {
            kind: 'text',
            text: '判断标准：这份数据变了，界面要不要跟着变？要变就用状态；不变但需要跨渲染保留，就用 ref；能由已有状态算出来，就每次渲染直接算。',
          },
          {
            kind: 'note',
            tone: 'info',
            title: '依赖数组',
            text: 'useEffect 的依赖数组要写全：用到的 props、state 与外部变量都应列出。漏写会读到旧值，多写会频繁重跑，两者都是 bug 来源。',
          },
        ],
      },
      {
        id: 'example',
        title: '受控输入与提交',
        blocks: [
          {
            kind: 'text',
            text: '受控组件把「输入框的值」放进状态，输入与展示始终一致；提交时直接读状态，不需要再操作 DOM。',
          },
          {
            kind: 'code',
            language: 'tsx',
            caption: '受控输入的最小写法',
            code: [
              'const [keyword, setKeyword] = useState("")',
              '',
              'function handleSubmit(event: FormEvent) {',
              '  event.preventDefault()',
              '  if (keyword.trim() === "") return',
              '  onSearch(keyword.trim())',
              '}',
              '',
              'return (',
              '  <form onSubmit={handleSubmit}>',
              '    <input',
              '      value={keyword}',
              '      onChange={(event) => setKeyword(event.target.value)}',
              '      placeholder="输入关键词"',
              '    />',
              '    <button type="submit">搜索</button>',
              '  </form>',
              ')',
            ].join('\n'),
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              '输入变化只改状态，不直接读 DOM。',
              '提交时用状态值，避免读到未同步的输入。',
              '空值在提交处拦截，表单与接口都不接收无效数据。',
            ],
          },
        ],
      },
      {
        id: 'pitfalls',
        title: '常见坑与自测',
        blocks: [
          {
            kind: 'note',
            tone: 'warn',
            title: '不要在渲染里改状态',
            text: '在组件函数体里直接调用 setState 会导致「渲染 → 更新状态 → 再渲染」的循环。需要根据 props 调整状态时，先想能否直接计算；确实不行再用 effect 并加好依赖。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: '为什么 setState 之后立刻打印状态还是旧值？',
                answer: '状态更新是异步批处理的，当前这次执行里闭包拿到的仍是旧值。下一次渲染才会得到新值。',
              },
              {
                question: 'useEffect 和 useLayoutEffect 怎么选？',
                answer: '默认用 useEffect；只有需要在浏览器绘制前同步读取布局、避免闪烁时才用 useLayoutEffect。',
              },
              {
                question: '列表渲染为什么要 key？',
                answer: 'key 让 React 在多次渲染之间识别同一个条目，复用与移动节点；用索引作 key 在插入/删除时容易错位。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'fe-render-performance',
    title: '渲染性能与浏览器原理',
    direction: '前端',
    sub_direction: '通用前端',
    level: '高级',
    summary: '从样式计算到合成层，讲清一次改属性会触发哪几个阶段，再用「分片渲染 + 虚拟列表」把长列表卡顿按下去。',
    sections: [
      {
        id: 'pipeline',
        title: '渲染流水线：从样式到像素',
        blocks: [
          {
            kind: 'text',
            text: '浏览器把 DOM 变成屏幕像素要经过五个阶段：样式计算 → 布局（Layout）→ 绘制（Paint）→ 合成（Composite）。改不同的属性，跳过的阶段不同，代价能差一个数量级。',
          },
          {
            kind: 'table',
            headers: ['改动类型', '触发阶段', '典型属性', '代价'],
            rows: [
              ['几何属性', '布局 + 绘制 + 合成', 'width / height / margin / font-size', '最高，整棵子树可能要重排'],
              ['外观属性', '绘制 + 合成', 'color / background / box-shadow', '中，重绘区域越大越慢'],
              ['合成属性', '仅合成', 'transform / opacity', '最低，交给 GPU 合成线程'],
              ['触发滚动/布局读取', '强制同步布局', 'offsetHeight / getBoundingClientRect', '最坏，可能引发读写交替的抖动'],
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: '动画为什么优先用 transform',
            text: 'transform 与 opacity 的动画可以在合成线程上完成，不阻塞主线程；改 left / top 每帧都要重排重绘，主线程一忙就掉帧。',
          },
        ],
      },
      {
        id: 'cost',
        title: '重排、重绘与合成层',
        blocks: [
          {
            kind: 'text',
            text: '「重排」是重新计算几何位置，「重绘」是重新填色，两者都可能波及整页。合成层把页面切成独立的图层，图层内的变化不影响其他图层——这是用 transform 做动画更流畅的根本原因。',
          },
          {
            kind: 'list',
            items: [
              '提升为合成层的手段：transform: translateZ(0)、will-change: transform、position: fixed、video / canvas。',
              '图层不是越多越好：每个层都要占显存，层数过多会让合成与内存都变慢。',
              '批量读写：先把需要读的布局值一次性读完，再统一写样式，避免「读 → 写 → 读」交替。',
              '长任务优先拆片：一帧内超过 50ms 的任务会明显掉帧。',
            ],
          },
          {
            kind: 'note',
            tone: 'warn',
            title: 'will-change 不要常驻',
            text: 'will-change 应当「用前加、用完撤」。常年挂在大量元素上会持续占用显存，反而拖慢滚动。',
          },
        ],
      },
      {
        id: 'example',
        title: '长列表卡顿怎么定位与修',
        blocks: [
          {
            kind: 'text',
            text: '先定位再优化：用 Performance 面板录一段滚动，看 Long Task 落在哪。常见结论是「一次渲染上千行 + 每行读布局」。修法有两条：只渲染视口内的行（虚拟列表），以及把大批量更新拆到多个帧。',
          },
          {
            kind: 'code',
            language: 'ts',
            caption: '按帧分片处理大数组（不阻塞渲染）',
            code: [
              'function processInChunks<T>(items: T[], handle: (item: T) => void): Promise<void> {',
              '  return new Promise((resolve) => {',
              '    let index = 0',
              '    const step = () => {',
              '      const deadline = performance.now() + 8   // 单帧只占 8ms，留出渲染余量',
              '      while (index < items.length && performance.now() < deadline) {',
              '        handle(items[index])',
              '        index += 1',
              '      }',
              '      if (index < items.length) requestAnimationFrame(step)',
              '      else resolve()',
              '    }',
              '    requestAnimationFrame(step)',
              '  })',
              '}',
            ].join('\n'),
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              '虚拟列表：只渲染「视口高度 / 行高 + 缓冲」这么多行，其余用占位高度撑开滚动条。',
              '分片更新：把一次处理一万条拆成每帧几百条，主线程始终有窗口响应输入。',
              '稳定 key 与记忆化：行组件用 memo、key 用业务 ID，滚动时不做无谓重渲染。',
            ],
          },
        ],
      },
      {
        id: 'pitfalls',
        title: '常见坑与自测',
        blocks: [
          {
            kind: 'note',
            tone: 'warn',
            title: '循环里读写布局 = 强制同步布局',
            text: '在同一个循环里先 el.style.height = ... 再读 el.offsetHeight，会让浏览器每次都立刻重排来返回准确值，复杂度从 O(1) 次重排变成 O(n) 次。把读与写分成两轮循环。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: '为什么改 transform 比改 top 流畅？',
                answer: 'transform 只影响合成阶段，可在合成线程完成；改 top 会触发布局与绘制，必须占用主线程，主线程一忙就掉帧。',
              },
              {
                question: '页面滚动卡顿，先看什么？',
                answer: '先看有没有滚动监听里做重活（节流/被动监听 passive）、有没有大图与阴影导致重绘、有没有在滚动时读取布局；再用 Performance 面板确认 Long Task 的位置。',
              },
              {
                question: '虚拟列表的坑在哪？',
                answer: '行高不定时无法估算总高度；用键盘查找、页内搜索、锚点跳转都要自己补；快速滚动时缓冲区太小会出现白屏。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'fe-typescript',
    title: 'TypeScript 类型系统实战',
    direction: '前端',
    sub_direction: 'ts',
    level: '进阶',
    summary: '联合类型与收窄、判别联合与穷尽性检查，把「运行时才发现的错」提前到编译期。',
    sections: [
      {
        id: 'model',
        title: '类型是编译期的证明',
        blocks: [
          {
            kind: 'text',
            text: 'TypeScript 的价值不是「写注解」，而是把数据形状写进代码，让编译器在保存时就指出错误。前端最常见的运行时报错——undefined 的属性、拼错的后端字段、漏处理的分支——大多可以用类型把守住入口。',
          },
          {
            kind: 'list',
            items: [
              '类型描述「数据长什么样」，接口契约（后端返回、props、localStorage 结构）都应该有类型。',
              '类型系统的立场是「只添乱不如不写」：any 会关掉所有检查，unknown 才是安全起点。',
              '编译期检查不等于运行时校验：接口返回仍可能和声明不符，边界数据要再校验一层。',
              '类型要跟着重构走：改字段名时编译器报的每一处错，都是你本要手工排查的调用点。',
            ],
          },
        ],
      },
      {
        id: 'narrowing',
        title: '联合类型与收窄',
        blocks: [
          {
            kind: 'text',
            text: '「值可能是几种形状之一」用联合类型表达，再用判断把范围收窄到具体一种。收窄的关键是写出编译器能理解的条件——这就是判别联合（discriminated union）：给每种形状一个字面量标签字段。',
          },
          {
            kind: 'table',
            headers: ['写法', '效果', '注意'],
            rows: [
              ['A | B 联合类型', '值是 A 或 B，只能访问公共属性', '用前必须收窄'],
              ['判别联合 + if (x.kind === …)', '分支内自动缩到对应形状', '标签用字面量类型，别用 string'],
              ['类型守卫 is', '把收窄逻辑封装成可复用函数', '守卫内部要真的校验数据'],
              ['as 断言', '强行改写类型', '绕过检查，仅限确有外部依据时'],
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: 'never 的用途',
            text: '把收窄后的剩余分支赋给 never 类型：联合里新增一种形状而某处 switch 没处理时，编译器立刻报错。这是「穷尽性检查」的标准写法。',
          },
        ],
      },
      {
        id: 'example',
        title: '用判别联合建模请求状态',
        blocks: [
          {
            kind: 'text',
            text: '「加载中不能读 data、失败时 message 才存在」这类约束，用四个带标签的分支表达后，编译器会替你拦住所有越界访问。',
          },
          {
            kind: 'code',
            language: 'ts',
            caption: '判别联合 + 收窄',
            code: [
              'type RequestState<T> =',
              '  | { status: "idle" }',
              '  | { status: "loading" }',
              '  | { status: "success"; data: T }',
              '  | { status: "error"; message: string }',
              '',
              'function render(state: RequestState<string[]>) {',
              '  switch (state.status) {',
              '    case "idle": return null',
              '    case "loading": return "加载中…"',
              '    case "success": return state.data.join(", ")  // 只有这里有 data',
              '    case "error": return `出错了：${state.message}`',
              '    default: {',
              '      const neverState: never = state  // 穷尽性检查',
              '      return neverState',
              '    }',
              '  }',
              '}',
            ].join('\n'),
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              '每个分支只带自己才有的字段，非法访问在编译期直接报错。',
              '新增一种状态（如 refreshing）时，所有没处理它的 switch 都会编译失败。',
              'UI 组件按 state.status 渲染，不再需要 isLoading && data 存在性双重判断。',
            ],
          },
        ],
      },
      {
        id: 'pitfalls',
        title: '常见坑与自测',
        blocks: [
          {
            kind: 'note',
            tone: 'warn',
            title: 'as 断言是逃生门不是正门',
            text: 'as 只说服编译器闭嘴，不改运行时行为。对接口返回用 as 断言等于放弃检查；正确做法是声明类型 + 在边界处运行时校验（手写或用 zod 这类库）。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: 'unknown 和 any 有什么区别？',
                answer: 'any 会传染：赋给谁都不再检查。unknown 用前必须收窄或断言，保持「先验证再使用」，是处理外部数据的安全类型。',
              },
              {
                question: 'interface 和 type 怎么选？',
                answer: '描述对象结构两者等价。需要联合、交叉、映射、条件类型时只能用 type；需要声明合并（全局扩展）时用 interface。团队统一一种为主即可。',
              },
              {
                question: 'Partial、Pick、Omit 这些工具类型的场景？',
                answer: 'Partial 用于「先有骨架再补全」的构建步骤；Pick/Omit 从大类型裁出小类型，避免同一形状写两份；需要新增字段时用交叉，别用 Omit 再补一遍。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'fe-css-layout',
    title: 'CSS 层叠上下文与响应式布局',
    direction: '前端',
    sub_direction: 'css',
    level: '基础',
    summary: '从盒模型到层叠上下文，再到 Flex/Grid 与媒体查询：把「样式不生效」变成可推理的布局问题。',
    sections: [
      {
        id: 'box-model',
        title: '盒模型：宽度到底算到哪一层',
        blocks: [
          {
            kind: 'text',
            text: 'CSS 里每个元素都是一个盒子：内容（content）→ 内边距（padding）→ 边框（border）→ 外边距（margin）。默认的 box-sizing: content-box 让 width 只指内容宽，padding 和 border 会额外加上去，于是「设了 100% 却撑出父容器」就成了高频问题。',
          },
          {
            kind: 'table',
            headers: ['box-sizing', 'width 包含', '典型症状'],
            rows: [
              ['content-box（默认）', '只有 content', '加 padding 后实际宽度超出设定值'],
              ['border-box', 'content + padding + border', '宽度所见即所得，栅格布局更稳'],
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: '全局设置的取舍',
            text: '工程里常用 *, *::before, *::after { box-sizing: border-box } 统一口径。它不改变 margin，改动面集中且可预测，比逐个组件修正省事。',
          },
        ],
      },
      {
        id: 'stacking',
        title: '层叠上下文：z-index 为什么不起作用',
        blocks: [
          {
            kind: 'text',
            text: 'z-index 只在同一个层叠上下文里比较。父元素一旦创建了层叠上下文（如 position 配合 z-index、opacity < 1、transform、filter），子元素的 z-index 就只在这个父级内部有效，再大也盖不过父级的兄弟节点。',
          },
          {
            kind: 'list',
            items: [
              '定位元素（relative/absolute/fixed）且 z-index 不是 auto：最常见的创建方式。',
              'opacity 小于 1、transform 非 none、filter 非 none、will-change 声明了相关属性。',
              'flex/grid 容器的子项，只要 z-index 不是 auto，即使没有 position 也会形成层叠上下文。',
              '排查顺序：先看两个元素是否在同一父级，再看父级是否创建了上下文，最后才看 z-index 数值。',
            ],
          },
          {
            kind: 'note',
            tone: 'warn',
            title: '不要用超大 z-index 救火',
            text: '写 z-index: 999999 往往说明层叠边界没理清。更稳的做法是控制上下文的层级：让弹窗挂到 body 下的独立容器，与业务内容不在同一上下文中比较。',
          },
        ],
      },
      {
        id: 'layout',
        title: 'Flex 与 Grid 怎么分工',
        blocks: [
          {
            kind: 'text',
            text: 'Flex 是一维布局，适合「一行或一列怎么排」；Grid 是二维布局，适合「行列同时约束」的页面骨架。两者不互斥：外层 Grid 定区域，区域内 Flex 排内容，是最常见的组合。',
          },
          {
            kind: 'code',
            language: 'css',
            caption: '外层 Grid 定骨架，内层 Flex 排工具条',
            code: [
              '.page {',
              '  display: grid;',
              '  grid-template-columns: 220px minmax(0, 1fr);',
              '  grid-template-areas: "side main";',
              '}',
              '',
              '.toolbar {',
              '  display: flex;',
              '  gap: 12px;',
              '  align-items: center;',
              '}',
              '',
              '.toolbar .spacer { flex: 1; }',
            ].join('\n'),
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              'minmax(0, 1fr) 而不是 1fr：后者最小尺寸默认是 auto，长内容会撑破网格列。',
              'Flex 的 flex: 1 是 grow/shrink/basis 的缩写，等价于 1 1 0%，不要和 width 混用猜结果。',
              '需要「等宽多列」优先 Grid 的 repeat(auto-fill, minmax(240px, 1fr))，比 Flex 换行更可控。',
            ],
          },
        ],
      },
      {
        id: 'pitfalls',
        title: '常见坑与自测',
        blocks: [
          {
            kind: 'text',
            text: '响应式布局的关键是「先让内容能收缩，再谈断点」。媒体查询只在弹性布局失效后才介入，把断点当万能补丁会让维护成本随屏幕数量线性增长。',
          },
          {
            kind: 'code',
            language: 'css',
            caption: '断点只处理真正的布局切换',
            code: [
              '.cards { display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); }',
              '',
              '@media (max-width: 640px) {',
              '  .cards { grid-template-columns: 1fr; }',
              '  .sidebar { display: none; }',
              '}',
            ].join('\n'),
          },
          {
            kind: 'qa',
            items: [
              {
                question: '元素设了 width: 100% 又加了 20px padding，为什么会横向溢出？',
                answer: '默认是 content-box，width 只算内容区，padding 会额外叠加。改为 box-sizing: border-box，让 width 包含 padding 与 border。',
              },
              {
                question: '子元素的 z-index 设成 9999 仍被盖住，最可能是什么原因？',
                answer: '父子不在同一个层叠上下文：父级创建了上下文（transform、opacity<1、定位+z-index 等），子元素的 z-index 只在父级内部比较。应先调整父级层级或把元素移出该上下文。',
              },
              {
                question: '什么时候用 Grid 而不是 Flex？',
                answer: '需要同时约束行与列、对齐到页面级栅格时用 Grid；只在单一方向排列、内容长度不确定时用 Flex。常见的组合是外层 Grid、内层 Flex。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'fe-react-concurrent',
    title: 'React 并发渲染与非阻塞更新',
    direction: '前端',
    sub_direction: 'react',
    level: '高级',
    summary: '从可中断渲染讲起，掌握 useTransition、Suspense 与优先级，让heavy 更新不卡住输入交互。',
    sections: [
      {
        id: 'concept',
        title: '并发不是并行',
        blocks: [
          {
            kind: 'text',
            text: 'JavaScript 仍是单线程，并发渲染指的是 React 可以把一次渲染拆成小块、在浏览器需要响应输入时暂停让位，之后再继续。它解决的是「大列表渲染时输入框卡顿」这类问题，而不是让计算真的多线程。',
          },
          {
            kind: 'list',
            items: [
              '紧急更新：用户打字、点击，必须立刻反馈。',
              '过渡更新：过滤大列表、切换视图，可以稍后完成。',
              '并发特性让低优先级的过渡更新可被高优先级更新打断。',
            ],
          },
        ],
      },
      {
        id: 'transition',
        title: 'useTransition 与 useDeferredValue',
        blocks: [
          {
            kind: 'code',
            language: 'tsx',
            caption: '把昂贵的过滤标记为过渡更新',
            code: [
              'const [query, setQuery] = useState("")',
              'const [isPending, startTransition] = useTransition()',
              '',
              'function onChange(e) {',
              '  setQuery(e.target.value)            // 紧急：输入框立即更新',
              '  startTransition(() => {',
              '    setFilter(e.target.value)         // 过渡：大列表可延后',
              '  })',
              '}',
              '',
              'return <>{isPending && <Spinner />}<List filter={filter} /></>',
            ].join('\n'),
          },
          {
            kind: 'table',
            headers: ['场景', '推荐', '原因'],
            rows: [
              ['状态由本组件直接设置', 'useTransition', '能拿到 isPending 显示加载态'],
              ['值来自 props 或下游', 'useDeferredValue', '无需改造状态更新处'],
            ],
          },
        ],
      },
      {
        id: 'suspense',
        title: 'Suspense 与加载边界',
        blocks: [
          {
            kind: 'text',
            text: 'Suspense 让组件在等待数据时声明「还没准备好」，由最近的边界展示 fallback。配合并发渲染，可以在切换视图时保留旧内容、避免整页闪烁，而不是立刻退回加载态。',
          },
          {
            kind: 'note',
            tone: 'warn',
            title: 'Effect 里的竞态',
            text: '请求返回顺序不一定等于发起顺序。在 Effect 里发起异步请求要提供清理函数，用标志位或 AbortController 忽略过期结果，否则慢请求会覆盖新结果。',
          },
        ],
      },
      {
        id: 'pitfalls',
        title: '常见坑与自测',
        blocks: [
          {
            kind: 'qa',
            items: [
              {
                question: '并发渲染会让我的计算变快吗？',
                answer: '不会。它优化的是响应性而非计算量：把渲染拆块并在需要时让位给输入。真正的 Heavy 计算要用 Web Worker 或防抖、虚拟化等手段减少工作量。',
              },
              {
                question: 'useTransition 和防抖有什么区别？',
                answer: '防抖按时间延后执行，代价是结果总是滞后固定时长；useTransition 让更新可中断，紧急输入一到就让位，输入体验更顺滑，且能给出 isPending 状态。',
              },
              {
                question: '为什么给组件加 memo 还是频繁重渲染？',
                answer: '常见原因是 props 里有每次新建的对象或函数引用，浅比较通不过。用 useMemo/useCallback 稳定引用，或把状态拆分下移，缩小重渲染范围。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'fe-ts-advanced',
    title: 'TypeScript 类型系统与工程实践',
    direction: '前端',
    sub_direction: 'ts',
    level: '高级',
    summary: '用泛型约束、条件类型与可辨识联合把类型写成可执行的设计文档，让非法状态在编译期就无处藏身。',
    sections: [
      {
        id: 'concept',
        title: '类型是设计工具，不只是注解',
        blocks: [
          {
            kind: 'text',
            text: '好的类型设计让「非法状态不可表示」：与其用一堆可选字段加一堆 if 判断，不如用可辨识联合把每种状态的合法字段绑定在一起。编译器会逼你处理每一种情况。',
          },
          {
            kind: 'code',
            language: 'ts',
            caption: '用可辨识联合建模请求状态',
            code: [
              'type LoadState<T> =',
              '  | { status: "idle" }',
              '  | { status: "loading" }',
              '  | { status: "success"; data: T }',
              '  | { status: "error"; message: string }',
              '',
              'function view<T>(s: LoadState<T>): string {',
              '  switch (s.status) {',
              '    case "success": return String(s.data)  // data 必定存在',
              '    case "error": return s.message',
              '    default: return "..."',
              '  }',
              '}',
            ].join('\n'),
          },
        ],
      },
      {
        id: 'generics',
        title: '泛型约束与条件类型',
        blocks: [
          {
            kind: 'table',
            headers: ['工具', '作用', '典型用法'],
            rows: [
              ['keyof / typeof', '取键集合与值的字面类型', '约束参数只能是对象已有键'],
              ['extends 约束', '限定泛型范围', '要求入参含某个字段'],
              ['条件类型 + infer', '按输入推导输出形状', '提取函数返回值类型'],
              ['satisfies', '校验但保留字面量精度', '配置对象不丢失具体键'],
            ],
          },
          {
            kind: 'code',
            language: 'ts',
            caption: 'satisfies 保留字面量类型',
            code: [
              'const routes = {',
              '  home: "/",',
              '  user: "/u/:id",',
              '} satisfies Record<string, string>',
              '',
              'type RouteKey = keyof typeof routes  // "home" | "user"，而非 string',
            ].join('\n'),
          },
          {
            kind: 'note',
            tone: 'info',
            title: '不等于断言',
            text: 'as 是告诉编译器「相信我」，会绕过检查；satisfies 是让编译器验证「确实符合」同时保留精度。能用 satisfies 就不用断言。',
          },
        ],
      },
      {
        id: 'engineering',
        title: '工程化配置要点',
        blocks: [
          {
            kind: 'list',
            ordered: true,
            items: [
              '开启 strict，尤其 strictNullChecks，把空值问题交给编译器。',
              '对外部数据（接口响应、localStorage）在边界处做运行时校验，类型注解本身没有运行时效果。',
              '公共类型集中管理，避免同一份接口在多个文件各写一遍。',
              '谨慎使用 any 与类型断言，它们是类型系统里的逃生口，滥用会让检查形同虚设。',
            ],
          },
        ],
      },
      {
        id: 'pitfalls',
        title: '常见坑与自测',
        blocks: [
          {
            kind: 'qa',
            items: [
              {
                question: '可辨识联合相比一堆可选字段好在哪？',
                answer: '可选字段允许多种不合理组合（既 loading 又有 data），代码里要靠约定和 if 去防。可辨识联合用判别字段把每种状态的合法字段绑定，编译器强制你穷尽处理，非法组合无法构造。',
              },
              {
                question: 'satisfies 和类型注解的区别？',
                answer: '类型注解会把变量类型拓宽成注解类型，丢失字面量信息；satisfies 只做符合性校验，变量仍是它最精确的字面量类型，适合配置对象与常量表。',
              },
              {
                question: '为什么编译过了运行时还会类型错？',
                answer: 'TypeScript 类型在编译后被擦除，接口返回、用户输入、存储数据这些外部来源不受编译期保护。要在进入系统的边界处做运行时校验，再交给类型系统。',
              },
            ],
          },
        ],
      },
    ],
  },
]
