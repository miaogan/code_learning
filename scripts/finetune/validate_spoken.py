#!/usr/bin/env python3
"""口播稿 SFT 数据 / 模型输出的质量检查（r150 制作工具链）。

与前端 `frontend/src/lib/spoken.ts` 的规则同口径（同一个训练目标、同一个门禁）：
结构合法、情绪闭集、单口/对口说话人、小句长度、逗哏长段、捧哏纯附和比例、
punch 上限、每节至少一个「说白了」小结。**规则是双源**（TS 是产品门禁的真源，
本文件是离线训练侧的可运行镜像）——改规则两边必须一起改，报告里会打版本号。

用法：
    python scripts/finetune/validate_spoken.py                       # 校验导出的 SFT 数据（期望 100%）
    python scripts/finetune/validate_spoken.py out/model_eval.jsonl --strict
    python scripts/finetune/validate_spoken.py --limit 5             # 只打印前几条问题

数据形态：每行 JSON，可取 assistant 内容或 output/response 字段。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

CLAUSE_MAX_CHARS = 20
DOU_MAX_LINES = 5
PENG_FILLER_MAX_RATIO = 1 / 3
PUNCH_MAX = 6
RECAP_MARKER = '说白了'
EMOTIONS = {'banter', 'setup', 'deadpan', 'punch', 'realize', 'contrast', 'wrap'}
SPEAKERS = {'dou', 'peng', 'narrator'}
# 与 spoken.ts 的 PENG_QUESTION_WORDS 保持同一份（短句里出现疑问词算推进）。
PENG_QUESTION_WORDS = ('吗', '呢', '什么', '怎么', '哪', '为啥', '为什么', '谁', '多少', '几', '会不会', '能不能', '要不要')
SEPARATORS = '，。！？；：、…,.!?;:'


def target_text(record: dict) -> str | None:
    messages = record.get('messages')
    if isinstance(messages, list) and messages:
        last = messages[-1]
        if isinstance(last, dict) and last.get('role') == 'assistant':
            return str(last.get('content') or '')
    for key in ('output', 'response', 'answer'):
        if isinstance(record.get(key), str):
            return record[key]
    return None


def clauses(line: str) -> list[str]:
    parts = [line]
    for sep in SEPARATORS:
        parts = [piece for part in parts for piece in part.split(sep)]
    return [piece.strip() for piece in parts if piece.strip()]


def is_peng_promoting(text: str) -> bool:
    core = ''.join(ch for ch in text if ch not in SEPARATORS and not ch.isspace())
    if len(core) >= 4:
        return True
    return any(word in text for word in PENG_QUESTION_WORDS)


def validate(record: dict) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    text = target_text(record)
    if text is None:
        return [('missing_target', '样本里找不到 assistant 内容')]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return [('invalid_json', f'不是合法 JSON：{exc.msg}')]
    if not isinstance(payload, dict):
        return [('invalid_json', 'JSON 顶层不是对象')]

    form = payload.get('form')
    if form not in ('solo', 'duo'):
        issues.append(('invalid_form', f'form={form!r}，只能是 solo 或 duo'))
    segments = payload.get('segments')
    if not isinstance(segments, list) or not segments:
        return issues + [('empty_segments', 'segments 为空')]

    utterances: list[tuple[str, str, str]] = []  # (speaker, emotion, line)
    for seg_index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            issues.append(('invalid_segment', f'第 {seg_index + 1} 段不是对象'))
            continue
        speaker = segment.get('speaker')
        emotion = segment.get('emotion')
        lines = segment.get('lines')
        if speaker not in SPEAKERS:
            issues.append(('invalid_speaker', f'第 {seg_index + 1} 段 speaker={speaker!r}'))
        if emotion not in EMOTIONS:
            issues.append(('invalid_emotion', f'第 {seg_index + 1} 段 emotion={emotion!r}'))
        if not isinstance(lines, list) or not lines:
            issues.append(('empty_lines', f'第 {seg_index + 1} 段 lines 为空'))
            continue
        for line in lines:
            if not isinstance(line, str) or not line.strip():
                issues.append(('empty_line', f'第 {seg_index + 1} 段有空句'))
                continue
            utterances.append((speaker, emotion, line))

    if not utterances:
        return issues + [('empty_segments', '没有任何句子')]

    if form == 'solo':
        outsiders = [u for u in utterances if u[0] != 'narrator']
        if outsiders:
            issues.append(('speaker_solo', f'单口出现 {outsiders[0][0]} 发言'))
    elif form == 'duo':
        speakers = {u[0] for u in utterances}
        if not {'dou', 'peng'} <= speakers:
            issues.append(('duo_missing_peng', '对口缺少逗哏或捧哏'))
        peng = [u for u in utterances if u[0] == 'peng']
        filler = [u for u in peng if not is_peng_promoting(u[2])]
        if peng and len(filler) / len(peng) > PENG_FILLER_MAX_RATIO:
            issues.append(('peng_filler_ratio', f'捧哏 {len(filler)}/{len(peng)} 句是纯附和'))

    for _, _, line in utterances:
        for clause in clauses(line):
            if len(clause.replace(' ', '')) > CLAUSE_MAX_CHARS:
                issues.append(('clause_too_long', f'「{clause}」超过 {CLAUSE_MAX_CHARS} 字'))

    run = 0
    for speaker, _, line in utterances:
        if speaker != 'dou':
            run = 0
            continue
        run += 1
        if run > DOU_MAX_LINES:
            issues.append(('dou_turn_too_long', f'逗哏连说 {run} 句（「{line[:12]}…」）'))
            run = 0

    punch = sum(1 for _, emotion, _ in utterances if emotion == 'punch')
    if punch > PUNCH_MAX:
        issues.append(('punch_count', f'punch {punch} 次，超过 {PUNCH_MAX}'))
    if not any(RECAP_MARKER in line for _, _, line in utterances):
        issues.append(('recap_missing', f'没有「{RECAP_MARKER}」小结'))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description='校验口播稿 SFT 数据 / 模型输出')
    parser.add_argument('path', nargs='?', default='scripts/finetune/out/spoken_sft.jsonl')
    parser.add_argument('--strict', action='store_true', help='有任何问题即退出码 1')
    parser.add_argument('--limit', type=int, default=10, help='最多打印多少条问题样本')
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f'找不到文件：{path}（先跑 cd frontend && node ../scripts/export_spoken_sft.mjs）')
        return 2

    records = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    codes: Counter[str] = Counter()
    failed = 0
    shown = 0
    invalid_json = 0
    for index, record in enumerate(records, start=1):
        issues = validate(record)
        if any(code in ('invalid_json', 'missing_target') for code, _ in issues):
            invalid_json += 1
        if issues:
            failed += 1
            codes.update(code for code, _ in issues)
            if shown < args.limit:
                shown += 1
                print(f'[#{index}] ' + '；'.join(f'{code}：{msg}' for code, msg in issues[:4]))

    total = len(records)
    passed = total - failed
    rate = (passed / total * 100) if total else 0.0
    print()
    print(f'样本 {total} 条 · 通过 {passed} 条（{rate:.1f}%）· JSON 解析失败 {invalid_json} 条')
    if codes:
        print('问题分布：' + '，'.join(f'{code}×{count}' for code, count in codes.most_common()))
    print('规则口径：spoken.ts 镜像（小句≤20 字 / 逗哏≤5 句 / 捧哏纯附和≤1/3 / punch≤6 / 每节 1 个「说白了」）')
    print('注：每章 punch 2–6 的下限由前端门禁按章合并判定，本节级检查只看上限。')

    if args.strict and failed:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
