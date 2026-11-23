#!/usr/bin/env python3
"""用 faster-whisper large-v3 重转训练切片（r150）。

为什么要重转：原来的 2003 条转写是 whisper **small** 产出的，实测有明显问题——
2003 条里只有 5 条带标点、164 条是繁体、且有同音错字（皮裤胡同→皮褲胡痛、出殡→出病）。

哪些错必须修、哪些可以将就（这条判断很重要，决定了要不要花时间重转）：
    - **繁体 → 必须修**。VoxCPM2 的 tokenizer 里繁简是不同 token，训练用繁体、
      推理用简体 = 教模型两套映射，必然劣化。
    - **漏字/多字 → 必须修**。会让模型学成「压缩发音」，比错字危害大。
    - **同音错字（出殡/出病）→ 几乎无害**。读音一样，TTS 学的是音，不是语义。
所以重转的收益主要来自前两项，而 large-v3 的准确率 + 标点预测正好覆盖。

关键技术点：
    - `initial_prompt` 用简体中文：whisper 中文默认常吐繁体，这是社区标准做法。
    - `condition_on_previous_text=False`：切片之间没有上下文，开着会让上一片污染下一片。
    - `vad_filter=True`：切片本身已裁过，但 VAD 能去掉残留的呼吸声，减少幻觉。
    - `--batched`：走 BatchedInferencePipeline，吞吐显著提升（长音频尤其明显）。

用法：
    python scripts/tts/retranscribe_fw.py \\
        --slices D:/work_space/_tts/dataset/slices \\
        --model  D:/work_space/_tts/models/faster-whisper-large-v3 \\
        --out    D:/work_space/_tts/dataset/list_largev3.txt \\
        --compare D:/work_space/_tts/dataset/list_all.txt
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROMPT = '以下是普通话的句子，使用简体中文，带标点。'


def similarity(a: str, b: str) -> float:
    """粗略字符级相似度（不算真正的编辑距离，够用来发现严重不一致）。"""
    import difflib

    return difflib.SequenceMatcher(None, a, b).ratio()


def main() -> int:
    ap = argparse.ArgumentParser(description='faster-whisper 重转训练切片')
    ap.add_argument('--slices', required=True)
    ap.add_argument('--model', required=True, help='CTranslate2 模型目录')
    ap.add_argument('--out', required=True, help='输出 `路径|spk|lang|文本`')
    ap.add_argument('--speaker', default='gdg')
    ap.add_argument('--lang', default='zh')
    ap.add_argument('--device', default='cuda')
    ap.add_argument('--compute-type', default='float16',
                    help='cuda 用 float16；显存不够用 int8_float16；CPU 用 int8')
    ap.add_argument('--batch-size', type=int, default=8)
    ap.add_argument('--no-batched', dest='batched', action='store_false')
    ap.add_argument('--pattern', default='*.wav')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--compare', default=None, help='旧转写，用于输出差异统计')
    args = ap.parse_args()

    from faster_whisper import WhisperModel

    files = sorted(Path(args.slices).glob(args.pattern))
    if args.limit:
        files = files[: args.limit]
    if not files:
        sys.exit(f'{args.slices} 下没有匹配 {args.pattern} 的文件')

    print(f'加载 {args.model} @ {args.device}/{args.compute_type} …', flush=True)
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)

    runner = model
    if args.batched:
        try:
            from faster_whisper import BatchedInferencePipeline

            runner = BatchedInferencePipeline(model=model)
            print(f'使用 BatchedInferencePipeline (batch={args.batch_size})', flush=True)
        except Exception as e:  # noqa: BLE001 - 老版本没有批处理就退回单条
            print(f'批处理不可用（{e}），退回单条', flush=True)

    old = {}
    if args.compare:
        for line in Path(args.compare).read_text(encoding='utf-8').splitlines():
            p = line.split('|')
            if len(p) >= 4:
                old[Path(p[0]).name] = p[3]

    results: list[tuple[str, str]] = []
    t0 = time.time()
    total_dur = 0.0
    for i, f in enumerate(files, 1):
        kw = dict(language=args.lang, initial_prompt=PROMPT,
                  beam_size=5, condition_on_previous_text=False, vad_filter=True)
        if args.batched:
            segs, info = runner.transcribe(str(f), batch_size=args.batch_size, **kw)
        else:
            segs, info = runner.transcribe(str(f), **kw)
        text = ''.join(s.text for s in segs).strip()
        total_dur += getattr(info, 'duration', 0.0) or 0.0
        results.append((str(f), text))
        if i % 100 == 0 or i == len(files):
            el = time.time() - t0
            rtf = total_dur / el if el > 0 else 0
            print(f'  {i}/{len(files)}  {el:.0f}s  音频 {total_dur/60:.1f} 分钟  '
                  f'加速比 {rtf:.1f}x', flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', encoding='utf-8') as fh:
        for path, text in results:
            fh.write(f'{path}|{args.speaker}|{args.lang}|{text}\n')
    print(f'\n写出 {out}  ({len(results)} 条)')

    if old:
        sims, changed, new_empty = [], 0, 0
        for path, text in results:
            name = Path(path).name
            if name not in old:
                continue
            prev = old[name]
            if not text:
                new_empty += 1
                continue
            s = similarity(prev, text)
            sims.append(s)
            if s < 0.9:
                changed += 1
        if sims:
            import statistics

            print(f'与旧转写对比：均值相似度 {statistics.mean(sims):.3f} · '
                  f'中位 {statistics.median(sims):.3f} · '
                  f'差异>10% 的 {changed} 条 · 新转写为空 {new_empty} 条')
            print('样例（差异最大的 3 条）：')
            pairs = sorted(
                ((similarity(old[Path(p).name], t), Path(p).name, old[Path(p).name], t)
                 for p, t in results if Path(p).name in old and t),
                key=lambda x: x[0],
            )[:3]
            for s, name, prev, now in pairs:
                print(f'  [{s:.2f}] {name}')
                print(f'     旧: {prev}')
                print(f'     新: {now}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
