#!/usr/bin/env python3
"""VoxCPM2 环境冒烟测试：确认能加载、能出声、带宽指标正常。

用途：换机器 / 重装环境后 30 秒确认链路通。跑完整实验请用 `infer_voxcpm.py`。

用法：
    D:/work_space/_tts/venv_voxcpm/Scripts/python.exe scripts/tts/smoke_voxcpm.py
"""

from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

REPO = Path(r"D:/work_space/_tts/VoxCPM-main")
MODEL_DIR = Path(r"D:/work_space/_tts/VoxCPM/pretrained_models")


def main() -> int:
    sys.path.insert(0, str(REPO / "src"))

    import torch

    print(f"torch {torch.__version__}  cuda={torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"gpu {torch.cuda.get_device_name(0)}")

    t0 = time.time()
    from voxcpm import VoxCPM

    print(f"import {time.time() - t0:.1f}s")

    t0 = time.time()
    model = VoxCPM.from_pretrained(
        hf_model_id=str(MODEL_DIR),
        load_denoiser=False,
        optimize=False,          # 冒烟测试不编译，省时间
        device="cuda",
        local_files_only=True,
    )
    print(f"load {time.time() - t0:.1f}s")

    tm = model.tts_model
    print(f"encode_sr={tm._encode_sample_rate}  out_sr={tm.sample_rate}  "
          f"dtype={next(tm.parameters()).dtype}")

    t0 = time.time()
    wav = model.generate(text="今天说个挺硬的话题。", denoise=False,
                         normalize=False, seed=0)
    dur = len(wav) / tm.sample_rate
    print(f"generate {dur:.2f}s 音频 / {time.time() - t0:.1f}s  "
          f"(RTF={(time.time() - t0) / dur:.2f})")

    if torch.cuda.is_available():
        print(f"vram reserved {torch.cuda.memory_reserved() / 1024**3:.2f} GB")

    # 带宽快检：4-6k / 8k 以上。正常语音 4-6k ≈1%，8k+ ≈3-5%
    import librosa
    import numpy as np

    spec = np.abs(librosa.stft(wav, n_fft=4096)) ** 2
    f = librosa.fft_frequencies(sr=tm.sample_rate, n_fft=4096)
    tot = spec.sum()
    print(f"带宽 4-6k={spec[(f >= 4000) & (f < 6000)].sum() / tot * 100:.3f}%  "
          f"8k+={spec[f >= 8000].sum() / tot * 100:.3f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
