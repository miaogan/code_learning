#!/usr/bin/env python3
"""修改率统计：提示词版 / 微调版初稿 vs 人工定稿（r150 / M1）。

为什么单列一个脚本：VERSION-PLAN §5.8 的决策门靠**人工修改率**，
而它既不能由模型自评，也不能用「过闸率」替代——只能把初稿与人工改后的稿子逐字比对。

用法：
    # 1) 人工把 drafts_out.jsonl 里的初稿改好，另存为 edited.jsonl（同 schema）
    # 2) 计算修改率
    python scripts/finetune/score_edits.py --draft out/drafts_out.jsonl --edited out/edited.jsonl

判定（§5.8）：
    修改率 ≤20%            → 提示词版够用，微调是过度工程
    20% < 修改率 < 35%     → 灰区：看问题是否集中在 top3 类型（人工标注，脚本不猜）
    修改率 ≥35%            → 微调划算（前提：问题系统性，占修改量 60% 以上）

修改率口径：字符级 1 − SequenceMatcher.ratio()，按节计算后**按字数加权**汇总；
空行、纯空白不计入。
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path


def load(path: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        key = f"{record['chapter']}/{record['section']}"
        rows[key] = str(record.get('response') or '')
    return rows


def normalize(text: str) -> str:
    return ''.join(text.split())


def main() -> int:
    parser = argparse.ArgumentParser(description='统计人工修改率')
    parser.add_argument('--draft', required=True, help='初稿 jsonl（drafts_out.jsonl）')
    parser.add_argument('--edited', required=True, help='人工定稿 jsonl（同 schema）')
    parser.add_argument('--limit', type=int, default=0, help='只打印前 N 节明细')
    args = parser.parse_args()

    draft = load(Path(args.draft))
    edited = load(Path(args.edited))
    common = [key for key in draft if key in edited]
    if not common:
        print('两份文件没有共同的 chapter/section，检查是否同一批小节。')
        return 2

    total_draft_chars = 0
    total_kept_chars = 0
    rows: list[tuple[str, float, int]] = []
    for key in common:
        before, after = normalize(draft[key]), normalize(edited[key])
        if not before:
            continue
        ratio = difflib.SequenceMatcher(None, before, after).ratio()
        edited_chars = 1 - ratio
        rows.append((key, edited_chars, len(before)))
        total_draft_chars += len(before)
        total_kept_chars += round(len(before) * ratio)

    weighted = 1 - total_kept_chars / total_draft_chars if total_draft_chars else 0.0
    missing = [key for key in draft if key not in edited]

    print(f'对比 {len(rows)} 节 · 被改字符 {total_draft_chars - total_kept_chars} / {total_draft_chars}')
    print(f'加权修改率：{weighted * 100:.1f}%')
    if missing:
        print(f'未提供定稿的小节：{len(missing)} 节（不参与计算）')

    if weighted >= 0.35:
        verdict = '微调划算（还需确认问题是否系统性：top3 问题占修改量 60% 以上）'
    elif weighted <= 0.20:
        verdict = '提示词版够用：微调属过度工程，继续打磨提示词与朗读词典'
    else:
        verdict = '灰区：先做问题分类统计，再决定是否微调'
    print(f'判定（§5.8）：{verdict}')

    shown = 0
    for key, rate, chars in sorted(rows, key=lambda row: -row[1]):
        if args.limit and shown >= args.limit:
            break
        shown += 1
        print(f'  {key:<40} 修改率 {rate * 100:5.1f}%（{chars} 字）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
