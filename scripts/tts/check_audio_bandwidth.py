#!/usr/bin/env python3
"""素材体检：训练前先确认音频带宽够不够（r150）。

为什么需要：模型只能复现素材里存在的频段。素材若是窄带（低通处理、老录音、
助眠版剪辑），训出来的声音一定闷、像电话——**这一点任何模型、任何参数都救不回来**，
只能换素材。所以在花 1.5 小时训练之前，先花 10 秒体检。

判据（对中文口播/相声人声）：
    4000–6000Hz 占比 ≥ 0.5%  且  6000–8000Hz 占比 ≥ 1.0%

为什么看这两段：正常语音的高频是「6–8k 比 4–6k 还高」（实测参考音 1.28% vs 6.45%），
因为齿音/气声集中在 6kHz 以上。被低通处理过的素材，6k 以上会掉到 0.01% 量级。

为什么不只用「99% 带宽」：低频能量少时累积曲线会被推高，
实测一个 6k 以上几乎为零的文件也会显示 11kHz 带宽（假合格）。

实测参考：
    正常 TTS 参考音/产物   带宽 7–9kHz，4–6k 占比 1.2%
    某「助眠」单口素材     带宽 1.7–3.3kHz，4–6k 占比 0.02–0.32%  ← 不合格

用法：
    python scripts/tts/check_audio_bandwidth.py <音频> [<音频2> ...]
    python scripts/tts/check_audio_bandwidth.py D:/refs/*.wav
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np

MIN_MID_HI = 0.5   # 4–6kHz 占比下限（%）
MIN_HIGH = 1.0     # 6–8kHz 占比下限（%）——齿音区，低通处理会把它打到 0.01


def probe(path: str, seconds: float = 20.0) -> dict:
    import librosa

    warnings.filterwarnings('ignore')
    total = librosa.get_duration(path=path)
    offset = max(0.0, total / 2 - seconds / 2)
    y, sr = librosa.load(path, sr=None, mono=True, offset=offset, duration=seconds)
    spec = np.abs(librosa.stft(y, n_fft=2048)) ** 2
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    cum = spec.sum(axis=1).cumsum()
    cum = cum / cum[-1] if cum[-1] > 0 else cum
    bw99 = float(freqs[np.searchsorted(cum, 0.99)])
    mid_hi = float(spec[(freqs >= 4000) & (freqs < 6000)].sum() / spec.sum() * 100)
    high = float(spec[(freqs >= 6000) & (freqs < 8000)].sum() / spec.sum() * 100)
    return {
        'name': Path(path).name,
        'minutes': total / 60,
        'bw99': bw99,
        'mid_hi': mid_hi,
        'high': high,
        'ok': mid_hi >= MIN_MID_HI and high >= MIN_HIGH,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    rows = [probe(p) for p in sys.argv[1:]]
    print(f"{'文件':<36}{'时长':>8}{'4-6k':>9}{'6-8k':>9}  判定")
    print('-' * 78)
    bad = 0
    for r in rows:
        verdict = '合格' if r['ok'] else '不合格（太窄）'
        if not r['ok']:
            bad += 1
        print(f"{r['name'][:35]:<36}{r['minutes']:>7.1f}分{r['mid_hi']:>8.2f}%{r['high']:>8.2f}%  {verdict}")
    print('-' * 78)
    print(f'合格 {len(rows) - bad} / {len(rows)}')
    if bad:
        print('\n不合格的素材训练出来的声音会发闷、像电话——模型无法生成素材里不存在的高频。')
        print('请换更高带宽的源（未做低通处理的版本、或别的录音）。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
