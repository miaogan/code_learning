#!/usr/bin/env python3
"""把写稿模型输出的口播稿转成 synthesize.py 能吃的 plans 格式。

背景（2026-11-23）：写稿模型（Qwen3-4B QLoRA v2）接入 r150 制作链路时，
`export_spoken_audio.mjs` 只从前端硬编码的黄金稿生成 plans，无法消费模型输出。
本脚本补上这一环：输入 swift infer 的结果 jsonl（每行含 response），
输出与 `buildAudioPlan()` 同构的 chapter plan JSON，交给 synthesize.py --backend voxcpm。

字段口径（与 spokenAudioExport.ts 对齐）：
    chapter: {chapterId, form, voice, sections[]}
    section: {sectionId, title, src, units[], estimateMs}
    unit:    {speaker, emotion, pauseBeforeMs, pauseAfterMs, lines[]}

停顿与 src 规则沿用现有 plans 的实测口径；改这里必须同步前端
（VERSION-PLAN 契约双改精神的离线版：输出只要 synthesize.py 认，不进运行时）。

用法：
    python scripts/finetune/build_spoken_plan.py \
        --result <llm-finetune-lab>/outputs/gen_bdc.jsonl \
        --chapter be-distributed-consistency \
        --out scripts/tts/out/plans_gen/be-distributed-consistency.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
from validate_spoken import validate  # noqa: E402

# 与 spokenAudioExport.ts / 现有 plans 同口径
PAUSE_BEFORE = {'banter': 0, 'setup': 200, 'deadpan': 350, 'contrast': 420, 'punch': 450, 'realize': 350, 'wrap': 400}
PAUSE_AFTER = {'banter': 160, 'setup': 260, 'deadpan': 400, 'contrast': 200, 'punch': 700, 'realize': 350, 'wrap': 800}
CHARS_PER_SEC = 5.5  # 口播语速估时（与前端 estimateMs 同量级）


def ms(text: str) -> int:
    return int(len(text) / CHARS_PER_SEC * 1000)


def load_result(path: Path) -> list[tuple[str, str]]:
    """从 swift infer 结果取 (sectionId, response)。sectionId 从 messages 的 user 里解析。"""
    rows: list[tuple[str, str]] = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        resp = str(rec.get('response') or '')
        # swift 结果带 messages（含 user prompt）与 response/labels
        msgs = rec.get('messages') or []
        section = None
        for m in msgs:
            if m.get('role') == 'user':
                for part in str(m.get('content') or '').splitlines():
                    if part.startswith('小节：'):
                        section = part.split('：', 1)[1].strip()
                        break
        rows.append((section or f'section-{len(rows) + 1}', resp))
    return rows


def load_id_map(plan_path: Path) -> list[str]:
    """从正式 plans 按 section 顺序取英文 ID，用于把 prompt 的「中文标题（N/4）」映射回稳定 ID。"""
    data = json.loads(plan_path.read_text(encoding='utf-8'))
    return [s['sectionId'] for s in data.get('sections', [])]


def to_plan(chapter_id: str, rows: list[tuple[str, str]], form: str, src_prefix: str = '/audio',
            id_map: list[str] | None = None) -> dict:
    sections = []
    for idx, (section_id, resp) in enumerate(rows, start=1):
        # 有正式 ID 映射时按序号取（prompt 里是「中文标题（N/4）」而非稳定 ID）
        if id_map and idx <= len(id_map):
            section_id = id_map[idx - 1]
        try:
            script = json.loads(resp) if isinstance(resp, str) else resp
        except json.JSONDecodeError:
            script = {}
        units = []
        for seg in script.get('segments') or []:
            speaker = str(seg.get('speaker') or ('narrator' if form == 'solo' else 'dou'))
            emotion = str(seg.get('emotion') or 'banter')
            lines = [str(x) for x in (seg.get('lines') or []) if str(x).strip()]
            if not lines:
                continue
            # v2 模型偶发把逗哏写成 6-8 句（规则上限 5）：制作期确定性切分，
            # 不重新生成、不改文本，只在超长段中间断开成多个 unit。
            # 这是已知的系统性偏差兜底（TTS-GAP-REVIEW §8），不是掩盖质量问题——
            # 门禁统计仍按原始 response 判，这里只保证合成单元可用。
            chunk_size = 5
            for start in range(0, len(lines), chunk_size):
                chunk = lines[start:start + chunk_size]
                units.append({
                    'speaker': speaker,
                    'emotion': emotion,
                    'pauseBeforeMs': PAUSE_BEFORE.get(emotion, 0),
                    'pauseAfterMs': PAUSE_AFTER.get(emotion, 160),
                    'lines': chunk,
                })
        total_ms = sum(
            ms(''.join(u['lines'])) + u['pauseBeforeMs'] + u['pauseAfterMs']
            for u in units
        )
        sections.append({
            'sectionId': section_id,
            'title': section_id,
            'src': f'{src_prefix}/{chapter_id}/{section_id}.wav',
            'units': units,
            'estimateMs': total_ms,
        })
    # voice.model 必须如实反映实际合成后端（VoxCPM2），不能照抄正式 plans 的 CosyVoice2——
    # manifest 由 synthesize.py 从 plan['voice'] 直接写出，写错会导致发布溯源说不清（SOP §3 必改点 1）
    voice = ({'model': 'VoxCPM2', 'emotionGain': 0.55, 'lead': 'dou-adult-male', 'support': 'peng-adult-male'}
             if form == 'duo' else
             {'model': 'VoxCPM2', 'emotionGain': 0.4, 'lead': 'solo-adult-male'})
    return {'chapterId': chapter_id, 'form': form, 'voice': voice, 'sections': sections}


def main() -> int:
    ap = argparse.ArgumentParser(description='写稿模型输出 → plans')
    ap.add_argument('--result', required=True, help='swift infer 结果 jsonl')
    ap.add_argument('--chapter', required=True, help='chapterId')
    ap.add_argument('--out', required=True, help='输出 plan JSON 路径')
    ap.add_argument('--form', default=None, choices=['solo', 'duo'], help='默认按输出里的 form')
    ap.add_argument('--src-prefix', default='audio', help='音频 src 前缀（不带前导斜杠），验证产物可填 verify')
    ap.add_argument('--id-map', default=None, help='正式 plans 路径：按序号取稳定 sectionId（如 concept/patterns）')
    ap.add_argument('--strict', action='store_true', help='先过 validate_spoken 门禁，未过不产出')
    args = ap.parse_args()

    rows = load_result(Path(args.result))
    # form 取第一条输出的 form；模型没给则用参数
    forms = []
    for _, resp in rows:
        try:
            forms.append(json.loads(resp).get('form'))
        except Exception:
            pass
    form = args.form or next((f for f in forms if f in {'solo', 'duo'}), 'solo')

    if args.strict:
        issues = []
        for section, resp in rows:
            for code, msg in validate({'response': resp}):
                issues.append(f'{section}: {code} {msg}')
        if issues:
            print(f'质量闸未过（{len(issues)} 项），未产出 plan：', file=sys.stderr)
            for line in issues[:20]:
                print('  ' + line, file=sys.stderr)
            return 1

    id_map = load_id_map(Path(args.id_map)) if args.id_map else None
    # Git Bash（MSYS）会把以 / 开头的参数转成 Windows 绝对路径；
    # 这里统一按「不带前导斜杠」重建，保证 manifest 里是 /audio/... 或 /verify/...。
    prefix = args.src_prefix.strip('/').split('/')[-1]
    plan = to_plan(args.chapter, rows, form, f'/{prefix}', id_map)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'已写出 {out}：{len(plan["sections"])} 节 / '
          f'{sum(len(s["units"]) for s in plan["sections"])} 个合成单元 / form={form}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
