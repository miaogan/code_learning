#!/usr/bin/env python3
"""从公开语料里筛「表演型男声」参考音（r150）。

为什么需要：CosyVoice 自带的中性播报音不适合相声；要的是**有辨识度、语气起伏大**的真人嗓子。
本脚本在许可明确的中文语料（如 Emilia, CC-BY-4.0）里按客观指标筛候选：

    - 时长 8–30 秒（够 TTS 零样本用）
    - 基频均值 75–175 Hz（男声）
    - 语气起伏：基频标准差 / 均值（越大越像"在演"）
    - 有效性：静音占比 < 0.45、RMS 不为 0

用法（CosyVoice 环境）：
    python scripts/tts/screen_refs.py --src D:/work_space/_tts/emilia/extracted --top 8

产物：`out/refs/<前缀>_NN.wav` + `refs_report.md`（每个候选的指标与来源路径），人工听选后
用 `--prompt-wav` 指给 synthesize.py。
"""

from __future__ import annotations

import argparse
import glob
import random
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description='筛表演型参考音')
    parser.add_argument('--src', required=True, help='语料目录（递归找 wav）')
    parser.add_argument('--out', default=str(HERE / 'out' / 'refs' / 'emilia'))
    parser.add_argument('--prefix', default='emilia')
    parser.add_argument('--top', type=int, default=8)
    parser.add_argument('--sample', type=int, default=600, help='最多检查多少个文件（随机抽样）')
    parser.add_argument('--min-dur', type=float, default=8.0)
    parser.add_argument('--max-dur', type=float, default=30.0)
    parser.add_argument('--f0-min', type=float, default=75.0)
    parser.add_argument('--f0-max', type=float, default=175.0)
    parser.add_argument('--seed', type=int, default=150)
    args = parser.parse_args()

    try:
        import librosa
        import numpy as np
        import soundfile as sf
    except Exception as exc:  # pragma: no cover
        sys.exit(f'需要 librosa/soundfile（CosyVoice 环境自带）：{exc}')

    files = sorted(glob.glob(str(Path(args.src) / '**' / '*.wav'), recursive=True))
    if not files:
        sys.exit(f'{args.src} 下没有 wav')
    random.seed(args.seed)
    if len(files) > args.sample:
        files = random.sample(files, args.sample)

    rows = []
    for path in files:
        try:
            info = sf.info(path)
            dur = info.frames / info.samplerate
            if not (args.min_dur <= dur <= args.max_dur):
                continue
            y, sr = librosa.load(path, sr=16000, mono=True)
            if y.size < 16000:
                continue
            rms = float(np.sqrt(np.mean(y**2)))
            if rms < 1e-4:
                continue
            silence = float(np.mean(np.abs(y) < 0.01))
            if silence > 0.45:
                continue
            f0 = librosa.yin(y, fmin=60, fmax=400, sr=16000, frame_length=1024, hop_length=256)
            f0 = f0[np.isfinite(f0)]
            if f0.size < 20:
                continue
            mean = float(np.mean(f0))
            if not (args.f0_min <= mean <= args.f0_max):
                continue
            spread = float(np.std(f0)) / mean
            rows.append((spread, path, dur, mean, silence, rms))
        except Exception:
            continue

    if not rows:
        sys.exit('没有候选：放宽 f0 范围或时长范围再试')
    rows.sort(key=lambda row: -row[0])
    picks = rows[: args.top]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = ['# 表演型参考音候选', '', '按「语气起伏」排序；人工听选后传给 synthesize.py 的 --prompt-wav', '',
              '| 文件 | 时长 | 基频 | 起伏 | 静音比 | 源文件 |', '|---|---|---|---|---|---|']
    for index, (spread, path, dur, mean, silence, _rms) in enumerate(picks, start=1):
        name = f'{args.prefix}_{index:02d}.wav'
        shutil.copyfile(path, out_dir / name)
        report.append(f'| {name} | {dur:.1f}s | {mean:.0f}Hz | {spread:.2f} | {silence:.2f} | `{path}` |')
        print(f'{name}: {dur:.1f}s f0={mean:.0f}Hz 起伏={spread:.2f}')
    (out_dir / 'refs_report.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
    print(f'\n已挑 {len(picks)} 个候选 → {out_dir}（报告 refs_report.md）')
    print('下一步：python scripts/tts/synthesize.py ... --prompt-wav <候选> --limit-sections 1 做 A/B')
    return 0


if __name__ == '__main__':
    sys.exit(main())
