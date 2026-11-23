# RVC 与语音栈实际使用整理（跨工作区，2026-11-23）

> **更正说明（第二版）**：上一版把 `_tts` 写成「独立测试场」，错了——`_tts` 是**本项目 r150 的语音实验工作目录**：
> `code_learning/scripts/tts/` 的所有默认路径都指向它（CosyVoice / PilotTTS / GPT-SoVITS / VoxCPM 的代码与权重、
> `voxcpm_ds` 数据集、`voxcpm_lora` 微调产物、`out_voxcpm_solo` 成品、`venv_voxcpm` 环境）。
> 换句话说，r150 的 TTS 产物不是「参考 `_tts`」，而是**就在 `_tts` 里生产**。
> 另一处 `alt_cunningham`（LDT 数字分身）是**相邻项目的 RVC 实战**，本项目只从它借参考音
> （`data/voices/xb3/da_feiyu/prompt.wav`），不共享 RVC 产物；严格意义的 RVC 只在那一边跑。

## 0. 一页速览

| 目录 | 项目 | 实际跑的框架 | 当前角色 | 状态 |
|---|---|---|---|---|
| `D:/work_space/code_learning` | 逃跑计划（SkillCoach）**本项目** | 驱动 `scripts/tts/`：CosyVoice2/3、PilotTTS、GPT-SoVITS、VoxCPM | 口播稿/相声音频合成 | r150 主线 |
| `D:/work_space/_tts` | **本项目 r150 的语音实验工作目录** | CosyVoice、GPT-SoVITS、IndexTTS / IndexTTS2、PilotTTS、VoxCPM（含 LoRA） | 存放代码/权重/数据集/环境/产物 | 本项目产物在这里生产 |
| `D:/work_space/alt_cunningham` | LDT 数字分身（相邻项目） | **RVC WebUI**、SoulX-Singer（SVC）、CosyVoice（CV2/CV3）、Kokoro、Edge TTS、ACE-Step、Fish-Speech（占位） | RVC 做实时变声 / DUET 备选；唱歌主线已换 SoulX-Singer-SVC | 已跑通、有产物；本项目只借其参考音 |

严格意义的 **RVC 只有一个**：`alt_cunningham/third_party/Retrieval-based-Voice-Conversion-WebUI`。
其余是 SVC（歌声转换）、SVS（歌声合成）与 TTS（文本转语音）框架，容易被统称为「变声/克隆框架」。

## 1. 先分清四类框架

| 类型 | 输入 → 输出 | 代表 | 在项目里的位置 |
|---|---|---|---|
| **RVC**（Retrieval-based VC） | 音频 → 同内容、目标音色音频 | RVC WebUI | 实时变声 / DUET、离线翻唱（旧主线） |
| **SVC**（歌声转换） | 干声 → 目标音色唱同一首 | SoulX-Singer-SVC | **唱歌主线**（`singing.engine: soulx_singer`） |
| **SVS**（歌声合成） | 歌词 + 旋律 → 歌声 | Fish-Speech / ACE-Step | 占位或实验，非主线 |
| **TTS**（文本转语音） | 文本 + 参考音 → 语音 | CosyVoice2/3、PilotTTS、GPT-SoVITS、IndexTTS、VoxCPM、Kokoro、Edge | 说话链路 / 口播稿合成 |

RVC 与 TTS 的本质区别：RVC **不生成内容**，只把一段已有音频换成目标音色；TTS 才是从文本生成语音。

## 2. alt_cunningham 里的 RVC 实战

### 2.1 版本与位置

| 项 | 值 |
|---|---|
| 仓库 | `third_party/Retrieval-based-Voice-Conversion-WebUI` |
| 版本 | commit `81eed5e`，2026-08-04（多说话人训练 WebUI + CLI 命令） |
| 推理核心 | `infer.vc.modules.VC`（`vc_single`） |
| 模型目录 | `assets/weights/`；索引 `assets/indices/` |
| 项目侧入口 | `ldt-mvp/services/singing/` 四件套 |

### 2.2 已训练的模型（不是只跑官方 demo）

`assets/weights/` 里有一批自己训练的 `.pth`，并配套 `.index`：

