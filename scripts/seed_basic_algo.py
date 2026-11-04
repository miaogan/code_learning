"""生成「基础算法」题库的 **staging 素材文件**（并入现有「算法与数据结构」方向）。

本脚本只产出 `docs/question-bank-staging/08-basic-algo.json`；`question_merge`
从该文件 + 存量重建 `app/seed/questions.json`（写完 staging 后跑
`python -m app.services.question_merge --write`）。

约束：
- 方向 direction = "算法与数据结构"（复用现有方向，不新增方向闭集）
- 语言 language = ""
- 来源 source = "algo"（question_merge.SOURCES 已新增；由 STAGING 文件名决定）
- kind ∈ {single, multiple, judge}

选项长度纪律同 seed_sql.py：正确项平均长度不超过干扰项平均的 3 倍，`validate()` 硬校验。
幂等：重跑整体重写该 staging 文件。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGING_PATH = ROOT / "docs" / "question-bank-staging" / "08-basic-algo.json"

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
        "direction": "算法与数据结构",
        "prompt": prompt,
        "options": options,
        "answer": answer,
        "explanation": explanation,
    }


def opt(*pairs: tuple[str, str]) -> list[dict]:
    return [{"key": k, "text": t} for k, t in pairs]


QUESTIONS: list[dict] = []

# ---- 复杂度与基础 ----
QUESTIONS += [
    q("algo-complexity-1", "single", "basic", "must_know",
      "在有序数组上二分查找的时间复杂度是？",
      opt(("A", "O(log n)"), ("B", "O(n)"), ("C", "O(n log n)"), ("D", "O(1)")),
      ["A"],
      "每次折半，比较次数与 log₂n 成正比，故为 O(log n)。"),
    q("algo-complexity-2", "single", "basic", "must_know",
      "快速排序的平均时间复杂度是？",
      opt(("A", "O(n log n)"), ("B", "O(n)"), ("C", "O(n²)"), ("D", "O(log n)")),
      ["A"],
      "平均与最优为 O(n log n)，最坏（如已有序且取端点基准）退化为 O(n²)。"),
    q("algo-complexity-3", "judge", "intermediate", "must_know",
      "哈希表查找的平均时间复杂度是 O(1)。",
      JUDGE_OPTIONS, ["A"],
      "良好哈希且负载因子可控时平均 O(1)；冲突严重退化时会接近 O(n)。"),
]

# ---- 排序 ----
QUESTIONS += [
    q("algo-sort-1", "single", "basic", "must_know",
      "下列哪种排序算法是稳定的？",
      opt(("A", "归并排序"), ("B", "快速排序"), ("C", "堆排序"), ("D", "选择排序")),
      ["A"],
      "归并排序稳定；快排/堆排/选择排序通常不稳定（相等元素相对次序可能改变）。"),
    q("algo-sort-2", "single", "intermediate", "advanced",
      "快速排序的最坏时间复杂度通常出现在？",
      opt(("A", "已基本有序且取端点为基准"),
          ("B", "数据完全随机分布"),
          ("C", "元素全部互不相同"),
          ("D", "数据量很小的数组")),
      ["A"],
      "取端点作基准且数据已有序时分区极不均衡，退化为 O(n²)；随机基准可缓解。"),
    q("algo-sort-3", "judge", "intermediate", "advanced",
      "归并排序的空间复杂度为 O(n)，且是稳定排序。",
      JUDGE_OPTIONS, ["A"],
      "归并需额外 O(n) 辅助数组，合并时相等元素保持原序，故稳定。"),
    q("algo-sort-4", "single", "intermediate", "advanced",
      "堆排序构建初始堆的时间复杂度是？",
      opt(("A", "O(n)"), ("B", "O(n log n)"), ("C", "O(log n)"), ("D", "O(n²)")),
      ["A"],
      "自底向上建堆为 O(n)；之后每次取堆顶再调整，整体排序为 O(n log n)。"),
]

# ---- 二分与查找 ----
QUESTIONS += [
    q("algo-search-1", "single", "basic", "must_know",
      "二分查找能正确工作的前提是？",
      opt(("A", "数组有序"), ("B", "数组无序"),
          ("C", "元素都是字符串"), ("D", "数组长度是偶数")),
      ["A"],
      "二分依赖有序性来判定收缩方向；无序数组需先排序或改用哈希/线性查找。"),
    q("algo-search-2", "single", "intermediate", "advanced",
      "二分查找（循环实现）的区间更新通常是？",
      opt(("A", "mid 命中即返回，否则据大小收缩 low 或 high"),
          ("B", "每次都把搜索区间整体翻倍扩大"),
          ("C", "从数组两端同时向中间遍历"),
          ("D", "先整体排序再做一轮线性扫描")),
      ["A"],
      "比较 a[mid] 与目标：小了抬 low、大了降 high，区间不断折半直至命中或越界。"),
    q("algo-search-3", "single", "intermediate", "advanced",
      "在有序数组中找第一个 >= target 的位置，常用哪种二分？",
      opt(("A", "二分查找下界（lower_bound）"),
          ("B", "用哈希表统计每个元素频次"),
          ("C", "用双指针从两端相向移动"),
          ("D", "先冒泡排序再逐个取值")),
      ["A"],
      "下界二分在 a[mid] >= target 时收缩右界，最终得第一个满足条件的位置。"),
    q("algo-search-4", "judge", "basic", "advanced",
      "二分查找只能用于数组，不能用于其他结构或单调函数。",
      JUDGE_OPTIONS, ["B"],
      "错误：二分的本质是「单调性」上的折半，可用于二分答案、单调函数、平衡 BST 等。"),
]

# ---- 双指针与滑动窗口 ----
QUESTIONS += [
    q("algo-twoptr-1", "single", "basic", "must_know",
      "有序数组中求两数之和等于目标，常用？",
      opt(("A", "左右双指针从两端向中间"),
          ("B", "暴力两重循环枚举"),
          ("C", "先排序再去重"),
          ("D", "按位异或")),
      ["A"],
      "和偏小移动左指针、偏大移动右指针，O(n) 内找到答案（数组已有序的前提下）。"),
    q("algo-twoptr-2", "single", "intermediate", "advanced",
      "滑动窗口最适合解决哪类问题？",
      opt(("A", "连续子数组/子串的区间最值或计数"),
          ("B", "树的最短路径"),
          ("C", "图的强连通分量"),
          ("D", "全排列的生成")),
      ["A"],
      "窗口在满足「单调可维护」的区间条件上做右扩左缩，适合连续子段统计。"),
    q("algo-twoptr-3", "single", "intermediate", "advanced",
      "滑动窗口「右扩左缩」的典型判定是？",
      opt(("A", "满足条件时收缩左界、否则扩张右界"),
          ("B", "左右界同时向中间移动"),
          ("C", "只扩张右界、从不收缩"),
          ("D", "只收缩左界、从不扩张")),
      ["A"],
      "右界负责纳入新元素，一旦窗口满足约束就移动左界缩小，直到不再满足。"),
    q("algo-twoptr-4", "judge", "intermediate", "advanced",
      "滑动窗口内维护的状态（如频次计数）必须在左界收缩时同步更新。",
      JUDGE_OPTIONS, ["A"],
      "否则窗口状态与实际区间不一致，会导致判断错误；左右移动都要维护同一份状态。"),
]

# ---- 递归与回溯 ----
QUESTIONS += [
    q("algo-recursion-1", "single", "basic", "must_know",
      "一个正确的递归算法必须包含的两部分是？",
      opt(("A", "基础情形（终止条件）与递推关系"),
          ("B", "循环与条件分支"),
          ("C", "栈与队列结构"),
          ("D", "哈希与排序算法")),
      ["A"],
      "没有终止条件会无限递归；递推关系把大问题化为更小的同类子问题。"),
    q("algo-recursion-2", "single", "intermediate", "advanced",
      "回溯法（backtracking）的核心操作是？",
      opt(("A", "做出选择→递归→撤销选择"),
          ("B", "只递归、从不撤销"),
          ("C", "只做记忆化存储"),
          ("D", "用循环替换所有递归")),
      ["A"],
      "回溯在递归前后分别「选择」与「撤销选择」，从而系统地枚举并剪枝。"),
    q("algo-recursion-3", "judge", "intermediate", "advanced",
      "递归过深可能导致栈溢出，可改为迭代或使用显式栈。",
      JUDGE_OPTIONS, ["A"],
      "每层递归占用调用栈空间，深度过大溢出；迭代/显式栈可避免。"),
]

# ---- 动态规划入门 ----
QUESTIONS += [
    q("algo-dp-1", "single", "basic", "must_know",
      "动态规划适合的问题通常具有？",
      opt(("A", "最优子结构与重叠子问题"),
          ("B", "只能分治、不能重叠"),
          ("C", "必须是线性结构"),
          ("D", "无需定义状态")),
      ["A"],
      "最优子结构保证可递推，重叠子问题使「记忆化/表格」能避免重复计算。"),
    q("algo-dp-2", "single", "intermediate", "advanced",
      "动态规划与分治的关键区别是？",
      opt(("A", "DP 会缓存重叠子问题的结果"),
          ("B", "DP 不做任何重复计算"),
          ("C", "分治一定比 DP 更快"),
          ("D", "两者完全相同")),
      ["A"],
      "分治的子问题通常互不重叠；DP 针对重叠子问题缓存结果（自底向上或记忆化）。"),
    q("algo-dp-3", "single", "intermediate", "advanced",
      "0-1 背包中 dp[j] 通常表示？",
      opt(("A", "容量为 j 时能取得的最大价值"),
          ("B", "物品数量为 j 时的总重量"),
          ("C", "第 j 个物品的价值"),
          ("D", "容量为 j 时的物品个数")),
      ["A"],
      "dp[j] = 容量 j 下的最优价值，逐个物品更新；一维时容量需倒序以保证 0-1。"),
    q("algo-dp-4", "judge", "intermediate", "advanced",
      "一维 0-1 背包用一维数组时，容量维度需倒序遍历，避免同一物品被重复选入。",
      JUDGE_OPTIONS, ["A"],
      "倒序遍历保证 dp[j] 用到的是「上一轮」的值，等价于每件物品只用一次。"),
]

# ---- 哈希/栈/队列 ----
QUESTIONS += [
    q("algo-ds-1", "single", "basic", "must_know",
      "用哈希表统计元素频次，平均查找开销是？",
      opt(("A", "O(1)"), ("B", "O(n)"), ("C", "O(log n)"), ("D", "O(n²)")),
      ["A"],
      "哈希平均 O(1) 完成插入/查找/更新，是频次统计与去重的常用结构。"),
    q("algo-ds-2", "single", "intermediate", "must_know",
      "括号匹配问题最适合用哪种数据结构？",
      opt(("A", "栈"), ("B", "队列"), ("C", "堆"), ("D", "哈希表")),
      ["A"],
      "左括号入栈、右括号出栈比对，栈的 LIFO 正好匹配括号的嵌套顺序。"),
    q("algo-ds-3", "single", "intermediate", "advanced",
      "用两个栈可以实现一个？",
      opt(("A", "队列"), ("B", "堆"), ("C", "图"), ("D", "并查集")),
      ["A"],
      "一个入栈、一个出栈，倒腾两次即可实现先进先出，即用两个栈模拟队列。"),
    q("algo-ds-4", "judge", "basic", "advanced",
      "哈希表处理冲突时，链地址法与开放寻址法是常见策略。",
      JUDGE_OPTIONS, ["A"],
      "链地址法把冲突元素串成链表；开放寻址法按探测序列找空位，各有取舍。"),
]

# ---- 链表与树遍历 ----
QUESTIONS += [
    q("algo-tree-1", "single", "basic", "must_know",
      "二叉树的前序遍历顺序是？",
      opt(("A", "根→左→右"), ("B", "左→根→右"),
          ("C", "左→右→根"), ("D", "右→根→左")),
      ["A"],
      "前序「根左右」、中序「左根右」、后序「左右根」；层序则按层 BFS。"),
    q("algo-tree-2", "single", "intermediate", "must_know",
      "二叉搜索树（BST）的中序遍历结果是？",
      opt(("A", "升序有序序列"), ("B", "降序有序序列"),
          ("C", "随机无序序列"), ("D", "按层排列的序列")),
      ["A"],
      "BST 左<根<右，中序遍历「左根右」天然得到升序序列。"),
    q("algo-tree-3", "judge", "intermediate", "advanced",
      "判断链表是否有环常用快慢指针（Floyd 判圈）法。",
      JUDGE_OPTIONS, ["A"],
      "快指针每次两步、慢指针一步，若有环必相遇；相遇后可再求环入口。"),
]

# ---- 位运算 ----
QUESTIONS += [
    q("algo-bit-1", "single", "intermediate", "advanced",
      "表达式 x & (x - 1) 的作用是？",
      opt(("A", "清除 x 最低位的 1"),
          ("B", "把 x 整体置零"),
          ("C", "取出 x 的最高位"),
          ("D", "对 x 按位取反")),
      ["A"],
      "x-1 会把最低位的 1 变 0、其后变 1，再与 x 按位与即清除最低位的 1（可用于数 1 的个数）。"),
]


def _length_ratio(item: dict) -> float:
    if item["kind"] == "judge":
        return 1.0
    ans = set(item["answer"])
    right = [len(o["text"]) for o in item["options"] if o["key"] in ans]
    wrong = [len(o["text"]) for o in item["options"] if o["key"] not in ans]
    if not right or not wrong:
        return 1.0
    return (sum(right) / len(right)) / max(1, sum(wrong) / len(wrong))


def to_staging(questions: list[dict]) -> list[dict]:
    records = []
    for index, item in enumerate(questions, start=1):
        kind = item["kind"]
        if kind == "judge":
            answer = "正确" if item["answer"] == ["A"] else "错误"
            options = JUDGE_OPTIONS
        elif kind == "single":
            answer = item["answer"][0]
            options = item["options"]
        else:
            answer = ",".join(item["answer"])
            options = item["options"]
        records.append({
            "n": index,
            "id": item["id"],
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
        assert item["language"] == "", f"{item['id']} 算法题语言必须为空串"
        ratio = _length_ratio(item)
        assert ratio <= 2.9, f"{item['id']} 正确项/干扰项长度比 {ratio:.2f} > 2.9（需平衡选项）"


def main() -> None:
    validate(QUESTIONS)
    records = to_staging(QUESTIONS)
    STAGING_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写出 staging 素材：{STAGING_PATH}")
    print(f"题目数：{len(records)}（下一步请运行 "
          f"`python -m app.services.question_merge --write` 重建 questions.json）")


if __name__ == "__main__":
    main()
