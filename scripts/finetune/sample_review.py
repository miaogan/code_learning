#!/usr/bin/env python3
"""从初稿里抽一份「人工改稿清单」（r150 / M1）。

为什么要抽样而不是全改：§5.8 的决策门只需要一个**有代表性的**人工修改率。
185 节全改要一两天，40 节按问题类型分层抽，1–2 小时就能给出判断。

分桶规则（按校验码）：
    clean        一次过闸的
    punch_count  包袱超 6
    clause       小句超 20 字
    dou          逗哏连说超 5 句
    other        其余（JSON 截断等）

默认每桶 10 节、合计 40 节；某桶不够时由其他桶补足。抽样是**确定性**的
（按 seed + chapter/section 的 sha256 排序），同一份数据每次抽出同一批，便于复算。

用法：
    python scripts/finetune/sample_review.py                     # 40 节，seed 150
    python scripts/finetune/sample_review.py --count 20 --seed 7

产物（scripts/finetune/out/）：
    review_sample.md     人看的清单（问题 + 原文骨架 + 初稿）
    review_sample.jsonl  人改的文件（只含 chapter/section/response，改完另存 edited.jsonl）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = ROOT / 'scripts' / 'finetune' / 'out'


def bucket_of(issues: list[str]) -> str:
    if not issues:
        return 'clean'
    for code in ('punch_count', 'clause_too_long', 'dou_turn_too_long'):
        if code in issues:
            return {'punch_count': 'punch', 'clause_too_long': 'clause', 'dou_turn_too_long': 'dou'}[code]
    return 'other'


def sort_key(seed: int, row: dict) -> str:
    return hashlib.sha256(f'{seed}/{row["chapter"]}/{row["section"]}'.encode('utf-8')).hexdigest()


def outline_of(row: dict) -> str:
    for message in row.get('messages', []):
        if message.get('role') == 'user':
            return message.get('content', '')
    return ''


def main() -> int:
    parser = argparse.ArgumentParser(description='抽人工改稿清单')
    parser.add_argument('--drafts', default=str(OUT / 'drafts_out.jsonl'))
    parser.add_argument('--count', type=int, default=40)
    parser.add_argument('--seed', type=int, default=150)
    parser.add_argument('--out-md', default=str(OUT / 'review_sample.md'))
    parser.add_argument('--out-jsonl', default=str(OUT / 'review_sample.jsonl'))
    args = parser.parse_args()

    path = Path(args.drafts)
    if not path.exists():
        print(f'找不到 {path}；先跑 draft_spoken.py --live')
        return 2
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not rows:
        print('初稿文件为空。')
        return 2

    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        buckets[bucket_of(row.get('issues') or [])].append(row)

    order = ['clean', 'punch', 'clause', 'dou', 'other']
    per_bucket = max(1, args.count // len(order))
    picked: list[tuple[str, dict]] = []
    for name in order:
        candidates = sorted(buckets.get(name, []), key=lambda row: sort_key(args.seed, row))
        picked += [(name, row) for row in candidates[:per_bucket]]
    # 不足 / 超出时用剩余候选补齐到 count
    used = {(name, row['chapter'], row['section']) for name, row in picked}
    if len(picked) < args.count:
        leftovers = [
            (bucket_of(row.get('issues') or []), row)
            for row in rows
            if (bucket_of(row.get('issues') or []), row['chapter'], row['section']) not in used
        ]
        leftovers.sort(key=lambda item: sort_key(args.seed, item[1]))
        picked += leftovers[: args.count - len(picked)]
    picked = picked[: args.count]

    counts = Counter(name for name, _ in picked)
    lines = [
        '# 人工改稿清单（§5.8 决策门用）',
        '',
        f'共 {len(picked)} 节 · 来源 `{path.name}` · seed {args.seed}',
        '',
        f'分桶：' + '，'.join(f'{name} {counts.get(name, 0)}' for name in order if counts.get(name)),
        '',
        '**怎么用**：把每节初稿改到「你自己愿意录成音频」的程度，'
        f'改完另存为 `{Path(args.out_jsonl).stem}-edited.jsonl`，再跑：',
        '',
        '```bash',
        f'python scripts/finetune/score_edits.py --draft {args.out_jsonl} --edited {Path(args.out_jsonl).stem}-edited.jsonl',
        '```',
        '',
    ]
    for name, row in picked:
        issues = row.get('issues') or []
        lines.append(f'## [{name}] {row["chapter"]} / {row["section"]}（{row.get("form")}）')
        lines.append('')
        if issues:
            lines.append(f'**校验问题**：{"、".join(issues)}')
        else:
            lines.append('**校验**：通过')
        lines.append('')
        lines.append('<details><summary>原文骨架</summary>')
        lines.append('')
        lines.append('```')
        lines.append(outline_of(row)[:4000])
        lines.append('```')
        lines.append('')
        lines.append('</details>')
        lines.append('')
        lines.append('```json')
        lines.append(str(row.get('response') or '').strip()[:8000])
        lines.append('```')
        lines.append('')

    Path(args.out_md).write_text('\n'.join(lines), encoding='utf-8')
    Path(args.out_jsonl).write_text(
        '\n'.join(
            json.dumps(
                {'chapter': row['chapter'], 'section': row['section'], 'response': row.get('response') or ''},
                ensure_ascii=False,
            )
            for _, row in picked
        )
        + '\n',
        encoding='utf-8',
    )
    print(f'抽出 {len(picked)} 节：' + '，'.join(f'{name} {counts.get(name, 0)}' for name in order if counts.get(name)))
    print(f'清单：{args.out_md}')
    print(f'待改：{args.out_jsonl}（改完另存 reviewed，再跑 score_edits.py）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
