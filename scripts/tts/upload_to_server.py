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


def _scp(src: Path, remote_name: str) -> None:
    # 复用 SSH_BASE[1:]（-i key + 三组 -o 选项），ssh 与 scp 的认证参数一致
    scp = ['scp', *SSH_BASE[1:], '-r', str(src), f'{HOST}:{REMOTE_DIR}/{remote_name}']
    subprocess.run(scp, check=True, timeout=600)


def upload_tick(audio_src: Path) -> None:
    manifests = sorted(audio_src.glob('*/manifest.json'))
    if not manifests:
        print('[upload] 本地还没有完整章（等 manifest 落盘）')
        return

    remote = _remote_chapters()
    new = [m.parent for m in manifests if m.parent.name not in remote]
    for chapter_dir in new:
        size_mb = sum(f.stat().st_size for f in chapter_dir.rglob('*') if f.is_file()) / 1e6
        print(f'[upload] 上传 {chapter_dir.name}（{size_mb:.0f} MB）…', flush=True)
        _scp(chapter_dir, chapter_dir.name)
        print(f'[upload] {chapter_dir.name} 完成')

    # index.json：每轮重建（新章点亮前端入口）并同步
    sys.path.insert(0, str(HERE))
    from make_audio import build_index
    build_index(audio_src)
    index_path = audio_src / 'index.json'
    if index_path.exists():
        _scp(index_path, 'index.json')
        print(f'[upload] index.json 已同步（{len(manifests)} 章）')


def main() -> int:
    ap = argparse.ArgumentParser(description='按章增量上传音频到服务器')
    ap.add_argument('--audio-src', default='scripts/tts/out/audio_release')
    ap.add_argument('--interval', type=int, default=600, help='轮询秒（0 = 单轮）')
    ap.add_argument('--max-iterations', type=int, default=0, help='最多轮数（0 = 不限）')
    args = ap.parse_args()

    audio_src = Path(args.audio_src)
    audio_src.mkdir(parents=True, exist_ok=True)
    interval = max(0, args.interval)
    rounds = args.max_iterations if args.max_iterations > 0 else 10 ** 9
    for round_no in range(1, rounds + 1):
        print(f'\n===== upload 第 {round_no} 轮（{time.strftime("%H:%M:%S")}） =====', flush=True)
        try:
            upload_tick(audio_src)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f'[upload] 本轮异常（{exc!r}），继续下一轮', file=sys.stderr)
        if interval == 0:
            break
        time.sleep(interval)
    return 0


if __name__ == '__main__':
    sys.exit(main())
