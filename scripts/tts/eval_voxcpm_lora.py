#!/usr/bin/env python3
"""LoRA 微调前后 A/B 评测：同一文本、同一参考音、同一 seed 做对照。

为什么要自建而不是直接跑官方 test_voxcpm_lora_infer.py：
    官方脚本一次生成 5 条（with/disabled/reenabled/reset/reloaded），其中
    3 条是重复验证开关功能的；评测只需要 with vs disabled 两条，省一半时间。
    另外官方用 `model.generate` 逐句重编码参考音，这里复用 `build_prompt_cache`
    与生产链路（synthesize.py 的 VoxCPMBackend）保持一致。

指标：
    t20 / valley  见 measure_echo.py（回音/拖音）
    mid_hi/high   见 check_audio_bandwidth.py（4-6k / 6-8k 高频占比）

用法：
    D:/work_space/_tts/venv_voxcpm/Scripts/python.exe scripts/tts/eval_voxcpm_lora.py \
        --ckpt D:/work_space/_tts/voxcpm_lora/gdg_v1/checkpoints/step_0000300 \
        --out  D:/work_space/_tts/voxcpm_lora/gdg_v1/eval
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from measure_echo import metrics as echo_metrics  # noqa: E402

REPO = Path(r'D:/work_space/_tts/VoxCPM-main')
MODEL_DIR = Path(r'D:/work_space/_tts/VoxCPM/pretrained_models')
REF_WAV = Path(r'D:/work_space/_tts/dataset/slices/ep3-0386.wav')
DS_TRAIN = Path(r'D:/work_space/_tts/voxcpm_ds/train.jsonl')


def band_share(y: np.ndarray, sr: int) -> dict:
    """与 check_audio_bandwidth.probe 同口径的频段占比（%）。"""
    import librosa

    spec = np.abs(librosa.stft(y, n_fft=2048)) ** 2
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    total = float(spec.sum())
    if total <= 0:
        return {'mid_hi': 0.0, 'high': 0.0}
    return {
        'mid_hi': float(spec[(freqs >= 4000) & (freqs < 6000)].sum() / total * 100),
        'high': float(spec[(freqs >= 6000) & (freqs < 8000)].sum() / total * 100),
    }


def load_model(ckpt: Path, model_dir: Path):
    sys.path.insert(0, str(REPO / 'src'))
    from voxcpm.core import VoxCPM
    from voxcpm.model.voxcpm import LoRAConfig as LoRAConfigV1
    from voxcpm.model.voxcpm2 import LoRAConfig as LoRAConfigV2
    from voxcpm.model.utils import next_and_close

    info = json.loads((ckpt / 'lora_config.json').read_text(encoding='utf-8'))
    arch = json.loads((model_dir / 'config.json').read_text(encoding='utf-8'))
    arch = str(arch.get('architecture', 'voxcpm')).lower()
    cfg_cls = LoRAConfigV2 if arch == 'voxcpm2' else LoRAConfigV1
    lora_cfg = cfg_cls(**(info.get('lora_config') or {}))
    print(f'架构 {arch} · LoRA r={lora_cfg.r} alpha={lora_cfg.alpha}', flush=True)

    model = VoxCPM.from_pretrained(
        hf_model_id=str(model_dir),
        load_denoiser=False,
        optimize=False,
        device='cuda',
        local_files_only=True,
        lora_config=lora_cfg,
        lora_weights_path=str(ckpt),
    )
    return model, next_and_close


def main() -> int:
    ap = argparse.ArgumentParser(description='LoRA 微调前后 A/B 评测')
    ap.add_argument('--ckpt', required=True, help='含 lora_weights.safetensors 与 lora_config.json 的目录')
    ap.add_argument('--out', required=True)
    ap.add_argument('--model-dir', default=str(MODEL_DIR))
    ap.add_argument('--ref', default=str(REF_WAV))
    ap.add_argument('--texts-from', default=str(DS_TRAIN), help='JSONL，取其中 text 字段')
    ap.add_argument('--n-texts', type=int, default=4)
    ap.add_argument('--cfg', type=float, default=1.5)
    ap.add_argument('--timesteps', type=int, default=10)
    ap.add_argument('--seed', type=int, default=7)
    args = ap.parse_args()

    warnings.filterwarnings('ignore')
    ckpt, out = Path(args.ckpt), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if not (ckpt / 'lora_config.json').exists():
        raise SystemExit(f'checkpoint 缺 lora_config.json: {ckpt}')

    texts = [json.loads(ln)['text'] for ln in Path(args.texts_from).read_text(encoding='utf-8').splitlines()
             if ln.strip()][:args.n_texts]
    if not texts:
        raise SystemExit('没有可评测的文本')

    model, next_and_close = load_model(ckpt, Path(args.model_dir))
    tts = model.tts_model
    sr = int(tts.sample_rate)
    cache = tts.build_prompt_cache(reference_wav_path=str(args.ref))
    print(f'参考音 {args.ref} · 采样率 {sr} · {len(texts)} 条文本', flush=True)

    def synthesize(text: str) -> np.ndarray:
        gen = tts._generate_with_prompt_cache(
            target_text=text, prompt_cache=cache,
            inference_timesteps=args.timesteps, cfg_value=args.cfg, seed=args.seed,
        )
        wav, _, _ = next_and_close(gen)
        return wav.squeeze(0).float().cpu().numpy()

    rows = []
    for i, text in enumerate(texts):
        row = {'text': text}
        for tag, enabled in (('lora', True), ('base', False)):
            model.set_lora_enabled(enabled)
            audio = synthesize(text)
            path = out / f'{i:02d}_{tag}.wav'
            sf.write(str(path), audio, sr)
            m = echo_metrics(audio, sr)
            m.update(band_share(audio, sr))
            m['dur'] = len(audio) / sr
            row[tag] = m
        rows.append(row)
        print(f'[{i + 1}/{len(texts)}] {text[:28]}… '
              f't20 {row["base"]["t20"]:.0f}→{row["lora"]["t20"]:.0f}ms '
              f'high {row["base"]["high"]:.3f}→{row["lora"]["high"]:.3f}%', flush=True)

    def avg(tag: str, key: str) -> float:
        return float(np.mean([r[tag][key] for r in rows]))

    summary = {
        'ckpt': str(ckpt), 'cfg': args.cfg, 'seed': args.seed, 'n_texts': len(rows),
        'base': {'t20': avg('base', 't20'), 'valley': avg('base', 'valley'),
                 'mid_hi': avg('base', 'mid_hi'), 'high': avg('base', 'high')},
        'lora': {'t20': avg('lora', 't20'), 'valley': avg('lora', 'valley'),
                 'mid_hi': avg('lora', 'mid_hi'), 'high': avg('lora', 'high')},
        'rows': rows,
    }
    (out / 'eval.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\n均值对比:')
    for key in ('t20', 'valley', 'mid_hi', 'high'):
        print(f'  {key:8s} base {summary["base"][key]:8.3f}  →  lora {summary["lora"][key]:8.3f}')
    print(f'明细: {out / "eval.json"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
