#!/usr/bin/env python3
"""检查合成音频里有没有把 instruct 念出来（r150 回归闸）。

踩过两次：
1. CV2：instruct 缺 `<|endofprompt|>` → 指令被念；
2. CV3：instruct 缺 `You are a helpful assistant. ` 前缀 → 同样被念。

判据：whisper 转写每节音频的**前 N 秒**，命中任何指令特征串就判失败。
它不判断"好不好听"，只保证"念的是稿子，不是指令"。

用法（whisper 在 llm-finetune-lab 的 venv 里）：
    D:/work_space/llm-finetune-lab/.venv/Scripts/python.exe scripts/tts/check_instruction_leak.py
    ... --audio-dir scripts/tts/out/ab2 --seconds 25 --strict
"""

from __future__ import annotations

import argparse
import glob
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 指令特征串：命中即说明 instruct 被当正文念了
LEAK_MARKERS = [
    '语气说这句话',
    '说这句话',
    'You are a helpful',
    'helpful assistant',
    '一本正经',
    '轻松随意',
    '冷淡平板',
    '抖包袱',
    '放慢收束',
    '先轻后重',
]


def main() -> int:
    parser = argparse.ArgumentParser(description='检查 instruct 是否被念出来')
    parser.add_argument('--audio-dir', default=str(HERE / 'out' / 'audio'))
    parser.add_argument('--seconds', type=int, default=25, help='每节只转写开头 N 秒')
    parser.add_argument('--strict', action='store_true', help='有泄漏即退出码 1')
    args = parser.parse_args()

    try:
        import whisper
    except Exception as exc:  # pragma: no cover
        sys.exit(f'需要 whisper（llm-finetune-lab 的 venv 里有）：{exc}')
    try:
        import soundfile as sf
    except Exception:  # pragma: no cover
        sf = None

    wavs = sorted(glob.glob(str(Path(args.audio_dir) / '*' / '*.wav')))
    if not wavs:
        sys.exit(f'{args.audio_dir} 下没有 wav')

    model = whisper.load_model('base')
    leaks: list[tuple[str, str]] = []
    for wav in wavs:
        target = wav
        if sf is not None:
            # 剪辑写到系统临时目录，别污染音频产物目录
            data, sr = sf.read(wav)
            clip = data[: sr * args.seconds]
            handle = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            handle.close()
            target = handle.name
            sf.write(target, clip, sr)
        result = model.transcribe(target, language='zh', fp16=False)
        text = result['text']
        hit = [marker for marker in LEAK_MARKERS if marker in text]
        if hit:
            leaks.append((wav, hit[0]))
            print(f'[LEAK] {Path(wav).name}: {hit[0]}')
        else:
            print(f'[ ok ] {Path(wav).name}')

    print()
    if leaks:
        print(f'{len(leaks)}/{len(wavs)} 节把指令念了出来——检查 instruct 前缀/后缀（见 README 踩坑节）')
        return 1 if args.strict else 0
    print(f'{len(wavs)} 节全部干净：开头是正文，不是指令')
    return 0


if __name__ == '__main__':
    sys.exit(main())
