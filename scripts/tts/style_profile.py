#!/usr/bin/env python3
"""表演谱提取（r150）：把「相声的表演风格」量成可复现的统计量。

为什么需要它
------------
换模型解决不了「不像人」：瓶颈在编排（重叠、停顿、节奏），不在音色。
而编排参数是可以从参考音频里**量出来**的——风格属于「思想/方法」，不受著作权保护，
复制声线才侵权。所以：拿参考音频做统计，用自己的音色复现，法律与技术都成立。

本脚本**只输出统计量**：不保存、不转存、不重采样导出参考音频。

用法
----
    # 参考音频（仅内部分析）
    python scripts/tts/style_profile.py --wav D:/refs/xiangsheng.wav --out out/style/ref.json

    # 自己的产物（同样的尺子量一遍，才知道差在哪）
    python scripts/tts/style_profile.py --wav out/duo5/mw-observability/signals.wav --out out/style/duo5.json

    # 并排对比
    python scripts/tts/style_profile.py --compare out/style/ref.json out/style/duo5.json

方法
----
1. 能量门限判语音/静音（参考音频信噪比通常很高，不需要重型 VAD）
2. 对有声帧估基频（yin），按 log-f0 做二均值聚类 → 两个说话人
3. 连续同属一人的帧构成一个 turn；turn 之间无静音即为**重叠**
4. 统计 turn 间的间隙分布、重叠率、turn 内短停顿、每 turn 的基频动态范围

已知近似
--------
重叠判定用「f0 换人 + 无静音」近似，不是真正的双基频分离：
两人同时说且音高接近时会漏判。基准值只用于**相对比较**（同一把尺子量两边），
不要当成绝对真值引用。
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import numpy as np

SR = 16000
HOP = 160  # 10ms/帧
FMIN, FMAX = 70.0, 420.0
VOICED_DB_FLOOR = 32.0  # 低于峰值 32dB 视为静音
MIN_TURN_S = 0.30  # 短于 300ms 的段当噪声丢掉
MIN_WITHIN_PAUSE_S = 0.08  # turn 内短停顿下限
MAX_WITHIN_PAUSE_S = 0.60  # 超过算 turn 断开


def load_audio(path: str) -> np.ndarray:
    import librosa

    y, _ = librosa.load(path, sr=SR, mono=True)
    return y


def frame_energy_db(y: np.ndarray) -> np.ndarray:
    import librosa

    rms = librosa.feature.rms(y=y, frame_length=4 * HOP, hop_length=HOP)[0]
    peak = float(rms.max()) if rms.size else 1.0
    db = 20.0 * np.log10(np.maximum(rms, 1e-8) / max(peak, 1e-8))
    return db


def estimate_f0(y: np.ndarray, db: np.ndarray) -> np.ndarray:
    import librosa

    f0 = librosa.yin(y, fmin=FMIN, fmax=FMAX, sr=SR, hop_length=HOP)
    n = min(len(f0), len(db))
    f0, db = f0[:n], db[:n]
    voiced = db > -VOICED_DB_FLOOR
    f0 = np.where(voiced, f0, np.nan)
    return f0


def fix_octave(f0: np.ndarray) -> np.ndarray:
    """压掉 yin 的倍频错误。

    yin 在清音/过渡处容易把 105Hz 估成 210Hz，这会让人误以为换了说话人
    （实测：18 个 cue 被切成了 35 段）。以滑动中值为参考，
    比值接近 2 或 0.5 的帧做折半/加倍，比按 MFCC 聚类可靠——
    MFCC 反映的是「说了什么」，同一人不同字之间的差异比不同人还大。
    """
    from scipy.ndimage import median_filter

    out = f0.copy()
    idx = np.where(~np.isnan(f0))[0]
    if idx.size < 21:
        return out
    vals = out[idx]
    ref = median_filter(vals, size=21, mode="nearest")
    ratio = vals / np.maximum(ref, 1e-6)
    vals[ratio > 1.6] /= 2.0
    vals[ratio < 0.62] *= 2.0
    out[idx] = vals
    return out


def build_turns(y: np.ndarray, db: np.ndarray, f0: np.ndarray) -> tuple[list[dict], tuple[float, float]]:
    """把帧序列切成 turn；返回 (turns, (低音说话人Hz, 高音说话人Hz))。

    说话人归属只看基频（两个人的音高差通常在 60Hz 以上），
    前提是先修掉倍频错误——否则一个人会被当成两个人。
    """
    n = min(len(db), len(f0))
    db, f0 = db[:n], f0[:n]
    f0 = fix_octave(f0)
    voiced = db > -VOICED_DB_FLOOR
    idx = np.where(voiced)[0]
    if idx.size < 50:
        return [], (0.0, 0.0)

    vals = np.log(f0[idx])
    lo_v, hi_v = float(np.percentile(vals, 20)), float(np.percentile(vals, 80))
    for _ in range(40):
        lab = np.where(np.abs(vals - lo_v) <= np.abs(vals - hi_v), 0, 1)
        if lab.sum() == 0 or (1 - lab).sum() == 0:
            break
        nlo = float(vals[lab == 0].mean())
        nhi = float(vals[lab == 1].mean())
        if abs(nlo - lo_v) < 1e-3 and abs(nhi - hi_v) < 1e-3:
            lo_v, hi_v = nlo, nhi
            break
        lo_v, hi_v = nlo, nhi
    lo_v, hi_v = min(lo_v, hi_v), max(lo_v, hi_v)

    # 迟滞：越过 65% / 35% 才换人，中间带留出抖动空间
    to_hi = lo_v + (hi_v - lo_v) * 0.65
    to_lo = lo_v + (hi_v - lo_v) * 0.35
    owner = np.full(n, -1, dtype=int)
    cur = -1
    for i in idx:
        v = np.log(f0[i])
        if cur < 0:
            cur = 1 if v > to_hi else 0
        elif cur == 0 and v > to_hi:
            cur = 1
        elif cur == 1 and v < to_lo:
            cur = 0
        owner[i] = cur
    owner = _despike(owner, min_run=15)
    # 平滑不能吃掉静音：否则 turn 会把停顿吞进去，gap 一律算成 0
    owner[~voiced] = -1
    speakers = (round(float(np.exp(lo_v)), 1), round(float(np.exp(hi_v)), 1))

    turns: list[dict] = []
    cur = None
    silence = 0
    max_silence = int(2.0 * SR / HOP)  # 同一人静音超 2s 才算说完一段
    for i, who in enumerate(owner):
        if who < 0:
            silence += 1
            # 断点只看「是否超阈值」，end_frame 始终停在最后一个有声帧，不吃尾部静音
            if cur is not None and silence > max_silence:
                turns.append(cur)
                cur = None
            continue
        silence = 0
        if cur is None:
            cur = {"speaker": int(who), "start_frame": i, "end_frame": i + 1}
        elif cur["speaker"] == who:
            cur["end_frame"] = i + 1
        else:
            # 换人必断开：这正是要统计的「话轮切换」，与中间隔了多久无关
            turns.append(cur)
            cur = {"speaker": int(who), "start_frame": i, "end_frame": i + 1}
    if cur is not None:
        turns.append(cur)

    min_frames = int(MIN_TURN_S * SR / HOP)
    turns = [t for t in turns if t["end_frame"] - t["start_frame"] >= min_frames]

    # 过滤掉短段后，可能出现「同一个人被两个短段隔开」——把这两段接回来。
    # 不接的话，一次 200ms 的基频误判就会让 turn 数翻倍、切换频率虚高。
    merged: list[dict] = []
    for t in turns:
        if merged and merged[-1]["speaker"] == t["speaker"]:
            merged[-1]["end_frame"] = t["end_frame"]
        else:
            merged.append(dict(t))
    turns = merged

    frame_s = HOP / SR
    for t in turns:
        seg = f0[t["start_frame"]:t["end_frame"]]
        seg = seg[~np.isnan(seg)]
        t["start_s"] = round(t["start_frame"] * frame_s, 3)
        t["end_s"] = round(t["end_frame"] * frame_s, 3)
        t["dur_s"] = round(t["end_s"] - t["start_s"], 3)
        if seg.size >= 5:
            p10, p90 = np.percentile(seg, [10, 90])
            t["f0_median"] = round(float(np.median(seg)), 1)
            t["f0_range"] = round(float(p90 - p10), 1)
        else:
            t["f0_median"] = None
            t["f0_range"] = None
    return turns, speakers


def _despike(owner: np.ndarray, min_run: int) -> np.ndarray:
    if owner.size == 0:
        return owner
    out = owner.copy()
    i = 0
    n = len(out)
    while i < n:
        j = i + 1
        while j < n and out[j] == out[i]:
            j += 1
        if out[i] >= 0 and (j - i) < min_run:
            fill = out[i - 1] if i > 0 and out[i - 1] >= 0 else (out[j] if j < n and out[j] >= 0 else -1)
            out[i:j] = fill
        i = j
    return out


def within_turn_pauses(energy_db: np.ndarray, turn: dict) -> list[float]:
    """turn 内部的能量塌陷（短于 MAX_WITHIN_PAUSE_S 的静音）。"""
    seg = energy_db[turn["start_frame"]:turn["end_frame"]]
    if seg.size < 6:
        return []
    quiet = seg < -VOICED_DB_FLOOR
    pauses: list[float] = []
    i = 0
    frame_s = HOP / SR
    while i < len(quiet):
        if not quiet[i]:
            i += 1
            continue
        j = i
        while j < len(quiet) and quiet[j]:
            j += 1
        dur = (j - i) * frame_s
        if MIN_WITHIN_PAUSE_S <= dur <= MAX_WITHIN_PAUSE_S:
            pauses.append(round(dur * 1000.0, 0))
        i = j
    return pauses


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    return round(float(np.percentile(values, q)), 1)


def summarize(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "p10": pct(values, 10),
        "median": pct(values, 50),
        "p90": pct(values, 90),
    }


def analyze(path: str) -> dict:
    y = load_audio(path)
    db = frame_energy_db(y)
    f0 = estimate_f0(y, db)
    turns, speaker_hz = build_turns(y, db, f0)

    gaps: list[float] = []  # 正=间隙，负=重叠（ms）
    overlaps: list[float] = []
    switches = 0
    for a, b in zip(turns, turns[1:]):
        gap = (b["start_s"] - a["end_s"]) * 1000.0
        gaps.append(round(gap, 0))
        if gap < 0:
            overlaps.append(round(-gap, 0))
        if a["speaker"] != b["speaker"]:
            switches += 1

    pauses: list[float] = []
    for t in turns:
        pauses.extend(within_turn_pauses(db, t))

    ranges = [t["f0_range"] for t in turns if t["f0_range"] is not None]
    durs = [t["dur_s"] for t in turns]
    duration_s = len(y) / SR

    return {
        "source": Path(path).name,
        "duration_s": round(duration_s, 1),
        "speakers_hz": {"a": speaker_hz[0], "b": speaker_hz[1]},
        "turns": {
            "count": len(turns),
            "switches": switches,
            "switch_per_min": round(switches / max(duration_s / 60.0, 1e-6), 1),
            "dur_s": summarize(durs),
        },
        "turn_gap_ms": summarize(gaps),
        "overlap": {
            "ratio": round(len(overlaps) / max(len(gaps), 1), 3),
            "count": len(overlaps),
            "ms": summarize(overlaps),
        },
        "within_turn_pause": {
            "per_min": round(len(pauses) / max(duration_s / 60.0, 1e-6), 1),
            "ms": summarize(pauses),
        },
        "f0_range_per_turn_hz": summarize(ranges),
    }


def print_one(p: dict) -> None:
    def n(v, unit=""):
        return "—" if v is None else f"{v:.0f}{unit}"

    print(f"\n== {p['source']} ({p['duration_s']}s) ==")
    print(f"  说话人基频：低 {p['speakers_hz']['a']}Hz / 高 {p['speakers_hz']['b']}Hz")
    print(f"  turn 数：{p['turns']['count']}（切换 {p['turns']['switches']} 次，{p['turns']['switch_per_min']}/分）")
    g = p["turn_gap_ms"]
    print(f"  turn 间隙 ms：中位 {n(g.get('median'))} · P10 {n(g.get('p10'))} · P90 {n(g.get('p90'))}")
    o = p["overlap"]
    print(f"  重叠：{o['ratio'] * 100:.1f}% 的话轮（中位 {n(o['ms'].get('median'), 'ms')}）")
    w = p["within_turn_pause"]
    print(f"  turn 内停顿：{w['per_min']}/分（中位 {n(w['ms'].get('median'), 'ms')}）")
    r = p["f0_range_per_turn_hz"]
    print(f"  每 turn 基频动态：中位 {n(r.get('median'), 'Hz')}")


def print_compare(a: dict, b: dict) -> None:
    print("\n== 对比（左=参考，右=自己的产物）==")
    rows = [
        ("重叠率 %", lambda p: p["overlap"]["ratio"] * 100),
        ("turn 间隙中位 ms", lambda p: p["turn_gap_ms"].get("median", 0)),
        ("turn 间隙 P10 ms", lambda p: p["turn_gap_ms"].get("p10", 0)),
        ("切换/分钟", lambda p: p["turns"]["switch_per_min"]),
        ("turn 内停顿/分钟", lambda p: p["within_turn_pause"]["per_min"]),
        ("turn 内停顿中位 ms", lambda p: p["within_turn_pause"]["ms"].get("median", 0)),
        ("基频动态中位 Hz", lambda p: p["f0_range_per_turn_hz"].get("median", 0)),
    ]
    print(f"  {'指标':<22}{'参考':>10}{'产物':>10}{'差':>10}")
    for name, fn in rows:
        va, vb = fn(a), fn(b)
        print(f"  {name:<22}{va:>10.1f}{vb:>10.1f}{vb - va:>10.1f}")


def main() -> int:
    ap = argparse.ArgumentParser(description="相声表演谱提取（只输出统计量）")
    ap.add_argument("--wav", help="要分析的音频（wav/mp3 均可，librosa 能读就行）")
    ap.add_argument("--out", help="统计量输出 json")
    ap.add_argument("--compare", nargs=2, metavar=("REF", "OWN"), help="对比两份已生成的 json")
    args = ap.parse_args()

    if args.compare:
        a = json.loads(Path(args.compare[0]).read_text(encoding="utf-8"))
        b = json.loads(Path(args.compare[1]).read_text(encoding="utf-8"))
        print_one(a)
        print_one(b)
        print_compare(a, b)
        return 0

    if not args.wav:
        ap.error("需要 --wav 或 --compare")

    profile = analyze(args.wav)
    print_one(profile)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
