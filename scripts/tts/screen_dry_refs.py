#!/usr/bin/env python3
"""从切片库里挑「最干」的参考音（r150）。

背景：VoxCPM2 实测输出的衰减几乎完全复制参考音（t20 186ms vs 参考 174ms），
也就是说**「回音」是参考音自带的混响被一起克隆了**，不是模型加的。
既然「音色 = 频谱包络」，混响特征也在包络里，那唯一的解法就是换更干的参考音。

指标取自 `measure_echo.py`：衰减斜率 / t20 / 谷底电平。
另外附带 4–6k 占比（带宽），因为太窄的切片出来一定闷。

用法：
    python scripts/tts/screen_dry_refs.py --dir D:/work_space/_tts/dataset/slices --top 12
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_echo import metrics  # noqa: E402  复用同一套判定


def load(path: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf

    y, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if y.ndim > 1:
        y = y.mean(axis=1)
    return y, sr


def band_pct(y: np.ndarray, sr: int, lo: int, hi: int) -> float:
    import librosa

    spec = np.abs(librosa.stft(y, n_fft=2048)) ** 2
    f = librosa.fft_frequencies(sr=sr, n_fft=2048)
    tot = spec.sum()
    if tot <= 0:
        return 0.0
    return float(spec[(f >= lo) & (f < hi)].sum() / tot * 100)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--min-dur", type=float, default=4.0)
    ap.add_argument("--max-dur", type=float, default=12.0)
    ap.add_argument("--pattern", default="*.wav")
    args = ap.parse_args()

    files = sorted(Path(args.dir).glob(args.pattern))
    if not files:
        raise SystemExit(f"没找到 wav: {args.dir}")

    rows = []
    for i, p in enumerate(files, 1):
        try:
            y, sr = load(p)
        except Exception:  # noqa: BLE001 - 坏文件跳过
            continue
        dur = len(y) / sr
        if not (args.min_dur <= dur <= args.max_dur):
            continue
        m = metrics(y, sr)
        if not m or m["n"] < 5:
            continue
        m["name"] = p.name
        m["path"] = str(p)
        m["dur"] = dur
        m["m46"] = band_pct(y, sr, 4000, 6000)
        rows.append(m)
        if i % 400 == 0:
            print(f"  已扫 {i}/{len(files)}…", flush=True)

    if not rows:
        raise SystemExit("没有符合条件的切片")

    # 排序：先干（t20 小），再谷底深，再看带宽别太差
    rows.sort(key=lambda r: (r["t20"], -r["valley"]))
    print(f"\n共 {len(rows)} 个候选，按「最干」排序：\n")
    print(f"{'#':>3s} {'文件':22s} {'时长':>6s} {'t20':>7s} {'斜率':>8s} "
          f"{'谷底':>8s} {'4-6k':>7s}")
    print("-" * 74)
    for k, r in enumerate(rows[: args.top], 1):
        print(f"{k:3d} {r['name']:22s} {r['dur']:5.1f}s {r['t20']:6.0f}ms "
              f"{r['slope']:7.3f} {r['valley']:7.1f}dB {r['m46']:6.3f}%")
    print("\n路径（复制给 --ref）：")
    for r in rows[: args.top]:
        print(f"  {r['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
