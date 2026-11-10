"""题库素材合并工具（r12 · TECH-CHANGE §3）：离线、确定、运行时不调用的单一入口。

`python -X utf8 -m app.services.assessment.question_merge --check | --write | --rollback`

四件事，全部在离线阶段做完，运行时零改动（`question_bank.ensure_seeded()` 仍负责入库）：

1. **归一化**：`docs/question-bank-staging/` 的各份素材 → 种子行。越界只走「映射纠正」或
   「整条丢弃并记账」，不做静默改；方向归一只经 `rules.direction_of_language()` 派生
   （`dir = direction_of_language(language) or 原 direction`），本文件**不复述**方向表。
2. **去重**：题干归一化（NFKC → 去空白 → 去非文字符号，与 r11 测试侧口径逐字一致）后与存量
   260 行 + 本批已保留集做字面查重；再用字符 2-gram Jaccard ≥ `NEAR_DUP_JACCARD` 查近重复。
   存量行恒保留（只增不删），批内冲突按 `SOURCE_PRIORITY` → 解析更长 → 题干 sha1 小者取舍。
3. **落盘**：`dumps()` 是本轮唯一的格式知识（`--write` 与 `--check` 共用同一份），逐字节复现
   已提交 seed 的紧凑形态；`--check` 拿重算结果与磁盘字节比对，0 差异即幂等。
4. **回滚**：只经 `repository.delete_questions_by_source()`（唯一 SQL 出口），对未导入的库删 0 行；
   库不存在 / 尚未初始化时给中文原因 + 非 0 退出码，而不是 `no such table` 裸栈。

三条硬约束（都有门禁钉住，改这里前先读测试）：
- 校验不复制 `question_bank._usable()`：`write()` 落盘后用 `question_bank.load_seed()` 复核；
- 方向 / 语言归属只引用 `rules`，本文件不出现第二份语言闭集；
- 本文件**不得出现任何 SQL 关键字**（连注释也不行）——`test_sql_only_through_repository`
  会做文本扫描，回滚必须走 repository。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.core import repository
from app.services.assessment import question_bank, question_shuffle
from app.services.report import rules

#: 本批来源闭集（顺序即报表与批次落盘顺序）。
SOURCES: tuple[str, ...] = (
    "tiji",
    "local100",
    "iq380",
    "fe-interview",
    "ai-eng",
    "mw",
    "sql",
    "algo",
    "devprac",
    "ai-adv",
    "ai-sys",
    "acp-eng",
)

#: 来源 → 素材文件名（`docs/question-bank-staging/` 下的可复现输入，必须随仓库提交）。
STAGING_FILES: dict[str, str] = {
    "tiji": "01-题集20.json",
    "local100": "02-本地100题.json",
    "iq380": "03-七方向379题.json",
    "fe-interview": "04-fe-interview20.json",
    "ai-eng": "05-ai-engineering78.json",
    "mw": "06-middleware.json",
    "sql": "07-sql.json",
    "algo": "08-basic-algo.json",
    "devprac": "09-dev-practice.json",
    "ai-adv": "10-ai-engineering-advanced.json",
    "ai-sys": "11-ai-engineering-systems.json",
    "acp-eng": "12-acp-engineering.json",
}

#: 来源 → 种子 id 前缀（避开 legacy `fe-/be-/al-/cs-` 与 r11 九个语言前缀，保证
#: `test_question_bank_quality._is_new()` 的口径不被污染）。
#: `iq380-` 刻意不用 `iq-`：面试发言 id 也是 `iq-{序号}`（`interview.py` 写
#: `runs.payload.questions[].id`），同名不同域，数据不撞但 grep / 日志会混淆，故加宽前缀。
#: `aieng-` 为「AI 工程」方向题，独立前缀避免与面试发言 `iq-` 或既有语言前缀混淆。
#: `aiadv-` 是面向高级 AI 应用工程师的补题批次（10 号素材），独立于 `aieng-` 便于按批审计。
#: `aisys-` 是 11 号素材：多 Agent 编排 / RAG 评审 / 评测流水线工程，按批独立可审计。
#: `acpeng-` 是 12 号素材：面向阿里云大模型 ACP 知识覆盖的原创应用工程练习题，非官方真题。
ID_PREFIX: dict[str, str] = {
    "tiji": "tiji-",
    "local100": "l100-",
    "iq380": "iq380-",
    "fe-interview": "fei-",
    "ai-eng": "aieng-",
    "mw": "mw-",
    "sql": "sql-",
    "algo": "algo-",
    "devprac": "devprac-",
    "ai-adv": "aiadv-",
    "ai-sys": "aisys-",
    "acp-eng": "acpeng-",
}

#: 近重复口径：字符 n-gram 的 Jaccard 下界（常量只在这里，别处不得再写一个阈值）。
NGRAM = 2
NEAR_DUP_JACCARD = 0.62

#: 批内冲突取舍的来源优先级（高 → 低），与 `SOURCES` 顺序一致但**语义不同**：
#: 前者决定谁赢，后者决定写盘顺序。
SOURCE_PRIORITY: tuple[str, ...] = SOURCES

#: 判断题的固定选项（与存量 seed 的 36 道逐字一致：前端按 options 原样渲染，文案不可改）。
#: 素材里 4 条 key 是中文（`正确`/`错误`）、其余 116 条 key 已是 A/B —— 一律按本常量重建。
JUDGE_OPTIONS: tuple[dict[str, str], ...] = (
    {"key": "A", "text": "正确"},
    {"key": "B", "text": "错误"},
)

#: 素材编辑用语 → 面向考生的表述（r15 收口 r12 D-2 的「参考答案要点」遗留）。
#: 只做固定串整串替换、不做上下文推断：替换后不含原串即幂等（二次重算 0 差异）。
#: 题干用「要求」避免出现「参考」字样干扰作答；解析用「参考要点」保留原指代关系。
_TEXT_REWRITES: tuple[tuple[str, str, str], ...] = (
    ("prompt", "参考答案要点", "要求"),
    ("explanation", "参考答案要点", "参考要点"),
)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
#: 素材目录（可复现输入）。缺文件即「换机 / CI 上无法重建种子」，直接报错而不是静默空跑。
STAGING_DIR = _PROJECT_ROOT / "docs" / "question-bank-staging"
#: 题库唯一导入源：与 `question_bank.SEED_PATH` 同一路径，不另立副本。
SEED_PATH = question_bank.SEED_PATH
#: 导入报表（工具产物，非手写文档）：落本需求任务夹。
REPORT_PATH = (
    _PROJECT_ROOT
    / "docs"
    / "teamflow"
    / "20261102-r15-question-text-cleanup"
    / "QUESTION-BANK-MERGE-REPORT.md"
)

#: 种子条目的键序即文件格式（`dumps()` 按它输出，顺序变了就是全文件重写）。
_STRING_KEYS: tuple[str, ...] = (
    "id",
    "direction",
    "sub_direction",
    "kind",
    "difficulty",
    "essentiality",
    "language",
    "prompt",
)

#: 统计维度（报表的每一列都从这些计数来，避免手抄数字与数据漂移）。
_COUNTERS: tuple[str, ...] = (
    "read",
    "literal_dup",
    "near_dup",
    "out_of_range",
    "corrected",
    "derived",
    "added",
)

#: 判断题答案的各种写法 → 归一后的 key（越界值不猜，直接丢弃并记账）。
_JUDGE_TRUE = ("A", "正确", "对", "是", "true", "TRUE", "True")
_JUDGE_FALSE = ("B", "错误", "错", "否", "false", "FALSE", "False")

#: 答案字符串的分隔符（逗号 / 顿号 / 空白），多选形如 `A,B,D`。
_ANSWER_SPLIT = re.compile(r"[,，、\s]+")

#: 选项 key 的取值范围（与 `test_question_bank_quality` 同一口径）。
_OPTION_KEYS = tuple("ABCDEF")


# --- 归一化 -----------------------------------------------------------------
def normalize_prompt(text: str) -> str:
    """题干归一化：NFKC → 去空白 → 去非文字符号（与 r11 测试侧 `_normalize` 逐字一致）。

    两份实现跨侧（测试 / 工具）无法共享代码，但口径必须同源，
    `tests/test_r12_question_merge.py::test_normalize_prompt_matches_r11_normalization`
    反向钉住。**不要**改用 difflib/SequenceMatcher 形成第三套口径。
    """
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"\s+", "", text)
    return re.sub(r"[\W_]+", "", text)


def _bigrams(text: str) -> frozenset[str]:
    return frozenset(text[index : index + NGRAM] for index in range(len(text) - NGRAM + 1))


def ngram_jaccard(left: str, right: str, n: int = NGRAM) -> float:
    """两段文本的字符 n-gram Jaccard 相似度（先各自归一化，故对称且落在 [0, 1]）。

    近重复判定的唯一比较口径：空串与任何文本相似度为 0（不是 1），
    避免「两道空题干」被判成重复而互相掩盖数据错误。
    """
    first = normalize_prompt(left)
    second = normalize_prompt(right)
    if not first or not second:
        return 0.0
    left_grams = {first[index : index + n] for index in range(len(first) - n + 1)}
    right_grams = {second[index : index + n] for index in range(len(second) - n + 1)}
    union = left_grams | right_grams
    if not union:
        return 0.0
    return len(left_grams & right_grams) / len(union)


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    return 0.0 if not union else len(left & right) / len(union)


def _option_rows(raw_options: Any) -> list[dict[str, str]] | None:
    """素材选项 → 种子选项（key 大写、文本去首尾空白）；越界返回 None（整条丢弃）。"""
    if not isinstance(raw_options, list):
        return None
    options: list[dict[str, str]] = []
    for raw in raw_options:
        if not isinstance(raw, dict):
            return None
        key = str(raw.get("key") or "").strip().upper()
        text = str(raw.get("text") or "").strip()
        if key not in _OPTION_KEYS or not text:
            return None
        options.append({"key": key, "text": text})
    if not 2 <= len(options) <= 6:
        return None
    if len({option["key"] for option in options}) != len(options):
        return None
    return options


def _judge_answer(raw_answer: Any) -> list[str]:
    """判断题答案 → 指向 `JUDGE_OPTIONS` 的单个 key（`正确` → A、`错误` → B）。"""
    value = str(raw_answer or "").strip()
    if value in _JUDGE_TRUE:
        return ["A"]
    if value in _JUDGE_FALSE:
        return ["B"]
    return []


def _split_answer(raw_answer: Any) -> list[str]:
    """非判断题答案 → key 列表（素材是 `A` / `A,B,D` 这类字符串）。"""
    if isinstance(raw_answer, list):
        return [str(item).strip().upper() for item in raw_answer if str(item).strip()]
    parts = [part.strip().upper() for part in _ANSWER_SPLIT.split(str(raw_answer or ""))]
    return [part for part in parts if part]


def normalize_record(raw: dict[str, Any], source: str, index: int) -> dict[str, Any] | None:
    """素材条目 → 种子行（键序与 seed 一致）；越界 / 不可归一的条目返回 `None`。

    `None` 只表示「这一条不合格」，由调用方计入 `out_of_range` 并在报表里点名，
    **不**在这里静默改成「看起来能用」的样子。`index` 是源内原序（1 起），
    与 `ID_PREFIX[source]` 一起构成确定性 id（`%03d` 保证同源内字典序 == 原序）。
    """
    kind = str(raw.get("kind") or "").strip()
    if kind not in rules.OBJECTIVE_KINDS:  # 本批素材全是客观题，text 一律不合法
        return None

    prompt = str(raw.get("stem") or "").strip()
    explanation = str(raw.get("explanation") or "").strip()
    if not prompt or not explanation:
        return None

    difficulty = str(raw.get("difficulty") or "").strip()
    if difficulty not in rules.DIFFICULTIES:
        return None

    if kind == "judge":
        options = [dict(option) for option in JUDGE_OPTIONS]
        answer = _judge_answer(raw.get("answer"))
    else:
        options = _option_rows(raw.get("options"))
        answer = _split_answer(raw.get("answer"))
    if not options or not answer:
        return None
    keys = {option["key"] for option in options}
    if not set(answer) <= keys:
        return None
    if kind == "single" and len(answer) != 1:
        return None
    if kind == "multiple" and len(answer) < 2:
        return None

    language = str(raw.get("language") or "").strip()
    if language not in rules.LANGUAGES:
        return None
    direction = rules.direction_of_language(language) or str(raw.get("direction") or "").strip()
    if direction not in rules.DIRECTIONS:
        return None

    row: dict[str, Any] = {
        "id": f"{ID_PREFIX[source]}{index:03d}",
        "direction": direction,
        "kind": kind,
        "difficulty": difficulty,
        "essentiality": rules.essentiality_of(raw),
        "language": language,
        "prompt": prompt,
        "options": options,
        "answer": answer,
        "explanation": explanation,
        "source": source,
    }
    # 10 号素材起支持显式 sub_direction：合法值直接随行落盘，非法值不猜、交给
    # `_carry_sub_directions()` 兜底。没带该字段的老素材不新增键，保持 r12 的键序断言。
    declared = str(raw.get("sub_direction") or "").strip()
    if declared and rules.is_valid_sub_direction(direction, declared):
        row["sub_direction"] = declared
    return row


def load_staging(staging_dir: Path = STAGING_DIR) -> list[dict[str, Any]]:
    """按 `SOURCES` 顺序读四份素材，逐条附上 `source` 与源内原序 `_index`（1 起）。"""
    records: list[dict[str, Any]] = []
    for source in SOURCES:
        path = Path(staging_dir) / STAGING_FILES[source]
        if not path.is_file():
            raise FileNotFoundError(f"题库素材缺失：{path}（staging 必须随仓库提交，否则换机无法重建）")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError(f"题库素材顶层必须是列表：{path}")
        for index, item in enumerate(raw, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"题库素材条目必须是对象：{path} 第 {index} 条")
            record = dict(item)
            record["source"] = source
            record["_index"] = index
            records.append(record)
    return records


# --- 去重与合并 -------------------------------------------------------------
def _source_rank(source: str) -> int:
    return SOURCE_PRIORITY.index(source) if source in SOURCE_PRIORITY else len(SOURCE_PRIORITY)


def _explanation_length(row: dict[str, Any]) -> int:
    return len(re.sub(r"\s+", "", str(row.get("explanation") or "")))


def _rank(row: dict[str, Any]) -> tuple[int, int, str]:
    """批内冲突的取舍序：来源优先级 → 解析更长 → 题干 sha1 小者（确定性，无随机）。"""
    prompt = normalize_prompt(str(row.get("prompt") or ""))
    return (
        _source_rank(str(row.get("source") or "")),
        -_explanation_length(row),
        hashlib.sha1(prompt.encode("utf-8")).hexdigest(),
    )


def _blank_counters() -> dict[str, int]:
    return {key: 0 for key in _COUNTERS}


def _blank_stats() -> dict[str, Any]:
    return {
        "sources": {source: _blank_counters() for source in SOURCES},
        "duplicates": [],
        "corrections": [],
        "drops": [],
        "derived": [],
        "normalizations": {},
    }


def _fold(target: dict[str, Any], part: dict[str, Any]) -> None:
    """把 `merge_rows()` 的一份增量并进总统计（计数相加、明细追加）。"""
    for source, counters in part.get("sources", {}).items():
        bucket = target["sources"].setdefault(source, _blank_counters())
        for key, value in counters.items():
            bucket[key] = bucket.get(key, 0) + value
    for key in ("duplicates", "corrections", "drops", "derived"):
        target[key].extend(part.get(key, []))
    for key, value in part.get("normalizations", {}).items():
        target["normalizations"][key] = target["normalizations"].get(key, 0) + value


def merge_rows(
    existing: list[dict[str, Any]], candidates: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """存量行 + 候选行 → 合并后的行列表与本次增量统计。

    口径（TECH-CHANGE §3.2）：存量行逐字保留（只增不删，顺序不变）；候选按 `_rank()` 取舍后
    再按「来源序 → 源内原序」追加，因此同一份素材无论读入顺序如何都得到同一串字节。
    """
    rows = [dict(row) for row in existing]
    seen = {normalize_prompt(str(row.get("prompt") or "")) for row in rows}
    pool = [_bigrams(normalize_prompt(str(row.get("prompt") or ""))) for row in rows]
    delta = _blank_stats()
    kept: list[dict[str, Any]] = []

    for candidate in sorted(candidates, key=_rank):
        source = str(candidate.get("source") or "")
        bucket = delta["sources"].setdefault(source, _blank_counters())
        prompt = normalize_prompt(str(candidate.get("prompt") or ""))
        if prompt in seen:
            bucket["literal_dup"] += 1
            delta["duplicates"].append(
                {"id": candidate.get("id"), "source": source, "reason": "字面重复"}
            )
            continue
        grams = _bigrams(prompt)
        if any(_jaccard(grams, other) >= NEAR_DUP_JACCARD for other in pool):
            bucket["near_dup"] += 1
            delta["duplicates"].append(
                {"id": candidate.get("id"), "source": source, "reason": "近重复"}
            )
            continue
        seen.add(prompt)
        pool.append(grams)
        kept.append(dict(candidate))
        bucket["added"] += 1

    kept.sort(key=lambda row: (_source_rank(str(row.get("source") or "")), str(row.get("id"))))
    return rows + kept, delta


# --- 正文清理 ---------------------------------------------------------------
def sanitize_text(row: dict[str, Any]) -> dict[str, Any]:
    """把素材编辑用语替换成面向考生的表述（r15：只动 `_TEXT_REWRITES` 列出的字段）。

    返回**新字典**、不就地修改入参：`build_seed()` 的存量行是磁盘读回的对象，
    就地改会让「重算结果 vs 已提交 seed」的逐字节比对失去意义。替换后不含原串即幂等。
    """
    cleaned = dict(row)
    for field, old, new in _TEXT_REWRITES:
        value = str(cleaned.get(field) or "")
        if old in value:
            cleaned[field] = value.replace(old, new)
    return cleaned


# --- 组装 -------------------------------------------------------------------
def build_seed(
    staging_dir: Path = STAGING_DIR, seed_path: Path = SEED_PATH
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """素材 → (合并后的行, 统计)。

    存量行（**不带 `source` 键**的那批，r11 的 260 行）**原样读回**（不经 `_usable()` 过滤），
    保证逐字节不变；上一轮已导入的行（带 `source`）不当作存量：它们由素材确定性重算得到，
    因此重复 `--write` / 重复 `--check` 都落到同一串字节，报表也不会退化成「新增 0」。
    """
    raw = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"种子顶层必须是列表：{seed_path}")
    existing = [dict(row) for row in raw if not str(row.get("source") or "")]
    reimported = len(raw) - len(existing)

    stats = _blank_stats()
    candidates: list[dict[str, Any]] = []
    for record in load_staging(staging_dir):
        source = str(record["source"])
        index = int(record["_index"])
        bucket = stats["sources"].setdefault(source, _blank_counters())
        bucket["read"] += 1
        row = normalize_record(record, source, index)
        if row is None:
            bucket["out_of_range"] += 1
            stats["drops"].append({"source": source, "index": index})
            continue
        raw_direction = str(record.get("direction") or "").strip()
        if not raw_direction:
            # 素材缺 direction（04-fe-interview20.json）：按语言推断，不是「冲突纠正」。
            bucket["derived"] += 1
            stats["derived"].append(
                {
                    "id": row["id"],
                    "source": source,
                    "to": row["direction"],
                    "language": row["language"],
                }
            )
        elif row["direction"] != raw_direction:
            bucket["corrected"] += 1
            stats["corrections"].append(
                {
                    "id": row["id"],
                    "source": source,
                    "from": raw_direction,
                    "to": row["direction"],
                    "language": row["language"],
                }
            )
        stats["normalizations"]["judge_options_rebuilt"] = stats["normalizations"].get(
            "judge_options_rebuilt", 0
        ) + (1 if row["kind"] == "judge" else 0)
        stats["normalizations"]["answer_split"] = stats["normalizations"].get("answer_split", 0) + (
            0 if row["kind"] == "judge" else 1
        )
        candidates.append(row)

    merged, delta = merge_rows(existing, candidates)
    # 二级方向是「人工/脚本标注」的存量信息，素材里没有：按 id 沿用既有 seed 的标注，
    # 缺省或越出其方向闭集时落到该方向的通用兜底（闭集口径只有 rules.SUBDIRECTIONS 一份）。
    _carry_sub_directions(merged, raw)
    _fold(stats, delta)
    stats["total"] = _totals(stats)
    stats["existing"] = len(existing)
    stats["reimported"] = reimported
    # 先清正文再打乱：两步互不依赖，固定顺序只是为了让「改了什么」可读。
    merged = [sanitize_text(row) for row in merged]
    # 只在这条唯一重算路径上打乱：`--check` 与 `--write` 共用它，
    # 否则「重算 == 磁盘字节」不成立（拿未打乱的流水线比已打乱的 seed，恒红）。
    merged, shuffle_metrics = question_shuffle.apply(merged)
    stats["shuffle"] = shuffle_metrics
    return merged, stats


def _carry_sub_directions(rows: list[dict[str, Any]], raw: Sequence[dict[str, Any]]) -> None:
    """素材显式声明优先，其次按 id 沿用既有 seed 标注，最后落到方向通用兜底（原地写入）。

    10 号素材自带 `sub_direction`，不能让「按 id 继承」把新题一律覆盖成通用 AI；
    存量行与老素材仍走原来的继承口径，逐字节结果不变。
    """
    tagged = {str(row.get("id") or ""): row.get("sub_direction") for row in raw}
    for row in rows:
        direction = str(row.get("direction") or "")
        declared = row.get("sub_direction")
        if declared is not None and rules.is_valid_sub_direction(direction, declared):
            continue
        inherited = tagged.get(str(row.get("id") or ""))
        row["sub_direction"] = (
            inherited
            if rules.is_valid_sub_direction(direction, inherited) and inherited is not None
            else rules.generic_sub_direction_of(direction)
        )


def _totals(stats: dict[str, Any]) -> dict[str, int]:
    total = _blank_counters()
    for counters in stats["sources"].values():
        for key, value in counters.items():
            total[key] = total.get(key, 0) + value
    return total


# --- 序列化（本轮唯一的格式知识）-------------------------------------------
def _quote(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _entry_lines(row: dict[str, Any]) -> list[str]:
    """单条种子行 → 文本行（内部逗号已就位，末行不带逗号）。"""
    lines = [f'    "{key}": {_quote(row.get(key) or "")},' for key in _STRING_KEYS]

    options = list(row.get("options") or [])
    if options:
        lines.append('    "options": [')
        rendered = [
            f'      {{ "key": {_quote(option.get("key"))}, "text": {_quote(option.get("text"))} }}'
            for option in options
        ]
        lines.extend(f"{item}," for item in rendered[:-1])
        lines.append(rendered[-1])
        lines.append("    ],")
    else:
        lines.append('    "options": [],')

    answer = ", ".join(_quote(item) for item in list(row.get("answer") or []))
    lines.append(f'    "answer": [{answer}],')

    source = str(row.get("source") or "")
    explanation = f'    "explanation": {_quote(row.get("explanation") or "")}'
    lines.append(explanation + ("," if source else ""))
    if source:
        lines.append(f'    "source": {_quote(source)}')
    return lines


def dumps(rows: Sequence[dict[str, Any]]) -> str:
    """种子文件的规范序列化：同一批数据 → 同一串字节（`--write` 与 `--check` 共用这一份）。

    实测它能逐字节复现已提交的 260 行 seed（192393 字节、0 差异）；反例是
    `json.dump(indent=2)`（216281 字节）—— 那等于把整个文件重写一遍，真实 +519 行的改动
    会被格式噪声淹没，`--check` 也永远不可能 0 差异。
    """
    entries = ["  {\n" + "\n".join(_entry_lines(row)) + "\n  }" for row in rows]
    return "[\n" + ",\n".join(entries) + "\n]\n"


def check(seed_path: Path = SEED_PATH, staging_dir: Path = STAGING_DIR) -> bool:
    """从素材重算并与磁盘 seed **逐字节**比对：True = 幂等（0 差异）。"""
    rows, _stats = build_seed(staging_dir, seed_path)
    return dumps(rows).encode("utf-8") == Path(seed_path).read_bytes()


# --- 报表 -------------------------------------------------------------------
def _distribution(rows: Sequence[dict[str, Any]], key: str) -> str:
    counts = Counter(str(row.get(key) or "") for row in rows)
    return " / ".join(f"{name or '(空)'} {counts[name]}" for name in sorted(counts))


def generic_direction_with_language(rows: Sequence[dict[str, Any]]) -> int:
    """通用方向（算法与数据结构 / 计算机基础）上仍标了语言的行数 —— 合并后必须恒为 0。

    「哪些方向是通用方向」由 `rules.LANGUAGE_DIRECTION` 反推（有语言的方向 = 语言方向），
    本文件不写第二份方向表。
    """
    language_directions = set(rules.LANGUAGE_DIRECTION.values())
    generic_directions = [name for name in rules.DIRECTIONS if name not in language_directions]
    return sum(
        1
        for row in rows
        if str(row.get("direction") or "") in generic_directions
        and str(row.get("language") or "")
    )


def _source_rows(rows: Sequence[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    return sorted(
        (row for row in rows if str(row.get("source") or "") == source),
        key=lambda row: str(row.get("id")),
    )


def _spot_checks(rows: Sequence[dict[str, Any]]) -> list[str]:
    """每来源 3 道人工抽检（首 / 中 / 尾）：固定选点，不随机，便于 QA 复现。"""
    lines: list[str] = []
    for source in SOURCES:
        picks = _source_rows(rows, source)
        if not picks:
            lines.append(f"- `{source}`：本批无新增行")
            continue
        chosen = [picks[0], picks[len(picks) // 2], picks[-1]]
        for row in chosen:
            answer = ",".join(str(item) for item in row.get("answer") or [])
            prompt = str(row.get("prompt") or "").replace("\n", " ")[:46]
            lines.append(
                f"- `{row['id']}` [{row['kind']}/{row['language'] or '通用'}/"
                f"{row['difficulty']}] 答案 `{answer}`：{prompt}…"
            )
    return lines


def render_report(rows: Sequence[dict[str, Any]], stats: dict[str, Any]) -> str:
    """导入报表正文（工具产物：每个数字都来自本次合并，手抄必然与数据漂移）。"""
    total = stats.get("total") or _totals(stats)
    new_rows = [row for row in rows if str(row.get("source") or "")]
    plain = [row for row in rows if not str(row.get("source") or "")]

    explanations = [_explanation_length(row) for row in rows]
    short = [row["id"] for row in rows if _explanation_length(row) < 10]
    objective = [row for row in rows if str(row.get("kind") or "") in rules.OBJECTIVE_KINDS]
    option_ok = 0
    for row in objective:
        options = list(row.get("options") or [])
        keys = [str(option.get("key")) for option in options]
        answer = {str(item) for item in row.get("answer") or []}
        if 2 <= len(options) <= 6 and len(set(keys)) == len(keys) and answer <= set(keys):
            option_ok += 1
    generic = sum(1 for row in rows if not str(row.get("language") or ""))
    sources = Counter(str(row.get("source") or "seed") for row in rows)

    lines = [
        "# 题库合并导入报表（r15 · 工具生成，勿手改）",
        "",
        "命令：`cd backend && python -X utf8 -m app.services.assessment.question_merge --write`",
        "（重算 → 写 `backend/app/seed/questions.json` → 本报表；`--check` 用它做逐字节幂等比对）",
        "",
        "## 1 总量",
        "",
        f"- 合并前存量：{len(plain)} 条（无 `source` 键，运行时缺省 `seed`，逐字节不变）",
        f"- 本批新增：{len(new_rows)} 条",
        f"- 合并后总量：{len(rows)} 条",
        f"- 读入素材：{total.get('read', 0)} 条 → 越界丢弃 {total.get('out_of_range', 0)} 条、"
        f"字面重复 {total.get('literal_dup', 0)} 条、近重复 {total.get('near_dup', 0)} 条",
        "",
        "## 2 每来源计数",
        "",
        "| 来源 | 读入 | 字面重复 | 近重复 | 越界 | 纠正 | 方向推断 | 新增 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for source in SOURCES:
        bucket = stats["sources"].get(source, _blank_counters())
        lines.append(
            f"| `{source}` | {bucket['read']} | {bucket['literal_dup']} | {bucket['near_dup']} | "
            f"{bucket['out_of_range']} | {bucket['corrected']} | {bucket['derived']} | "
            f"{bucket['added']} |"
        )
    lines.extend(
        [
            "",
            "口径：`纠正` = 素材声明的方向与 language 归属冲突、以 language 为准被纠正的条数"
            "（不丢题）；`方向推断` = 素材缺 `direction`、由 `rules.direction_of_language()`"
            " 推断出来的条数（`04-fe-interview20.json` 全缺）。两者都不改语言、不丢题。",
            f"归一化动作：判断题选项重建 {stats['normalizations'].get('judge_options_rebuilt', 0)} 条、"
            f"答案字符串切分为列表 {stats['normalizations'].get('answer_split', 0)} 条。",
            "",
            "## 3 分布",
            "",
            f"- 总数：{len(rows)}",
            f"- 来源：{' / '.join(f'{name} {sources[name]}' for name in sorted(sources))}",
            f"- 题型：{_distribution(rows, 'kind')}",
            f"- 语言：{_distribution(rows, 'language')}",
            f"- 方向：{_distribution(rows, 'direction')}",
            f"- 难度：{_distribution(rows, 'difficulty')}",
            f"- 必备度：{_distribution(rows, 'essentiality')}",
            "",
            "## 4 质量口径",
            "",
            f"- 解析长度：最短 {min(explanations)} 字符 / 平均 "
            f"{sum(explanations) / len(explanations):.1f} 字符；不足 10 字符 {len(short)} 条"
            + (f"：{short}" if short else ""),
            f"- 客观题选项合规率：{option_ok}/{len(objective)}"
            f"（{option_ok / len(objective):.1%}，口径 = 选项 2–6 个、key 唯一、答案 ⊆ 选项）",
            f"- `language` 空白（通用 / 算法题）占比：{generic}/{len(rows)} = {generic / len(rows):.1%}",
            "- 通用方向（算法与数据结构 / 计算机基础）带语言的行数："
            f"{generic_direction_with_language(rows)}",
            "",
            "## 5 方向纠正与推断",
            "",
        ]
    )
    corrections = stats.get("corrections") or []
    derived = stats.get("derived") or []
    if derived:
        by_direction = Counter(str(item["to"]) for item in derived)
        detail = " / ".join(f"{name} {count}" for name, count in sorted(by_direction.items()))
        lines.append(
            f"- 素材缺 `direction`、按 language 推断：{len(derived)} 条"
            f"（{derived[0]['id']} … {derived[-1]['id']}；{detail}）"
        )
    else:
        lines.append("- 素材均自带 `direction`，无需推断")
    lines.append("")
    lines.append(f"方向冲突纠正：{len(corrections)} 条" + ("" if corrections else "（无）"))
    if corrections:
        for item in corrections:
            lines.append(
                f"- `{item['id']}`（{item['source']}，language={item['language'] or '通用'}）："
                f"{item['from']} → {item['to']}"
            )
    else:
        lines.append("- 无（素材方向与语言归属完全一致）")
    if stats.get("drops"):
        drops = "、".join(f"{item['source']}#{item['index']}" for item in stats["drops"])
        lines.append("")
        lines.append(f"丢弃清单：{drops}")
    if stats.get("duplicates"):
        lines.append("")
        lines.append(
            "去重清单："
            + "、".join(f"{item['id']}（{item['reason']}）" for item in stats["duplicates"])
        )

    lines.extend(["", "## 6 人工抽检（每来源 3 道，首 / 中 / 尾）", ""])
    lines.extend(_spot_checks(rows))
    lines.extend(
        [
            "",
            "## 7 断言改造清单",
            "",
            "- r11 的题库质量断言在 r12 **0 处需要改基数**：题量类断言已收敛为前缀子集"
            "（`fe-/be-/al-/cs-` 存量 + 九个 r11 语言前缀）或按 `len(_seed_rows())` 动态推导，"
            "本批新前缀（`tiji-` / `l100-` / `iq380-` / `fei-`）不在任何前缀集合里。",
            "- `test_question_bank_quality.py` 只**追加** r12 三条断言（source 枚举与计数、总量 779、"
            "通用方向恒空 language），r11 断言一字未改。",
            "- `test_engineering_gates.py` 追加 `R12_TOUCHED` + 三条门禁（改动面可解析、"
            "合并工具不被运行时导入、`source` 不进 HTTP 契约）。",
            "",
            "## 8 回滚",
            "",
            "代码回退后**必须**再跑数据回滚（数据只增不删，只回退代码不会清理已导入的 519 行）：",
            "",
            "```bash",
            "cd backend && python -X utf8 -m app.services.assessment.question_merge --rollback",
            "# 只删 source ∈ tiji/local100/iq380/fe-interview 的行，存量 260 行（source='seed'）不受影响",
            "# 幂等：再跑一次删 0 行",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


# --- 落盘 / 回滚 ------------------------------------------------------------
def write(
    seed_path: Path = SEED_PATH,
    staging_dir: Path = STAGING_DIR,
    report_path: Path = REPORT_PATH,
    shuffle_report_path: Path = question_shuffle.REPORT_PATH,
) -> dict[str, Any]:
    """重算 → 写 seed（字节）→ 写两份报表 → 用 `question_bank.load_seed()` 复核可用条数。"""
    rows, stats = build_seed(staging_dir, seed_path)
    payload = dumps(rows)
    Path(seed_path).write_bytes(payload.encode("utf-8"))
    # 报表必须与「落盘后的重算」同源：`apply()` 的「重算前」分布取自磁盘存量行，
    # 首轮写入后存量行已变成打乱后的状态。若仍用首轮 stats，报表会与任何后续
    # `build_seed()`（含 `test_shuffle_report_matches_recomputed_metrics`）永久分叉。
    rows, stats = build_seed(staging_dir, seed_path)
    if dumps(rows) != payload:
        raise ValueError("二次重算与首次写盘不一致（`question_shuffle.apply()` 不幂等）")
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(render_report(rows, stats), encoding="utf-8", newline="\n")
    # 打乱报表与数据同源生成（指标来自 `build_seed` 里的同一次 `apply()`），不手抄数字。
    Path(shuffle_report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(shuffle_report_path).write_text(
        question_shuffle.render_report(stats.get("shuffle") or {}),
        encoding="utf-8",
        newline="\n",
    )

    usable = len(question_bank.load_seed(Path(seed_path)))
    if usable != len(rows):
        raise ValueError(f"种子写入后可用条数 {usable} 与合并结果 {len(rows)} 不一致（存在坏行）")
    return {
        "total": len(rows),
        "existing": int(stats.get("existing", 0)),
        "added": int((stats.get("total") or {}).get("added", 0)),
        "bytes": len(payload.encode("utf-8")),
        "usable": usable,
        "seed_path": str(seed_path),
        "report_path": str(report_path),
        "shuffle_report_path": str(shuffle_report_path),
        "stats": stats,
    }


class RollbackUnavailable(RuntimeError):
    """库不存在 / 尚未初始化：回滚无从下手，CLI 只打中文原因（不打栈、不建空库）。"""


def rollback(sources: tuple[str, ...] = SOURCES) -> int:
    """按来源删除本批题库行，返回删除条数（未导入的库删 0 行；再跑一次恒 0）。

    `sqlite3.connect()` 会顺手创建 0 字节库文件，所以库未初始化时由
    `repository.delete_questions_by_source()` 先拦住（`DatabaseNotInitialized`），
    这里再翻成中文原因，CLI 给非 0 退出码而不是 `no such table` 裸栈。
    """
    try:
        return repository.delete_questions_by_source(sources)
    except repository.DatabaseNotInitialized as exc:
        raise RollbackUnavailable(f"{exc}，请先启动一次后端再回滚") from None
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            raise RollbackUnavailable("库还没有题库表（尚未初始化），请先启动一次后端再回滚") from None
        raise



# --- CLI --------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    """离线唯一入口：`--check` / `--write` / `--rollback`（其它参数打印用法并返回 2）。"""
    args = list(sys.argv[1:] if argv is None else argv)
    if "--check" in args:
        if check():
            usable = len(question_bank.load_seed())
            print(f"题库 seed 与素材重算逐字节一致：可用 {usable} 道（幂等成立）")
            return 0
        print("题库 seed 与素材重算不一致：请重跑 --write 后提交 seed（报表一并更新）")
        return 1
    if "--write" in args:
        result = write()
        total = result["stats"].get("total") or {}
        print(
            f"已写入 {result['total']} 条（存量 {result['existing']} + 新增 {result['added']}，"
            f"{result['bytes']} 字节）；越界丢弃 {total.get('out_of_range', 0)}、"
            f"字面重复 {total.get('literal_dup', 0)}、近重复 {total.get('near_dup', 0)}、"
            f"方向纠正 {total.get('corrected', 0)}、方向推断 {total.get('derived', 0)}"
        )
        print(f"报表：{result['report_path']}")
        print(f"打乱报表：{result['shuffle_report_path']}")
        return 0
    if "--rollback" in args:
        try:
            removed = rollback()
        except RollbackUnavailable as exc:
            print(f"无法回滚：{exc}")
            return 1
        print(f"已按来源删除 {removed} 行（存量 260 行不受影响；再跑一次恒 0）")
        return 0
    print("用法：python -X utf8 -m app.services.assessment.question_merge --check | --write | --rollback")
    return 2


if __name__ == "__main__":  # pragma: no cover - 手工离线入口
    raise SystemExit(main())
