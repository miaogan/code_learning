#!/usr/bin/env python3
"""训练集切片（r150 制作链）：把长音频切成 3–10 秒的训练片段。

为什么不用 GPT-SoVITS 自带的 `tools/slice_audio.py`：
它的 `tools/my_utils.py` 里 `import gradio`，命令行跑切片要额外装一整套 UI 依赖。
切片算法本体在 `tools/slicer2.py`，只依赖 numpy，这里直接调用它。

用法：
    python scripts/tts/prepare_trainset.py --in <长音频.wav> --out <切片目录>
    python scripts/tts/prepare_trainset.py --in a.wav --in b.wav --out slices --min-ms 3000 --max-ms 10000

产物：`<out>/<源名>-0000.wav …`，32kHz 单声道 16-bit，可直接喂 GPT-SoVITS。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

# slicer2 只依赖 numpy，直接按路径导入，不经过 tools 包（那个包会拉 gradio）
DEFAULT_SLICER_DIR = Path('D:/work_space/_tts/GPT-SoVITS/tools')


def load_mono(path: Path, sr: int = 32000) -> np.ndarray:
    import librosa

    audio, _ = librosa.load(str(path), sr=sr, mono=True)
    return audio


def main() -> int:
    ap = argparse.ArgumentParser(description='长音频切成训练片段（3–10 秒）')
    ap.add_argument('--in', dest='inputs', action='append', required=True, help='输入音频（可重复）')
    ap.add_argument('--out', required=True, help='切片输出目录')
    ap.add_argument('--slicer-dir', default=str(DEFAULT_SLICER_DIR), help='slicer2.py 所在目录')
    ap.add_argument('--threshold', type=int, default=-34, help='低于该 dB 视为静音切割点')
    ap.add_argument('--min-ms', type=int, default=3000, help='片段最短时长')
    ap.add_argument('--max-ms', type=int, default=10000, help='片段最长时长（超出会被算法切开）')
    ap.add_argument('--min-interval', type=int, default=300, help='最短切割间隔')
    ap.add_argument('--hop-size', type=int, default=10)
    ap.add_argument('--max-sil-kept', type=int, default=500, help='切完每段最多保留多少静音')
    args = ap.parse_args()

    sys.path.insert(0, args.slicer_dir)
    from slicer2 import Slicer  # noqa: PLC0415 - 依赖运行时路径

    import soundfile as sf

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    slicer = Slicer(
        sr=32000,
        threshold=args.threshold,
        min_length=args.min_ms,
        min_interval=args.min_interval,
        hop_size=args.hop_size,
        max_sil_kept=args.max_sil_kept,
    )

    total = 0
    kept_seconds = 0.0
    for src in args.inputs:
        path = Path(src)
        if not path.exists():
            sys.exit(f'输入不存在：{path}')
        audio = load_mono(path)
        stem = path.stem
        n = 0
        for chunk, _start, _end in slicer.slice(audio):
            dur = len(chunk) / 32000
            if dur * 1000 < args.min_ms:
                continue
            # 过长的段按 max_ms 硬切：GPT-SoVITS 训练片段太长的收益很低，
            # 而且会让显存和注意力跨度一起涨。
            step = int(args.max_ms / 1000 * 32000)
            for offset in range(0, len(chunk), step):
                part = chunk[offset:offset + step]
                if len(part) / 32000 * 1000 < args.min_ms:
                    continue
                peak = float(np.abs(part).max()) or 1.0
                part = part / peak * 0.9
                name = f'{stem}-{n:04d}.wav'
                sf.write(str(out_dir / name), (part * 32767).astype(np.int16), 32000)
                n += 1
                kept_seconds += len(part) / 32000
        print(f'{path.name}: {n} 片')
        total += n

    print(f'\n共 {total} 片 · {kept_seconds / 60:.1f} 分钟 · → {out_dir}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
