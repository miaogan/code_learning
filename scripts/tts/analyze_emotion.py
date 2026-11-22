#!/usr/bin/env python3
"""情绪是否真的体现在声学上（r150 / M1 客观检查）。

听感靠耳朵，但「7 类情绪有没有差别」可以先量出来：按 timeline 的句级 cue 切音频，
统计每类情绪的 **基频均值（音高）/ 基频标准差（起伏）/ 能量（响度）**，
再对比「类间差异」与「类内波动」——如果 7 类的分布几乎重叠，说明 instruct 没起作用。

用法（在 CosyVoice 环境里跑，需要 librosa）：
    python scripts/tts/analyze_emotion.py
    python scripts/tts/analyze_emotion.py --chapter mw-observability
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
AUDIO_DIR = HERE / 'out' / 'audio'
SR = 16000


def load_librosa():
    try:
        import librosa
        return librosa
    except Exception as exc:  # pragma: no cover
        sys.exit(f'需要 librosa（CosyVoice 环境自带）：{exc}')


def f0_stats(librosa, y: np.ndarray) -> tuple[float, float, float]:
    """返回（基频均值, 基频标准差, RMS）；静音段返回 NaN。"""
    if y.size < SR * 0.15:
        return float('nan'), float('nan'), float('nan')
    f0 = librosa.yin(y, fmin=70, fmax=400, sr=SR, frame_length=1024, hop_length=256)
    f0 = f0[np.isfinite(f0)]
    rms = float(np.sqrt(np.mean(y ** 2)))
    if f0.size == 0:
        return float('nan'), float('nan'), rms
    return float(np.mean(f0)), float(np.std(f0)), rms


def main() -> int:
    parser = argparse.ArgumentParser(description='量化各情绪的声学差异')
    parser.add_argument('--chapter', action='append', default=None)
    parser.add_argument('--out', default=str(HERE / 'out' / 'emotion_stats.json'))
    args = parser.parse_args()
    librosa = load_librosa()

    rows: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    for chapter_dir in sorted(AUDIO_DIR.glob('*')):
        if not chapter_dir.is_dir():
            continue
        if args.chapter and chapter_dir.name not in set(args.chapter):
            continue
        for timeline_path in sorted(chapter_dir.glob('*.timeline.json')):
            track = json.loads(timeline_path.read_text(encoding='utf-8'))
            wav_path = chapter_dir / timeline_path.name.replace('.timeline.json', '.wav')
            if not wav_path.exists():
                continue
            y, _ = librosa.load(str(wav_path), sr=SR, mono=True)
            for cue in track['cues']:
                start = int(cue['startMs'] / 1000 * SR)
                end = int(cue['endMs'] / 1000 * SR)
                mean, std, rms = f0_stats(librosa, y[start:end])
                if np.isnan(mean):
                    continue
                rows[cue['emotion']].append((mean, std, rms))

    if not rows:
        sys.exit('没有可分析的音频；先跑 synthesize.py --backend cosyvoice')

    stats = {}
    print(f"{'情绪':<10}{'句数':>5}{'基频均值':>10}{'基频起伏':>10}{'能量':>10}")
    for emotion in ['banter', 'setup', 'deadpan', 'punch', 'realize', 'contrast', 'wrap']:
        items = rows.get(emotion, [])
        if not items:
            continue
        means = [item[0] for item in items]
        stds = [item[1] for item in items]
        rms = [item[2] for item in items]
        stats[emotion] = {
            'cues': len(items),
            'f0_mean': round(statistics.mean(means), 1),
            'f0_std_between_cues': round(statistics.pstdev(means), 1) if len(means) > 1 else 0.0,
            'f0_std_within_cue': round(statistics.mean(stds), 1),
            'rms': round(statistics.mean(rms), 4),
        }
        print(
            f'{emotion:<10}{len(items):>5}{stats[emotion]["f0_mean"]:>10}'
            f'{stats[emotion]["f0_std_between_cues"]:>10}{stats[emotion]["rms"]:>10}'
        )

    all_means = [value['f0_mean'] for value in stats.values()]
    spread = max(all_means) - min(all_means) if all_means else 0.0
    print()
    print(f'类间基频极差：{spread:.1f} Hz（越大说明情绪越"分得开"）')
    print('读法：类间极差 < 10Hz 基本等于没区分；> 25Hz 才可能在听感上有冷暖差别。')

    Path(args.out).write_text(json.dumps(stats, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'已写出：{args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
