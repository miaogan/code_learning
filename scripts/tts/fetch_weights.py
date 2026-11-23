#!/usr/bin/env python3
"""从 ModelScope 拉权重（支持分块并行 + 断点续传）。

为什么需要这个脚本：HuggingFace 在这台机器上要么被代理挡（502），要么走
hf-mirror 只有 0.2–0.8 MB/s（4.4GB 要 6 小时）。ModelScope（魔搭）同一个仓库
实测 12 MB/s，快 50 倍。**这是本次踩坑最有价值的一条**：OpenBMB / 阿里 / 智谱
这类国内团队的模型，优先去 ModelScope 拿。

特性：
    - 分块并行（默认 8 块），每块独立重试，单块失败不影响其他块
    - 断点续传：已有的 .part 文件按块进度继续，不重下
    - 按字节校验最终大小，不匹配则报错退出

用法：
    python scripts/tts/fetch_weights.py \\
        --repo OpenBMB/VoxCPM2 \\
        --out D:/work_space/_tts/VoxCPM/pretrained_models \\
        --files model.safetensors tokenizer.json tokenization_voxcpm2.py \\
                tokenizer_config.json special_tokens_map.json

    # 只下载大文件、调并行数
    python scripts/tts/fetch_weights.py --repo X/Y --out dir --workers 16
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path

import httpx

MS_FILE_URL = "https://modelscope.cn/api/v1/models/{repo}/repo?Revision={rev}&FilePath={f}"
MS_LIST_URL = "https://modelscope.cn/api/v1/models/{repo}/repo/files?Revision={rev}&Root="
CHUNK = 4 * 1024 * 1024          # 每块 4MB，太小则请求数暴涨


def list_files(repo: str, rev: str) -> dict[str, dict]:
    r = httpx.get(MS_LIST_URL.format(repo=repo, rev=rev), timeout=30, follow_redirects=True)
    r.raise_for_status()
    out = {}
    for f in r.json().get("Data", {}).get("Files", []):
        name = f.get("Name")
        if name:
            out[name] = {"size": int(f.get("Size") or 0),
                         "sha256": (f.get("Sha256") or "").lower() or None}
    return out


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(path: Path, want_sha: str | None) -> None:
    """有期望哈希就强校验；没有则至少确认大小已在上层核对过。"""
    if not want_sha:
        print(f"    （无哈希可比对，仅按大小校验）", flush=True)
        return
    got = sha256_of(path)
    if got != want_sha:
        raise RuntimeError(f"sha256 不匹配\n     期望 {want_sha}\n     实际 {got}")
    print(f"    sha256 OK", flush=True)


def write_all(fh, data, offset: int) -> None:
    """把 data 完整写到文件对象的 offset 处。

    两个坑都在这里：
    1. **不要用 os.open/os.write**：Windows 上 os.open 缺 O_BINARY 时 fd 是文本模式，
       os.write 会把 \\n 翻成 \\r\\n，把 4MB 二进制块整块错位——文件大小对、开头魔数对，
       但内容全坏（本次踩坑：torch 轮子报 "Wheel is invalid"、权重 sha256 对不上）。
       普通文件对象 'r+b' 天然二进制，没有这个问题。
    2. **写要循环**：文件对象的 write 也可能只写一部分，不循环会留空洞。
    """
    fh.seek(offset)
    view = memoryview(data)
    written = 0
    while written < len(view):
        n = fh.write(view[written:])
        if n <= 0:
            raise IOError(f"写入停滞于 {offset + written}")
        written += n
    fh.flush()


def download_range(url: str, start: int, end: int, buf: bytearray, off: int,
                   retries: int = 5) -> None:
    """下载 [start, end] 闭区间，写入 buf 的 off 位置。"""
    last = None
    for attempt in range(1, retries + 1):
        try:
            with httpx.Client(timeout=httpx.Timeout(60.0, connect=20.0),
                              follow_redirects=True) as c:
                with c.stream("GET", url, headers={"Range": f"bytes={start}-{end}"}) as r:
                    r.raise_for_status()
                    pos = off
                    for piece in r.iter_bytes(262144):
                        buf[pos:pos + len(piece)] = piece
                        pos += len(piece)
                    if pos - off != end - start + 1:
                        raise IOError(f"短读 {pos - off}/{end - start + 1}")
                    return
        except Exception as e:  # noqa: BLE001 - 网络错误统一重试
            last = e
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"块 {start}-{end} 失败: {last}")


def fetch_file(repo: str, rev: str, name: str, out_dir: Path, meta: dict,
               workers: int) -> Path:
    size = int(meta["size"])
    want = meta.get("sha256")
    dst = out_dir / name
    if dst.exists() and dst.stat().st_size == size:
        try:
            verify(dst, want)
            print(f"  跳过（已完整）: {name}  {size / 1048576:.1f} MB", flush=True)
            return dst
        except Exception as e:  # noqa: BLE001 - 校验不过就重下
            print(f"  已有文件校验失败，重下: {name} ({e})", flush=True)

    url = MS_FILE_URL.format(repo=repo, rev=rev, f=name)
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_suffix(dst.suffix + ".part")

    # 小文件直接一把梭，不走分块
    if size <= CHUNK * 2:
        t0 = time.time()
        with httpx.Client(timeout=120, follow_redirects=True) as c:
            data = c.get(url).content
        if len(data) != size:
            raise RuntimeError(f"{name} 大小不符 {len(data)} != {size}")
        dst.write_bytes(data)
        print(f"  {name}  {size / 1048576:.2f} MB  {time.time() - t0:.1f}s", flush=True)
        verify(dst, want)
        return dst

    # 大文件：按块并行。part 文件预分配，块进度记在 .part.idx
    idx_path = dst.with_suffix(dst.suffix + ".part.idx")
    done: set[int] = set()
    if part.exists() and idx_path.exists() and part.stat().st_size == size:
        try:
            done = set(json.loads(idx_path.read_text()))
        except Exception:  # noqa: BLE001
            done = set()

    offsets = list(range(0, size, CHUNK))
    nblocks = len(offsets)
    if not (part.exists() and part.stat().st_size == size):
        done = set()
        with open(part, "wb") as f:
            f.truncate(size)

    todo = [i for i in range(nblocks) if i not in done]
    print(f"  {name}  {size / 1048576:.1f} MB  共 {nblocks} 块，待下 {len(todo)} 块，"
          f"{workers} 并发", flush=True)
    if not todo:
        os.replace(part, dst)
        idx_path.unlink(missing_ok=True)
        return dst

    # 分块用 pwrite 写入同一文件句柄，避免整块进内存
    fh = open(part, "r+b")  # 二进制模式，别用 os.open
    buf = bytearray(CHUNK)
    lock = threading.Lock()
    finished = [0]
    t0 = time.time()

    def run(block: int) -> None:
        start = offsets[block]
        end = min(start + CHUNK, size) - 1
        local = bytearray(end - start + 1)
        download_range(url, start, end, local, 0)
        with lock:
            write_all(fh, local, start)
            finished[0] += 1
            el = time.time() - t0
            got = sum(min(CHUNK, size - offsets[i]) for i in range(nblocks)
                      if i in done or i == block)
            if finished[0] % 40 == 0 or finished[0] == len(todo):
                rate = got / 1048576 / max(el, 1e-6)
                print(f"    {finished[0]}/{len(todo)} 块  {got / 1048576:.0f} MB  "
                      f"{rate:.1f} MB/s", flush=True)
            done.add(block)
            idx_path.write_text(json.dumps(sorted(done)))

    threads: list[threading.Thread] = []
    pending = list(todo)
    while pending or threads:
        while pending and len(threads) < workers:
            b = pending.pop(0)
            th = threading.Thread(target=run, args=(b,), daemon=True)
            th.start()
            threads.append(th)
        threads = [t for t in threads if t.is_alive()]
        time.sleep(0.05)

    fh.close()
    actual = part.stat().st_size
    if actual > size:                 # 预分配后被别的句柄追加过，截掉尾部
        os.truncate(part, size)
        actual = size
    if actual != size:
        raise RuntimeError(f"{name} 最终大小不符 {actual} != {size}")
    verify(part, want)
    os.replace(part, dst)
    idx_path.unlink(missing_ok=True)
    print(f"  完成 {name}  {time.time() - t0:.0f}s", flush=True)
    return dst


def fetch_url(url: str, dst: Path, size: int, workers: int,
              want_sha: str | None = None) -> Path:
    """通用并行分块下载（不依赖 ModelScope API）。

    dst.part 预分配为 size，块进度记在 dst.part.idx，可断点续传。
    """
    if dst.exists() and dst.stat().st_size == size:
        try:
            verify(dst, want_sha)
            print(f"  跳过（已完整）: {dst.name}  {size / 1048576:.1f} MB", flush=True)
            return dst
        except Exception as e:  # noqa: BLE001 - 校验不过就重下
            print(f"  已有文件校验失败，重下: {dst.name} ({e})", flush=True)

    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_suffix(dst.suffix + ".part")
    idx_path = dst.with_suffix(dst.suffix + ".part.idx")

    offsets = list(range(0, size, CHUNK))
    nblocks = len(offsets)
    done: set[int] = set()
    intact = part.exists() and part.stat().st_size == size
    if intact and idx_path.exists():
        try:
            done = set(json.loads(idx_path.read_text()))
        except Exception:  # noqa: BLE001
            done = set()
    if not intact:
        done = set()
        with open(part, "wb") as f:
            f.truncate(size)
    # 丢掉越界的脏记录（防止 size 改变后误判）
    done = {i for i in done if 0 <= i < nblocks}

    todo = [i for i in range(nblocks) if i not in done]
    print(f"  {dst.name}  {size / 1048576:.1f} MB  共 {nblocks} 块，"
          f"待下 {len(todo)} 块，{workers} 并发", flush=True)
    if not todo:
        if part.stat().st_size > size:
            os.truncate(part, size)
        verify(part, want_sha)
        os.replace(part, dst)
        idx_path.unlink(missing_ok=True)
        return dst

    fh = open(part, "r+b")  # 二进制模式，别用 os.open
    lock = threading.Lock()
    finished = [0]
    t0 = time.time()

    def run(block: int) -> None:
        start = offsets[block]
        end = min(start + CHUNK, size) - 1
        local = bytearray(end - start + 1)
        download_range(url, start, end, local, 0)
        with lock:
            write_all(fh, local, start)
            finished[0] += 1
            got = sum(min(CHUNK, size - offsets[i]) for i in range(nblocks)
                      if i in done or i == block)
            if finished[0] % 40 == 0 or finished[0] == len(todo):
                el = time.time() - t0
                print(f"    {finished[0]}/{len(todo)} 块  {got / 1048576:.0f} MB  "
                      f"{got / 1048576 / max(el, 1e-6):.1f} MB/s", flush=True)
            done.add(block)
            idx_path.write_text(json.dumps(sorted(done)))

    threads: list[threading.Thread] = []
    pending = list(todo)
    while pending or threads:
        while pending and len(threads) < workers:
            b = pending.pop(0)
            th = threading.Thread(target=run, args=(b,), daemon=True)
            th.start()
            threads.append(th)
        threads = [t for t in threads if t.is_alive()]
        time.sleep(0.05)

    fh.close()
    actual = part.stat().st_size
    if actual > size:                 # 预分配后被别的句柄追加过，截掉尾部
        os.truncate(part, size)
        actual = size
    if actual != size:
        raise RuntimeError(f"{dst.name} 最终大小不符 {actual} != {size}")
    verify(part, want_sha)
    os.replace(part, dst)
    idx_path.unlink(missing_ok=True)
    print(f"  完成 {dst.name}  {time.time() - t0:.0f}s", flush=True)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None, help="如 OpenBMB/VoxCPM2")
    ap.add_argument("--rev", default="master")
    ap.add_argument("--out", required=True, help="输出目录（--url 模式则为输出文件路径）")
    ap.add_argument("--files", nargs="*", default=None, help="留空=全部")
    ap.add_argument("--url", default=None, help="直接给 URL（跳过 ModelScope API）")
    ap.add_argument("--size", type=int, default=0, help="--url 模式下的字节数")
    ap.add_argument("--sha256", default=None, help="--url 模式下的期望 sha256")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    if args.url:
        dst = Path(args.out)
        size = args.size
        if not size:
            r = httpx.head(args.url, timeout=30, follow_redirects=True)
            size = int(r.headers["content-length"])
        return 0 if fetch_url(args.url, dst, size, args.workers, args.sha256) else 1

    if not args.repo:
        raise SystemExit("需要 --repo 或 --url")

    out_dir = Path(args.out)
    remote = list_files(args.repo, args.rev)
    if not remote:
        raise SystemExit(f"仓库列表为空：{args.repo}")

    targets = args.files or list(remote)
    missing = [t for t in targets if t not in remote]
    if missing:
        raise SystemExit(f"仓库里没有这些文件：{missing}\n可用：{list(remote)}")

    print(f"目标目录 {out_dir}", flush=True)
    for name in targets:
        try:
            fetch_file(args.repo, args.rev, name, out_dir, remote[name], args.workers)
        except Exception as e:  # noqa: BLE001 - 单文件失败不阻断其余
            print(f"  !! {name} 失败: {e}", file=sys.stderr, flush=True)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
