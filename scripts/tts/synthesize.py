#!/usr/bin/env python3
"""音频合成驱动（r150 / M1）：把「音频计划」变成 wav + 时间轴 + 质检报告。

**当前主线是单口相声（form=solo）**。对口（duo）的分角色参考音与抢话叠音逻辑保留在
代码里但默认不跑——单口没有话轮切换，抢话无从谈起，硬套只会把节奏弄乱。

三种后端：
    --backend mock       不依赖 GPU/模型：按估算时长生成等长静音 + 比例时间轴
                         用途：先把播放器与断点续听的契约跑通、CI 里可跑
    --backend voxcpm     VoxCPM2（定稿），--vox-ref 零样本或 --vox-lora 挂音色 LoRA
    --backend voxcpm     真合成：VoxCPM2（原生 48kHz，音色克隆最强，r150 定稿方案）

单口相比对口，脚本上只做三件事（其余沿用原逻辑）：
    1. **强制串行**：不抢话（`--overlap-ratio` 在 solo 下被忽略）
    2. **包袱留白**：`punch` 段落地后额外静默 `--punch-hold-ms`（默认 900ms）
       —— 这是单口的节奏核心，相当于给「观众笑声」留位置，不留白包袱就砸了
    3. **停顿缩放**：按情绪微调 unit 的 pauseBefore/pauseAfter（`--no-pace-scale` 可关）

输入：`scripts/tts/out/plans/<chapterId>.json`（由 `scripts/export_spoken_audio.mjs` 生成）
输出：`scripts/tts/out/audio/<chapterId>/<sectionId>.wav` + `<sectionId>.timeline.json`
      `scripts/tts/out/audio/<chapterId>/manifest.json`（播放器只读这份）+ `out/qa.json`

用法：
    # 单口章（默认只跑 solo）
    python scripts/tts/synthesize.py --backend mock --limit-sections 2
    # 用 VoxCPM2 的专用环境跑（venv_voxcpm，torch>=2.5）
    D:/work_space/_tts/venv_voxcpm/Scripts/python.exe scripts/tts/synthesize.py \\
        --backend voxcpm --vox-ref D:/work_space/_tts/dataset/slices/ep3-0386.wav
"""

from __future__ import annotations

import argparse
import json
import math
import random
import struct
import sys
import wave
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PLAN_DIR = HERE / 'out' / 'plans'
AUDIO_DIR = HERE / 'out' / 'audio'
SAMPLE_RATE = 24000
CHARS_PER_SECOND = 4.5

# 不同 speaker 用不同音色参考：pilot 阶段两个参考音色，M2 再定音色库
# solo = 单口（一个人从头说到尾）；narrator 是单口章里的默认说话人
SPEAKER_LABEL = {'solo': '单口', 'narrator': '旁白', 'dou': '逗哏', 'peng': '捧哏'}

# ---- 单口节奏参数 ----
# 包袱落地后的留白（毫秒）。单口没有捧哏接话，包袱响不响全靠这一下停顿；
# 不给留白等于把笑点踩过去，是「念稿」和「说相声」最直接的差别。
PUNCH_HOLD_MS = 900
# 单口合段上限：一个知识点通常在 5–8 句内说完；再长一次合成音色会漂、
# TTS 也容易在中段丢韵律。超了就在下一个 unit 边界断开（那里本来就有情绪切换）。
MAX_MERGED_LINES = 8
# 按情绪缩放 unit 自带停顿：铺垫要稳、翻包袱要收、收尾要拖。
# 只在 solo 下生效（对口由抢话逻辑主导，再叠缩放会把重叠算乱）。
PAUSE_SCALE = {
    'banter': 1.00,
    'setup': 0.95,
    'deadpan': 1.15,
    'punch': 1.00,
    'realize': 0.90,
    'contrast': 1.05,
    'wrap': 1.25,
}


def normalize_solo_plan(plan: dict, merge: bool = True, max_pause_ms: int = 300) -> None:
    """单口章制作期归一化：合并相邻同人情绪段 + 压缩换段停顿（就地修改 plan）。

    为什么需要（2026-11-23 试听反馈）：
    - 写稿模型/黄金稿按情绪切 unit（banter→setup→deadpan…），单口其实是**同一个人**，
      段间 pauseBefore+pauseAfter 叠到 600–900ms，听感像每句话都喘一口气；
    - 一个知识点被切到两个 unit 里，停顿正好落在论述中间。
    合段后一个 unit 承载完整知识点，段内由 split_lines() 按真实静音切句级 cue，
    播放器高亮不受影响（cue 是从音频测的，不依赖 unit 边界）。
    **对口章完全不动**——那里的停顿与抢话是表演的一部分。
    """
    if plan.get('form') != 'solo':
        return
    for section in plan.get('sections', []):
        units = section.get('units', [])
        if not units:
            continue
        if merge:
            merged: list[dict] = []
            for unit in units:
                lines = list(unit.get('lines') or [])
                if (merged and unit.get('speaker') == merged[-1]['speaker']
                        and len(merged[-1]['lines']) + len(lines) <= MAX_MERGED_LINES):
                    prev = merged[-1]
                    # lines 拼接；情绪取最后一段（包袱收尾决定语气）；停顿取后段
                    prev['lines'] = prev['lines'] + lines
                    prev['emotion'] = unit.get('emotion', prev['emotion'])
                    prev['pauseBeforeMs'] = unit.get('pauseBeforeMs', 0)
                    prev['pauseAfterMs'] = unit.get('pauseAfterMs', 0)
                else:
                    merged.append(dict(unit))
            units = merged
        for unit in units:
            unit['pauseBeforeMs'] = min(unit.get('pauseBeforeMs', 0), max_pause_ms)
            unit['pauseAfterMs'] = min(unit.get('pauseAfterMs', 0), max_pause_ms)
        section['units'] = units


