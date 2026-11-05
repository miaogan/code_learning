import type { TutorialChapter } from '../../lib/tutorialTypes'

/** 计算机基础方向：进程/线程/并发、TCP 与 HTTP、IO 模型与零拷贝、内存与虚拟内存。 */
export const CS_CHAPTERS: TutorialChapter[] = [
  {
    id: 'cs-process-thread',
    title: '进程、线程与并发',
    direction: '计算机基础',
    level: '进阶',
    summary: '进程与线程各自拥有什么、为什么会互相阻塞、锁与死锁是怎么产生的。',
    sections: [
      {
        id: 'memory',
        title: '进程与线程的区别',
        blocks: [
          {
            kind: 'text',
            text: '进程是资源分配的基本单位：每个进程有独立的虚拟地址空间、文件描述符和打开的资源。线程是 CPU 调度的基本单位：同一进程内的线程共享地址空间与文件描述符，但各自有独立的栈和寄存器上下文。',
          },
          {
            kind: 'table',
            headers: ['维度', '进程', '线程'],
            rows: [
              ['地址空间', '独立', '同进程内共享'],
              ['创建开销', '较大', '较小'],
              ['通信方式', '管道、消息队列、共享内存', '直接读写共享变量（需要同步）'],
              ['崩溃影响', '通常只影响自身', '可能拖垮整个进程'],
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: '一句话记忆',
            text: '进程隔离资源，线程共享资源。共享带来通信效率，也带来竞态条件。',
          },
        ],
      },
      {
        id: 'race',
        title: '竞态、锁与死锁',
        blocks: [
          {
            kind: 'text',
            text: '多个线程同时读写同一份数据时，最终结果取决于执行顺序，这就是竞态条件。锁把一段临界区变成「同一时刻只允许一个线程进入」，代价是等待与上下文切换。',
          },
          {
            kind: 'list',
            items: [
              '临界区要尽量短，锁内不要做 I/O 或等待用户输入。',
              '加锁顺序要全局一致，否则两个线程互相等待对方持有的锁就会死锁。',
              '死锁的四个必要条件：互斥、持有并等待、不可剥夺、循环等待；打破任意一个即可。',
              '读多写少的场景可以用读写锁，但读锁也可能被写者饿死，需要具体实现评估。',
            ],
          },
        ],
      },
      {
        id: 'example',
        title: '一个竞态与修复',
        blocks: [
          {
            kind: 'text',
            text: '下面两个线程都对同一个计数器加一。没有锁时，读-改-写不是原子操作，最终结果可能小于 2000；加锁后结果稳定。',
          },
          {
            kind: 'code',
            language: 'python',
            caption: '共享计数器与互斥锁',
            code: [
              'import threading',
              '',
              'counter = 0',
              'lock = threading.Lock()',
              '',
              'def worker():',
              '    global counter',
              '    for _ in range(1000):',
              '        with lock:',
              '            counter += 1',
              '',
              'threads = [threading.Thread(target=worker) for _ in range(2)]',
              '[t.start() for t in threads]',
              '[t.join() for t in threads]',
              'print(counter)  # 稳定输出 2000',
            ].join('\n'),
          },
          {
            kind: 'note',
            tone: 'warn',
            title: 'GIL 不是万能锁',
            text: 'CPython 的全局解释器锁让同一时刻只有一个线程执行 Python 字节码，但它保护不了「多条字节码组合成的业务逻辑」。计数器这类操作仍然需要显式加锁。',
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
                question: '多线程一定比单线程快吗？',
                answer: '不一定。CPU 密集型任务受核心数与 GIL 限制，线程切换还有开销；I/O 密集型任务才更容易从并发中获益。',
              },
              {
                question: '死锁现场怎么排查？',
                answer: '先拿到线程栈（如 jstack、py-spy），看哪些线程在等锁、锁被谁持有；再检查是否存在相反的加锁顺序。',
              },
              {
                question: '进程间通信为什么不能直接读变量？',
                answer: '进程地址空间相互隔离，一个进程无法直接访问另一个进程的内存；必须通过内核提供的管道、消息队列、共享内存等机制。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'cs-tcp-http',
    title: 'TCP 与 HTTP 基础',
    direction: '计算机基础',
    level: '基础',
    summary: '从三次握手到 HTTP 报文：连接怎么建立、请求怎么走、HTTPS 多了什么。',
    sections: [
      {
        id: 'layers',
        title: '分层与职责',
        blocks: [
          {
            kind: 'text',
            text: 'TCP 负责「可靠地把数据送到」：建立连接、按序传输、丢包重传、流量控制。HTTP 负责「用什么格式表达请求和响应」：方法、路径、头部、正文。它们不在同一层，但组合成了浏览器访问网页的基础。',
          },
          {
            kind: 'list',
            items: [
              '应用层：HTTP、HTTPS，定义报文语义。',
              '传输层：TCP、UDP，负责端到端传输。',
              '网络层：IP，负责寻址与路由。',
              '链路层：以太网、Wi-Fi，负责相邻节点传输。',
            ],
          },
        ],
      },
      {
        id: 'handshake',
        title: '三次握手与四次挥手',
        blocks: [
          {
            kind: 'text',
            text: '三次握手的目标是让双方确认「我能发、你能收」并且同步初始序列号。少一次就无法同时确认双向通道，还可能让旧连接请求造成混乱。',
          },
          {
            kind: 'table',
            headers: ['步骤', '方向', '关键动作'],
            rows: [
              ['第一次', '客户端 → 服务端', 'SYN，携带客户端初始序列号'],
              ['第二次', '服务端 → 客户端', 'SYN + ACK，确认并给出服务端序列号'],
              ['第三次', '客户端 → 服务端', 'ACK，确认服务端序列号'],
            ],
          },
          {
            kind: 'text',
            text: '关闭连接需要四次挥手，因为 TCP 是全双工的：一方先发 FIN 表示「我没有数据要发了」，另一方可能还有数据要发，所以 ACK 与 FIN 通常分两次发送。',
          },
          {
            kind: 'note',
            tone: 'info',
            title: '为什么不是两次',
            text: '两次只能确认「客户端能发、服务端能收」，无法确认「服务端能发、客户端能收」。第三次 ACK 补上这个确认，同时避免历史连接请求被误认为新连接。',
          },
        ],
      },
      {
        id: 'example',
        title: '一条 HTTP 请求长什么样',
        blocks: [
          {
            kind: 'text',
            text: 'HTTP/1.1 是文本协议，请求行 + 头部 + 空行 + 正文。服务端用状态行 + 头部 + 正文响应。理解报文结构，排查问题时就能直接看出是路径、认证还是缓存的问题。',
          },
          {
            kind: 'code',
            language: 'http',
            caption: '请求与响应',
            code: [
              'GET /api/reports/latest HTTP/1.1',
              'Host: example.com',
              'Authorization: Bearer <token>',
              'Accept: application/json',
              '',
              'HTTP/1.1 200 OK',
              'Content-Type: application/json',
              'Cache-Control: no-store',
              '',
              '{"id": "r-01", "score": 7.5}',
            ].join('\n'),
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              '先看请求方法与路径，确认命中的是哪个资源。',
              '再看认证与内容协商头部，确认身份与返回格式。',
              '最后看状态码与缓存头，判断是业务失败还是缓存问题。',
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
            title: 'HTTPS 不是「HTTP 加个 S」',
            text: 'HTTPS 在传输层之上加了 TLS：先握手协商密钥、校验证书，再用对称加密传输数据。它同时解决机密性、完整性与身份认证，不是简单换端口。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: 'HTTP/2 相比 HTTP/1.1 最大的改进是什么？',
                answer: '多路复用：一个连接上可以并行传输多个请求，避免队头阻塞；同时压缩头部、支持服务端推送。',
              },
              {
                question: '为什么 TCP 需要流量控制？',
                answer: '接收方缓冲区有限，流量控制通过窗口告诉发送方「还能接收多少」，避免发送过快导致丢包。',
              },
              {
                question: 'Cookie 和 Session 的关系是什么？',
                answer: 'Cookie 是浏览器存储并随请求发送的小段数据；Session 是服务端保存的会话状态，通常用 Cookie 里的 Session ID 关联。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'cs-memory-virtual',
    title: '内存管理与虚拟内存',
    direction: '计算机基础',
    level: '高级',
    summary: '进程看到的地址是假的：栈、堆、页表、TLB 与缺页各自负责一段，理解了才知道「内存泄漏」与「OOM」到底发生在哪。',
    sections: [
      {
        id: 'layout',
        title: '进程地址空间长什么样',
        blocks: [
          {
            kind: 'text',
            text: '每个进程都以为自己独占一大片连续内存，这只是一个假象。真实的物理内存由操作系统按页（通常 4KB）分配，进程手里的只是虚拟地址。',
          },
          {
            kind: 'table',
            headers: ['区域', '存放内容', '分配方式', '常见问题'],
            rows: [
              ['代码段', '编译后的机器指令', '加载时映射，只读', '几乎不出问题'],
              ['数据段', '全局变量、静态变量', '启动时分配', '静态集合只增不减'],
              ['栈', '函数栈帧、局部变量', '随调用自动伸缩', '递归过深 → 栈溢出'],
              ['堆', 'new / malloc 的对象', '运行时按需申请', '忘记释放 → 内存泄漏'],
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: '栈溢出不是内存不够',
            text: '栈默认只有几 MB。无终止递归会很快撞上它，报错看着像「内存耗尽」，实际是栈空间用完了。',
          },
        ],
      },
      {
        id: 'virtual',
        title: '页表、TLB 与缺页',
        blocks: [
          {
            kind: 'text',
            text: '虚拟地址到物理地址的翻译靠页表。每次访存都查页表太慢，于是有了 TLB（地址翻译缓存）；页表里没有对应物理页时，触发缺页中断，由操作系统把页从磁盘换进来。',
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              'CPU 发出虚拟地址，先查 TLB；命中则直接拿到物理地址（一次访存）。',
              'TLB 未命中则查页表（多级页表，可能要多次访存），并把结果写回 TLB。',
              '页表项标记「不在内存」时触发缺页中断：分配物理页 → 从磁盘读入 → 更新页表 → 重新执行指令。',
              '物理内存紧张时，操作系统把不常用的页换出到 swap；换入换出频繁就是「抖动」。',
            ],
          },
          {
            kind: 'table',
            headers: ['概念', '解决什么问题', '代价'],
            rows: [
              ['多级页表', '页表本身太大', '多几次访存'],
              ['TLB', '地址翻译太慢', '上下文切换要刷 TLB'],
              ['写时复制', 'fork 后立刻复制整片内存', '写时缺页 + 一次复制'],
              ['mmap', '大文件读进内存再处理', '缺页按需加载，随机访问有页错误'],
            ],
          },
        ],
      },
      {
        id: 'example',
        title: '一次缺页与一次 mmap',
        blocks: [
          {
            kind: 'text',
            text: '下面的代码把文件映射进地址空间，只在真正访问时才从磁盘读入对应的页。日志处理、大文件检索都靠这个技巧避免一次性读满内存。',
          },
          {
            kind: 'code',
            language: 'c',
            caption: 'mmap 读文件：访问到哪页才加载哪页',
            code: [
              '#include <fcntl.h>',
              '#include <sys/mman.h>',
              '#include <sys/stat.h>',
              '#include <unistd.h>',
              '',
              'int main(void) {',
              '  int fd = open("data.bin", O_RDONLY);',
              '  struct stat st;',
              '  fstat(fd, &st);',
              '',
              '  char *p = mmap(NULL, st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);',
              '  if (p == MAP_FAILED) return 1;',
              '',
              '  long sum = 0;',
              '  for (off_t i = 0; i < st.st_size; i += 4096) sum += p[i];  // 首次访问触发缺页',
              '',
              '  munmap(p, st.st_size);',
              '  close(fd);',
              '  return 0;',
              '}',
            ].join('\n'),
          },
          {
            kind: 'list',
            items: [
              'MAP_PRIVATE：写时复制，只读场景下不额外占内存。',
              '顺序访问的缺页可以由内核预读掩盖；随机访问会明显变慢。',
              'munmap 之后继续访问该地址是未定义行为，指针要立即置空。',
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
            title: 'RSS 涨不等于泄漏',
            text: '分配器向操作系统要了内存但暂时没还，RSS 会保持高位；缓存也会占内存。判断泄漏要看「长时间运行后是否持续单调上涨」，而不是某一刻的数字。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: '内存泄漏和内存溢出有什么区别？',
                answer: '泄漏是「该释放的没释放」，进程占用持续增长；溢出是「一次要的比能给的多」，如栈溢出或申请超大对象直接失败。',
              },
              {
                question: '为什么进程刚启动时 RSS 很小，跑一会儿变大了？',
                answer: '按需分页：只有真正访问到的页才会分配物理内存；预热、缓存与堆增长都会让 RSS 上升，稳定后不再单调上涨就是正常的。',
              },
              {
                question: 'swap 被大量使用为什么反而更慢？',
                answer: '换出换入都要读写磁盘，比内存慢几个数量级；频繁抖动时 CPU 大量时间耗在等 IO 上，表现为整体卡死。',
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'cs-io-model',
    title: 'IO 模型与零拷贝',
    direction: '计算机基础',
    level: '进阶',
    summary: '从「等数据」到「事件通知」，用 select/poll/epoll 的演进讲清高并发服务为什么不怕慢 IO，再看零拷贝省掉了什么。',
    sections: [
      {
        id: 'models',
        title: '阻塞到异步：五个台阶',
        blocks: [
          {
            kind: 'text',
            text: '一次网络读分两个阶段：等数据到达内核缓冲区、把数据从内核拷到用户空间。各 IO 模型的差别就在于这两个阶段里线程在干什么。',
          },
          {
            kind: 'table',
            headers: ['模型', '等数据时', '拷数据时', '一句话'],
            rows: [
              ['阻塞 IO', '线程挂起', '阻塞', '一连接一线程，连接多了线程耗尽'],
              ['非阻塞 IO', '立刻返回，反复轮询', '阻塞', '轮询白烧 CPU，很少单用'],
              ['IO 多路复用', 'select/epoll 帮你盯一批连接', '阻塞', '一个线程管上万连接的主流方案'],
              ['信号驱动', '内核发信号', '阻塞', '信号处理麻烦，实际少用'],
              ['异步 IO', '完全不管', '内核代劳', '理论最优，生态与成熟度有限'],
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: 'Nginx/Redis 为什么快',
            text: '它们都是「单线程（或少线程）+ IO 多路复用」的模型：不把线程耗在等待上，而是让内核在就绪时通知自己，线程永远在做正事。',
          },
        ],
      },
      {
        id: 'multiplex',
        title: 'select → epoll，以及零拷贝',
        blocks: [
          {
            kind: 'list',
            items: [
              'select：每次调用把整批 fd 从用户态拷进内核，返回后还要逐个遍历；有 1024 上限。连接多、活跃少时开销全在「白扫」。',
              'epoll：内核维护红黑树，就绪的 fd 挂到就绪链表，调用只取就绪列表——开销与总连接数无关，只与活跃数有关。',
              '零拷贝：传统「读文件→发网络」要四次拷贝（磁盘→内核→用户→socket 缓冲→网卡）+ 四次上下文切换；sendfile 让数据全程不离开内核，直接从页缓存送进网卡缓冲。',
              'Kafka 高吞吐、Nginx 静态文件快，零拷贝都是重要贡献之一。',
            ],
          },
          {
            kind: 'note',
            tone: 'info',
            title: 'epoll 的两种触发模式',
            text: '水平触发（LT）：没处理完会反复通知，编程简单，是默认。边缘触发（ET）：只在状态变化时通知一次，必须一次性把数据读干净（循环读到 EAGAIN），少一次系统调用但容易漏读——Nginx 用 ET，多数库用 LT。',
          },
        ],
      },
      {
        id: 'example',
        title: '一个 epoll 回声服务器',
        blocks: [
          {
            kind: 'text',
            text: '二十行以内的单线程服务器，可以同时服务成百上千个连接——这就是多路复用的价值。每个连接 socket 都设为非阻塞，交给 epoll 监听。',
          },
          {
            kind: 'code',
            language: 'python',
            caption: 'selectors（epoll 封装）回声服务器',
            code: [
              'import selectors, socket',
              '',
              'sel = selectors.DefaultSelector()',
              'server = socket.socket()',
              'server.bind(("0.0.0.0", 9000))',
              'server.listen()',
              'server.setblocking(False)',
              'sel.register(server, selectors.EVENT_READ, accept)',
              '',
              'def accept(sock):',
              '    conn, _ = sock.accept()',
              '    conn.setblocking(False)',
              '    sel.register(conn, selectors.EVENT_READ, read)',
              '',
              'def read(conn):',
              '    data = conn.recv(4096)',
              '    if data: conn.sendall(data)',
              '    else:',
              '        sel.unregister(conn)',
              '        conn.close()',
              '',
              'while True:',
              '    for key, _ in sel.select():',
              '        key.data(key.fileobj)',
            ].join('\n'),
          },
          {
            kind: 'list',
            ordered: true,
            items: [
              '主循环只有一行：select() 返回就绪的 fd，逐个回调。',
              '没有任何线程在「等」：内核只把就绪的连接交出来。',
              '真实生产实现还要处理半包/粘包、写缓冲与错误分支，这里只为演示骨架。',
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
            title: '多路复用不等于多核利用',
            text: '单线程 epoll 只能吃满一个核。CPU 密集任务会卡住整个事件循环——这也是「Node 单线程却要 worker pool」「Redis 6 后加多线程 IO」的原因：事件循环管 IO，重活另外派发。',
          },
          {
            kind: 'qa',
            items: [
              {
                question: 'epoll 一定比 select 快吗？',
                answer: '连接多且活跃比例低时优势巨大；连接少或几乎全活跃时差距不大（red-black tree 维护也有成本）。性能问题永远先量再选。',
              },
              {
                question: 'ET 模式漏读会怎样？',
                answer: '那批数据永远不会再通知你，连接“卡住”。所以 ET 必须循环读直到返回 EAGAIN/EWOULDBLOCK。',
              },
              {
                question: 'sendfile 为什么不能用于 HTTPS？',
                answer: 'TLS 加密发生在用户态，数据必须回到用户空间加密后再发出，零拷贝的“不过用户态”前提不成立。',
              },
            ],
          },
        ],
      },
    ],
  },
]
