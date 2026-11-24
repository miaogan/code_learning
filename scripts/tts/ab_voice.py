#!/usr/bin/env python3
"""音色 A/B 试听（r151）：同一小节、多个参考音/参数各合成一遍，生成可点播的对比页。

背景（2026-11-24 用户反馈）：官方演示参考音的成品「不如 gdg LoRA 版好听」。
差距有两个来源，必须分开验证：
  1. **参考音**：零样本克隆只能模仿参考音的音色与韵律（官方 demo 是英文演示音）；
  2. **LoRA**：gdg 版有 1718 条同音色数据微调，韵律更像真人表演。
本脚本把候选参考音（AISHELL-3 开源中文，Apache-2.0）与参数（cfg / timesteps）并排跑，
产出 `ab/index.html` 供人工盲听挑选——**选音色是主观决策，脚本只负责把样本摆齐**。

用法（须在 voxcpm venv 下跑，且 GPU 空闲）：
    D:/work_space/_tts/venv_voxcpm/Scripts/python.exe scripts/tts/ab_voice.py \
        --chapter ai-agent-memory --section layers
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
AISHELL = Path('D:/work_space/_tts/opensrc_refs/aishell3_samples')

#: 候选：名称 → (参考音, cfg, timesteps, lora, 说明)
#: AISHELL 样本由"6kHz 以上能量占比"筛出（越亮越清楚），音色偏好需人工听。
VARIANTS: list[tuple[str, str, float, int, str | None, str]] = [
    ('A-official', 'D:/work_space/_tts/VoxCPM-main/examples/reference_speaker.wav', 1.5, 10, None,
     '当前线上用的官方演示参考音（基线）'),
    ('B-aish-7', str(AISHELL / 'sample_7.wav'), 1.5, 10, None, 'AISHELL-3 中文音色 #7（高频 19.7%）'),
    ('C-aish-168', str(AISHELL / 'sample_168.wav'), 1.5, 10, None, 'AISHELL-3 中文音色 #168（高频 17.9%）'),
    ('D-aish-88', str(AISHELL / 'sample_88.wav'), 1.5, 10, None, 'AISHELL-3 中文音色 #88（高频 16.8%）'),
    ('E-aish-9', str(AISHELL / 'sample_9.wav'), 1.5, 10, None, 'AISHELL-3 中文音色 #9（更长、静音少）'),
    ('F-official-cfg2', 'D:/work_space/_tts/VoxCPM-main/examples/reference_speaker.wav', 2.0, 10, None,
     '官方参考音 + cfg 2.0（更强引导，看是否更有表现力）'),
    ('G-official-t16', 'D:/work_space/_tts/VoxCPM-main/examples/reference_speaker.wav', 1.5, 16, None,
     '官方参考音 + 采样步数 16（质量上限探测，更慢）'),
]


def build_plan(chapter: str, section: str | None, out_dir: Path) -> Path:
    """把正式 plan 裁成单节，写进独立目录（不动正式产物）。"""
    plans_src = ROOT / 'scripts/tts/out/plans_full'
    plan = json.loads((plans_src / f'{chapter}.json').read_text(encoding='utf-8'))
    sections = plan['sections']
    if section:
        sections = [s for s in sections if s['sectionId'] == section]
        if not sections:
            sys.exit(f'{chapter} 没有小节 {section}；可选：{[s["sectionId"] for s in plan["sections"]]}')
    plan['sections'] = sections[:1]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f'{chapter}.json'
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description='同一小节多音色 A/B 试听')
    ap.add_argument('--chapter', default='ai-agent-memory')
    ap.add_argument('--section', default=None, help='只跑指定小节（默认第一节）')
    ap.add_argument('--out', default='scripts/tts/out/ab_voices')
    ap.add_argument('--only', default=None, help='只跑指定变体名（如 B-aish-7）')
    ap.add_argument('--index-only', action='store_true', help='只重建对比页，不重新合成')
    args = ap.parse_args()

    out_root = ROOT / args.out
    out_root.mkdir(parents=True, exist_ok=True)
    plan_dir = out_root / '_plan'
    build_plan(args.chapter, args.section, plan_dir)

    variants = [v for v in VARIANTS if args.only is None or v[0] == args.only]
    results: list[tuple[str, Path, str]] = []
    if args.index_only:
        # 只重建对比页：合成早就跑完了，没必要再动 GPU
        for name, _ref, _cfg, _steps, _lora, note in variants:
            wavs = sorted((out_root / name).rglob('*.wav'))
            if wavs:
                results.append((name, wavs[0], note))
        variants = []
    for name, ref, cfg, steps, lora, note in variants:
        if not Path(ref).exists():
            print(f'[skip] {name}：参考音不存在 {ref}')
            continue
        audio_dir = out_root / name
        if audio_dir.exists():
            shutil.rmtree(audio_dir)
        cmd = [
            sys.executable, str(HERE / 'synthesize.py'),
            '--backend', 'voxcpm',
            '--plan-dir', str(plan_dir),
            '--out-audio', str(audio_dir),
            '--chapter', args.chapter,
            '--vox-ref', ref,
            '--vox-cfg', str(cfg),
            '--vox-timesteps', str(steps),
        ]
        if lora:
            cmd += ['--vox-lora', lora]
        print(f'[ab] {name}：{" ".join([Path(ref).name, f"cfg={cfg}", f"t={steps}"])}')
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            print(f'[ab] {name} 失败（exit {result.returncode}）')
            continue
        wavs = sorted(audio_dir.rglob('*.wav'))
        if wavs:
            results.append((name, wavs[0], note))

    index = out_root / 'index.html'
    rows = '\n'.join(
        f'''    <section>
      <h2>{html.escape(name)} <span class="note">{html.escape(note)}</span></h2>
      <audio controls preload="metadata" src="{html.escape(p.relative_to(out_root).as_posix())}"></audio>
    </section>'''
        for name, p, note in results
    )
    index.write_text(
        f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>音色 A/B · {args.chapter}</title>
<style>
 body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;max-width:860px;margin:40px auto;padding:0 20px;background:#17171a;color:#eee}}
 h1{{font-size:20px;font-weight:600}} h2{{font-size:15px;font-weight:600;margin:0 0 8px}}
 .note{{font-weight:400;color:#9aa;font-size:13px;margin-left:8px}}
 section{{border:1px solid #2c2c31;border-radius:10px;padding:14px 16px;margin:12px 0;background:#1e1e22}}
 audio{{width:100%}} .hint{{color:#8a8a92;font-size:13px;line-height:1.7}}
</style>
<h1>音色 A/B 试听 · {args.chapter}</h1>
<p class="hint">同一小节、相同文本。A 是线上现用版本；B–E 是开源中文音色；F/G 是参数变化。<br>
听着挑一个最舒服的告诉我编号即可（选完我用它重跑全量）。</p>
{rows}
</html>''',
        encoding='utf-8',
    )
    print(f'\n对比页 → {index}')
    print(f'完成 {len(results)}/{len(variants)} 个变体')
    return 0


if __name__ == '__main__':
    sys.exit(main())