def load_plans(chapters: list[str] | None, plan_dir: str | Path | None = None) -> list[dict]:
    plan_path = Path(plan_dir) if plan_dir else PLAN_DIR
    if not plan_path.exists():
        sys.exit(f'找不到 {plan_path}；先跑 cd frontend && node ../scripts/export_spoken_audio.mjs')
    plans = [json.loads(path.read_text(encoding='utf-8')) for path in sorted(plan_path.glob('*.json')) if path.name != 'index.json']
    if chapters:
        plans = [plan for plan in plans if plan['chapterId'] in set(chapters)]
    if not plans:
        sys.exit('没有匹配的音频计划。')
    return plans


def unit_text(unit: dict) -> str:
    return '，'.join(line.rstrip('。！？；') for line in unit['lines']) + '。'


def estimate_unit_ms(unit: dict) -> int:
    chars = sum(len(line) for line in unit['lines'])
    return int(chars / CHARS_PER_SECOND * 1000)


# ---------------------------------------------------------------- 时间轴

def split_lines(pcm: bytes, n_lines: int, sr: int = SAMPLE_RATE,
                min_gap_ms: int = 60) -> list[tuple[int, int]]:
    """把一段 unit 音频按**内部静音**切成 n_lines 段，返回相对毫秒区间。

    为什么不能按字数比例摊：实测按字数摊时 **30–55% 的 cue 起点落在静音里**——
    每个 unit 的第二句基本都飘到停顿中，播放器高亮会提前跳。TTS 的语速不均匀，
    字数比例只是猜测；而 unit 文本是用逗号把多句连起来的，模型会在逗号处真的停顿，
    所以「找停顿」比「数汉字」可靠得多。

    兜底：内部停顿不够时退回等分，绝不返回空。
    """
    import numpy as np

    audio = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768.0
    total_ms = int(len(audio) / sr * 1000)
    if audio.size == 0:
        return [(0, total_ms)]

    hop = max(1, int(sr * 0.01))
    n = len(audio) // hop
    if n < 4:
        return [(0, total_ms)]
    env = np.sqrt((audio[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    thr = max(float(env.max()) * 0.04, 0.002)

    quiet = env < thr
    # 首段对齐到真正的开口处：unit 音频可能带残留静音，cue 不该指着静音
    loud_idx = np.where(~quiet)[0]
    first = max(0, int(loud_idx[0]) * 10 - 40) if loud_idx.size else 0

    # 单句 unit：不需要切分，但**首段对齐仍要生效**（否则 cue 会指着残留静音）
    if n_lines <= 1:
        return [(first, total_ms)]

    gaps: list[tuple[int, int, float]] = []
    i = 0
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if (j - i) * 10 >= min_gap_ms:
                gaps.append((i, j, float(env[i:j].mean())))
            i = j
        else:
            i += 1

    if len(gaps) < n_lines - 1:
        step = (total_ms - first) / n_lines
        return [(int(first + step * k), int(first + step * (k + 1)))
                for k in range(n_lines)]

    # 取「最长且最安静」的 n-1 个停顿作为切点，再按时间排序。
    # **切点放在停顿结束处（=下一句开口）而不是停顿中点**：播放器是按 startMs
    # 找"当前句"的，落在静音里会让高亮提前跳。提前 40ms 是为了吃进起音的爆破/气声。
    gaps.sort(key=lambda g: (-(g[1] - g[0]), g[2]))
    chosen = sorted(gaps[: n_lines - 1], key=lambda g: g[0])
    bounds = [first]
    prev = first
    for start_i, end_i, _ in chosen:
        cut = max(prev + 1, int(end_i * 10) - 40)
        cut = min(cut, total_ms - 1)
        if cut <= prev:
            continue
        bounds.append(cut)
        prev = cut
    if len(bounds) < n_lines:
        # 切点被合并掉了，退回等分，保证段数正确
        step = (total_ms - first) / n_lines
        return [(int(first + step * k), int(first + step * (k + 1)))
                for k in range(n_lines)]
    bounds.append(total_ms)
    return [(bounds[k], bounds[k + 1]) for k in range(n_lines)]


def build_cues(units: list[dict], spans: list[tuple[int, int]],
               line_spans: list[list[tuple[int, int]]] | None = None) -> list[dict]:
    """按每个 unit 在**混音轴**上的实际位置摊到句级。

    r150 之后 spans 来自真实混音坐标而不是累加推算：重叠时相邻 cue 的区间会相交，
    这是刻意的——播放器按 startMs 找当前句，相交说明两句同时在说。

    line_spans 是 `split_lines()` 从音频里测出的句级边界（已加上 unit 起点）；
    缺省时退回按字数比例（mock 后端就走这条）。
    """
    cues: list[dict] = []
    for index, (unit, (start, duration)) in enumerate(zip(units, spans)):
        lines = unit['lines']
        if line_spans is not None and index < len(line_spans) \
                and len(line_spans[index]) == len(lines):
            bounds = line_spans[index]
        else:
            total_chars = sum(len(line) for line in lines) or 1
            cursor = start
            bounds = []
            for line in lines:
                share = len(line) / total_chars
                length = max(1, int(round(duration * share)))
                bounds.append((cursor, cursor + length))
                cursor += length
        for (seg_start, seg_end), line in zip(bounds, lines):
            cues.append(
                {
                    'startMs': int(seg_start),
                    'endMs': int(seg_end),
                    'speaker': unit['speaker'],
                    'emotion': unit['emotion'],
                    'text': line,
                }
            )
    return cues


# ---------------------------------------------------------------- mock 后端

def mock_unit(unit: dict, sr: int = SAMPLE_RATE) -> tuple[bytes, int]:
    duration = estimate_unit_ms(unit)
    return b'\x00\x00' * int(sr * duration / 1000), duration


# ---------------------------------------------------------------- VoxCPM2 后端

class VoxCPM2Backend:
    """VoxCPM2 真合成（r150 定稿方案）。

    为什么用它的原因写在 TTS-GAP-REVIEW §2.12/§2.13：原生 48kHz、音色克隆最像、
    衰减尾巴最短（配 cfg1.5 + 干参考音，t20 100ms）。

    两个工程要点：
    1. **参考音只编码一次**：`build_prompt_cache()` 拿到的缓存对所有 unit 复用。
       逐句重编码既慢又会让音色轻微漂移。
    2. **`anchor_prev`**：把已生成的上一句并回缓存当 continuation 锚
       （`merge_prompt_cache`），官方给长文本稳定音色准备的机制。默认关，
       因为相声句间本来就有大停顿，强锚可能把语气拖平；需要时再开。
    """

    def __init__(self, model_dir: str, repo_dir: str, ref_wav: str,
                 cfg: float = 1.5, timesteps: int = 10, seed: int | None = 7,
                 anchor_prev: bool = False, lora_ckpt: str | None = None):
        repo = Path(repo_dir)
        # voxcpm 依赖 torch>=2.5 → 用 venv_voxcpm 环境
        sys.path.insert(0, str(repo / 'src'))
        try:
            from voxcpm import VoxCPM
            from voxcpm.model.utils import next_and_close
        except Exception as exc:  # pragma: no cover
            sys.exit(
                f'VoxCPM 依赖未就绪（{exc}）。\n'
                f'  请用专用环境运行：D:/work_space/_tts/venv_voxcpm/Scripts/python.exe'
            )
        ref = Path(ref_wav)
        if not ref.exists():
            sys.exit(f'参考音不存在：{ref}')
        self._close = next_and_close
        lora_kwargs = {}
        if lora_ckpt:
            # 官方推理示例用 V1 的 LoRAConfig 读配置，但 V2 的配置里
            # target_proj_modules 多一个 fusion_concat_proj——按 base 架构选类才不丢字段。
            import json as _json

            from voxcpm.model.voxcpm import LoRAConfig as LoRAConfigV1
            from voxcpm.model.voxcpm2 import LoRAConfig as LoRAConfigV2

            ckpt = Path(lora_ckpt)
            info = _json.loads((ckpt / 'lora_config.json').read_text(encoding='utf-8'))
            arch_info = _json.loads((Path(model_dir) / 'config.json').read_text(encoding='utf-8'))
            arch = str(arch_info.get('architecture', 'voxcpm')).lower()
            cfg_cls = LoRAConfigV2 if arch == 'voxcpm2' else LoRAConfigV1
            lora_kwargs = {
                'lora_config': cfg_cls(**(info.get('lora_config') or {})),
                'lora_weights_path': str(ckpt),
            }
            print(f'加载 LoRA: {ckpt}（{arch}）', flush=True)
        self.model = VoxCPM.from_pretrained(
            hf_model_id=str(model_dir),
            load_denoiser=False,      # 避开 modelscope 的 zipenhancer 权重
            optimize=False,           # Windows 无 triton，compile 会退化；关掉更稳
            device='cuda',
            local_files_only=True,
            **lora_kwargs,
        )
        self.tts = self.model.tts_model
        self.sample_rate = int(self.tts.sample_rate)      # 48000
        self.cfg = cfg
        self.timesteps = timesteps
        self.seed = seed
        self.anchor_prev = anchor_prev
        self.base_cache = self.tts.build_prompt_cache(reference_wav_path=str(ref))
        self._anchor_cache = None

    def synthesize(self, unit: dict) -> tuple[bytes, int]:
        import numpy as np

        cache = self._anchor_cache if self._anchor_cache is not None else self.base_cache
        gen = self.tts._generate_with_prompt_cache(
            target_text=unit_text(unit),
            prompt_cache=cache,
            inference_timesteps=self.timesteps,
            cfg_value=self.cfg,
            seed=self.seed,
        )
        wav, _, feat = self._close(gen)
        audio = wav.squeeze(0).cpu().numpy().astype(np.float32)
        if self.anchor_prev:
            # 只锚上一句，避免缓存无限膨胀
            self._anchor_cache = self.tts.merge_prompt_cache(
                self.base_cache, unit_text(unit), feat
            )
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > 0.99:
            audio = audio * (0.99 / peak)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype('<i2').tobytes()
        return pcm, int(len(audio) / self.sample_rate * 1000)


# ---------------------------------------------------------------- 写盘与质检

def silence(ms: int, sr: int = SAMPLE_RATE) -> bytes:
    return b'\x00\x00' * int(sr * ms / 1000)


def trim_edges(pcm: bytes, threshold: int = 200, keep_ms: int = 40,
               sr: int = SAMPLE_RATE) -> tuple[bytes, int]:
    """裁掉首尾静音，两侧各留 keep_ms 余量。返回 (pcm, 被裁掉的毫秒数)。

    为什么必须裁：TTS 输出自带句首句尾静音。实测 timeline 设 610ms 间隙，
    音频里却是 1245ms——多出来的 635ms 全是模型边界静音。
    不裁的话，**任何 gap 设置都会被它吃掉**，重叠更无从谈起。

    **不能用固定阈值**（第一版就是 ±200）。实测 VoxCPM2 句首静音的底噪偶尔会短暂越过
    这个门限，裁剪随即停在那里，留下 0.5–1s 静音——于是每个 unit 第一句的 cue
    都落在静音里（实测 22% 的 cue 起点无 speech）。改为按**包络分位数**自适应：
    底噪取 10 分位、语音取 90 分位，门限设在两者之间 8% 处。
    """
    import numpy as np

    audio = np.frombuffer(pcm, dtype='<i2')
    if audio.size == 0:
        return pcm, 0
    f = audio.astype(np.float32) / 32768.0
    hop = max(1, int(sr * 0.01))
    n = len(f) // hop
    if n < 10:
        return pcm, 0
    env = np.sqrt((f[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    floor = float(np.percentile(env, 10))
    speech = float(np.percentile(env, 90))
    if speech <= floor:
        return pcm, 0                      # 全静音（mock 后端）：保持原长
    gate = floor + 0.08 * (speech - floor)
    loud = np.where(env > gate)[0]
    if loud.size == 0:
        return pcm, 0
    pad = int(sr * keep_ms / 1000)
    start = max(0, int(loud[0]) * hop - pad)
    end = min(len(audio), (int(loud[-1]) + 1) * hop + pad)
    removed_ms = int((len(audio) - (end - start)) / sr * 1000)
    return audio[start:end].tobytes(), removed_ms


def mix_clips(clips: list[tuple[int, bytes]], tail_ms: int = 0,
              sr: int = SAMPLE_RATE) -> bytes:
    """把 (start_ms, pcm) 叠加到一条时间轴上，start_ms 允许为负。

    负值是「抢话」：后一句在上一句尾音还没落时开口。真人对话有 10–25% 的话轮是这样，
    而顺序拼接（`b''.join`）在结构上无法表达——这是"像朗读"而不是"像对话"的根因。
    用 int32 累加再 clip，避免两轨同时达到峰值时溢出。

    **单口不用负值**：一个人说不存在抢话，但同一套混音器仍然必要——
    它才是把「真实坐标」交给时间轴的地方。
    """
    import numpy as np

    if not clips:
        return b''
    span_ms = max(start + int(len(pcm) / 2 / sr * 1000) for start, pcm in clips)
    total = int(sr * (span_ms + max(tail_ms, 0)) / 1000) + 2
    buf = np.zeros(max(total, 2), dtype=np.int32)
    for start_ms, pcm in clips:
        audio = np.frombuffer(pcm, dtype='<i2').astype(np.int32)
        pos = int(sr * start_ms / 1000)
        if pos < 0:
            audio = audio[-pos:]
            pos = 0
        if audio.size == 0:
            continue
        end = pos + audio.size
        if end > len(buf):
            buf = np.pad(buf, (0, end - len(buf)))
        buf[pos:end] += audio
    return np.clip(buf, -32768, 32767).astype('<i2').tobytes()


def normalize_loudness(pcm: bytes, target_lufs: float = -22.0,
                       sr: int = SAMPLE_RATE) -> tuple[bytes, float]:
    """整节归一到 -20 LUFS（有声书区间）；归一后做峰值保护，返回（新 pcm, 最终 LUFS）。

    为什么不是 -16：口播稿有大量短句与停顿，峰值因子高，-16 会被峰值保护拉回 -21 左右；
    -20 能在不削顶的前提下保持一致响度。
    """
    import numpy as np

    audio = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768.0
    if audio.size == 0:
        return pcm, float('nan')
    meter = None
    try:
        import pyloudnorm as pyln

        meter = pyln.Meter(sr)
        loudness = meter.integrated_loudness(audio)
        if loudness == float('-inf') or np.isnan(loudness):
            raise ValueError('silence')
        audio = pyln.normalize.loudness(audio, loudness, target_lufs)
    except Exception:
        peak = float(np.max(np.abs(audio))) or 1.0
        audio = audio / peak * 0.89

    # 峰值保护：归一化常把峰值推过满幅，直接 clip 会失真并让响度反向变低
    peak = float(np.max(np.abs(audio)))
    if peak > 0.95:
        audio = audio * (0.95 / peak)

    final = float('nan')
    if meter is not None:
        try:
            final = float(meter.integrated_loudness(audio))
        except Exception:
            final = float('nan')
    audio = np.clip(audio, -1.0, 1.0)
    return (audio * 32767).astype('<i2').tobytes(), final


def write_wav(path: Path, pcm: bytes, sr: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(pcm)


def _riff_chunk(cid: bytes, body: bytes) -> bytes:
    """单个 RIFF 顶层块（含 word 对齐 pad）。"""
    return cid + struct.pack('<I', len(body)) + body + (b'\x00' if len(body) & 1 else b'')


def embed_ai_metadata(path: Path, model: str) -> bool:
    """在 RIFF 头里插一个 LIST/INFO 块（r151，《标识办法》隐式标识）。

    wave 模块不支持 INFO 块，这里手写 RIFF 顶层重排：读出全部顶层块，
    在 `fmt ` 之后插 `LIST (INFO)`，`data` 等其它块原样搬运（PCM 字节零改动）。
    不认识 INFO 的解码器会跳过未知块，音频内容与时长不变。

    尽力而为：非标准 RIFF / 解析越界一律放弃并返回 False，标识失败不打断合成；
    显式标识（界面角标 + manifest `aiGenerated`）不依赖这里，是主口径。
    """
    raw = path.read_bytes()
    if len(raw) < 12 or raw[:4] != b'RIFF' or raw[8:12] != b'WAVE':
        return False
    pos = 12
    chunks: list[tuple[bytes, bytes]] = []
    while pos + 8 <= len(raw):
        cid = raw[pos:pos + 4]
        size = struct.unpack('<I', raw[pos + 4:pos + 8])[0]
        if pos + 8 + size > len(raw):
            return False
        chunks.append((cid, raw[pos + 8:pos + 8 + size]))
        pos += 8 + size + (size & 1)

    info: list[bytes] = []

    def _add(tag: bytes, text: str) -> None:
        data = text.encode('ascii', 'replace') + b'\x00'  # INFO 文本以 NUL 结尾
        info.append(tag + struct.pack('<I', len(data)) + data + (b'\x00' if len(data) & 1 else b''))

    _add(b'ICMT', 'AI-generated speech (SkillCoach) - synthesized voice, not a human recording')
    _add(b'ISFT', model[:120])
    _add(b'ICRD', datetime.now().strftime('%Y-%m-%d'))
    list_body = b'INFO' + b''.join(info)

    fmt_chunks = [item for item in chunks if item[0] == b'fmt ']
    rest = [item for item in chunks if item[0] != b'fmt ']
    parts = [b'WAVE']
    parts += [_riff_chunk(cid, body) for cid, body in fmt_chunks]
    parts.append(_riff_chunk(b'LIST', list_body))
    parts += [_riff_chunk(cid, body) for cid, body in rest]
    payload = b''.join(parts)
    path.write_bytes(b'RIFF' + struct.pack('<I', len(payload)) + payload)
    return True


def peak_of(pcm: bytes) -> int:
    if not pcm:
        return 0
    samples = struct.unpack(f'<{len(pcm) // 2}h', pcm)
    return max(abs(value) for value in samples)


def silence_ratio(pcm: bytes) -> float:
    if not pcm:
        return 1.0
    samples = struct.unpack(f'<{len(pcm) // 2}h', pcm)
    quiet = sum(1 for value in samples if abs(value) < 200)
    return quiet / len(samples)


def recue_out(out_audio: Path, plans: list[dict]) -> int:
    """只重算句级 cue，不重新合成。

    场景：切分逻辑改了，但音频本身没变。重跑一次 TTS 要几分钟，而句级边界纯粹是
    从音频里量出来的——所以只要时间轴里存了 `unitSpans`，就能秒级修好。
    """
    import numpy as np

    fixed = 0
    for plan in plans:
        chapter_dir = out_audio / plan['chapterId']
        for section in plan['sections']:
            tpath = chapter_dir / f'{section["sectionId"]}.timeline.json'
            wpath = chapter_dir / f'{section["sectionId"]}.wav'
            if not (tpath.exists() and wpath.exists()):
                continue
            track = json.loads(tpath.read_text(encoding='utf-8'))
            units = section['units']
            unit_spans = track.get('unitSpans')
            if not unit_spans:
                # 老时间轴没有 unitSpans：但旧的 cue 是按比例**连续覆盖**整个 unit 的，
                # 所以「首句 startMs + 末句 endMs」能精确反推 unit 边界。
                old_cues = track.get('cues') or []
                expect = sum(len(u['lines']) for u in units)
                if len(old_cues) == expect and expect:
                    unit_spans = []
                    k = 0
                    for unit in units:
                        n = len(unit['lines'])
                        grp = old_cues[k:k + n]
                        k += n
                        unit_spans.append((grp[0]['startMs'], grp[-1]['endMs'] - grp[0]['startMs']))
                    print(f'  {plan["chapterId"]}/{section["sectionId"]}：从旧 cue 反推 unitSpans')
                else:
                    print(f'  跳过 {plan["chapterId"]}/{section["sectionId"]}：'
                          f'没有 unitSpans，旧 cue 数也对不上剧本')
                    continue
            if len(unit_spans) != len(units):
                print(f'  跳过 {plan["chapterId"]}/{section["sectionId"]}：'
                      f'unitSpans({len(unit_spans)}) 与剧本 unit 数({len(units)}) 不一致')
                continue
            sr = int(track.get('sampleRate', SAMPLE_RATE))
            with wave.open(str(wpath), 'rb') as handle:
                sr = handle.getframerate()
                raw = np.frombuffer(handle.readframes(handle.getnframes()), dtype='<i2')

            spans: list[tuple[int, int]] = []
            line_spans: list[list[tuple[int, int]]] = []
            for (start, duration), unit in zip(unit_spans, units):
                spans.append((int(start), int(duration)))
                a = int(start * sr / 1000)
                b = a + int(duration * sr / 1000)
                clip = raw[a:b].astype('<i2').tobytes()
                line_spans.append([(int(start) + x, int(start) + y)
                                   for x, y in split_lines(clip, len(unit['lines']), sr=sr)])

            track['cues'] = build_cues(units, spans, line_spans)
            tpath.write_text(json.dumps(track, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            fixed += 1
            print(f'  重算 {plan["chapterId"]}/{section["sectionId"]}：{len(track["cues"])} 句')
    print(f'完成，重算 {fixed} 节时间轴（音频未改动）')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='口播稿合成（mock / VoxCPM2）')
    parser.add_argument('--backend', choices=['mock', 'voxcpm'], default='mock')
    parser.add_argument('--chapter', action='append', default=None, help='只跑指定章（可重复）')
    parser.add_argument('--limit-sections', type=int, default=0, help='每章最多跑几节（0 = 全部）')
    parser.add_argument('--out-audio', default=str(AUDIO_DIR), help='音频输出目录（A/B 对比时分开）')
    parser.add_argument('--plan-dir', default=None, help='音频计划目录（默认 out/plans；验证产物可用独立目录）')
    parser.add_argument('--no-trim-edges', dest='trim_edges', action='store_false', help='不裁句首句尾静音（默认裁）')
    parser.add_argument('--overlap-ratio', type=float, default=0.25,
                        help='换人时触发抢话的比例（0 = 严格串行；真人对话约 0.1–0.25）')
    parser.add_argument('--overlap-ms', type=int, default=180, help='抢话提前量（毫秒）')
    parser.add_argument('--seed', type=int, default=0, help='抢话抽样种子（可复现）')
    parser.add_argument('--tts-seed', type=int, default=1234,
                        help='TTS 自回归采样种子（固定它才能复现；0 = 不固定）')
    parser.add_argument('--force-emotion', default=None,
                        help='诊断用：强制所有 unit 用同一情绪标签（验证音高波动是否来自情绪切换）')
    # ---- 形态（单口 / 对口） ----
    parser.add_argument('--only-form', choices=['solo', 'duo', 'all'], default='solo',
                        help='只跑指定形态（默认 solo；单口是第一优先级，duo 先搁置）')
    parser.add_argument('--punch-hold-ms', type=int, default=PUNCH_HOLD_MS,
                        help='单口：包袱落地后的留白毫秒（相当于给观众笑声留位置）')
    parser.add_argument('--no-pace-scale', dest='pace_scale', action='store_false',
                        help='单口：不按情绪缩放 unit 的停顿')
    parser.add_argument('--no-merge-solo', dest='merge_solo', action='store_false',
                        help='单口：不合并相邻同人情绪段（默认合并，让知识点不被段间停顿切断）')
    parser.add_argument('--max-pause-ms', type=int, default=300,
                        help='单口段间停顿上限 ms（默认 300；对口不受限）')
    # ---- VoxCPM2 ----
    parser.add_argument('--vox-model-dir', default='D:/work_space/_tts/VoxCPM/pretrained_models',
                        help='VoxCPM2 权重目录（本地，不走网络）')
    parser.add_argument('--vox-repo', default='D:/work_space/_tts/VoxCPM-main', help='VoxCPM 代码目录')
    parser.add_argument('--vox-ref', default=None,
                        help='VoxCPM2 参考音。实测最干+最清晰的是 dataset/slices/ep3-0386.wav')
    parser.add_argument('--vox-cfg', type=float, default=1.5,
                        help='VoxCPM2 引导强度。1.5–2.0 尾巴最短(回音最轻)；4.5 高频多但回音重')
    parser.add_argument('--vox-timesteps', type=int, default=10, help='VoxCPM2 CFM 采样步数')
    parser.add_argument('--vox-lora', default=None,
                        help='可选：LoRA checkpoint 目录（含 lora_config.json + lora_weights.safetensors）')
    parser.add_argument('--anchor-prev', action='store_true',
                        help='VoxCPM2：把上一句并进缓存当 continuation 锚（长文音色更稳）')
    parser.add_argument('--recue-only', action='store_true',
                        help='只按音频重算句级 cue，不重新合成（时间轴里需有 unitSpans）')
    args = parser.parse_args()
    rng = random.Random(args.seed)

    plans = load_plans(args.chapter, args.plan_dir)
    # 形态过滤：单口先做，对口搁置（duo 章需要把捧哏台词并进去才能改单口，属内容改造）
    if args.only_form != 'all':
        kept = [p for p in plans if p.get('form', 'solo') == args.only_form]
        skipped = [p['chapterId'] for p in plans if p.get('form', 'solo') != args.only_form]
        if skipped:
            print(f'跳过非 {args.only_form} 章：{", ".join(skipped)}'
                  f'（--only-form all 可一起跑）')
        plans = kept
        if not plans:
            hint = ''
            if args.chapter:
                hint = (f'\n  你指定了 --chapter {args.chapter}，但它是 duo 章。'
                        f'单口优先阶段请加 --only-form all，或把该章剧本改成单口。')
            sys.exit(f'没有 form={args.only_form} 的音频计划。{hint}')

    out_audio = Path(args.out_audio)
    if args.recue_only:
        return recue_out(out_audio, plans)
    out_audio.mkdir(parents=True, exist_ok=True)
    if args.backend == 'voxcpm':
        ref = args.vox_ref
        if not ref:
            sys.exit('--backend voxcpm 需要 --vox-ref（建议 dataset/slices/ep3-0386.wav）')
        backend = VoxCPM2Backend(
            args.vox_model_dir, args.vox_repo, ref,
            cfg=args.vox_cfg, timesteps=args.vox_timesteps,
            seed=args.tts_seed or None, anchor_prev=args.anchor_prev,
            lora_ckpt=args.vox_lora,
        )
    else:
        backend = None
    sample_rate = int(getattr(backend, 'sample_rate', SAMPLE_RATE))
    print(f'后端={args.backend} · 采样率={sample_rate}Hz · 章数={len(plans)}')
    qa: list[dict] = []

    for plan in plans:
        chapter_dir = out_audio / plan['chapterId']
        form = plan.get('form', 'solo')
        is_solo = form == 'solo'
        if is_solo:
            normalize_solo_plan(plan, merge=args.merge_solo, max_pause_ms=args.max_pause_ms)
        sections = plan['sections'][: args.limit_sections] if args.limit_sections else plan['sections']
        tracks = []
        for section in sections:
            units = section['units']
            if is_solo:
                speakers = {u['speaker'] for u in units}
                if len(speakers) > 1:
                    sys.exit(f'[{plan["chapterId"]}/{section["sectionId"]}] 标了 solo 却有多个说话人 '
                             f'{sorted(speakers)}。单口只能一个人，先改剧本或把 form 改成 duo。')
            clips: list[tuple[int, bytes]] = []
            spans: list[tuple[int, int]] = []
            line_spans: list[list[tuple[int, int]]] = []
            cursor = 0
            trimmed_ms = 0
            overlap_count = 0
            since_overlap = 0
            last_end = 0
            last_after = 0
            punch_holds = 0
            for index, unit in enumerate(units):
                if args.force_emotion:
                    unit = {**unit, 'emotion': args.force_emotion}
                if backend:
                    pcm, _ = backend.synthesize(unit)
                else:
                    pcm, _ = mock_unit(unit)
                if args.trim_edges:
                    pcm, removed = trim_edges(pcm, sr=sample_rate)
                    trimmed_ms += removed
                duration = int(len(pcm) / 2 / sample_rate * 1000)

                # 单口：按情绪缩放停顿（铺垫稳、收尾拖），包袱再加留白。
                # 对口：完全用剧本给的停顿，不缩放——否则会把抢话的重叠算乱。
                scale = PAUSE_SCALE.get(unit['emotion'], 1.0) if (is_solo and args.pace_scale) else 1.0
                before = int(unit['pauseBeforeMs'] * scale)
                after = int(unit['pauseAfterMs'] * scale)
                if is_solo and unit['emotion'] == 'punch' and args.punch_hold_ms > 0:
                    after += args.punch_hold_ms
                    punch_holds += 1

                prev = units[index - 1] if index > 0 else None
                # 抢话：只在换人时发生。注意不能只把 before 设成负数——
                # cursor 里已经含了上一句的 pauseAfter，before=-180 只是把间隙从 610 缩到 430，
                # 仍然是串行。真正重叠要跨过上一句末音：start = 上一句结束 − overlap。
                start = cursor + before
                if (not is_solo) and prev is not None and prev['speaker'] != unit['speaker'] \
                        and args.overlap_ratio > 0:
                    since_overlap += 1
                    trigger = rng.random() < args.overlap_ratio
                    if since_overlap >= 4:  # 保底：样本少时纯随机可能一次都不触发
                        trigger = True
                    if trigger:
                        start = last_end - args.overlap_ms
                        overlap_count += 1
                        since_overlap = 0
                start = max(0, start)
                clips.append((start, pcm))
                spans.append((start, duration))
                # 句级边界从音频里测，别用字数猜（否则第二句会飘到停顿里）
                line_spans.append([(start + a, start + b)
                                   for a, b in split_lines(pcm, len(unit['lines']), sr=sample_rate)])
                last_end = start + duration
                last_after = after
                cursor = last_end + after
            tail_ms = last_after if units else 0
            pcm = mix_clips(clips, tail_ms, sr=sample_rate)
            pcm, loudness = normalize_loudness(pcm, sr=sample_rate)
            wav_path = chapter_dir / f'{section["sectionId"]}.wav'
            write_wav(wav_path, pcm, sr=sample_rate)
            # 隐式 AI 标识：写进 RIFF INFO（ICMT/ISFT/ICRD），随文件走、与发布渠道无关
            if not embed_ai_metadata(wav_path, str(plan.get('voice', {}).get('model', 'unknown'))):
                print(f'  [warn] {wav_path.name} 非标准 RIFF，隐式标识未写入（显式标识不受影响）')
            cues = build_cues(units, spans, line_spans)
            duration_ms = int(len(pcm) / 2 / sample_rate * 1000)
            track = {
                'sectionId': section['sectionId'],
                'src': section['src'],
                # 小节标题（可读名，播放器切节 tab 用；plans 由导出器/流水线写入）
                'title': str(section.get('title') or section['sectionId']),
                'durationMs': duration_ms,
                'sampleRate': sample_rate,
                # 存下 unit 级坐标：以后只想重算句级切分时不必重新合成
                'unitSpans': [[int(s), int(d)] for s, d in spans],
                'cues': cues,
            }
            (chapter_dir / f'{section["sectionId"]}.timeline.json').write_text(
                json.dumps(track, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
            )
            tracks.append(track)
            qa.append(
                {
                    'chapterId': plan['chapterId'],
                    'sectionId': section['sectionId'],
                    'backend': args.backend,
                    'form': form,
                    'units': len(units),
                    'cues': len(cues),
                    'durationMs': duration_ms,
                    'estimateMs': section['estimateMs'],
                    'peak': peak_of(pcm),
                    'silenceRatio': round(silence_ratio(pcm), 3),
                    'loudnessLufs': round(loudness, 1) if loudness == loudness else None,
                    'trimmedMs': trimmed_ms,
                    'overlaps': overlap_count,
                    'punchHolds': punch_holds,
                }
            )
            print(
                f'[{plan["chapterId"]}/{section["sectionId"]}] {len(cues)} 句 · {duration_ms / 1000:.1f}s'
                + (f' · 裁静音 {trimmed_ms / 1000:.1f}s' if trimmed_ms else '')
                + (f' · 包袱留白 {punch_holds} 处' if punch_holds else '')
                + (f' · 抢话 {overlap_count} 处' if overlap_count else '')
            )
        (chapter_dir / 'manifest.json').write_text(
            json.dumps({'chapterId': plan['chapterId'],
                        'title': str(plan.get('title') or plan['chapterId']),
                        'form': form,
                        'sampleRate': sample_rate, 'voice': plan['voice'],
                        # AI 生成标识（RELEASE-DATA-SOP 合规红线 #4，隐式标识）：
                        # 播放器缺省也按 true 兜底，但工具链显式写出才算完整。
                        'aiGenerated': True, 'tracks': tracks},
                       ensure_ascii=False, indent=2)
            + '\n',
            encoding='utf-8',
        )

    # 全量音频索引（r151 流水线）：前端「听听」入口只认这一份 —— 新章音频部署后，
    # 入口自动出现，前端零发版。聚合 out_audio 下**所有**章的 manifest（含历史章）。
    chapters_index = []
    for chapter_manifest in sorted(out_audio.glob('*/manifest.json')):
        try:
            data = json.loads(chapter_manifest.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            continue
        tracks_idx = [
            {'sectionId': t.get('sectionId'), 'title': t.get('title') or t.get('sectionId'),
             'durationMs': t.get('durationMs', 0)}
            for t in data.get('tracks', []) if isinstance(t, dict) and t.get('sectionId')
        ]
        if not tracks_idx:
            continue
        chapters_index.append({
            'chapterId': data.get('chapterId', chapter_manifest.parent.name),
            'title': data.get('title') or data.get('chapterId', chapter_manifest.parent.name),
            'form': data.get('form', 'solo'),
            'aiGenerated': data.get('aiGenerated', True),
            'sections': tracks_idx,
            'totalMs': sum(t['durationMs'] for t in tracks_idx),
        })
    if chapters_index:
        index_path = out_audio / 'index.json'
        index_path.write_text(
            json.dumps({'generatedAt': datetime.now().isoformat(timespec='seconds'),
                        'chapters': chapters_index},
                       ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8',
        )
        print(f'音频索引 → {index_path}（{len(chapters_index)} 章）')

    out_qa = out_audio / 'qa.json'
    out_qa.parent.mkdir(parents=True, exist_ok=True)
    out_qa.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    total_minutes = sum(item['durationMs'] for item in qa) / 60000
    print(f'\n完成 {len(qa)} 节 · 总时长 {total_minutes:.1f} 分钟 · 质检 → {out_qa}')
    if args.backend == 'mock':
        print('注意：mock 后端是静音占位，只验契约与时间轴，不能用来听。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
