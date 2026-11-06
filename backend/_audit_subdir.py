"""扫题库每个方向的关键词分布，为 sub_direction 自动打标签做准备。"""
import json
from collections import Counter, defaultdict

data = json.load(open("app/seed/questions.json", encoding="utf-8"))
by_dir = defaultdict(list)
for q in data:
    by_dir[q.get("direction", "")].append(q)

KEYWORDS = {
    "算法与数据结构": {
        "动态规划": ["动态规划", "背包", "状态转移", "dp"],
        "二叉树/递归": ["二叉树", "递归", "递归树", "后序", "中序", "前序"],
        "链表": ["链表", "单链表", "双链表", "环形链表"],
        "排序": ["排序", "快排", "归并", "堆排", "插入排序", "冒泡"],
        "图": ["图", "BFS", "DFS", "拓扑", "最短路径", "dijkstra", "dijkstra"],
        "复杂度": ["复杂度", "O(n", "时间复杂度", "空间复杂度", "渐进"],
        "哈希": ["哈希", "hash", "散列表"],
        "其他数据结构": ["栈", "队列", "堆", "优先队列", "集合", "字典"],
    },
    "计算机基础": {
        "操作系统": ["进程", "线程", "协程", "内存", "分页", "虚拟内存", "死锁", "调度", "操作系统"],
        "网络": ["TCP", "UDP", "HTTP", "HTTPS", "三次握手", "四次挥手", "IP", "DNS", "网络", "Socket"],
        "编译原理": ["编译", "编译器", "词法", "语法树", "AST", "字节码"],
        "组成原理": ["寄存器", "CPU", "指令", "缓存", "流水线", "中断"],
    },
    "SQL 与数据库": {
        "SQL 基础": ["SELECT", "JOIN", "GROUP BY", "HAVING", "聚合", "SQL"],
        "事务/ACID": ["事务", "ACID", "隔离级别", "脏读", "幻读", "不可重复读", "commit", "rollback"],
        "索引": ["索引", "B+树", "B树", "哈希索引", "回表", "覆盖索引"],
        "分库分表": ["分库分表", "分片", "sharding", "水平拆分", "垂直拆分"],
        "性能调优": ["慢查询", "调优", "explain", "执行计划", "优化"],
        "NoSQL": ["Redis", "MongoDB", "Elasticsearch", "ES", "KV", "文档数据库"],
    },
    "中间件与运维": {
        "Docker/容器": ["Docker", "容器", "镜像", "K8s", "Kubernetes", "Pod", "编排"],
        "Nginx/Web": ["Nginx", "反向代理", "负载均衡", "HTTPS", "SSL", "CDN"],
        "Redis/缓存": ["Redis", "缓存", "穿透", "击穿", "雪崩", "分布式锁"],
        "消息队列": ["Kafka", "RabbitMQ", "RocketMQ", "消息队列", "MQ", "生产者", "消费者"],
        "监控/日志": ["监控", "Prometheus", "Grafana", "日志", "ELK", "链路追踪"],
        "CI-CD": ["Jenkins", "GitLab CI", "GitHub Actions", "持续集成", "持续部署", "CI/CD", "流水线"],
    },
    "AI 工程": {
        "LLM/RAG": ["LLM", "RAG", "大模型", "检索增强", "向量", "embedding", "召回"],
        "Agent": ["Agent", "工具调用", "function call", "function_call", "ReAct"],
        "Prompt 工程": ["Prompt", "提示词", "system prompt", "few-shot", "零样本", "少样本"],
        "Fine-tuning": ["微调", "fine-tun", "LoRA", "adapter", "参数高效"],
        "模型评估": ["评估", "benchmark", "BLEU", "ROUGE", "准确率", "precision"],
        "部署/推理": ["推理", "部署", "GPU", "量化", "vLLM", "TGI", "serving"],
    },
    "研发工程实践": {
        "Git/版本控制": ["Git", "commit", "merge", "rebase", "分支", "PR", "Pull Request"],
        "测试": ["测试", "单元测试", "集成测试", "TDD", "Mock", "pytest", "JUnit"],
        "架构设计": ["架构", "微服务", "单体", "领域驱动", "DDD", "设计模式", "SOLID"],
        "代码审查": ["代码审查", "Code Review", "CR", "结对编程"],
        "性能": ["性能", "压测", "负载测试", "profiling", "火焰图"],
    },
}

# 先抽样看每个方向的关键词命中情况
for d, patterns in KEYWORDS.items():
    subset = by_dir.get(d, [])
    print(f"\n=== {d} ({len(subset)} 题) ===")
    for sub, kws in patterns.items():
        hits = sum(1 for q in subset if any(kw.lower() in q["prompt"].lower() for kw in kws))
        print(f"  {sub}: {hits}")
    unmatched = [q for q in subset if not any(
        any(kw.lower() in q["prompt"].lower() for kw in patterns[s]) for s in patterns
    )]
    print(f"  未匹配: {len(unmatched)}")
    for q in unmatched[:5]:
        print(f"    [{q['id']}] {q['prompt'][:70]}")
