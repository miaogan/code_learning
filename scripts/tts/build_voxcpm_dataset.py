#!/usr/bin/env python3
"""把切片 + 转写整理成 VoxCPM2 微调用的 manifest（r150）。

为什么需要单独一步：VoxCPM2 的训练脚本要求
    1. 音频采样率**必须等于** `sample_rate`（16000，即 AudioVAE 编码器输入）
    2. manifest 是 JSONL，每行 `{"text":..., "audio":..., "ref_audio":...}`
    ——而我们的切片是 **32000Hz**（GPT-SoVITS 时代产的），直接喂会被 validate 全部判错。

除了格式，这里做的都是**质量闸**，因为「垃圾进 = 垃圾出」在音色克隆上尤其明显：

    - `繁→简`：VoxCPM2 的 tokenizer 里繁简是不同 token。训练用繁体、推理用简体，
      等于教模型两套映射，必然劣化。原转写里 164 条繁体（whisper 中文老毛病）。
    - `字数/时长比`：这是**最便宜的对齐质检**。正常中文口播 3–5 字/秒；
      比值 <2 说明文本漏了一大段，>7 说明多写了字。这类错配比错别字危害大得多
      ——错别字多是同音字（如 出殡→出病），读音一样，对 TTS 几乎无害；
      但漏字会让模型学成「压缩发音」。
    - `时长/文本长度`上下限：太短的切片学不到韵律，太长的显存吃紧且对齐易错。

用法：
    python scripts/tts/build_voxcpm_dataset.py \\
        --list D:/work_space/_tts/dataset/list_all.txt \\
        --out  D:/work_space/_tts/voxcpm_ds \\
        --ref  D:/work_space/_tts/dataset/slices/ep3-0386.wav
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

TARGET_SR = 16000          # AudioVAE 编码器输入
MIN_DUR, MAX_DUR = 2.5, 12.0
MIN_CHARS = 4
CPS_MIN, CPS_MAX = 2.0, 7.5     # 字/秒，对齐质检
KEEP_PEAK = 0.97


def load_rows(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split('|')
        if len(parts) < 4:
            continue
        rows.append({'audio': parts[0], 'speaker': parts[1], 'text': parts[3]})
    return rows


def clean_text(text: str, t2s=None) -> str:
    """繁转简 + 标点归一 + 空白归一。

    标点为什么要归一：faster-whisper 输出中文时用的是**半角** `,` `?`
    （实测 1093 条带标点里绝大多数是半角），而我们的推理剧本用全角 `，`。
    训练和推理的标点 token 不一致会让模型学到两种节奏线索，所以统一成全角。
    """
    import re

    if t2s is not None:
        text = t2s.convert(text)
    text = text.replace('\u3000', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    # 去掉 whisper 偶尔加的非语言标记与括号注释
    text = re.sub(r'[\(（\[【][^\)）\]】]*[\)）\]】]', '', text)
    text = re.sub(r'[\*#_`~]+', '', text)
    # 半角 → 全角（只在中文字符旁转换，避免动到数字/英文里的符号）
    zh = r'[\u4e00-\u9fff]'
    pairs = [(',', '，'), ('?', '？'), ('!', '！'), (':', '：'), (';', '；')]
    for half, full in pairs:
        h = re.escape(half)
        text = re.sub(rf'(?<={zh}){h}|{h}(?={zh})', full, text)
    text = re.sub(r'\.{2,}', '。', text)
    text = re.sub(r'(?<=[\u4e00-\u9fff])\.(?!\d)', '。', text)
    return text.strip()


def read_audio_16k(path: Path) -> tuple[np.ndarray, int]:
    import librosa

    y, sr = librosa.load(str(path), sr=None, mono=True)
    if sr != TARGET_SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=TARGET_SR)
    return y.astype(np.float32), TARGET_SR


def main() -> int:
    ap = argparse.ArgumentParser(description='构建 VoxCPM2 微调数据集')
    ap.add_argument('--list', required=True, help='`路径|说话人|语言|文本` 的清单')
    ap.add_argument('--out', required=True, help='输出目录')
    ap.add_argument('--ref', required=True, help='ref_audio：同一说话人的干净参考音')
    ap.add_argument('--val-ratio', type=float, default=0.05)
    ap.add_argument('--min-dur', type=float, default=MIN_DUR)
    ap.add_argument('--max-dur', type=float, default=MAX_DUR)
    ap.add_argument('--min-chars', type=int, default=MIN_CHARS)
    ap.add_argument('--cps-min', type=float, default=CPS_MIN)
    ap.add_argument('--cps-max', type=float, default=CPS_MAX)
    ap.add_argument('--seed', type=int, default=0)
    args = ap.parse_args()

    out = Path(args.out)
    wav_dir = out / 'wav16k'
    wav_dir.mkdir(parents=True, exist_ok=True)

    try:
        import opencc

        t2s = opencc.OpenCC('t2s')
    except Exception:
        print('警告：opencc 不可用，跳过繁转简（会显著劣化训练）', file=sys.stderr)
        t2s = None

    import soundfile as sf

    rows = load_rows(Path(args.list))
    if not rows:
        sys.exit(f'{args.list} 里没解析出任何条目')

    ref = Path(args.ref)
    if not ref.exists():
        sys.exit(f'ref_audio 不存在：{ref}')
    # 参考音也统一到 16k，保证与训练音频同域
    ref_y, _ = read_audio_16k(ref)
    ref_out = out / 'ref_16k.wav'
    sf.write(str(ref_out), ref_y, TARGET_SR)
    print(f'ref_audio -> {ref_out}  {len(ref_y) / TARGET_SR:.2f}s')

    kept: list[dict] = []
    drop = Counter()
    for row in rows:
        src = Path(row['audio'])
        if not src.exists():
            drop['文件不存在'] += 1
            continue
        text = clean_text(row['text'], t2s)
        if len(text) < args.min_chars:
            drop[f'文本<{args.min_chars}字'] += 1
            continue
        try:
            y, sr = read_audio_16k(src)
        except Exception:
            drop['读音频失败'] += 1
            continue
        dur = len(y) / sr
        if not (args.min_dur <= dur <= args.max_dur):
            drop['时长越界'] += 1
            continue
        cps = len(text) / dur
        if not (args.cps_min <= cps <= args.cps_max):
            drop['字数/时长比异常'] += 1
            continue
        peak = float(np.max(np.abs(y))) if y.size else 0.0
        if peak < 0.01:
            drop['近乎静音'] += 1
            continue
        if peak > KEEP_PEAK:
            y = y * (KEEP_PEAK / peak)

        dst = wav_dir / (src.stem + '.wav')
        sf.write(str(dst), y, sr)
        kept.append({'text': text, 'audio': str(dst), 'ref_audio': str(ref_out),
                     'duration': round(dur, 2), 'cps': round(cps, 2)})

    if not kept:
        sys.exit('全部条目被过滤掉了，检查阈值。')

    random.Random(args.seed).shuffle(kept)
    n_val = max(1, int(len(kept) * args.val_ratio)) if args.val_ratio > 0 else 0
    val = kept[:n_val]
    train = kept[n_val:]

    def dump(path: Path, items: list[dict]) -> None:
        with path.open('w', encoding='utf-8') as f:
            for it in items:
                f.write(json.dumps({'text': it['text'], 'audio': it['audio'],
                                    'ref_audio': it['ref_audio']}, ensure_ascii=False) + '\n')

    dump(out / 'train.jsonl', train)
    if val:
        dump(out / 'val.jsonl', val)
    (out / 'stats.json').write_text(
        json.dumps({'total': len(rows), 'kept': len(kept), 'train': len(train),
                    'val': len(val), 'dropped': dict(drop),
                    'total_minutes': round(sum(it['duration'] for it in kept) / 60, 1)},
                   ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    print(f'\n保留 {len(kept)}/{len(rows)} 条 · 共 {sum(it["duration"] for it in kept)/60:.1f} 分钟')
    print(f'  train {len(train)} · val {len(val)}')
    if drop:
        print('  丢弃原因:', '、'.join(f'{k} {v}' for k, v in drop.most_common()))
    print(f'清单: {out / "train.jsonl"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
