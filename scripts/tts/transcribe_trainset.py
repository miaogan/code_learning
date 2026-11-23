#!/usr/bin/env python3
"""训练集转写：切片 → GPT-SoVITS 的 list.txt（`路径|说话人|语言|文本`）。

为什么要单独一步：GPT-SoVITS 的训练依赖「音频 + 逐字文本」对齐，
文本错了会训成「读错字」的音色。所以转写质量直接决定成品。

相声是口语化中文，whisper 对语气词（嗯/啊/这个）容易漏或加，属于可接受范围——
微调主要学音色与韵律，偶发错字的影响远小于零样本的音色漂移。

用法：
    python scripts/tts/transcribe_trainset.py --slices <目录> --out list.txt --speaker gdg
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description='批量转写训练切片')
    ap.add_argument('--slices', required=True, help='切片目录')
    ap.add_argument('--out', required=True, help='输出 list.txt')
    ap.add_argument('--speaker', default='spk', help='说话人标识（GPT-SoVITS 的 speaker 字段）')
    ap.add_argument('--model', default='small', help='whisper 模型（tiny/base/small/medium）')
    ap.add_argument('--device', default='cuda')
    ap.add_argument('--limit', type=int, default=0, help='只转前 N 片（调试用）')
    ap.add_argument('--pattern', default='*.wav', help='只转匹配的文件（如 ep[34]-*.wav）')
    args = ap.parse_args()

    import whisper

    files = sorted(Path(args.slices).glob(args.pattern))
    if args.limit:
        files = files[: args.limit]
    if not files:
        sys.exit(f'{args.slices} 下没有 wav')

    print(f'加载 whisper-{args.model} @ {args.device} …', flush=True)
    model = whisper.load_model(args.model, device=args.device)

    out_lines: list[str] = []
    empty = 0
    for index, path in enumerate(files, 1):
        try:
            result = model.transcribe(
                str(path),
                language='zh',
                fp16=args.device == 'cuda',
                condition_on_previous_text=False,
            )
        except Exception as exc:  # 单片失败不阻断整批
            print(f'  [跳过] {path.name}: {exc}', flush=True)
            continue
        text = (result.get('text') or '').strip()
        if not text:
            empty += 1
            continue
        out_lines.append(f'{path.as_posix()}|{args.speaker}|zh|{text}')
        if index % 50 == 0:
            print(f'  {index}/{len(files)}', flush=True)

    Path(args.out).write_text('\n'.join(out_lines) + '\n', encoding='utf-8')
    print(f'\n完成 {len(out_lines)} 条（空文本 {empty}）→ {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
