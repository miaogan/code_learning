# 口播稿音频合成链（r150 / M1 制作工具链）

> 定位：**离线生产工具**。音频是发布资产，运行期零 TTS、零新增出网（VERSION-PLAN C1/C4）。
> 合成在制作机（RTX 4070 Laptop 8GB）跑，产物走 `/audio/` 静态分发，不进 Git、不进镜像。

## 1. 链路

```
口播稿（frontend/src/content/spoken/*.ts）
  └─ scripts/export_spoken_audio.mjs ──► out/plans/<chapterId>.json      音频计划（合成单元 + 停顿）
        └─ scripts/tts/synthesize.py ──► out/audio/<chapter>/<section>.wav
                                         <section>.timeline.json         句级时间轴（播放器用）
                                         <chapter>/manifest.json         章节清单（播放器只读这份）
                                         out/qa.json                     质检（时长 / 句数 / 峰值 / 静音比）
```

**唯一真源是口播稿**：改稿 → 重新导出 → 重新合成。计划 JSON 里的停顿来自情绪表，驱动不二次猜。

## 2. 两步跑通（不依赖 GPU）

```bash
cd frontend && node ../scripts/export_spoken_audio.mjs   # 3 章 → 3 份计划（12 节 / 159 单元）
cd .. && python scripts/tts/synthesize.py --backend mock --limit-sections 2
```

mock 后端生成**等长静音** + 比例时间轴：用来先把播放器、断点续听、句级高亮的契约跑通，
不能拿来听。产物结构与真合成完全一致，播放器不需要为 mock 写分支。

## 3. 真合成（CosyVoice2-0.5B，Apache-2.0）

**实际跑通的环境（2026-11-22 实测，别再从头试）**：

| 件 | 路径 / 版本 |
|---|---|
| Python | `D:/ProgramData/miniconda3/envs/cosyvoice/python.exe`（torch 2.3.1+cu121，非 lab venv） |
| CosyVoice 代码 | `D:/work_space/_tts/CosyVoice`（**新克隆这份**；`alt_cunningham/third_party/CosyVoice` 的 `weights_only=True` 与这份权重不兼容，会 `UnpicklingError`） |
| 权重 | `D:/work_space/_tts/models/CosyVoice2-0.5B`（modelscope 下载，21 文件 / 2.0GB） |
| 参考音 | `alt_cunningham/ldt-mvp/data/voices/xb3/da_feiyu/prompt.wav`（中文女声；0.5B 版 `spk2info` 为空，必须给参考音） |
| 依赖补丁 | `scripts/tts/stubs/wget.py`（PyPI 的 wget 在本机反复校验失败，推理用不到它） |

```bash
cd D:/work_space/code_learning
D:/ProgramData/miniconda3/envs/cosyvoice/python.exe scripts/tts/synthesize.py   --backend cosyvoice   --repo-dir D:/work_space/_tts/CosyVoice   --model-dir D:/work_space/_tts/models/CosyVoice2-0.5B   --prompt-wav D:/work_space/alt_cunningham/ldt-mvp/data/voices/xb3/da_feiyu/prompt.wav   --chapter mw-cache-strategy --limit-sections 1
```

首节实测（`mw-cache-strategy/where`）：14 个合成单元 / 32 句 cue / **152.8 秒** / RTF 0.84–0.87 /
峰值 32439（接近满幅，说明没被判静音，也提示要做响度归一化）。

### 踩坑：instruct 必须带 `<|endofprompt|>`

第一版音频**把情绪指令念了出来**（开头是「就像跟朋友聊天，随便点儿，语速偏快…」）。
根因不是模型能力，是调用约定：`inference_instruct2` 把 instruct 当 `prompt_text` 喂给 LLM，
官方示例（`example.py:57`）的 instruct 结尾必须带 **`<|endofprompt|>`**，长描述同样会被念。

- 正确：`'用开心的语气说这句话<|endofprompt|>'`
- 错误：`'就像跟朋友聊天，随便点儿，语速偏快，别端着'`（无结束符 + 描述性长句）

验证方法：合成后跑 whisper 转写，开头出现指令文本就说明又踩了。
驱动里已加 `<|endofprompt|>` 与「缺结束符直接退出」的防御。

修复前后同节对比：`mw-cache-strategy/where` 152.8s（含念指令）→ **88.1s**（正常）。

