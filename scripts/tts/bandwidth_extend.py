#!/usr/bin/env python3
"""带宽扩展（SBR）：给窄带人声补高频（r150）。

背景：训练素材 6kHz 以上几乎为零，模型只能复现这个上限（实测换更强的 IndexTTS2
也一样，因为音色=频谱包络，带宽是包络的一部分）。既想要音色又要亮度，只剩后处理。

方法：spectral band replication（SBR，MP3/AAC 时代的经典手段）——
把 2–4kHz 的能量按衰减曲线搬移到 4–8kHz，再叠回原信号。

必须说清：**补出来的是"像齿音"的能量，不是真实齿音**。它让声音不闷，
但高频细节是算法猜的，可能带来轻微"沙沙"感。听感接受度要靠试。

用法：
    python scripts/tts/bandwidth_extend.py --in narrow.wav --out wide.wav --strength 0.35
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def _sbr_one(y: np.ndarray, sr: int, src_band: tuple[int, int], dst_band: tuple[int, int],
             strength: float, gain: float, n_fft: int = 1024, hop: int = 256) -> np.ndarray:
    import librosa

    spec = librosa.stft(y, n_fft=n_fft, hop_length=hop)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    mag, phase = np.abs(spec), np.angle(spec)

    src_lo, src_hi = np.searchsorted(freqs, src_band[0]), np.searchsorted(freqs, src_band[1])
    dst_lo, dst_hi = np.searchsorted(freqs, dst_band[0]), np.searchsorted(freqs, dst_band[1])
    width = min(src_hi - src_lo, dst_hi - dst_lo)
    if width <= 0:
        return y

    # 直接搬**复数谱**（含相位）。只搬幅度再套源相位会导致重建时相互抵消
    # （实测 4–6k 反而从 0.12% 掉到 0.03%）。
    # 源带能量本身很弱，所以需要 gain 补偿，否则补了等于没补。
    src = spec[src_lo:src_lo + width, :]
    falloff = np.linspace(1.0, 0.5, width)[:, None]
    spec[dst_lo:dst_lo + width, :] += src * falloff * strength * gain

    wide = librosa.istft(spec, hop_length=hop, length=len(y))
    peak = float(np.abs(wide).max()) or 1.0
    if peak > 0.95:
        wide = wide / peak * 0.95
    return wide


def extend(y: np.ndarray, sr: int, strength: float = 0.35, gain: float = 4.0,
           stages: int = 2, n_fft: int = 1024, hop: int = 256) -> np.ndarray:
    """级联 SBR：每级把上一级补出来的频带再往上搬一层。

    单级只能填 4–5.4kHz（源带 1.8–4k 仅 2.2kHz 宽）。second stage 用刚补出的
    4–6.5k 再去填 6.5–9k，才能覆盖到真人该有的 6–8kHz。
    级联会累积"借用"痕迹，沙沙感更明显，所以每级的 strength 递减。
    """
    bands = [((1800, 4000), (4000, 6500)), ((4000, 6500), (6500, 9000))]
    for i in range(min(stages, len(bands))):
        src, dst = bands[i]
        decay = 1.0 if i == 0 else 0.6  # 第二级更保守
        y = _sbr_one(y, sr, src, dst, strength * decay, gain, n_fft, hop)
    return y


def main() -> int:
    import librosa
    import soundfile as sf

    ap = argparse.ArgumentParser(description='窄带人声带宽扩展（SBR）')
    ap.add_argument('--in', dest='src', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--strength', type=float, default=0.35, help='高频叠加强度（0.2–0.5 比较自然）')
    ap.add_argument('--gain', type=float, default=4.0, help='源带补偿增益（源带能量弱，需放大）')
    ap.add_argument('--stages', type=int, default=2, help='级联层数（1=只补 4-6.5k，2=再补 6.5-9k）')
    args = ap.parse_args()

    y, sr = librosa.load(args.src, sr=None, mono=True)
    wide = extend(y, sr, strength=args.strength, gain=args.gain, stages=args.stages)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), (np.clip(wide, -1, 1) * 32767).astype(np.int16), sr)
    print(f'{out}  ({len(wide) / sr:.1f}s, {sr}Hz, strength={args.strength})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
