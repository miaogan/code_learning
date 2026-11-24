#!/usr/bin/env python3
"""按章增量上传音频到生产服务器（r151）：合成一章 → 上传一章 → nginx 即时可见。

设计：
- 只上传「manifest.json 已落盘」的完整章（半成品章绝不出去）；
- 远端对比 `ls`，已存在的章跳过（幂等，重跑安全）；
- 每轮重建本地 index.json 并同步到服务器——前端「听听」入口随之逐章点亮；
- 与 synthesize/make_audio 完全解耦：合成在跑时随时可挂上这个循环。

用法：
    python scripts/tts/upload_to_server.py --interval 600   # 每 10 分钟一轮（常驻）
    python scripts/tts/upload_to_server.py --interval 0     # 单轮
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

SSH_BASE = [
    'ssh',
    '-i', str(ROOT / 'logs/teamflow/interview-ssh/id_ed25519_interview'),
    '-o', 'UserKnownHostsFile=' + str(ROOT / 'logs/teamflow/interview-ssh/known_hosts'),
    '-o', 'BatchMode=True',
    '-o', 'ConnectTimeout=15',
]
HOST = 'cyz@43.166.23.144'
REMOTE_DIR = 'skillcoach/audio'


def _remote_chapters() -> set[str]:
    result = subprocess.run([*SSH_BASE, HOST, f'ls {REMOTE_DIR}/'],
                            capture_output=True, text=True, check=True, timeout=30)
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _remote_has_m4a() -> set[str]:
    """远端已经有 m4a 的章（用来判断哪些章还需要补传压缩版）。"""
    result = _ssh(f'cd {REMOTE_DIR} && for d in */; do ls "$d"*.m4a >/dev/null 2>&1 '
                  '&& echo "${d%/}"; done')
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _ssh(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run([*SSH_BASE, HOST, cmd], capture_output=True, text=True,
                          check=False, timeout=60)


def upload_tick(audio_src: Path, bitrate: str) -> None:
    manifests = sorted(audio_src.glob('*/manifest.json'))
    if not manifests:
        print('[upload] 本地还没有完整章（等 manifest 落盘）')
        return

    # 先把本地新章转成 m4a（服务器 3M 带宽实测 ~196KB/s，wav 768kbps 会卡；
    # 64k AAC 体积 1/12，manifest 的 src 同步改写为 .m4a）
    sys.path.insert(0, str(HERE))
    from transcode_audio import transcode_chapter
    for manifest_path in manifests:
        made = transcode_chapter(manifest_path.parent, bitrate)
        if made:
            print(f'[upload] 转码 {manifest_path.parent.name}：{len(made)} 节 → m4a')

    remote = _remote_chapters()
    remote_m4a = _remote_has_m4a()
    todo = [m.parent for m in manifests
            if m.parent.name not in remote or m.parent.name not in remote_m4a]
    for chapter_dir in todo:
        files = sorted([*chapter_dir.glob('*.m4a'), *chapter_dir.glob('*.json')])
        if not files:
            continue
        size_mb = sum(f.stat().st_size for f in files) / 1e6
        print(f'[upload] 上传 {chapter_dir.name}（{len(files)} 个文件 / {size_mb:.1f} MB）…',
              flush=True)
        _ssh(f'mkdir -p {REMOTE_DIR}/{chapter_dir.name}')
        scp = ['scp', *SSH_BASE[1:], *[str(f) for f in files],
               f'{HOST}:{REMOTE_DIR}/{chapter_dir.name}/']
        subprocess.run(scp, check=True, timeout=600)
        # 清掉该章旧 wav（转 m4a 后不再需要，白占带宽与磁盘）
        _ssh(f'cd {REMOTE_DIR}/{chapter_dir.name} && rm -f *.wav; true')
        print(f'[upload] {chapter_dir.name} 完成')

    # index.json：每轮重建（新章点亮前端入口）并同步
    from make_audio import build_index
    build_index(audio_src)
    index_path = audio_src / 'index.json'
    if index_path.exists():
        scp_index = ['scp', *SSH_BASE[1:], str(index_path), f'{HOST}:{REMOTE_DIR}/index.json']
        subprocess.run(scp_index, check=True, timeout=120)
        print(f'[upload] index.json 已同步（{len(manifests)} 章）')


def main() -> int:
    ap = argparse.ArgumentParser(description='按章增量上传音频到服务器')
    ap.add_argument('--audio-src', default='scripts/tts/out/audio_release')
    ap.add_argument('--interval', type=int, default=600, help='轮询秒（0 = 单轮）')
    ap.add_argument('--max-iterations', type=int, default=0, help='最多轮数（0 = 不限）')
    ap.add_argument('--bitrate', default='64k', help='AAC 码率（口播 48–64k 够用）')
    args = ap.parse_args()

    audio_src = Path(args.audio_src)
    audio_src.mkdir(parents=True, exist_ok=True)
    interval = max(0, args.interval)
    rounds = args.max_iterations if args.max_iterations > 0 else 10 ** 9
    for round_no in range(1, rounds + 1):
        print(f'\n===== upload 第 {round_no} 轮（{time.strftime("%H:%M:%S")}） =====', flush=True)
        try:
            upload_tick(audio_src, args.bitrate)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f'[upload] 本轮异常（{exc!r}），继续下一轮', file=sys.stderr)
        if interval == 0:
            break
        time.sleep(interval)
    return 0


if __name__ == '__main__':
    sys.exit(main())
