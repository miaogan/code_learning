#!/usr/bin/env python3
"""音频合成驱动（r150 / M1）：把「音频计划」变成 wav + 时间轴 + 质检报告。

两种后端：
    --backend mock       不依赖 GPU/模型：按估算时长生成等长静音 + 比例时间轴
                         用途：先把播放器与断点续听的契约跑通、CI 里可跑
    --backend cosyvoice  真合成：CosyVoice2-0.5B（Apache-2.0），按情绪段调 instruct

输入：`scripts/tts/out/plans/<chapterId>.json`（由 `scripts/export_spoken_audio.mjs` 生成）
输出：`scripts/tts/out/audio/<chapterId>/<sectionId>.wav` + `<sectionId>.timeline.json`
      `scripts/tts/out/audio/<chapterId>/manifest.json`（播放器只读这份）+ `out/qa.json`

用法：
    python scripts/tts/synthesize.py --backend mock --limit-sections 2
    python scripts/tts/synthesize.py --backend cosyvoice --model-dir D:/work_space/_tts/models/CosyVoice2-0.5B
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PLAN_DIR = HERE / 'out' / 'plans'
AUDIO_DIR = HERE / 'out' / 'audio'
SAMPLE_RATE = 24000
CHARS_PER_SECOND = 4.5

# 7 类情绪的 instruct 模板。
# **必须带 `<|endofprompt|>` 结束符**：CosyVoice2 的 instruct2 把 instruct 当 prompt_text 喂给 LLM，
# 没有结束符它会把指令当正文念出来（r150 实测：第一版音频开头就是「就像跟朋友聊天…」）。
# 措辞也要短祈使句（「用…的语气说这句话」），描述性长句同样会被念。
INSTRUCT_SUFFIX = '<|endofprompt|>'
# 措辞只用**模型认的基础情绪词**（实测：自创的表演腔如「先轻后重」「收尾咬住」它基本无感）。
INSTRUCT = {
    'banter': '用轻松的语气说这句话',
    'setup': '用自信的语气说这句话',
    'deadpan': '用平静的语气说这句话',
    'punch': '用兴奋的语气说这句话',
    'realize': '用惊讶的语气说这句话',
    'contrast': '用无奈的语气说这句话',
    'wrap': '用温柔的语气说这句话',
}

# 语速是相声节奏的主要杠杆：instruct 管音色冷暖，speed 管快慢（实测 0.85→5.6s / 1.35→3.82s）。
SPEED = {
    'banter': 1.10,
    'setup': 1.00,
    'deadpan': 0.92,
    'punch': 1.15,
    'realize': 1.05,
    'contrast': 1.00,
    'wrap': 0.88,
}

# 不同 speaker 用不同音色参考：pilot 阶段两个参考音色，M2 再定音色库
SPEAKER_LABEL = {'dou': '逗哏', 'peng': '捧哏', 'narrator': '旁白'}


def load_plans(chapters: list[str] | None) -> list[dict]:
    if not PLAN_DIR.exists():
        sys.exit(f'找不到 {PLAN_DIR}；先跑 cd frontend && node ../scripts/export_spoken_audio.mjs')
    plans = [json.loads(path.read_text(encoding='utf-8')) for path in sorted(PLAN_DIR.glob('*.json')) if path.name != 'index.json']
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

def build_cues(units: list[dict], durations_ms: list[int], pauses: list[tuple[int, int]]) -> list[dict]:
    """把段级时间按字数比例摊到句级：pilot 的近似时间轴（VAD 精修在 M1 收尾做）。"""
    cues: list[dict] = []
    cursor = 0
    for unit, duration, (before, after) in zip(units, durations_ms, pauses):
        cursor += before
        total_chars = sum(len(line) for line in unit['lines']) or 1
        span_start = cursor
        for line in unit['lines']:
            share = len(line) / total_chars
            length = max(1, int(round(duration * share)))
            cues.append(
                {
                    'startMs': span_start,
                    'endMs': span_start + length,
                    'speaker': unit['speaker'],
                    'emotion': unit['emotion'],
                    'text': line,
                }
            )
            span_start += length
        cursor += duration + after
    return cues


# ---------------------------------------------------------------- mock 后端

def mock_unit(unit: dict) -> tuple[bytes, int]:
    duration = estimate_unit_ms(unit)
    return b'\x00\x00' * int(SAMPLE_RATE * duration / 1000), duration


# ---------------------------------------------------------------- CosyVoice 后端

class CosyVoiceBackend:
    def __init__(self, model_dir: str, repo_dir: str, spk: str = '中文男', prompt_wav: str | None = None,
                 model_kind: str = 'auto'):
        repo = Path(repo_dir)
        # flow matching 依赖 third_party/Matcha-TTS（submodule），要一起进 sys.path
        sys.path.insert(0, str(repo / 'third_party' / 'Matcha-TTS'))
        sys.path.insert(0, str(repo))
        # wget 在 PyPI 反复校验失败，用本地 stub 顶掉（推理不需要它，见 scripts/tts/stubs/）
        sys.path.insert(0, str(HERE / 'stubs'))
        try:
            import torch
            import torchaudio
            from cosyvoice.cli.cosyvoice import CosyVoice2, CosyVoice3
        except Exception as exc:  # pragma: no cover - 依赖缺失时给出可执行提示
            sys.exit(f'CosyVoice 依赖未就绪（{exc}）。先按 scripts/tts/README.md 装环境。')
        kind = model_kind
        if kind == 'auto':
            kind = 'cv3' if (Path(model_dir) / 'cosyvoice3.yaml').exists() else 'cv2'
        self.torch = torch
        self.torchaudio = torchaudio
        self.repo_dir = str(repo)
        self.model_kind = kind
        if kind == 'cv3':
            self.model = CosyVoice3(model_dir, load_trt=False, load_vllm=False, fp16=False)
        else:
            self.model = CosyVoice2(model_dir, load_jit=False, load_trt=False, fp16=False)
        self.sample_rate = self.model.sample_rate
        self.prompt = self._make_prompt(spk, prompt_wav)

    def _make_prompt(self, spk: str, prompt_wav: str | None = None) -> str:
        """参考音色：返回**路径**（CosyVoice 的 inference_instruct2 自己读+重采样）。

        CosyVoice2-0.5B 的 `spk2info` 为空（实测），所以必须给参考 wav：
        优先 `--prompt-wav`，其次仓库自带 `asset/zero_shot_prompt.wav`。
        """
        if prompt_wav:
            path = Path(prompt_wav)
            if not path.exists():
                sys.exit(f'参考音不存在：{path}')
            return str(path)
        asset = Path(self.repo_dir) / 'asset' / 'zero_shot_prompt.wav'
        if asset.exists():
            return str(asset)
        sys.exit('没有参考音色：模型无 SFT 音色，也没找到 asset/zero_shot_prompt.wav')

    def synthesize(self, unit: dict) -> tuple[bytes, int]:
        import numpy as np

        instruct = INSTRUCT.get(unit['emotion'], INSTRUCT['banter']) + INSTRUCT_SUFFIX
        if not instruct.endswith(INSTRUCT_SUFFIX):  # 防御：改模板时别漏结束符
            sys.exit(f'instruct 缺少结束符：{instruct}')
        chunks = []
        speed = SPEED.get(unit['emotion'], 1.0)
        for output in self.model.inference_instruct2(unit_text(unit), instruct, self.prompt, stream=False, speed=speed):
            chunks.append(output['tts_speech'].squeeze(0).cpu().numpy())
        if not chunks:
            return b'', 0
        audio = np.concatenate(chunks)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype('<i2').tobytes()
        return pcm, int(len(audio) / self.sample_rate * 1000)


# ---------------------------------------------------------------- 写盘与质检

def silence(ms: int) -> bytes:
    return b'\x00\x00' * int(SAMPLE_RATE * ms / 1000)


def write_wav(path: Path, pcm: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm)


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


def main() -> int:
    parser = argparse.ArgumentParser(description='口播稿合成（mock / CosyVoice）')
    parser.add_argument('--backend', choices=['mock', 'cosyvoice'], default='mock')
    parser.add_argument('--chapter', action='append', default=None, help='只跑指定章（可重复）')
    parser.add_argument('--limit-sections', type=int, default=0, help='每章最多跑几节（0 = 全部）')
    parser.add_argument('--model-dir', default='D:/work_space/_tts/models/CosyVoice2-0.5B')
    parser.add_argument('--repo-dir', default='D:/work_space/_tts/CosyVoice', help='CosyVoice 代码目录（加进 sys.path）')
    parser.add_argument('--spk', default='中文男', help='CosyVoice SFT 参考音色')
    parser.add_argument('--prompt-wav', default=None, help='零样本参考音频（16k/24k 均可，自动重采样）')
    parser.add_argument('--model-kind', choices=['auto', 'cv2', 'cv3'], default='auto', help='模型代际（auto 按 cosyvoice3.yaml 识别）')
    args = parser.parse_args()

    plans = load_plans(args.chapter)
    backend = CosyVoiceBackend(args.model_dir, args.repo_dir, args.spk, args.prompt_wav, args.model_kind) if args.backend == 'cosyvoice' else None
    qa: list[dict] = []

    for plan in plans:
        chapter_dir = AUDIO_DIR / plan['chapterId']
        sections = plan['sections'][: args.limit_sections] if args.limit_sections else plan['sections']
        tracks = []
        for section in sections:
            units = section['units']
            pcm_parts: list[bytes] = []
            durations: list[int] = []
            pauses: list[tuple[int, int]] = []
            for unit in units:
                if backend:
                    pcm, duration = backend.synthesize(unit)
                else:
                    pcm, duration = mock_unit(unit)
                pcm_parts.append(silence(unit['pauseBeforeMs']))
                pcm_parts.append(pcm)
                pcm_parts.append(silence(unit['pauseAfterMs']))
                durations.append(duration)
                pauses.append((unit['pauseBeforeMs'], unit['pauseAfterMs']))
            pcm = b''.join(pcm_parts)
            wav_path = chapter_dir / f'{section["sectionId"]}.wav'
            write_wav(wav_path, pcm)
            cues = build_cues(units, durations, pauses)
            duration_ms = int(len(pcm) / 2 / SAMPLE_RATE * 1000)
            track = {
                'sectionId': section['sectionId'],
                'src': section['src'],
                'durationMs': duration_ms,
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
                    'units': len(units),
                    'cues': len(cues),
                    'durationMs': duration_ms,
                    'estimateMs': section['estimateMs'],
                    'peak': peak_of(pcm),
                    'silenceRatio': round(silence_ratio(pcm), 3),
                }
            )
            print(f'[{plan["chapterId"]}/{section["sectionId"]}] {len(cues)} 句 · {duration_ms / 1000:.1f}s')
        (chapter_dir / 'manifest.json').write_text(
            json.dumps({'chapterId': plan['chapterId'], 'form': plan['form'], 'voice': plan['voice'], 'tracks': tracks}, ensure_ascii=False, indent=2)
            + '\n',
            encoding='utf-8',
        )

    out_qa = HERE / 'out' / 'qa.json'
    out_qa.parent.mkdir(parents=True, exist_ok=True)
    out_qa.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    total_minutes = sum(item['durationMs'] for item in qa) / 60000
    print(f'\n完成 {len(qa)} 节 · 总时长 {total_minutes:.1f} 分钟 · 质检 → {out_qa}')
    if args.backend == 'mock':
        print('注意：mock 后端是静音占位，只验契约与时间轴，不能用来听。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
