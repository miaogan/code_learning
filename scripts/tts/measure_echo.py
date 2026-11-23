#!/usr/bin/env python3
"""回音/拖音体检（r150）：判断「听起来有回音」到底是真混响还是解码拖尾。

为什么需要单独一个指标：用户反复反馈「有回音」，但此前实测参考音混响只有 140ms，
排除了真混响，最后定位到「GPT 解码温度过高导致拖音」。所以「回音」至少对应三种
成因，必须能用数字区分：

    1. **真混响/回声**：音节结束后还有清晰的反射声 → 包络衰减变平、谷底被抬
    2. **解码拖音**：尾巴长但平滑，没有延时重复
    3. **削顶/失真**：听着「糊」，那是谐波不是延时（用 SNR/削顶率判，见 infer 脚本）

核心指标是**衰减斜率**（dB/ms），因为它不受「文件里有没有静音」影响：

    - `slope` 中位衰减斜率。干声口播 −0.4 ~ −0.7 dB/ms；
      混响重的 −0.1 ~ −0.2；拖音介于两者之间。
    - `t20` 按该斜率衰减 20dB 需要多少毫秒（更好读）。干声 30–60ms，带混响 120ms+。
    - `valley` 谷底相对峰值的电平（dB，越接近 0 越平）。
      **回声会把音节之间的谷抬起来**；干声通常 −30dB 以下。

用法：
    python scripts/tts/measure_echo.py <音频> [<音频2> ...]
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np

HOP_MS = 5.0


def envelope(y: np.ndarray, sr: int) -> np.ndarray:
    hop = max(1, int(sr * HOP_MS / 1000))
    n = len(y) // hop
    if n < 40:
        return np.zeros(0)
    frames = y[: n * hop].reshape(n, hop)
    env = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    # 轻度平滑，压掉单帧毛刺但保留衰减形状
    return np.convolve(env, np.ones(3) / 3, mode="same")


def metrics(y: np.ndarray, sr: int) -> dict:
    env = envelope(y, sr)
    if env.size == 0:
        return {}
    env_db = 20 * np.log10(np.maximum(env, 1e-9))
    peak = env.max()
    if peak <= 0:
        return {}

    # ---- 衰减斜率：从每个强峰往后 50–150ms 线性拟合 ----
    slopes: list[float] = []
    a_off, b_off = int(50 / HOP_MS), int(150 / HOP_MS)
    for i in range(1, len(env) - 1):
        if env[i] < peak * 0.35:
            continue
        if not (env[i] >= env[i - 1] and env[i] > env[i + 1]):
            continue
        a, b = i + a_off, i + b_off
        if b >= len(env):
            continue
        seg = env_db[a:b]
        if not np.all(np.isfinite(seg)):
            continue
        x = np.arange(len(seg)) * HOP_MS
        slopes.append(float(np.polyfit(x, seg, 1)[0]))   # dB/ms，负值

    slopes = [s for s in slopes if s < 0]                # 只保留正在衰减的
    if slopes:
        slope = float(np.median(slopes))
        t20 = float(-20.0 / slope) if slope < -1e-6 else 999.0
    else:
        slope, t20 = 0.0, 999.0

    # ---- 谷底电平：局部最小值的电平相对峰值 ----
    mins = [env_db[i] for i in range(2, len(env) - 2)
            if env[i] <= env[i - 2] and env[i] <= env[i + 2]]
    if mins:
        # 取最深的 60%，避开换气/段间长静音，只看音节之间的谷
        mins_sorted = np.sort(mins)
        n_keep = max(1, int(len(mins_sorted) * 0.6))
        valley = float(np.median(mins_sorted[:n_keep]) - 20 * np.log10(peak))
    else:
        valley = 0.0

    dr = float(np.percentile(env_db, 90) - np.percentile(env_db, 10))
    return {"slope": slope, "t20": t20, "valley": valley, "dr": dr,
            "n": len(slopes)}


def probe(path: str) -> dict | None:
    import librosa

    warnings.filterwarnings("ignore")
    try:
        y, sr = librosa.load(path, sr=None, mono=True)
    except Exception as e:  # noqa: BLE001 - 单文件坏了不该中断整批
        print(f"  ! {Path(path).name}: {e}", flush=True)
        return None
    m = metrics(y, sr)
    if not m:
        return None
    m["name"] = Path(path).name
    m["dur"] = len(y) / sr
    return m


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    rows = [r for r in (probe(p) for p in sys.argv[1:]) if r]
    if not rows:
        return 1
    print(f"{'文件':30s} {'时长':>6s} {'衰减斜率':>10s} {'t20':>7s} "
          f"{'谷底':>8s}  判定")
    print("-" * 84)
    for r in rows:
        flags = []
        if r["t20"] >= 200:
            flags.append("拖尾/混响很重")
        elif r["t20"] >= 110:
            flags.append("尾巴偏长")
        if r["valley"] > -20:
            flags.append("谷底被抬(有回声)")
        print(f"{r['name']:30s} {r['dur']:5.1f}s {r['slope']:9.3f} "
              f"{r['t20']:6.0f}ms {r['valley']:7.1f}dB  "
              f"{' / '.join(flags) if flags else '干净'}")
    print("\n判据：t20 <110ms 干净；110–200 尾巴偏长；>200 混响/拖音重。"
          "\n      谷底 > -20dB → 音节之间抬起来了，听感就是「有回音」。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
