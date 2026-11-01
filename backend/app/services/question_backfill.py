"""存量题库的语言回填算法（r11 · TECHNICAL §3.2）：纯函数、无 DB、无网络、运行时不调用。

为什么单独成一个模块：`language` 是题库的第五维，存量 80 题原本没有这一列。若靠人一题一题
「感觉」打标签，同一份种子跑两次会得到不同结果，AC-2 的「两次运行字节相等」永远不成立。
因此回填必须是**确定性算法**：方向约束 → 关键词表（长词优先）→ 命中即停 → 未命中留空。

五步（顺序即语义，改顺序等于改口径）：

1. **方向预判**：`算法与数据结构` / `计算机基础` → 恒返回 `""`（这两类题与语言无关，不看关键词）。
2. **候选集约束**：候选 language = `rules.languages_for_direction(direction)`（前端 6 种、后端 3 种）。
3. **长词优先**：`(-len(关键词), LANGUAGES 序号, 关键词)` 全序排序，稳定可复现。
4. **边界安全匹配**：纯 ASCII 关键词要词边界（否则 `go` 会命中 `django`、`js` 会命中 `json`），
   中文关键词按子串；文本 = 题干 + 空格 + 各选项 text，统一小写。
5. **命中即停**：第一个命中项若不在候选集（方向不符，例如前端方向命中 `python`）→ **丢弃并继续**；
   全部不命中 → 返回 `""`（留空，绝不硬凑）。

两条只读不写的使用方式：

- 一次性落地（把结果写进 `app/seed/questions.json`）由人执行文件编辑，不由命令行改写源文件；
- `python -m app.services.question_backfill --check` 只打印/断言「种子是否已回填完成」，不写任何文件。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

from . import rules

#: 每语言的关键词表（**长词在前**是可读性约定；真正的顺序由 `ordered_keywords()` 按长度重排）。
#: 只允许「加长词 / 加专有名词」来提升命中，**不允许**为此改算法（AC-2）。
#: 关键原则：宁缺勿滥 —— 一个泛化词（`map` / `协程` / `标签`）宁可不要，也不要让通用题被硬归类。
BACKFILL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "python": (
        "列表推导",
        "上下文管理器",
        "装饰器",
        "生成器",
        "鸭子类型",
        "python",
        "gil",
        "pandas",
        "django",
        "flask",
        "numpy",
        "asyncio",
    ),
    "java": (
        "垃圾回收",
        "线程池",
        "字节码",
        "spring boot",
        "java",
        "jvm",
        "jdk",
        "spring",
        "maven",
        "泛型",
    ),
    "go": (
        "goroutine",
        "interface{}",
        "channel",
        "defer",
        "go 语言",
        "go语言",
        "golang",
        "切片",
        "并发安全",
    ),
    "ts": (
        "typescript",
        "类型体操",
        "类型收窄",
        "类型守卫",
        "tsconfig",
        "as const",
        "interface",
        "泛型",
        "tsx",
        "枚举",
    ),
    "js": (
        "javascript",
        "event loop",
        "事件循环",
        "原型链",
        "箭头函数",
        "微任务",
        "事件传播",
        "事件冒泡",
        "localstorage",
        "闭包",
        "promise",
        "async",
        "await",
        "js",
    ),
    "css": (
        "选择器权重",
        "层叠上下文",
        "盒模型",
        "css",
        "flex",
        "grid",
        "z-index",
        "position",
        "浮动",
        "伪类",
    ),
    "html": (
        "语义化",
        "无障碍",
        "html",
        "dom",
        "<div",
        "表单",
        "href",
        "alt",
    ),
    "vue3": (
        "组合式 api",
        "响应式原理",
        "模板编译",
        "vue 3",
        "vue3",
        "vuex",
        "pinia",
        "vue-router",
        "v-model",
        "vue",
    ),
    "react": (
        "usecontext",
        "useeffect",
        "usememo",
        "usestate",
        "虚拟 dom",
        "redux",
        "hooks",
        "fiber",
        "react",
        "hook",
        "jsx",
        "tsx",
    ),
}

#: 词边界字符集：只有「ASCII 字母 / 数字 / 下划线」相连才算同一个词。
#: 中文不是词边界字符 —— `Python的列表推导` 里 `python` 仍应命中（中文紧贴英文是中文技术文常态）。
_WORD_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")

#: 与语言无关的方向（由 `DIRECTIONS` 与 `LANGUAGE_DIRECTION` 派生，不写第二份方向字面量）。
_NO_LANGUAGE_DIRECTIONS: frozenset[str] = frozenset(
    direction
    for direction in rules.DIRECTIONS
    if direction not in set(rules.LANGUAGE_DIRECTION.values())
)

_ORDER_CACHE: dict[tuple[str, ...], tuple[tuple[re.Pattern[str], str], ...]] = {}


def _edge_pattern(keyword: str) -> re.Pattern[str]:
    """单个关键词的匹配式：ASCII 端加词边界断言，中文端不加（中文天然是边界）。"""
    prefix = r"(?<![a-z0-9_])" if keyword[0] in _WORD_CHARS else ""
    suffix = r"(?![a-z0-9_])" if keyword[-1] in _WORD_CHARS else ""
    return re.compile(prefix + re.escape(keyword) + suffix)


def ordered_keywords(languages: Sequence[str] | None = None) -> list[tuple[str, str]]:
    """把关键词拍平成 `(keyword, language)` 并按「长词优先 + 语言闭集序号 + 字典序」全序排列。

    传入 `languages` 可限定候选语言（缺省取整个闭集）：排序键里仍用 `LANGUAGES` 的全局序号，
    这样「同一批关键词、不同候选集」的相对顺序不变 —— 回填结果不会因为过滤顺序而抖动。
    """
    allowed = list(rules.LANGUAGES if languages is None else languages)
    pairs = [
        (keyword.lower(), language)
        for language in allowed
        for keyword in BACKFILL_KEYWORDS.get(language, ())
    ]
    order = {language: index for index, language in enumerate(rules.LANGUAGES)}
    pairs.sort(key=lambda pair: (-len(pair[0]), order.get(pair[1], len(order)), pair[0]))
    return pairs


def _ordered_patterns() -> tuple[tuple[re.Pattern[str], str], ...]:
    """全闭集的关键词匹配式（进程内只编译一次，避免回填 260 题时反复编译）。"""
    cached = _ORDER_CACHE.get(rules.LANGUAGES)
    if cached is None:
        cached = tuple((_edge_pattern(keyword), language) for keyword, language in ordered_keywords())
        _ORDER_CACHE[rules.LANGUAGES] = cached
    return cached


def question_text(question: dict[str, Any]) -> str:
    """参与匹配的文本 = 题干 + 空格 + 各选项 text（答案不参与：答案本身就是标签，会自我强化）。"""
    parts = [str(question.get("prompt") or "")]
    for option in question.get("options") or []:
        if isinstance(option, dict):
            parts.append(str(option.get("text") or ""))
        elif isinstance(option, str):
            parts.append(option)
    return " ".join(part for part in parts if part)


def infer_language(direction: str, text: str) -> str:
    """五步算法 → `language`（闭集成员；未命中返回 `""` = 通用/算法题）。"""
    if direction in _NO_LANGUAGE_DIRECTIONS:
        return ""
    candidates = set(rules.languages_for_direction(direction))
    haystack = text.lower()
    for pattern, language in _ordered_patterns():
        if not pattern.search(haystack):
            continue
        if language in candidates:
            return language
        # 方向不符（示例：前端方向命中 `python`）：丢弃这个命中，继续找下一个关键词。
    return ""


def backfill_seed(
    questions: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """对**还没有 language 键**的条目回填语言，返回 `(新列表, 本次判定计数)`。

    - 判定条件严格是「键缺失 / 值为 None」：`"language": ""` 是**已经做出的判定**（通用题），
      不会被重新推断。这样同一份已回填的种子跑第二次 `hits` 为空、内容逐字相等（AC-2 的
      「两次运行字节相等」），也不会把人工确认的留空悄悄改成别的语言。
    - 想重新推导某题语言：删掉它的 `language` 键再跑（而不是改关键词去凑答案）。
    - 返回的是**新列表 / 新字典**（不改入参），便于测试直接比较两次运行的序列化结果。
    - `hits` 的键是判定出的语言（`""` 表示留空），值是条数；只统计本次真正做出判定的行。
    """
    rows: list[dict[str, Any]] = []
    hits: dict[str, int] = {}
    for question in questions:
        row = dict(question)
        if row.get("language") is None:
            language = infer_language(str(row.get("direction") or ""), question_text(row))
            row["language"] = language
            hits[language] = hits.get(language, 0) + 1
        rows.append(row)
    return rows, hits


def dumps(questions: Sequence[dict[str, Any]]) -> str:
    """种子文件的规范序列化（AC-2 的「字节相等」以它为准：同一份数据 → 同一串字节）。"""
    return json.dumps(list(questions), ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    """`python -m app.services.question_backfill [--check]`：只读诊断，绝不写文件。

    - 无参数：打印当前种子的回填判定（每语言命中数 + 留空数），并打印语言分布。
    - `--check`：断言种子已全部回填（再跑一次 0 条判定），否则以退出码 1 报出待补条目。
    """
    from .question_bank import SEED_PATH

    args = list(sys.argv[1:] if argv is None else argv)
    raw = json.loads(Path(SEED_PATH).read_text(encoding="utf-8"))
    _, hits = backfill_seed(raw)
    pending = sum(hits.values())
    if "--check" in args:
        if pending:
            print(f"未回填条目：{pending} 条 → {hits}")
            return 1
        print("回填完成：种子内所有条目都有 language")
        return 0
    print(f"本次判定 {pending} 条：{hits}")
    return 0


if __name__ == "__main__":  # pragma: no cover - 手工诊断入口
    raise SystemExit(main())