| 模型 | 索引 | 说明 |
|---|---|---|
| `aatrox.pth` | `aatrox_added_IVF555_Flat_nprobe_1_aatrox_v2.index` | 剑魔，主用；另有 `aatrox_e10_s400` 到 `aatrox_e200_s8000` 共 20 个 epoch checkpoint，做过轮数扫描 |
| `hanser.pth` | 无独立 index | 陈汉桑，做过 `p0~p5` 音高扫描 |
| `kugimiya_luna.pth` / `kugimiya_vyrn.pth` | 各自 `.index` | 钉宫理惠两个角色，做过 `p0/p4` 对比 |
| `taiga.pth` | `taiga.index` | 逢坂大河，做过 fast/emo 对比 |
| `smokefull2.pth` | `smokefull2_..._v2.index` | 冒烟/全流程验证模型 |
| `vm-e7a0354f.pth` | `vm-e7a0354f_..._v2.index` | 训练服务产出的模型（模型管理页链路） |

这说明不是「装了个 WebUI 点两下」，而是**完整走过数据准备 → 训练 → 建索引 → 参数扫描 → 成品混音**。

### 2.3 代码结构（四件套）

| 文件 | 职责 |
|---|---|
| `services/singing/svc_rvc_sing.py` | 两层设计：`RVCInferCore`（进程内 torch 内核，只在 `.venv-ml` 跑）/ `RVCSingEngine`（py313 主进程编排器，子进程调用 worker） |
| `services/singing/rvc_worker.py` | 子进程 worker：在 ML 环境跑一次完整转换，stdout 打 `RVC_WORKER_OK` 标记 |
| `services/singing/rvc_pipeline.py` | 纯函数后处理：人声分离子进程、噪声门、mid/side 净化、响度对齐、低通、混音 |
| `services/singing/rvc_cover.py` | 端到端 CLI：分离 → 转换 → 后处理 → 混音，一键出成品 |

**关键工程决策**：API 主进程跑系统 Python 3.13、不装 torch（避免搅乱 1664 条测试基线），
所以 RVC 推理全部拆到 `.venv-ml` 子进程；顺带修掉了旧实现 `os.chdir(rvc_root)` 污染主进程工作目录的副作用。

### 2.4 五步流水线

```
歌曲 → [1 karaoke 人声分离] → 干声 + 伴奏
     → [2 RVC vc_single 转换] → 目标音色人声
     → [3 低通柔化 + 噪声门]   → 去电音 / 压静音段电流声
     → [4 mid/side 净化伴奏]   → mid×0.18 压残留原唱
     → [5 响度对齐 + 混音]     → 立体声成品
```

### 2.5 参数与调参结论

代码默认值（`svc_rvc_sing.py` / `rvc_cover.py` 一致）：

| 参数 | 默认 | 作用 | 实测口径 |
|---|---|---|---|
| `pitch` | 0 | 半音升降调 | 音准优先靠训练模型 + pitch=0，别用 pitch_shift 硬拉（音色会变形） |
| `index_rate` | 0.75 | 索引检索占比 | 越高越像、越容易生硬；扫描过 0 / 0.3 / 0.5 |
| `protect` | 0.33 | 清辅音/呼吸保护（0~0.5） | 扫描过 0.10 / 0.33，减轻电子味 |
| `f0_method` | `rmvpe`（唱歌用 `rmvpe_sing`） | 音高提取 | 唱歌的 F0 比说话更精确 |
| 低通截止 | 9000 Hz | 柔化电音 | 固定后处理 |
| 输出响度 | RMS 0.25 起扫 | 对齐成品 | 扫描过 0.25 / 1.0 |

`samples/` 里的文件名就是参数扫描证据：`param_idx0.0_prot0.33_rms0.25.wav`、
`param_idx0.3_prot0.10_rms0.25.wav`、`param_idx0.5_prot0.33_rms0.25.wav`、
`hanser_pitch_p0~p5.wav`、`kugimiya_rvc_idx0.wav` 等。

### 2.6 环境

- 统一 `.venv-ml`：Python 3.11.16 + torch/torchaudio/torchvision **2.6.0+cu124**，151 包。
- 官方要求 RVC 2.7.1+cu128、SoulX 2.2.0，**实测不是硬约束**：两者在 2.6.0+cu124 下 import 与推理都正常，共用一套省约 10GB。
- 旧 conda 环境（`rvc` / `soulxsinger` / `.venv-singing`）已废弃，文档里明确「别再照抄」。
- 人声分离仍走子进程（分离模型会 chdir + 改 sys.path，隔离进程避免污染）。

### 2.7 实测数据（来自 DELIVERY / RVC_PIPELINE）

| 项 | 结果 |
|---|---|
| 30s teeth 片段转换 | `sr=40000 dur=30.0s`，成品 44.1kHz / peak 0.796 / rms 0.150 |
| teeth 全曲 | 成品 peak 0.815 / rms 0.149 |
| API 侧子进程探活 | 10.2s ready，主进程无 torch |
| 四链路 import | TTS / Wav2Lip / SoulX 模型+F0 / 分离 / RVC 全通 |
| 测试基线 | 1676 passed / 12 skipped，新增 `test_rvc_sing.py` 12 例 |

