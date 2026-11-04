"""把一个方向的题库导出为「可直接刷」的 Markdown（仿 docs/AI工程面试题集.md 格式）。

用法：
    python scripts/export_direction_md.py "中间件与运维"
    python scripts/export_direction_md.py "AI 工程"

读取 `docs/question-bank-staging/*.json`（staging 是带分类前缀 id 的 canonical 源，
如 mw-pg-1 / mw-rd-1，能保留 PostgreSQL / Redis 等小节），按 id 第二段归类成小节，
选项后标 ✅ 表示正确项，末尾给出「答案 + 解析」。不写第二份题目数据——唯一来源仍是
staging / questions.json，本脚本只是可读镜像。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGING_DIR = ROOT / "docs" / "question-bank-staging"

CATEGORY_MAP = {
    # 中间件与运维
    "pg": "PostgreSQL",
    "rd": "Redis",
    "ng": "Nginx",
    "dk": "Docker",
    "k8s": "Kubernetes",
    "mq": "消息队列与通用运维",
    # SQL 与数据库
    "select": "基础查询与过滤",
    "join": "JOIN 连接",
    "agg": "聚合与分组",
    "subq": "子查询与 CTE",
    "window": "窗口函数",
    "index": "索引与执行计划",
    "tx": "事务与锁",
    "design": "范式与设计",
    "perf": "性能优化",
    # 基础算法（并入「算法与数据结构」方向时按需导出）
    "complexity": "复杂度与基础",
    "sort": "排序",
    "search": "二分与查找",
    "twoptr": "双指针与滑动窗口",
    "recursion": "递归与回溯",
    "dp": "动态规划入门",
    "ds": "哈希/栈/队列",
    "tree": "链表与树遍历",
    "bit": "位运算入门",
    # 研发工程实践
    "git": "Git 与版本控制",
    "cicd": "CI/CD 与流水线",
    "req": "需求对接与协作",
    "test": "测试与质量",
    "review": "代码评审与规范",
    "release": "发布与故障协作",
}
KIND_LABEL = {"single": "单选", "multiple": "多选", "judge": "判断"}
DIFF_LABEL = {"basic": "基础", "intermediate": "进阶", "challenge": "挑战"}
ESS_LABEL = {"must_know": "必会", "advanced": "进阶", "nice_to_know": "选修"}


def _category(row: dict) -> str:
    segs = str(row.get("id") or "").split("-")
    if len(segs) >= 2:
        return CATEGORY_MAP.get(segs[1], segs[1])
    return "其他"


def _option_is_correct(row: dict, option: dict) -> bool:
    answer = str(row.get("answer") or "")
    key = str(option.get("key") or "")
    text = str(option.get("text") or "")
    if row.get("kind") == "judge":
        return text == answer  # 判断题 answer 是「正确」/「错误」文案
    return key in {part.strip() for part in answer.replace("，", ",").split(",") if part.strip()}


def _answer_text(row: dict) -> str:
    answer = str(row.get("answer") or "")
    if row.get("kind") == "judge":
        return answer
    labels = {"A": "A", "B": "B", "C": "C", "D": "D", "E": "E", "F": "F"}
    return "、".join(
        labels.get(part.strip(), part.strip())
        for part in answer.replace("，", ",").split(",")
        if part.strip()
    )


def render(rows: list[dict], direction: str) -> str:
    kinds = {"single": 0, "multiple": 0, "judge": 0}
    elective = 0
    sections: dict[str, list[dict]] = {}
    for row in rows:
        kind = str(row.get("kind"))
        kinds[kind] = kinds.get(kind, 0) + 1
        if str(row.get("essentiality")) == "nice_to_know":
            elective += 1
        sections.setdefault(_category(row), []).append(row)

    lines: list[str] = []
    total = len(rows)
    lines.append(f"# {direction}面试题集（{total} 题 · 可直接刷）\n")
    lines.append(
        f"> 来源：`backend/app/seed/questions.json` 的 `{direction}` 方向题"
        f"（已并入统一题库，方向与语言闭集一致）。\n"
    )
    lines.append(
        "> 题型：单选 / 多选 / 判断；标注「选修」的为非核心进阶内容，可作为对应方向的进阶选读。\n"
    )
    lines.append(
        f"**题量**：{total} 道 ｜ 单选 {kinds['single']} ｜ 多选 {kinds['multiple']} "
        f"｜ 判断 {kinds['judge']} ｜ 选修 {elective} 道\n"
    )
    lines.append("")

    for category, items in sections.items():
        lines.append(f"## {category}\n")
        for index, row in enumerate(items, start=1):
            kind = KIND_LABEL.get(str(row.get("kind")), str(row.get("kind")))
            diff = DIFF_LABEL.get(str(row.get("difficulty")), str(row.get("difficulty")))
            ess = ESS_LABEL.get(str(row.get("essentiality")), str(row.get("essentiality")))
            lines.append(
                f"### Q{index}. 【{kind} · {diff} · {ess}】 {row.get('stem') or row.get('prompt')}\n"
            )
            for opt in row.get("options") or []:
                mark = " ✅" if _option_is_correct(row, opt) else ""
                lines.append(f"- {opt.get('key')}. {opt.get('text')}{mark}")
            lines.append("")
            lines.append(
                f"**答案**：{_answer_text(row)}　**解析**：{row.get('explanation')}\n"
            )
    return "\n".join(lines)


def main() -> None:
    direction = sys.argv[1] if len(sys.argv) > 1 else "中间件与运维"
    rows: list[dict] = []
    for path in sorted(STAGING_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, list):
            continue
        rows.extend(r for r in data if str(r.get("direction") or "") == direction)
    if not rows:
        raise SystemExit(f"方向「{direction}」在 staging 中无题目")
    out_path = ROOT / "docs" / f"{direction}面试题集.md"
    out_path.write_text(render(rows, direction), encoding="utf-8")
    print(f"已写出：{out_path}（{len(rows)} 题，{len({_category(r) for r in rows})} 个分类）")


if __name__ == "__main__":
    main()