### 试听结论：CV2 的 instruct 太弱，换 CosyVoice3

修好结束符后，指令不再被念，但**语气也没真正生效**。客观量化（`analyze_emotion.py`，按句切段量基频/能量）：

| 模型 | 12 节全量·类间基频极差 | 四种反差指令（开心/悲伤/生气/平静） |
|---|---|---|
| CosyVoice2-0.5B | **6.0 Hz**（≈没区分） | 时长 3.56–3.88s、基频无方向，悲伤只是音量小 |
| Fun-CosyVoice3-0.5B | 单节 16.6 Hz（全量待测） | **悲伤 10.2s vs 平静 3.2s**（慢 3 倍）、开心/生气更响 |

结论：这一层是**模型代际差异**，不是调用约定。驱动已支持 `--model-kind auto|cv2|cv3`（按 `cosyvoice3.yaml` 自动识别），
默认建议用 CV3。注意 CV3 的构造参数不同（无 `load_jit`，用 `load_vllm`）。

### 第三层：情绪词 + 语速（当前方案）

七词探测（同一句、同一参考音，CV3）：轻松/自信/平静/兴奋/惊讶/无奈/温柔 的基频 247–264Hz、时长 4.16–4.84s——**只靠 instruct 拉不开**。
但 `speed` 参数很有效：0.85→5.6s、1.35→3.82s（约 1.7 倍跨度）。

于是改成组合拳：**instruct 只管音色冷暖（基础情绪词），speed 管快慢（喜剧节奏）**。

| 情绪 | instruct | speed |
|---|---|---|
| banter | 用轻松的语气说这句话 | 1.10 |
| setup | 用自信的语气说这句话 | 1.00 |
| deadpan | 用平静的语气说这句话 | 0.92 |
| punch | 用兴奋的语气说这句话 | 1.15 |
| realize | 用惊讶的语气说这句话 | 1.05 |
| contrast | 用无奈的语气说这句话 | 1.00 |
| wrap | 用温柔的语气说这句话 | 0.88 |

实测（可听章 2 节、CV3）：类间基频极差从 **7.6 Hz → 31.4 Hz**（punch 207.7Hz 压低、contrast 239.1Hz 偏高），
说明「基础情绪词 + 语速」才拉得开。**自创的表演腔（「先轻后重」「收尾咬住」）模型基本不认，别再往里加。**

### 换机器 / 重建环境（未验证，仅供参照）

```bash
git clone --depth 1 https://github.com/FunAudioLLM/CosyVoice.git D:/work_space/_tts/CosyVoice
git -C D:/work_space/_tts/CosyVoice submodule update --init --recursive --depth 1
# 用 conda 建 Python 3.10 环境（Windows 上 pynini 只有 conda-forge 有 wheel）
conda create -n cosyvoice -y python=3.10
conda install -n cosyvoice -y -c conda-forge pynini=2.1.6
pip install torch==2.3.1 torchaudio==2.3.1 --index-url https://download.pytorch.org/whl/cu121
```

## 4. 质检口径

`out/qa.json` 每节一条：`units` / `cues` / `durationMs` / `estimateMs` / `peak` / `silenceRatio`。

| 指标 | 用来判断 |
|---|---|
| `durationMs` vs `estimateMs` | 偏差 > 40% 说明语速或停顿没按情绪表走 |
| `peak` | 接近 0 说明合成失败（静音）；接近 32767 说明爆音 |
| `silenceRatio` | 过高说明停顿堆太多或合成截断 |
| `cues` | 与口播稿句数一致；少了说明句子被合并 |

## 5. 已知限制

1. **句级时间轴是比例摊分**（按字数），不是 VAD 采样级对齐；M1 收尾要接 silero-vad 精修，
   播放器的高亮精度取决于这一步。
2. 每节一个 wav 是 pilot 形态；正式版按 §5.3 改 m4a（需要 ffmpeg，本机未验证转码）。
3. 音色只有「中文男」一个参考；对口章需要第二个能盲听区分的音色（§5.7），M2 补。
4. 没有做响度归一化与爆音检测（只报 peak）。
5. CosyVoice2 权重与代码是 Apache-2.0；**生成的音频许可口径仍待产品拍板**（VERSION-PLAN §7.2 第 3 条）。
