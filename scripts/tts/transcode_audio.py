#!/usr/bin/env python3
"""音频转码：48kHz wav → AAC(m4a) 单声道 64kbps（r151，2026-11-24）。

为什么必须转（实测）：服务器 3M 带宽，跨境实测下载只有 ~196 KB/s；
而 wav 是 48kHz/16bit 单声道 = 768 kbps（96 KB/s），一个听众就吃掉半条线路，
页面资源 + 上传并发一叠就卡。口播类音频 64kbps AAC 听感几乎无损
（有声书行业标准 32–64kbps），体积压到 1/12：
    一章 4 节 33MB wav → ~2.7MB m4a

做了什么：
- 逐章逐节 ffmpeg 转码（跳过已是最新的 m4a）；
- **改写 manifest 的 track.src 扩展名为 .m4a**（播放器只读 manifest，时间轴/cue 不用动，
  时长不变——AAC 与源等长，durationMs 无需重算）；
- 默认保留本地 wav（质量母版，日后换码率可重转），只清理服务器上的旧 wav。

用法：
    python scripts/tts/transcode_audio.py --audio-src scripts/tts/out/audio_release
    python scripts/tts/transcode_audio.py --bitrate 48k --only ai-agent-memory
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _ffmpeg_ok() -> str:
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        sys.exit('找不到 ffmpeg（请安装并加入 PATH）')
    if result.returncode != 0:
        sys.exit('ffmpeg 不可用')
    return result.stdout.splitlines()[0].split()[2]


def transcode_chapter(chapter_dir: Path, bitrate: str) -> list[str]:
    """转一章：返回新生成的 m4a 文件名列表。"""
    manifest_path = chapter_dir / 'manifest.json'
    if not manifest_path.exists():
        return []
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    made: list[str] = []
    changed = False
    for track in manifest.get('tracks', []):
        src = str(track.get('src') or '')
        if not src.endswith('.wav'):
            continue
        wav_path = chapter_dir / Path(src).name
        m4a_path = wav_path.with_suffix('.m4a')
        if not wav_path.exists():
            continue
        if not m4a_path.exists() or m4a_path.stat().st_mtime < wav_path.stat().st_mtime:
            subprocess.run([
                'ffmpeg', '-y', '-loglevel', 'error',
                '-i', str(wav_path),
                '-c:a', 'aac', '-b:a', bitrate, '-ac', '1',
                '-movflags', '+faststart',   # moov 前置：边下边播/拖动都靠它
                str(m4a_path),
            ], check=True)
            made.append(m4a_path.name)
        new_src = src[: -len('.wav')] + '.m4a'
        if track.get('src') != new_src:
            track['src'] = new_src
            changed = True
    if changed:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
                                 encoding='utf-8')
    return made


def main() -> int:
    ap = argparse.ArgumentParser(description='wav → m4a(AAC) 转码并改写 manifest')
    ap.add_argument('--audio-src', default='scripts/tts/out/audio_release')
    ap.add_argument('--bitrate', default='64k')
    ap.add_argument('--only', default=None, help='只转指定章')
    args = ap.parse_args()

    audio_src = Path(args.audio_src)
    version = _ffmpeg_ok()
    print(f'ffmpeg {version} · 目标码率 {args.bitrate}')
    chapters = sorted(p.parent for p in audio_src.glob('*/manifest.json'))
    if args.only:
        chapters = [c for c in chapters if c.name == args.only]
    total_before = total_after = 0
    for chapter_dir in chapters:
        for wav in chapter_dir.glob('*.wav'):
            total_before += wav.stat().st_size
        made = transcode_chapter(chapter_dir, args.bitrate)
        for m4a in chapter_dir.glob('*.m4a'):
            total_after += m4a.stat().st_size
        if made:
            print(f'[{chapter_dir.name}] 转码 {len(made)} 节')
    if total_before:
        print(f'\n完成：wav {total_before / 1e6:.0f}MB → m4a {total_after / 1e6:.0f}MB'
              f'（压缩 {total_before / max(total_after, 1):.1f}×；本地 wav 保留为母版）')
    else:
        print('没有可转码的章（检查 --audio-src / manifest 是否存在 .wav 引用）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
