#!/usr/bin/env python3
"""VoxCPM2 推理脚本（r150）：验证「窄带参考音 → 48kHz 宽带输出」是否成立。

为什么单独写一个：前面的结论已经很硬——**音色与带宽不可分割**。郭德纲那批素材
本身是窄带（4-6k 仅 0.12%，6-8k 只有 0.02%），GPT-SoVITS / IndexTTS2 都只能复现
素材里存在的频段，所以出来一定是「手机通话」质感。VoxCPM2 是唯一一个把超分做进
解码器的模型：

    AudioVAE V2：编码 16kHz in → 解码 48kHz out（sr_bin_boundaries 20k/30k/40k）

如果它能「拿窄带参考音、吐宽带音频」，音色和清晰度就能同时拿到——这正是整条
验证链路最后一块拼图。若不行，就定稿 gdg2_t07。

用法：
    # 单句
    python scripts/tts/infer_voxcpm.py --ref ref.wav --text "今天咱们说一段" --out a.wav

    # 批量（每行一句，# 开头为注释）
    python scripts/tts/infer_voxcpm.py --ref ref.wav --text-file lines.txt --out-dir out/

注意：
    - 不用 normalize=True（会走 wetext → ModelScope 403 那个坑）
    - 不用 denoise=True（要额外拉 modelscope zipenhancer 权重）
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(r"D:/work_space/_tts/VoxCPM-main")
DEFAULT_MODEL = Path(r"D:/work_space/_tts/VoxCPM/pretrained_models")


def load_lines(args) -> list[str]:
    if args.text:
        return [args.text]
    if args.text_file:
        raw = Path(args.text_file).read_text(encoding="utf-8").splitlines()
        return [ln.strip() for ln in raw if ln.strip() and not ln.strip().startswith("#")]
    raise SystemExit("需要 --text 或 --text-file")


def build_model(model_dir: Path, device: str, optimize: bool):
    sys.path.insert(0, str(REPO / "src"))
    from voxcpm import VoxCPM

    t0 = time.time()
    model = VoxCPM.from_pretrained(
        hf_model_id=str(model_dir),
        load_denoiser=False,          # 避开 modelscope 额外权重
        optimize=optimize,            # torch.compile 预热
        device=device,
        local_files_only=True,        # 权重已在本地，不走网络
    )
    print(f"[load] {time.time() - t0:.1f}s  device={device}  optimize={optimize}", flush=True)
    return model


def write_wav(path: Path, wav: np.ndarray, sr: int) -> None:
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    peak = float(np.max(np.abs(wav))) if wav.size else 1.0
    if peak > 0.99:                    # 只做峰值保护，不动整体响度
        wav = wav * (0.99 / peak)
    sf.write(str(path), wav.astype(np.float32), sr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default=str(DEFAULT_MODEL))
    ap.add_argument("--ref", required=True, help="参考音（音色来源）")
    ap.add_argument("--prompt-text", default=None,
                    help="配合 --prompt-wav 做 continuation 模式，需给出参考音的文字")
    ap.add_argument("--prompt-wav", default=None,
                    help="continuation 模式的音频（可同时给 --ref）")
    ap.add_argument("--text", default=None)
    ap.add_argument("--text-file", default=None)
    ap.add_argument("--out", default=None, help="多句时把结果顺序拼成一个文件")
    ap.add_argument("--out-dir", default=None, help="逐句输出目录")
    ap.add_argument("--gap-ms", type=int, default=150, help="拼接时间隙")
    ap.add_argument("--anchor-prev", action="store_true",
                    help="把上一句并进缓存当 continuation 锚（长文本音色更稳）")
    ap.add_argument("--cfg", type=float, default=1.5,
                    help="引导强度。实测 1.5–2.0 尾巴最短（回音最轻）；"
                         "调到 4.5 高频更多但衰减尾巴从 186ms 拉到 363ms，回音明显加重")
    ap.add_argument("--timesteps", type=int, default=10)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--no-optimize", action="store_true",
                    help="关掉 torch.compile（编译失败或调试时用）")
    ap.add_argument("--probe", action="store_true", default=True,
                    help="输出带宽体检（默认开）")
    args = ap.parse_args()

    lines = load_lines(args)
    if not args.out and not args.out_dir:
        args.out_dir = str(Path(args.ref).with_suffix("").parent / "voxcpm_out")

    model = build_model(Path(args.model_dir), args.device, not args.no_optimize)
    sr = int(model.tts_model.sample_rate)
    enc_sr = int(getattr(model.tts_model, "_encode_sample_rate", 0))
    print(f"[sr] encode={enc_sr}Hz  output={sr}Hz", flush=True)

    ref_p = Path(args.ref)
    if not ref_p.exists():
        raise SystemExit(f"参考音不存在：{ref_p}")

    out_dir = Path(args.out_dir) if args.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    # ---- 音色锚定缓存 ----
    # 参考音只编码一次（build_prompt_cache），所有句子复用。多句时可用
    # merge_prompt_cache 把上一句并进缓存当 continuation 锚，让下一句接着
    # 上一句的气口/音色走 —— 这是官方给长文本稳定音色准备的机制。
    base_cache = model.tts_model.build_prompt_cache(
        prompt_text=args.prompt_text if args.prompt_wav else None,
        prompt_wav_path=args.prompt_wav,
        reference_wav_path=str(ref_p),
    )
    anchor_cache = base_cache if args.anchor_prev else None
    print(f"[cache] mode={base_cache.get('mode')}  ref锚定已编码，多句复用", flush=True)

    from voxcpm.model.utils import next_and_close  # 局部导入，避免公开 API 依赖

    clips: list[np.ndarray] = []
    for i, text in enumerate(lines, 1):
        t0 = time.time()
        cache = anchor_cache if anchor_cache is not None else base_cache
        gen = model.tts_model._generate_with_prompt_cache(
            target_text=text,
            prompt_cache=cache,
            inference_timesteps=args.timesteps,
            cfg_value=args.cfg,
            seed=args.seed,
        )
        wav_t, _, feat = next_and_close(gen)
        wav = wav_t.squeeze(0).cpu().numpy().astype(np.float32)

        if args.anchor_prev:
            # 只带上一句做锚，不让缓存无限膨胀
            anchor_cache = model.tts_model.merge_prompt_cache(base_cache, text, feat)

        dur = len(wav) / sr
        dt = time.time() - t0
        print(f"[{i}/{len(lines)}] {dur:.2f}s 音频 / {dt:.2f}s 耗时 "
              f"(RTF={dt / max(dur, 1e-6):.2f})  {text[:28]}", flush=True)

        if out_dir:
            write_wav(out_dir / f"{i:04d}.wav", wav, sr)
        clips.append(wav)

    if args.out and clips:
        gap = np.zeros(int(sr * args.gap_ms / 1000), dtype=np.float32)
        joined = np.concatenate(
            [np.concatenate([c, gap]) for c in clips[:-1]] + [clips[-1]]
        )
        write_wav(Path(args.out), joined, sr)
        print(f"[out] {args.out}  {len(joined) / sr:.2f}s", flush=True)

    if args.probe:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from check_audio_bandwidth import probe

            targets = [str(ref_p)]
            if args.out:
                targets.append(args.out)
            elif out_dir and clips:
                targets.append(str(out_dir / "0001.wav"))
            print("\n文件                            4-6k     6-8k    99%带宽", flush=True)
            for t in targets:
                r = probe(t)
                print(f"{Path(t).name:32s} {r['mid_hi']:6.2f}%  {r['high']:6.2f}%  "
                      f"{r['bw99']:6.0f}Hz", flush=True)
        except Exception as e:  # noqa: BLE001 - 体检失败不该中断主流程
            print(f"[probe] 跳过：{e}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
