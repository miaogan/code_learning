#!/usr/bin/env python3
"""用 jsDelivr 逐文件重建 GitHub 仓库（绕过单连接下载限制）。

背景：本机网络对 GitHub 大文件有约 6–7MB 的硬限制（git clone / curl / urllib 全部
在同一个位置断开），但 jsDelivr 的 CDN 与 metadata API 是通的。

做法：从 `data.jsdelivr.com` 拿完整文件树，再从 `cdn.jsdelivr.net` 逐个下载，
跳过图片等无关资源。单个文件都远小于限制，因此不会被截断。

用法：
    python scripts/tts/fetch_repo_via_jsdelivr.py --repo index-tts/index-tts --out D:/work_space/_tts/IndexTTS
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

SKIP_DIRS = {'assets', '.github', 'examples', 'figures', 'docs/images'}
SKIP_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.mp4', '.webp', '.DS_Store'}


def walk(nodes: list[dict], prefix: str = ''):
    for node in nodes:
        name = node.get('name', '')
        path = f'{prefix}/{name}' if prefix else name
        if node.get('type') == 'directory':
            if name in SKIP_DIRS:
                continue
            yield from walk(node.get('files', []), path)
        else:
            yield path, node.get('size', 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', required=True, help='user/repo')
    ap.add_argument('--ref', default='main')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    api = f'https://data.jsdelivr.com/v1/packages/gh/{args.repo}@{args.ref}'
    with urllib.request.urlopen(api, timeout=60) as resp:
        tree = json.load(resp)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    targets = [(p, s) for p, s in walk(tree.get('files', []))
               if Path(p).suffix.lower() not in SKIP_EXT and not p.endswith('.DS_Store')]
    print(f'共 {len(targets)} 个文件待下载（已跳过图片/示例）', flush=True)

    ok = 0
    fail = 0
    for index, (path, size) in enumerate(targets, 1):
        dst = out / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and dst.stat().st_size == size:
            ok += 1
            continue
        url = f'https://cdn.jsdelivr.net/gh/{args.repo}@{args.ref}/{path}'
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=45) as resp:
                    dst.write_bytes(resp.read())
                ok += 1
                break
            except Exception as exc:
                if attempt == 2:
                    fail += 1
                    print(f'  [失败] {path}: {type(exc).__name__}', flush=True)
                else:
                    time.sleep(1.5)
        if index % 20 == 0:
            print(f'  {index}/{len(targets)}', flush=True)

    print(f'\n完成 {ok}，失败 {fail} → {out}')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
