import type { TutorialChapter } from '../../lib/tutorialTypes'

/** 前端方向：事件循环与异步、React 状态与渲染。 */
export const FRONTEND_CHAPTERS: TutorialChapter[] = [
  {
    id: 'fe-event-loop',
    title: 'JavaScript 事件循环与异步',
    direction: '前端',
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
]
