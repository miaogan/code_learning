#!/usr/bin/env python3
"""提示词版 baseline：把可听章的小节起草成口播稿候选（r150 / M1）。

为什么先做这一步（VERSION-PLAN §5.8 的决策门）：
铺 40 章训练数据很贵，先用「强模型 + 同一套提示词」跑一版初稿，
测人工修改率 —— 若 <20% 或问题分散，微调就是过度工程；若 >35% 且问题是系统性的，
才把数据喂给 4B 做 QLoRA。**这一步不训练，只花钱调模型。**

用法：
    python scripts/finetune/draft_spoken.py --dry-run            # 只统计，不出网
    python scripts/finetune/draft_spoken.py --live --limit 5     # 真跑前 5 节
    python scripts/finetune/draft_spoken.py --live               # 全量（43 章 ≈ 170 节）

模型调用走 OpenAI 兼容接口；Key 默认从 backend/.env 读取（AI_BASE_URL / AI_MODEL / AI_API_KEY），
也可用同名环境变量覆盖。**Key 不会出现在输出与日志里。**

产物（scripts/finetune/out/）：
    drafts_out.jsonl     每行 {chapter, section, form, response, issues}
    drafts_review.md     人工审阅用：原文骨架 + 初稿 + 校验问题
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DRAFTS = ROOT / 'scripts' / 'finetune' / 'out' / 'spoken_drafts.jsonl'
OUT_DIR = ROOT / 'scripts' / 'finetune' / 'out'

sys.path.insert(0, str(HERE))
from validate_spoken import validate  # noqa: E402


def load_env() -> dict[str, str]:
    """读 backend/.env（KEY=VALUE，忽略注释与空行）；不打印任何值。"""
    env: dict[str, str] = {}
    path = ROOT / 'backend' / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def resolve_settings(env: dict[str, str]) -> tuple[str, str, str]:
    base = os.environ.get('AI_BASE_URL') or env.get('AI_DEEPSEEK_BASE_URL') or env.get('AI_BASE_URL') or ''
    model = os.environ.get('AI_MODEL') or env.get('AI_DEEPSEEK_MODEL') or env.get('AI_MODEL') or ''
    key = os.environ.get('AI_API_KEY') or env.get('AI_DEEPSEEK_API_KEY') or env.get('AI_API_KEY') or ''
    return base.rstrip('/'), model, key


def call_model(base: str, model: str, key: str, messages: list[dict], timeout: float = 180.0) -> str:
    """一次 chat/completions；先试 JSON 模式，400（提示词缺 json 字样）则退回普通模式。"""
    url = f'{base}/chat/completions'
    payload = {
        'model': model,
        'messages': messages,
        'temperature': 0,
        'max_tokens': 2000,
        'response_format': {'type': 'json_object'},
    }
    for attempt in range(2):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        request = urllib.request.Request(
            url, data=body, headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode('utf-8'))
            return data['choices'][0]['message'].get('content') or ''
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', errors='ignore')[:300]
            if exc.code == 400 and 'response_format' in payload and attempt == 0:
                payload.pop('response_format', None)
                continue
            raise SystemExit(f'模型返回 {exc.code}：{detail}') from exc
        except urllib.error.URLError as exc:
            raise SystemExit(f'连不上模型端点（{base}）：{exc.reason}') from exc
    return ''


def render_review(chapter: str, section: str, form: str, prompt: str, response: str, issues: list) -> str:
    lines = [f'## {chapter} / {section}（{form}）', '']
    if issues:
        lines.append('**校验问题**：' + '；'.join(f'{code}：{msg}' for code, msg in issues))
    else:
        lines.append('**校验**：通过')
    lines += ['', '<details><summary>原 prompt</summary>', '', '```', prompt[:6000], '```', '', '</details>', '']
    lines += ['```json', response.strip()[:8000], '```', '']
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description='提示词版 baseline 起草')
    parser.add_argument('--drafts', default=str(DRAFTS))
    parser.add_argument('--live', action='store_true', help='真调模型（默认 dry-run）')
    parser.add_argument('--dry-run', action='store_true', help='显式声明只统计、不出网（默认行为，便于脚本里写清楚）')
    parser.add_argument('--limit', type=int, default=0, help='只跑前 N 节（0 = 全部）')
    parser.add_argument('--out', default=str(OUT_DIR / 'drafts_out.jsonl'))
    parser.add_argument('--review', default=str(OUT_DIR / 'drafts_review.md'))
    args = parser.parse_args()

    drafts_path = Path(args.drafts)
    if not drafts_path.exists():
        print(f'找不到 {drafts_path}；先跑 cd frontend && node ../scripts/export_spoken_sft.mjs')
        return 2

    rows = [json.loads(line) for line in drafts_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if args.limit:
        rows = rows[: args.limit]
    chapters = len({row['chapter'] for row in rows})
    print(f'起草请求：{len(rows)} 节 / {chapters} 章')

    env = load_env()
    base, model, key = resolve_settings(env)
    if not args.live:
        print('dry-run：不出网。真实运行加 --live（模型端点从 backend/.env 读取）。')
        print(f'端点已配置：{"是" if base else "否"} · 模型已配置：{"是" if model else "否"} · Key 已配置：{"是" if key else "否"}')
        return 0
    if not (base and model and key):
        print('缺少 AI_BASE_URL / AI_MODEL / AI_API_KEY（backend/.env 或环境变量），无法真跑。')
        return 2

    out_lines: list[str] = []
    review: list[str] = [f'# 提示词版 baseline 初稿现审（{len(rows)} 节）', '', f'模型：{model}', '']
    codes: dict[str, int] = {}
    call_failed = 0
    invalid = 0
    started = time.time()
    for index, row in enumerate(rows, start=1):
        try:
            response = call_model(base, model, key, row['messages'])
        except SystemExit as exc:
            print(f'[#{index}] 调用失败：{exc}')
            call_failed += 1
            continue
        record = {
            'chapter': row['chapter'],
            'section': row['section'],
            'form': row['form'],
            'response': response,
        }
        issues = validate(record)
        if issues:
            invalid += 1
            for code, _ in issues:
                codes[code] = codes.get(code, 0) + 1
        out_lines.append(json.dumps({**record, 'issues': [code for code, _ in issues]}, ensure_ascii=False))
        review.append(render_review(row['chapter'], row['section'], row['form'], row['messages'][1]['content'], response, issues))
        print(f'[#{index}/{len(rows)}] {row["chapter"]}/{row["section"]} · {"通过" if not issues else "、".join(c for c, _ in issues)}')

    Path(args.out).write_text('\n'.join(out_lines) + '\n', encoding='utf-8')
    Path(args.review).write_text('\n'.join(review), encoding='utf-8')
    passed = len(out_lines) - invalid
    rate = passed / len(rows) * 100 if rows else 0
    print()
    print(f'完成 {len(out_lines)}/{len(rows)} 节，耗时 {time.time() - started:.0f}s')
    print(f'自动通过 {passed} 节（{rate:.1f}%）· 校验未过 {invalid} 节 · 调用失败 {call_failed} 节')
    if codes:
        print('问题分布：' + '，'.join(f'{code}×{count}' for code, count in sorted(codes.items(), key=lambda kv: -kv[1])))
    print(f'产物：{args.out} 与 {args.review}')
    print('下一步：按 drafts_review.md 人工改稿，再用 score_edits.py 算修改率（§5.8 决策门）。')
    return 0 if not (call_failed or invalid) else 1


if __name__ == '__main__':
    sys.exit(main())
