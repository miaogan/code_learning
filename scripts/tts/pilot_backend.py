"""PilotTTS 后端（高德开源，Apache-2.0）：情绪标签驱动的合成。

为什么加它：CosyVoice 的 instruct 只能做「音色冷暖」的粗调（r150 实测类间基频极差 10–36Hz 且方向不稳），
PilotTTS 是**显式情绪标签 + 副语言标记**（happy/sad/angry/surprise/serious/blue/… 与 LAUGH/BREATH/CRY/COUGH），
同一句的能量差可达 2 倍以上，更接近"在演"而不是"在念"。

用法（由 synthesize.py 调用）：
    --backend pilot --pilot-repo D:/work_space/_tts/PilotTTS
    --checkpoint pretrained_models/pilot_tts_instruct.pt（相对 pilot-repo）

已知环境坑：wetext 的 Normalizer 每次初始化都会向 ModelScope 请求 revisions，
现在匿名访问返回 403（`Authentication token does not exist`）。本地缓存里有模型，
所以这里把 `wetext.wetext.snapshot_download` 直接指向缓存目录。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# 我们的 7 类口播情绪 → PilotTTS 情绪标签（None = 不加标签，用模型默认）
EMOTION_MAP = {
    'banter': 'happy',
    'setup': 'serious',
    'deadpan': None,
    'punch': 'surprise',
    'realize': 'surprise',
    'contrast': 'blue',
    'wrap': 'serious',
}

DEFAULT_CHECKPOINT = 'pretrained_models/pilot_tts_instruct.pt'
DEFAULT_CONFIG = 'configs/infer_pilot_tts_instruct.yaml'


class PilotBackend:
    def __init__(self, repo_dir: str, checkpoint: str = DEFAULT_CHECKPOINT,
                 config: str = DEFAULT_CONFIG, prompts: dict[str, str] | None = None,
                 prompt_wav: str | None = None):
        # 先转绝对路径：下面会 chdir 到 PilotTTS 目录，相对路径会失效
        prompt_wav = str(Path(prompt_wav).resolve()) if prompt_wav else None
        prompts = {k: (str(Path(v).resolve()) if v else None) for k, v in (prompts or {}).items()}
        repo = Path(repo_dir).resolve()
        if not (repo / checkpoint).exists():
            sys.exit(f'PilotTTS 权重不存在：{repo / checkpoint}（先按 README 下载 AmapVoice/PilotTTS）')

        cache = Path.home() / '.cache' / 'modelscope' / 'hub' / 'pengzhendong' / 'wetext'
        try:
            import wetext.wetext as wetext_impl

            wetext_impl.snapshot_download = lambda *a, **k: str(cache)  # 绕过 403
        except Exception:
            pass

        # PilotTTS 的配置与 demo 用相对路径，加载期临时切到仓库目录，加载完必须切回来，
        # 否则驱动后续的相对输出路径会落到 PilotTTS 目录里（r150 实测踩过）。
        cwd = os.getcwd()
        os.chdir(repo)
        try:
            sys.path[:0] = [str(repo), str(repo / 'third_party'), str(repo / 'third_party' / 'Matcha-TTS')]
            from demo import load_engine  # noqa: PLC0415 - 依赖 sys.path 调整
            from demo import synthesize as demo_synthesize  # noqa: PLC0415

            self._synthesize = demo_synthesize
            self.engine = load_engine(config_path=config, checkpoint=checkpoint)
        finally:
            os.chdir(cwd)
        self.prompt_default = prompt_wav
        self.prompts = {'dou': prompt_wav, 'peng': prompt_wav, 'narrator': prompt_wav}
        for speaker, path in prompts.items():
            if path:
                self.prompts[speaker] = path

    def synthesize(self, unit: dict) -> tuple[bytes, int]:
        """返回（16-bit PCM 字节, 时长 ms）。采样率由驱动按 24000 处理。"""
        import soundfile as sf

        text = '，'.join(unit['lines']) + '。'
        prompt = self.prompts.get(unit['speaker']) or self.prompt_default
        if not prompt:
            sys.exit('PilotTTS 需要参考音：传 --prompt-wav')
        emotion = EMOTION_MAP.get(unit['emotion'])

        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as handle:
            tmp = handle.name
        try:
            self._synthesize(self.engine, text=text, prompt_wav=str(prompt), emotion=emotion, output_path=tmp)
            audio, rate = sf.read(tmp, dtype='float32')
        finally:
            Path(tmp).unlink(missing_ok=True)

        import numpy as np

        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if rate != 24000:
            sys.exit(f'PilotTTS 输出采样率 {rate}，驱动按 24000 处理，请检查声码器')
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype('<i2').tobytes()
        return pcm, int(len(audio) / rate * 1000)
