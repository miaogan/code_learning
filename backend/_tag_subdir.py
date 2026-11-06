"""为题库 seed/questions.json 补齐 sub_direction 字段（方案 A：保留 direction，加二级细分）。

策略：
- 前端 / 后端：直接用 language 字段值（空 → 通用前端 / 通用后端）
- 其余 6 方向：题面关键词匹配（首条命中），未命中 → 通用 XX

闭集来源：rules.SUBDIRECTIONS（扩展子方向时只需在那里追加，本脚本零改动）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services.report import rules  # noqa: E402

SEED_PATH = Path(__file__).resolve().parent / "app" / "seed" / "questions.json"

#: direction → (sub_direction 候选, [关键词列表])；**顺序即优先级**（首条命中胜出）。
#: 子方向名必须与 rules.SUBDIRECTIONS 完全对齐（已在 rules.py 定义）。
_SUB_DIRECTION_HINTS: dict[str, list[tuple[str, list[str]]]] = {
    "算法与数据结构": [
        ("动态规划", ["动态规划", "背包", "状态转移方程", "dp["]),
        ("二叉树与递归", ["二叉树", "递归", "后序遍历", "中序遍历", "前序遍历", "镜像二叉树"]),
        ("链表", ["链表", "单链表", "双链表", "环形链表", "反转链表"]),
        ("排序", ["排序", "快排", "归并", "堆排", "插入排序", "冒泡排序", "选择排序"]),
        ("图", ["BFS", "DFS", "拓扑", "最短路径", "dijkstra", "bellman", "邻接表"]),
        ("复杂度", ["时间复杂度", "空间复杂度", "渐进复杂度", "O(log n)", "O(n log n)"]),
        ("哈希", ["哈希", "hash", "散列表", "哈希表"]),
    ],
    "计算机基础": [
        ("操作系统", ["进程", "线程", "协程", "内存管理", "虚拟内存", "死锁", "调度", "操作系统", "上下文切换"]),
        ("网络", ["TCP", "UDP", "三次握手", "四次挥手", "HTTP", "HTTPS", "DNS", "Socket", "SSL", "网络协议"]),
        ("组成原理", ["寄存器", "CPU", "指令集", "缓存", "流水线", "中断", "ALU"]),
    ],
    "SQL 与数据库": [
        ("事务与 ACID", ["事务", "ACID", "隔离级别", "脏读", "幻读", "不可重复读", "commit", "rollback"]),
        ("索引", ["索引", "B+树", "哈希索引", "回表", "覆盖索引", "explain"]),
        ("SQL 基础", ["SELECT", "JOIN", "GROUP BY", "HAVING", "ORDER BY", "聚合函数", "LEFT JOIN", "RIGHT JOIN"]),
        ("NoSQL", ["Redis", "MongoDB", "Elasticsearch", "KV 存储", "文档数据库", "NoSQL"]),
    ],
    "中间件与运维": [
        ("Docker 与容器", ["Docker", "容器", "镜像", "K8s", "Kubernetes", "Pod", "编排", "kubelet"]),
        ("Nginx", ["Nginx", "反向代理", "负载均衡", "upstream"]),
        ("Redis", ["Redis", "缓存穿透", "缓存击穿", "缓存雪崩", "分布式锁", "Redis Cluster"]),
        ("消息队列", ["Kafka", "RabbitMQ", "RocketMQ", "消息队列", "生产者", "消费者", "死信队列"]),
        ("监控与日志", ["监控", "Prometheus", "Grafana", "ELK", "链路追踪", "OpenTelemetry", "Metrics"]),
        ("CI-CD", ["Jenkins", "GitLab CI", "GitHub Actions", "持续集成", "持续部署", "CI/CD", "流水线"]),
    ],
    "AI 工程": [
        ("LLM 与 RAG", ["LLM", "大模型", "RAG", "检索增强", "embedding", "向量检索", "召回", "向量数据库"]),
        ("Agent", ["Agent", "工具调用", "function_call", "function call", "ReAct", "tool call", "planning"]),
        ("Prompt 工程", ["Prompt", "提示词", "system prompt", "few-shot", "zero-shot", "链式思考", "CoT"]),
        ("部署与推理", ["推理", "GPU", "vLLM", "TGI", "量化", "serving", "TensorRT", "ONNX", "CUDA"]),
    ],
    "研发工程实践": [
        ("Git 与版本控制", ["git ", "Git ", "commit", "rebase", "merge", "分支策略", "代码提交", "PR"]),
        ("测试", ["单元测试", "集成测试", "TDD", "Mock", "JUnit", "pytest", "覆盖率", "测试驱动"]),
        ("CI-CD", ["持续集成", "持续交付", "持续部署", "CI 流水线", "质量门禁"]),
        ("架构设计", ["微服务", "DDD", "领域驱动", "设计模式", "SOLID", "单体架构", "架构风格"]),
    ],
}


def _match_sub_direction(direction: str, prompt: str, language: str) -> str:
    """按 direction 选分支，返回 sub_direction。"""
    # 前端 / 后端：直接用 language
    if direction in ("前端", "后端"):
        if language and language in rules.SUBDIRECTIONS[direction]:
            return language
        return rules.generic_sub_direction_of(direction)

    # 其余方向：关键词匹配
    hints = _SUB_DIRECTION_HINTS.get(direction, [])
    prompt_lower = prompt.lower()
    for sub, kws in hints:
        if any(kw.lower() in prompt_lower for kw in kws):
            return sub
    return rules.generic_sub_direction_of(direction)


def main() -> None:
    questions = json.loads(SEED_PATH.read_text(encoding="utf-8"))

    # 第一轮：匹配并收集统计
    from collections import Counter

    old_count = sum(1 for q in questions if q.get("sub_direction"))
    print(f"已有 sub_direction: {old_count} / {len(questions)}")

    for q in questions:
        direction = q.get("direction", "")
        language = (q.get("language") or "").strip()
        prompt = q.get("prompt", "")
        sub = _match_sub_direction(direction, prompt, language)
        q["sub_direction"] = sub

    # 统计
    from collections import defaultdict

    by_dir_sub: dict[str, Counter[str]] = defaultdict(Counter)
    for q in questions:
        by_dir_sub[q["direction"]][q.get("sub_direction", "")] += 1

    print("\n=== 各方向 sub_direction 分布 ===")
    for d, counter in by_dir_sub.items():
        print(f"\n{d}: {len(counter)} 个子方向")
        for sub, n in counter.most_common():
            print(f"  {sub:<16} {n:>4}")

    # 校验：所有 sub_direction 都在闭集里
    bad = [
        (q["id"], q["direction"], q.get("sub_direction"))
        for q in questions
        if not rules.is_valid_sub_direction(q.get("direction", ""), q.get("sub_direction"))
    ]
    if bad:
        print(f"\n!!! 有 {len(bad)} 题 sub_direction 越界：")
        for qid, d, sub in bad[:10]:
            print(f"  {qid}: {d} -> {sub}")
        sys.exit(1)

    # 写回
    SEED_PATH.write_text(json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 已写入 {len(questions)} 题（{SEED_PATH}）")


if __name__ == "__main__":
    main()
