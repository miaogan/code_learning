"""生成「中间件与运维」方向题库的 **staging 素材文件**（canonical 输入）。

本脚本只产出 `docs/question-bank-staging/06-middleware.json`；`question_merge`
从该文件 + 存量 260 行重建 `app/seed/questions.json`（写完 staging 后跑
`python -m app.services.question_merge --write`）。

约束（与产品闭集一致）：
- 方向 direction = "中间件与运维"（rules.DIRECTIONS 已新增）
- 语言 language = ""（无语言方向；rules.LANGUAGES 含 ""，归一化合法）
- 来源 source = "mw"（question_merge.SOURCES 已新增）
- kind ∈ {single, multiple, judge}（合并批不允许 text；practice / 笔试只认客观题）

幂等：重跑会整体重写该 staging 文件。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGING_PATH = ROOT / "docs" / "question-bank-staging" / "06-middleware.json"

JUDGE_OPTIONS = [
    {"key": "A", "text": "正确"},
    {"key": "B", "text": "错误"},
]


def q(
    qid: str,
    kind: str,
    difficulty: str,
    essentiality: str,
    prompt: str,
    options: list[dict],
    answer: list[str],
    explanation: str,
) -> dict:
    return {
        "id": qid,
        "kind": kind,
        "difficulty": difficulty,
        "essentiality": essentiality,
        "language": "",
        "direction": "中间件与运维",
        "prompt": prompt,
        "options": options,
        "answer": answer,
        "explanation": explanation,
    }


def opt(*pairs: tuple[str, str]) -> list[dict]:
    return [{"key": k, "text": t} for k, t in pairs]


# ---------------------------------------------------------------------------
# 题库内容（全客观：single / multiple / judge）
# ---------------------------------------------------------------------------
QUESTIONS: list[dict] = []

# ---- PostgreSQL (must_know / advanced) ----
QUESTIONS += [
    q("mw-pg-1", "single", "basic", "must_know",
      "PostgreSQL 的默认端口是？",
      opt(("A", "3306"), ("B", "5432"), ("C", "6379"), ("D", "27017")),
      ["B"],
      "5432 是 PostgreSQL 默认端口；3306 是 MySQL、6379 是 Redis、27017 是 MongoDB。"),
    q("mw-pg-2", "multiple", "intermediate", "must_know",
      "关于事务的 ACID 特性，下列说法正确的有？",
      opt(("A", "原子性（Atomicity）：事务要么全成要么全不成"),
          ("B", "一致性（Consistency）：约束不被破坏"),
          ("C", "隔离性（Isolation）：并发事务互不干扰"),
          ("D", "持久性（Durability）：提交后不丢")),
      ["A", "B", "C", "D"],
      "ACID 是关系型事务的四要素；持久性由 WAL/落盘机制保证。"),
    q("mw-pg-3", "single", "intermediate", "must_know",
      "B-tree 索引最适合哪种查询？",
      opt(("A", "等值查询与范围查询（=、>、BETWEEN、排序）"),
          ("B", "全文检索文本"), ("C", "仅随机访问"), ("D", "只能用于唯一约束")),
      ["A"],
      "B-tree 是默认索引，擅长等值/范围与有序扫描；全文检索通常用 GIN + tsvector。"),
    q("mw-pg-4", "single", "basic", "must_know",
      "PostgreSQL 默认的事务隔离级别是？",
      opt(("A", "读已提交（READ COMMITTED）"), ("B", "可串行化（SERIALIZABLE）"),
          ("C", "读未提交（READ UNCOMMITTED）"), ("D", "无隔离")),
      ["A"],
      "PG 默认 READ COMMITTED：防止脏读；更强隔离需在会话/事务中显式设置。"),
    q("mw-pg-5", "single", "intermediate", "advanced",
      "MVCC（多版本并发控制）的核心价值是？",
      opt(("A", "读不阻塞写、写不阻塞读：每个事务看自己的快照"),
          ("B", "彻底消除所有锁"), ("C", "仅用于主从复制"), ("D", "替代事务语义")),
      ["A"],
      "MVCC 让读走历史快照、写追加新版本，从而读写互不阻塞，是 PG 高并发的基础。"),
    q("mw-pg-6", "multiple", "challenge", "advanced",
      "关于 EXPLAIN（不含 ANALYZE），下列说法正确的有？",
      opt(("A", "展示查询的执行计划"), ("B", "能看到是否走了索引"),
          ("C", "给出的是估算行数与代价"), ("D", "给出真实执行耗时")),
      ["A", "B", "C"],
      "EXPLAIN 看计划与估算；要真实耗时与行数需 EXPLAIN ANALYZE（有实际执行开销）。"),
    q("mw-pg-7", "single", "intermediate", "must_know",
      "PostgreSQL 流复制（物理/流复制）中，从库（standby）默认是？",
      opt(("A", "只读，异步复制存在主从延迟"), ("B", "可读写"),
          ("C", "完全不能连接"), ("D", "与主库实时强一致零延迟")),
      ["A"],
      "流复制备库默认只读，异步模式下主库提交后从库有延迟；同步复制可降延迟但有性能代价。"),
    q("mw-pg-8", "judge", "intermediate", "must_know",
      "VACUUM 用于回收已删除/更新行占用的空间，并防止事务 ID 回卷导致的数据损坏。",
      JUDGE_OPTIONS, ["A"],
      "PG 的 MVCC 会产生死元组，VACUUM 回收空间并冻结旧事务 ID；长期不 vacuum 会触发回卷保护停机。"),
    q("mw-pg-9", "single", "intermediate", "advanced",
      "WAL（预写日志，Write-Ahead Logging）的主要作用是？",
      opt(("A", "先写日志再改数据，保证崩溃后可恢复、保障持久性"),
          ("B", "直接加速查询"), ("C", "替代索引"), ("D", "仅用于审计")),
      ["A"],
      "WAL 是崩溃恢复与持久性的基石：先落日志再应用修改，故障重放日志即可回放。"),
    q("mw-pg-10", "multiple", "challenge", "advanced",
      "关于表分区（partitioning），合理的收益包括？",
      opt(("A", "大表查询/维护更快（分区裁剪）"),
          ("B", "便于按时间归档或快速删除历史分区"),
          ("C", "可减小单分区上的索引体积"),
          ("D", "自动消除一切慢查询")),
      ["A", "B", "C"],
      "分区通过裁剪提升效率并方便生命周期管理，但不会自动消除所有慢查询（仍需好索引与 SQL）。"),
    q("mw-pg-11", "single", "intermediate", "must_know",
      "相比 JSON 类型，JSONB 的主要优势是？",
      opt(("A", "二进制存储、去重键、支持 GIN 索引与高效查询"),
          ("B", "输出更快但无法查询"), ("C", "只能存字符串"),
          ("D", "不支持任何索引")),
      ["A"],
      "JSONB 以解析后的二进制存储，支持 GIN 索引与字段级查询；JSON 仅保留文本原文。"),
    q("mw-pg-12", "multiple", "challenge", "advanced",
      "避免/处理数据库死锁的合理手段包括？",
      opt(("A", "统一多个事务访问资源的加锁顺序"),
          ("B", "缩短事务、减小锁粒度与持有时间"),
          ("C", "依赖数据库死锁检测后回滚其中一个事务"),
          ("D", "永远不会发生死锁，可忽略")),
      ["A", "B", "C"],
      "统一加锁顺序与缩短事务能减少死锁；DB 也会检测并回滚代价小的一方，但不能据此放任。"),
    q("mw-pg-13", "judge", "basic", "must_know",
      "连接池（如 pgbouncer）可复用数据库连接，显著降低频繁建连/断连的开销。",
      JUDGE_OPTIONS, ["A"],
      "短连接高并发下建连成本很高，连接池复用是 PG 生产部署的标配。"),
    q("mw-pg-14", "multiple", "challenge", "advanced",
      "关于 PostgreSQL 的复制，下列说法正确的有？",
      opt(("A", "流复制（物理）是块级，备库默认只读"),
          ("B", "逻辑复制可按表/库选择性发布，便于大版本迁移"),
          ("C", "异步复制存在主从延迟"),
          ("D", "复制可以完全替代备份")),
      ["A", "B", "C"],
      "物理复制镜像块、逻辑复制更灵活；但复制不是备份（误删会同步），仍需独立备份。"),
]

# ---- Redis (must_know / advanced) ----
QUESTIONS += [
    q("mw-rd-1", "single", "basic", "must_know",
      "Redis 的默认端口是？",
      opt(("A", "6379"), ("B", "5432"), ("C", "3306"), ("D", "11211")),
      ["A"],
      "6379 是 Redis 默认端口；11211 是 Memcached。"),
    q("mw-rd-2", "multiple", "intermediate", "must_know",
      "Redis 常见的数据结构包括？",
      opt(("A", "String / Hash"), ("B", "List / Set"),
          ("C", "Sorted Set（有序集合）"), ("D", "Bitmap / HyperLogLog / Stream")),
      ["A", "B", "C", "D"],
      "Redis 是多数据结构存储：字符串、哈希、列表、集合、有序集合，以及位图、HLL、Stream 等。"),
    q("mw-rd-3", "single", "intermediate", "must_know",
      "Sorted Set（ZSet）最典型的使用场景是？",
      opt(("A", "按分数排序的排行榜 / 延迟队列"), ("B", "仅缓存整页 HTML"),
          ("C", "仅发布订阅"), ("D", "仅做简单计数器")),
      ["A"],
      "ZSet 按 score 排序且可范围取TopN，是实时排行榜、延迟队列的首选。"),
    q("mw-rd-4", "single", "basic", "must_know",
      "RDB 与 AOF 两种持久化的主要区别是？",
      opt(("A", "RDB 是定时快照，AOF 记录写命令流水"),
          ("B", "两者完全相同"), ("C", "RDB 记录命令、AOF 是快照"),
          ("D", "AOF 只能存内存")),
      ["A"],
      "RDB 紧凑快照、恢复快但可能丢较多数据；AOF 记录写命令、更耐用但文件大。"),
    q("mw-rd-5", "multiple", "challenge", "advanced",
      "应对缓存穿透 / 击穿 / 雪崩的合理手段包括？",
      opt(("A", "布隆过滤器或缓存空值防穿透"),
          ("B", "热点 key 互斥重建 / 逻辑过期防击穿"),
          ("C", "过期时间加随机量与限流防雪崩"),
          ("D", "让缓存永不过期即可")),
      ["A", "B", "C"],
      "三类问题根因不同：穿透是查不存在的数据、击穿是单热点失效、雪崩是批量同时失效；D 反而放大风险。"),
    q("mw-rd-6", "single", "intermediate", "must_know",
      "用 Redis 实现分布式锁，最关键的是？",
      opt(("A", "加锁原子性（SET key val NX）且只有持有者能释放"),
          ("B", "用 GET 再 SET 两步即可"), ("C", "锁无需过期时间"),
          ("D", "任意客户端都能释放该锁")),
      ["A"],
      "原子加锁（SET NX）+ 唯一标识校验释放 + 合理过期，是安全分布式锁的要点；两步 GET/SET 非原子。"),
    q("mw-rd-7", "judge", "intermediate", "must_know",
      "Redis 核心命令执行是单线程的，因此一个超大 key 或慢命令会阻塞其他请求。",
      JUDGE_OPTIONS, ["A"],
      "执行模型单线程（6.x 后 IO 多线程但仍单线程执行），大 key、慢查询会拖垮整体吞吐，应避免。"),
    q("mw-rd-8", "single", "intermediate", "advanced",
      "内存淘汰策略（如 LRU/LFU）在什么情况下触发？",
      opt(("A", "使用内存达到 maxmemory 上限时"),
          ("B", "每次写入之前"), ("C", "仅在重启时"), ("D", "永不发生")),
      ["A"],
      "当内存触及 maxmemory，Redis 按策略（noeviction/LRU/LFU/random/ttl）淘汰键；noeviction 会拒绝写入。"),
    q("mw-rd-9", "single", "intermediate", "advanced",
      "HyperLogLog 主要解决什么问题？",
      opt(("A", "海量元素的基数（去重计数，如 UV）估算，且内存极小"),
          ("B", "精确去重计数"), ("C", "有序排行榜"), ("D", "消息队列")),
      ["A"],
      "HLL 以约 12KB 估算上亿基数，误差可控，是 PV/UV 统计的省内存方案；它给的是近似值。"),
    q("mw-rd-10", "single", "intermediate", "must_know",
      "Pipeline（管道）的主要作用是？",
      opt(("A", "批量发送命令、减少多次网络 RTT"),
          ("B", "替代事务语义"), ("C", "保证原子性"), ("D", "加速磁盘 IO")),
      ["A"],
      "Pipeline 把多条命令合并收发，降低网络往返开销；它不等于事务（无回滚），也不保证原子。"),
    q("mw-rd-11", "judge", "intermediate", "advanced",
      "Redis Cluster 通过 16384 个槽（slot）分片实现水平扩展，且要求多数主节点可用。",
      JUDGE_OPTIONS, ["A"],
      "Cluster 把 keyspace 分到 16384 槽并由主节点持有，故障转移需多数派，是 Redis 横向扩展方案。"),
    q("mw-rd-12", "multiple", "challenge", "advanced",
      "关于 Redis 持久化与数据安全，下列说法正确的有？",
      opt(("A", "AOF 的 everysec 在性能与最多丢约 1 秒间权衡"),
          ("B", "RDB 可能丢失最近一次快照之后的写入"),
          ("C", "主从 + 哨兵可提升可用性，但不等于备份"),
          ("D", "有了持久化就保证零数据丢失")),
      ["A", "B", "C"],
      "持久化降低丢失概率但不保证零丢失；主从/哨兵解决高可用而非备份，仍需独立备份策略。"),
    q("mw-rd-13", "single", "intermediate", "must_know",
      "Pub/Sub（发布订阅）的消息模型特点是？",
      opt(("A", "发布即推送、无持久化、离线订阅者收不到历史消息"),
          ("B", "可靠的持久化队列"), ("C", "自动事务回滚"), ("D", "仅本地进程内")),
      ["A"],
      "Pub/Sub 是实时广播、不落盘；需要可靠消费应改用 Stream 或外部 MQ。"),
    q("mw-rd-14", "judge", "basic", "must_know",
      "把 Redis 当持久数据库使用时，需要配置合适的持久化与内存/淘汰策略，否则重启或淘汰会丢数据。",
      JUDGE_OPTIONS, ["A"],
      "Redis 以内存为主，若持久化/策略不当，重启或触发淘汰都会丢数据；按场景选型很重要。"),
]

# ---- Nginx (must_know / advanced) ----
QUESTIONS += [
    q("mw-ng-1", "single", "basic", "must_know",
      "反向代理与正向代理的主要区别是？",
      opt(("A", "反向代理代表服务端、对客户端透明，常用于负载均衡"),
          ("B", "正向代理代表服务端"), ("C", "两者完全相同"),
          ("D", "反向代理只能做缓存")),
      ["A"],
      "正向代理代表客户端（如科学上网/内网出网），反向代理代表服务端（如 Nginx 前置后端）。"),
    q("mw-ng-2", "multiple", "intermediate", "must_know",
      "Nginx 负载均衡的常用策略包括？",
      opt(("A", "轮询（round-robin）"), ("B", "最少连接（least_conn）"),
          ("C", "IP 哈希（ip_hash）做会话保持"), ("D", "随机且永不均衡")),
      ["A", "B", "C"],
      "轮询、最少连接、ip_hash 等是常见后端分发策略；还可加权与第三方一致性哈希。"),
    q("mw-ng-3", "single", "intermediate", "must_know",
      "Nginx 的 location 匹配优先级，正确的是？",
      opt(("A", "= 精确匹配 > ^~ 前缀 > 正则(~) > 普通前缀"),
          ("B", "正则优先级最低"), ("C", "按配置文件书写顺序随意"),
          ("D", "普通前缀永远最高")),
      ["A"],
      "精确匹配 = 最高，其次 ^~ 前缀，再次正则，最后普通前缀；理解顺序才能正确路由。"),
    q("mw-ng-4", "single", "intermediate", "advanced",
      "Nginx 作为 HTTPS 接入层通常负责？",
      opt(("A", "TLS 终止（卸载），之后以明文转发内网后端"),
          ("B", "替代应用业务逻辑"), ("C", "仅做 DNS 解析"), ("D", "仅记录日志")),
      ["A"],
      "TLS 终止在 Nginx 完成，内网用 HTTP 减少后端加解密开销；证书与安全策略集中管理。"),
    q("mw-ng-5", "judge", "intermediate", "must_know",
      "Nginx 通常采用一个 master 进程管理多个 worker 进程，worker 数常设为 CPU 核数。",
      JUDGE_OPTIONS, ["A"],
      "master 负责信号/配置加载，worker 处理连接；worker 数与核数对齐以充分利用多核。"),
    q("mw-ng-6", "multiple", "challenge", "advanced",
      "提升 Nginx 静态资源服务性能的做法包括？",
      opt(("A", "开启 gzip 压缩"), ("B", "设置长缓存 Cache-Control"),
          ("C", "开启 sendfile 零拷贝"), ("D", "关闭所有缓冲与缓存")),
      ["A", "B", "C"],
      "gzip、长缓存与 sendfile 都能显著提速静态服务；D 反而降低性能。"),
    q("mw-ng-7", "single", "intermediate", "must_know",
      "upstream 模块的主要作用是？",
      opt(("A", "定义一组后端服务器，供 proxy_pass 引用做负载均衡"),
          ("B", "仅做 DNS 解析"), ("C", "只用于静态文件"), ("D", "替代 SSL 配置")),
      ["A"],
      "upstream 把后端池抽象出来，配合负载均衡策略与健康检查，是反向代理的核心配置。"),
    q("mw-ng-8", "judge", "intermediate", "advanced",
      "启用 keepalive 连接复用可以降低与后端建连的 TCP 握手开销。",
      JUDGE_OPTIONS, ["A"],
      "与后端保持长连接避免每次请求三次握手，是高并发反向代理的常见优化。"),
    q("mw-ng-9", "single", "challenge", "advanced",
      "返回 502 Bad Gateway 通常意味着？",
      opt(("A", "网关/代理收到后端无效或不可达的响应"),
          ("B", "请求的资源不存在"), ("C", "纯客户端参数错误"),
          ("D", "静态文件缺失")),
      ["A"],
      "502 是网关错误：Nginx 作为代理却从上游拿到非法响应/连接失败；排查后端健康与网络。"),
    q("mw-ng-10", "multiple", "challenge", "advanced",
      "把 Nginx 当作 API 网关的合理用法包括？",
      opt(("A", "反向代理 + 负载均衡"),
          ("B", "限流（limit_req / limit_conn）"),
          ("C", "TLS 终止与统一入口"),
          ("D", "用它替代业务数据库")),
      ["A", "B", "C"],
      "Nginx 适合做入口、均衡、限流与 TLS；但不应越俎代庖承担业务存储职责。"),
]

# ---- Docker (must_know / advanced) ----
QUESTIONS += [
    q("mw-dk-1", "single", "basic", "must_know",
      "镜像（image）与容器（container）的关系是？",
      opt(("A", "镜像是只读模板，容器是其运行实例"),
          ("B", "两者完全相同"), ("C", "容器是镜像的备份文件"),
          ("D", "镜像必须运行起来才存在")),
      ["A"],
      "镜像不可变、是分层模板；容器是镜像加可写层后的运行态，可被创建/启动/销毁。"),
    q("mw-dk-2", "single", "intermediate", "must_know",
      "Dockerfile 中 COPY 与 ADD 的主要区别是？",
      opt(("A", "COPY 仅复制本地文件；ADD 还能解压归档与拉取远程 URL"),
          ("B", "两者完全相同"), ("C", "ADD 只能复制本地文件"),
          ("D", "COPY 能自动解压")),
      ["A"],
      "最佳实践用 COPY（语义清晰、可预期）；ADD 的自动解压/远程下载易带来意外，慎用。"),
    q("mw-dk-3", "single", "intermediate", "must_know",
      "ENTRYPOINT 与 CMD 的主要区别是？",
      opt(("A", "ENTRYPOINT 定义可执行程序，CMD 提供默认参数"),
          ("B", "两者完全相同"), ("C", "CMD 必须存在、ENTRYPOINT 可选"),
          ("D", "ENTRYPOINT 不能接收参数")),
      ["A"],
      "ENTRYPOINT 固定容器主进程、CMD 作默认参数；运行时命令行参数会覆盖 CMD。"),
    q("mw-dk-4", "multiple", "intermediate", "must_know",
      "关于 Docker 镜像分层与写时复制（COW），下列说法正确的有？",
      opt(("A", "相同基础层可在镜像间共享，节省存储与传输"),
          ("B", "容器读写发生在可写层，不污染只读镜像层"),
          ("C", "镜像层只读、不可变"),
          ("D", "每次修改都会拷贝整个镜像")),
      ["A", "B", "C"],
      "分层+COW 让镜像可复用、启动快；修改只落在容器可写层，不影响只读层。"),
    q("mw-dk-5", "single", "intermediate", "advanced",
      "多阶段构建（multi-stage build）的主要目的是？",
      opt(("A", "把编译工具留在构建阶段，最终镜像只留运行所需，显著减小体积"),
          ("B", "单纯加快网络"), ("C", "替代镜像仓库"), ("D", "只能用于 Go 项目")),
      ["A"],
      "多阶段构建只把产物拷入精简的最终镜像，剥离编译器/依赖，是减镜像体积的关键手段。"),
    q("mw-dk-6", "judge", "intermediate", "must_know",
      "数据卷（volume）比 bind mount 更适合数据持久化与跨容器共享，且生命周期独立于容器。",
      JUDGE_OPTIONS, ["A"],
      "volume 由 Docker 管理、与容器解耦、便于备份与共享；bind mount 直接挂宿主机路径，移植性较差。"),
    q("mw-dk-7", "single", "intermediate", "must_know",
      "默认的 bridge 网络模式的作用是？",
      opt(("A", "容器在网桥内互通、通过端口映射访问宿主机"),
          ("B", "与宿主机完全共享网络栈"), ("C", "容器不能联网"),
          ("D", "仅用于 Windows")),
      ["A"],
      "bridge 是默认网络，容器各有独立网络命名空间并通过网桥通信；host 模式才共享宿主机网络栈。"),
    q("mw-dk-8", "multiple", "challenge", "advanced",
      "Docker 可对容器施加的资源限制包括？",
      opt(("A", "CPU 配额 / 核数限制"), ("B", "内存上限"),
          ("C", "磁盘 IO 权重"), ("D", "容器无法限制任何资源")),
      ["A", "B", "C"],
      "通过 cgroups 可限 CPU、内存、IO 等；不设限的容器可能拖垮宿主机其他负载。"),
    q("mw-dk-9", "judge", "intermediate", "advanced",
      "在容器中用 root 运行并挂载宿主机敏感目录（如 /、/var/run/docker.sock）会带来严重安全风险。",
      JUDGE_OPTIONS, ["A"],
      "root + 挂载敏感路径可能逃逸到宿主机；生产应降权运行并最小化挂载。"),
    q("mw-dk-10", "single", "challenge", "advanced",
      "docker-compose 最适合的场景是？",
      opt(("A", "单机编排多个互联容器及其网络/卷依赖"),
          ("B", "跨集群大规模调度"), ("C", "替代 Kubernetes 全部能力"),
          ("D", "仅用于构建镜像")),
      ["A"],
      "compose 用声明式文件把多容器应用一键拉起，适合单机/开发；集群调度交给 K8s。"),
    q("mw-dk-11", "single", "intermediate", "must_know",
      "Docker Registry 的作用是？",
      opt(("A", "集中存储与分发镜像"), ("B", "运行容器"),
          ("C", "替代数据库"), ("D", "做负载均衡")),
      ["A"],
      "Registry（如 Docker Hub、私有 Harbor）负责镜像的版本化存储与拉取分发。"),
    q("mw-dk-12", "judge", "intermediate", "advanced",
      "镜像标签 latest 是易变的、不保证内容稳定，生产环境应钉具体版本标签。",
      JUDGE_OPTIONS, ["A"],
      "latest 会随推送漂移，回滚与可复现性差；生产应锁定 digest 或明确版本标签。"),
    q("mw-dk-13", "multiple", "challenge", "advanced",
      "减小镜像体积的常见手段包括？",
      opt(("A", "使用多阶段构建"), ("B", "选用精简基础镜像（alpine / distroless）"),
          ("C", "合并 RUN 并清理包缓存"), ("D", "把全部源码塞进单层")),
      ["A", "B", "C"],
      "精简基础镜像、多阶段与层合并能显著降体积；D 反而增大层且无收益。"),
    q("mw-dk-14", "single", "challenge", "advanced",
      "容器健康检查（HEALTHCHECK）的作用是？",
      opt(("A", "让编排器感知容器应用层是否真正就绪/存活"),
          ("B", "仅检查进程是否存活"), ("C", "替代日志收集"), ("D", "仅用于网络探测")),
      ["A"],
      "HEALTHCHECK 探测应用真实可用性（如 HTTP 探活），比“进程在”更能反映就绪状态。"),
]

# ---- Kubernetes (must_know / advanced) ----
QUESTIONS += [
    q("mw-k8s-1", "single", "basic", "must_know",
      "Kubernetes 中 Pod 的概念是？",
      opt(("A", "最小调度单位，可包含一个或多个共享网络/存储的容器"),
          ("B", "等同于虚拟机"), ("C", "仅是一种存储对象"), ("D", "是负载均衡器")),
      ["A"],
      "Pod 是 K8s 调度与资源管理的最小单元，同 Pod 内容器共享 IP 与卷。"),
    q("mw-k8s-2", "single", "intermediate", "must_know",
      "Deployment 的主要作用是？",
      opt(("A", "管理 ReplicaSet/Pod 副本数，并支持滚动更新与回滚"),
          ("B", "仅存储配置"), ("C", "替代 Service"), ("D", "只做 DNS 解析")),
      ["A"],
      "Deployment 声明期望副本与版本，控制器维持副本并负责无损升级/回滚。"),
    q("mw-k8s-3", "multiple", "intermediate", "must_know",
      "Kubernetes Service 的常见类型包括？",
      opt(("A", "ClusterIP（集群内访问）"), ("B", "NodePort（节点端口）"),
          ("C", "LoadBalancer（云负载均衡）"), ("D", "只有 Ingress 一种")),
      ["A", "B", "C"],
      "Service 暴露方式主要为 ClusterIP/NodePort/LoadBalancer；Ingress 是七层路由，不是 Service 类型。"),
    q("mw-k8s-4", "single", "intermediate", "must_know",
      "按域名/路径做 HTTP 路由暴露服务，通常用？",
      opt(("A", "Ingress"), ("B", "ConfigMap"), ("C", "Secret"), ("D", "Namespace")),
      ["A"],
      "Ingress 提供七层（域名/路径）路由与 TLS，统一入口；Service 解决四层发现与负载。"),
    q("mw-k8s-5", "single", "intermediate", "must_know",
      "ConfigMap 与 Secret 的主要区别是？",
      opt(("A", "ConfigMap 存普通配置，Secret 存敏感数据（口令/密钥）且可加密/收紧权限"),
          ("B", "两者完全相同"), ("C", "Secret 只能存日志"),
          ("D", "把密码放 ConfigMap 更安全")),
      ["A"],
      "Secret 面向敏感信息、有静态加密与访问收敛；敏感配置不应误放 ConfigMap。"),
    q("mw-k8s-6", "judge", "intermediate", "must_know",
      "Namespace 用于多环境/多租户隔离资源，但默认网络仍互通（需用 NetworkPolicy 限制）。",
      JUDGE_OPTIONS, ["A"],
      "Namespace 是逻辑隔离边界而非网络隔离；跨命名空间默认仍可达，需 NetworkPolicy 显式约束。"),
    q("mw-k8s-7", "single", "intermediate", "advanced",
      "Horizontal Pod Autoscaler（HPA）扩缩容的依据通常是？",
      opt(("A", "CPU/内存或自定义指标自动扩缩副本"),
          ("B", "只能手动"), ("C", "仅按时间"), ("D", "完全随机")),
      ["A"],
      "HPA 依据指标（CPU、QPS 等）自动增减副本，应对负载波动；需配 requests 才能计算使用率。"),
    q("mw-k8s-8", "multiple", "challenge", "advanced",
      "liveness 与 readiness 探针的区别是？",
      opt(("A", "liveness 失败会重启容器"),
          ("B", "readiness 失败会把 Pod 从 Service 后端摘除"),
          ("C", "两者都用于探测，但目的不同"),
          ("D", "readiness 失败也会重启容器")),
      ["A", "B", "C"],
      "liveness 探活（失败重启），readiness 探就绪（失败摘流量不重启）；二者不可混淆。"),
    q("mw-k8s-9", "single", "challenge", "advanced",
      "有状态服务（如数据库、中间件）通常更适合用哪种工作负载？",
      opt(("A", "StatefulSet（稳定网络标识与持久化卷）"),
          ("B", "普通 Deployment"), ("C", "仅 Job"), ("D", "仅 ConfigMap")),
      ["A"],
      "StatefulSet 提供稳定的 Pod 名/网络标识与按序滚动，配合 PVC 适合有状态中间件。"),
    q("mw-k8s-10", "single", "intermediate", "must_know",
      "持久化存储的抽象层级是？",
      opt(("A", "PV（集群存储资源）与 PVC（用户存储申请）解耦存储实现"),
          ("B", "直接挂载节点固定路径"), ("C", "仅内存临时存储"), ("D", "用 Secret 存数据")),
      ["A"],
      "PV/PVC 把“存储供给”与“使用”解耦，应用只声明 PVC，底层可以是云盘/NFS/本地盘。"),
    q("mw-k8s-11", "judge", "challenge", "advanced",
      "etcd 是 Kubernetes 的分布式键值存储，保存集群全部状态，是一致性与高可用的关键组件。",
      JUDGE_OPTIONS, ["A"],
      "K8s 所有对象与状态都落在 etcd；etcd 的多数派可用与数据健康直接决定集群可用性。"),
    q("mw-k8s-12", "multiple", "challenge", "advanced",
      "滚动更新（rolling update）的优点包括？",
      opt(("A", "逐步替换 Pod、实现低/零停机"),
          ("B", "可配置最大不可用/超出量平滑过渡"),
          ("C", "可一键回滚到旧 ReplicaSet"),
          ("D", "必须整批停服再切换")),
      ["A", "B", "C"],
      "滚动更新逐批替换并可控比例，配合健康检查实现平滑发布与快速回滚；D 违背其初衷。"),
    q("mw-k8s-13", "single", "challenge", "advanced",
      "Pod 长时间处于 Pending（调度失败），可能的原因包括？",
      opt(("A", "节点资源不足 / 亲和性不符 / 污点无容忍 / 配额限制 / 镜像拉取失败等"),
          ("B", "仅网络配置问题"), ("C", "仅镜像缺失"), ("D", "仅命名空间不存在")),
      ["A"],
      "Pending 多为不可调度：资源、亲和/污点、PVC 绑定、配额、镜像拉取等都可能导致。"),
    q("mw-k8s-14", "multiple", "challenge", "advanced",
      "提升 Kubernetes 集群安全与稳定的实践包括？",
      opt(("A", "基于 RBAC 的最小权限授权"), ("B", "为容器设置 resources requests/limits"),
          ("C", "镜像漏洞扫描与准入控制"), ("D", "关闭所有探针与限流")),
      ["A", "B", "C"],
      "RBAC、资源约束、镜像与准入管控是基线；D 削弱可用性与可观测性，适得其反。"),
]

# ---- 消息队列与通用运维 (must_know / advanced) ----
QUESTIONS += [
    q("mw-mq-1", "single", "basic", "must_know",
      "Kafka 与 RabbitMQ 的典型定位区别是？",
      opt(("A", "Kafka 擅长高吞吐日志/事件流，RabbitMQ 擅长低延迟路由与复杂 exchange"),
          ("B", "两者完全一样"), ("C", "都只做 RPC 调用"), ("D", "都不可持久化")),
      ["A"],
      "Kafka 面向高吞吐、可重放的流；RabbitMQ 面向灵活路由、低延迟的消息投递。"),
    q("mw-mq-2", "single", "intermediate", "must_know",
      "Kafka 中 topic 与 partition 的关系是？",
      opt(("A", "topic 可分为多个 partition，分区内消息有序、可并行消费"),
          ("B", "同一 topic 全局严格有序"), ("C", "partition 等同于 topic"),
          ("D", "二者毫无关系")),
      ["A"],
      "partition 是并行与伸缩单元，单分区内保序；跨分区不保证全局顺序。"),
    q("mw-mq-3", "multiple", "intermediate", "must_know",
      "关于消费组（consumer group），下列说法正确的有？",
      opt(("A", "同组内消费者分担不同分区，实现并行消费"),
          ("B", "组内可水平扩展提升消费能力"),
          ("C", "不同组可独立、重复消费同一 topic"),
          ("D", "一个组只能有一个消费者")),
      ["A", "B", "C"],
      "消费组实现“发布-订阅 + 队列”语义：组内竞争、组间广播；分区数限制了组内并行度。"),
    q("mw-mq-4", "single", "intermediate", "advanced",
      "消息投递语义通常包括？",
      opt(("A", "至少一次 / 至多一次 / 精确一次（exactly-once）三种常见语义"),
          ("B", "只有 exactly-once 一种，无需处理重复"),
          ("C", "重复无害，不需要幂等"), ("D", "仅 at-most-once")),
      ["A"],
      "多数 MQ 至少实现 at-least-once，精准一次需配合消费端幂等/事务；幂等设计很重要。"),
    q("mw-mq-5", "multiple", "challenge", "advanced",
      "消息积压（backlog）激增时，合理的处理方式是？",
      opt(("A", "扩容消费者实例或增加分区数"),
          ("B", "优化消费逻辑、提升单条处理速度"),
          ("C", "紧急场景临时多实例突击消费"),
          ("D", "无视即可，系统会自愈")),
      ["A", "B", "C"],
      "积压需从“消费能力”与“处理逻辑”两端入手扩缩与优化；D 只会导致延迟持续恶化。"),
    q("mw-mq-6", "single", "intermediate", "must_know",
      "死信队列（DLQ）的主要用途是？",
      opt(("A", "收容多次消费失败的消息，便于隔离与排查"),
          ("B", "单纯加速消费"), ("C", "替代主业务队列"), ("D", "仅用于打印日志")),
      ["A"],
      "DLQ 把处理失败的消息隔离，避免阻塞主队列，同时保留现场供复盘与重试。"),
    q("mw-mq-7", "judge", "intermediate", "advanced",
      "引入消息队列可以解耦生产者与消费者、削峰填谷，但带来的是最终一致性而非强一致。",
      JUDGE_OPTIONS, ["A"],
      "异步解耦提升弹性，但跨服务数据需容忍短暂不一致，并用对账/补偿保证最终一致。"),
    q("mw-mq-8", "single", "intermediate", "must_know",
      "在 Linux 上排查 CPU/内存瓶颈常用的命令是？",
      opt(("A", "top/htop、free、vmstat、iostat"), ("B", "仅 ping"),
          ("C", "仅 ls"), ("D", "仅 cat /etc/hostname")),
      ["A"],
      "top/free/vmstat/iostat 分别对应 CPU、内存、整体与磁盘 IO，是性能排查基础工具。"),
    q("mw-mq-9", "multiple", "challenge", "advanced",
      "CI/CD 流水线的目标包括？",
      opt(("A", "自动化构建/测试/部署"), ("B", "快速反馈与可重复的发布过程"),
          ("C", "把质量门禁前置、降低人工出错"), ("D", "完全替代代码评审")),
      ["A", "B", "C"],
      "CI/CD 用自动化与门禁提升交付速度与稳定性；评审仍重要，不能被流水线取代。"),
    q("mw-mq-10", "judge", "intermediate", "advanced",
      "监控告警应覆盖“四大黄金指标”：延迟、流量、错误率与饱和度。",
      JUDGE_OPTIONS, ["A"],
      "RED/USE 与四大黄金指标（延迟、流量、错误、饱和度）是服务可观测性的核心维度。"),
]


def to_staging(questions: list[dict]) -> list[dict]:
    """canonical → staging 素材格式（question_merge 读取的 schema）。"""
    records = []
    for index, item in enumerate(questions, start=1):
        kind = item["kind"]
        if kind == "judge":
            answer = "正确" if item["answer"] == ["A"] else "错误"
            options = JUDGE_OPTIONS
        elif kind == "single":
            answer = item["answer"][0]
            options = item["options"]
        else:  # multiple
            answer = ",".join(item["answer"])
            options = item["options"]
        records.append({
            "n": index,
            "language": item["language"],
            "direction": item["direction"],
            "kind": kind,
            "difficulty": item["difficulty"],
            "essentiality": item["essentiality"],
            "stem": item["prompt"],
            "options": options,
            "answer": answer,
            "explanation": item["explanation"],
        })
    return records


def validate(questions: list[dict]) -> None:
    seen_ids, seen_prompts = set(), set()
    for item in questions:
        assert item["id"] not in seen_ids, f"重复 id: {item['id']}"
        seen_ids.add(item["id"])
        assert item["prompt"] not in seen_prompts, f"重复 prompt: {item['prompt']}"
        seen_prompts.add(item["prompt"])
        opts, ans = item["options"], item["answer"]
        assert item["kind"] in ("single", "multiple", "judge")
        if item["kind"] == "judge":
            assert opts == JUDGE_OPTIONS, f"{item['id']} 判断题选项文案不符"
            assert ans in (["A"], ["B"]), f"{item['id']} 判断题答案应为 A 或 B"
        else:
            keys = {o["key"] for o in opts}
            assert 2 <= len(opts) <= 6, f"{item['id']} 选项数越界"
            assert set(ans).issubset(keys), f"{item['id']} answer 越出 options: {ans} vs {keys}"
            if item["kind"] == "single":
                assert len(ans) == 1, f"{item['id']} 单选答案应恰 1"
            else:
                assert len(ans) >= 2, f"{item['id']} 多选答案应 ≥2"
        assert item["explanation"].strip(), f"{item['id']} explanation 为空"
        assert item["difficulty"] in ("basic", "intermediate", "challenge")
        assert item["essentiality"] in ("must_know", "advanced", "nice_to_know")
        assert item["language"] == "", f"{item['id']} 中间件题语言必须为空串"


def main() -> None:
    validate(QUESTIONS)
    records = to_staging(QUESTIONS)
    STAGING_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写出 staging 素材：{STAGING_PATH}")
    print(f"题目数：{len(records)}（下一步请运行 "
          f"`python -m app.services.question_merge --write` 重建 questions.json）")


if __name__ == "__main__":
    main()