### 2.8 已踩过的坑

1. **前奏/间奏电流声**：RVC 对静音段也检索 + 硬凑 F0 → 电子嗡鸣；用原干声包络做噪声门（env>0.01 + 200ms 淡入淡出）。
2. **`vc_single` 返回 int16**：pipeline 末段转 int16，引擎要 `/32768` 归一化回 float32。
3. **相对路径**：`weight_root` / `rmvpe_root` 必须在 load 前设好；RVC 内部 `i18n/configs` 读相对路径，工作目录须在 RVC 根（现在只在子进程 chdir）。
4. **音域物理限制**：低音音色（剑魔 70Hz）唱高音歌（319Hz+）零样本会发虚跑调；训练模型学过各音高样本才「喊得上去」。
5. **输出目录**：`--no-mix` 分支原来不 mkdir，推理几十秒后才在 `sf.write` 报 `LibsndfileError`，已修。
6. **旧路径写死**：曾写死 `D:/work_space/beta_cunningham/...` 和 conda 解释器，目录改名/conda 卸载后全部失效；现改为按仓库相对位置推 + `libs/pyenv.py:find_ml_python()` 统一探测。

### 2.9 当前定位（重要）

`agent.md` 的现状更正写得很明确：

- **唱歌主线 = SoulX-Singer-SVC**（`singing.engine: soulx_singer`，零样本、免转录/MIDI、Apache-2.0、<8GB）。
- **RVC 只留实时变声 / DUET**（`configs/default.example.yaml` 的 `rvc_model: models/rvc/self.pth`，麦克风 → 变声 → 虚拟声卡，40ms 块）。
- `svc_rvc_sing` 引擎仍可切、仍可跑，但已不是离线翻唱的首选；`tts-engine-options-2026-10-28.md` 的 P1 就是「RVC 从离线翻唱退到实时 DUET」。
- 原因：SoulX 零样本 30s 参考音即可、不用训练；RVC 要 10~30 分钟数据 + 训练，只在实时性（40~50ms）上不可替代。

## 3. `_tts`：本项目 r150 的语音实验工作目录

`D:/work_space/_tts` 不是外部项目，而是 `code_learning` r150 的**外部依赖 + 产物区**：
`scripts/tts/` 的默认参数全部指向这里（`synthesize.py:621-657`、`train_voxcpm_lora.py`、`build_voxcpm_dataset.py`、`eval_voxcpm_lora.py` 等）。
统一 `.venv`（Python 3.12 + torch 2.3.1+cu121），VoxCPM 另用 `venv_voxcpm`（torch 2.5.1+cu121）：

| 目录 | 版本 / commit | 类型 | 测试状态 |
|---|---|---|---|
| `CosyVoice` | `074ca6d`（2026-05-26，含 CosyVoice3 类） | TTS / 零样本克隆 | 已装；CV2 权重在 `models/CosyVoice2-0.5B` |
| `GPT-SoVITS` | `6d51ffc`（2026-11-12） | TTS / few-shot 克隆 | 已装，含 `api_v2.py` |
| `IndexTTS` | zip 解压 | TTS / 零样本 | 已解压 |
| `IndexTTS2` | `2.0.0`（zip） | TTS / 零样本 | 已解压，含 checkpoints |
| `PilotTTS` | `c9083aa`（2026-06-02） | TTS / 情绪 + 副语言 | 已装，`pretrained_models` 在位 |
| `VoxCPM` / `VoxCPM-main` | zip / 源码 | TTS / LoRA 微调 | 已装，有 LoRA 训练产物 |

**本项目脚本 → `_tts` 路径映射**（默认值，可直接从代码核对）：

| 本项目脚本 | 默认指向 `_tts` 的路径 | 用途 |
|---|---|---|
| `synthesize.py` | `_tts/CosyVoice`、`_tts/models/CosyVoice2-0.5B`、`_tts/PilotTTS`、`_tts/GPT-SoVITS`、`_tts/VoxCPM(-main)` | 四个 TTS 后端的代码/权重 |
| `train_voxcpm_lora.py` | `_tts/VoxCPM-main`、`_tts/VoxCPM/pretrained_models`、`_tts/voxcpm_ds`、`_tts/voxcpm_lora/gdg_v1` | VoxCPM LoRA 训练 |
| `build_voxcpm_dataset.py` | `_tts/dataset/list_all.txt` → `_tts/voxcpm_ds` | 训练集构建 |
| `eval_voxcpm_lora.py` | `_tts/voxcpm_lora/gdg_v1/checkpoints/step_0000300`、`_tts/dataset/slices/ep3-0386.wav` | LoRA 评估 |
| `prepare_trainset.py` / `retranscribe_fw.py` | `_tts/GPT-SoVITS/tools`、`_tts/models/faster-whisper-large-v3`、`_tts/dataset/list_largev3.txt` | 切片与转写 |
| `smoke_voxcpm.py` / `infer_voxcpm.py` | `_tts/venv_voxcpm`、`_tts/VoxCPM-main` | VoxCPM 冒烟/推理 |

配套数据与产物：

- **数据集**：`dataset/list.txt` 671 条、`dataset/list_largev3.txt` 2003 条、`dataset_t3/list.txt` 134 条；`dataset/raw`、`slices`、`refs_pp`、`infer` 分目录。
- **VoxCPM LoRA**：`voxcpm_lora/gdg_v1/train_config.yaml` —— 16k 输入 / 48k 输出、LoRA r=32 / alpha=32、LM+DiT 的 q/k/v/o 全开、150 iters、batch 1 + grad_accum 8、lr 1e-4。
- **VoxCPM 合成质检**：`out_voxcpm_solo/qa.json` —— 3 节 solo，duration 63.3s / 63.7s，silenceRatio 0.465~0.471，LUFS -22.0。
- 这些实验与 `code_learning` r150 的 `TTS-GAP-REVIEW.md`、`TECHNICAL.md` §11–13 是同一批下游验证。

## 4. 与 code_learning r150 的关系

`code_learning` 的口播稿链路本身**不含 RVC**，只做「文本 → TTS → 时间轴 → 质检」：

- 当前后端：CosyVoice2/3、PilotTTS；实验过 GPT-SoVITS、VoxCPM LoRA。
- 已定位的瓶颈：**编排**（重叠率 0%、切换间隙过大）和**参考音质量**（4.1s 合成音），不是合成器。
- RVC 对这两点都帮不上：它不改时间轴，也不生成内容；只能做「音色后处理」或「实时变声」。
- 若要在 r150 用 RVC，合理位置是：TTS 出干声 → RVC 统一到固定 IP 音色，或对口章做双音色后处理；但会引入二次编码损失与 GPU 依赖，需盲听对照。

## 5. 现状结论

1. **RVC 确实用过，而且用得很完整**——在 `alt_cunningham`，训练了 6+ 个音色模型、扫过 epoch/pitch/index/protect/rms，跑通了 30s 与全曲成品。
2. **但 RVC 已从「离线翻唱主线」退居「实时变声/DUET 备选」**，唱歌主线换成 SoulX-Singer-SVC（零样本、免训练、Apache-2.0）。
3. **`_tts` 是本项目 r150 的语音实验工作目录**，不是外部测试场：代码/权重/数据集/LoRA/成品都在这里，`scripts/tts/` 只是驱动。
4. **本项目（code_learning）只用 TTS，不用 RVC**；r150 的瓶颈是编排与参考音，不是缺一个变声框架。RVC 实战在相邻的 `alt_cunningham`，与本项目只共享参考音。

## 6. 路径索引

| 内容 | 路径 |
|---|---|
| RVC 仓库 | `D:/work_space/alt_cunningham/third_party/Retrieval-based-Voice-Conversion-WebUI` |
| RVC 模型/索引 | 同上 `assets/weights/`、`assets/indices/` |
| RVC 流水线文档 | `alt_cunningham/ldt-mvp/services/singing/RVC_PIPELINE.md` |
| 引擎代码 | `alt_cunningham/ldt-mvp/services/singing/{svc_rvc_sing,rvc_worker,rvc_pipeline,rvc_cover}.py` |
| 引擎选型调研 | `alt_cunningham/ldt-mvp/docs/singing-engine-survey.md`、`tts-engine-options-2026-10-28.md` |
| 交付记录（RVC 子进程化/实测） | `alt_cunningham/ldt-mvp/docs/DELIVERY.md` §4.47–4.49 |
| 交接现状 | `alt_cunningham/agent.md` 顶部「2026-10-28 现状更正」 |
| 本项目语音实验目录（依赖+产物） | `D:/work_space/_tts/{CosyVoice,GPT-SoVITS,IndexTTS,IndexTTS2,PilotTTS,VoxCPM}` |
| VoxCPM LoRA | `D:/work_space/_tts/voxcpm_lora/gdg_v1/train_config.yaml` |
| r150 语音评审 | `code_learning/docs/teamflow/20261121-r150-learning-modalities/TTS-GAP-REVIEW.md` |
