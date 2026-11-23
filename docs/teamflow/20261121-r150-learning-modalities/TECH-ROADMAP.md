# 语音技术线路图（r150 · 2026-11-23）

> 本文汇总 r150 语音链路的**技术栈现状、里程碑路线与决策点**，作为 `TTS-GAP-REVIEW.md`、
> `VERSION-PLAN.md`、`FINETUNE-PLAN.md`、`RVC-FRAMEWORK-NOTES.md` 的顶层索引。
> 数字均有实测出处，标注见括号内引用。

## 1. 全景：两条线，一个原则

```text
线 A（code_learning / r150 有声书主线）
  口播稿 JSON ──> TTS 合成 ──> 编排/混音 ──> 离线 m4a 资产 ──> 静态分发（443）
  制作期GPU本机                    发布资产不进仓库（C7）    运行期零出网（C4）

线 B（alt_cunningham / LDT 数字分身）
  MIRROR 替身：麦克风 ──> RVC 实时变声 ──> 换脸 ──> 推流（延迟 ≤200ms）
  AVATAR 自主：文本 ──> LLM ──> TTS ──> 口型驱动（开口 ≈1.2s）

原则：编排 > 模型。实测裁静音+抢话把间隙中位 1245ms→105ms，
远大于任何一次换模型的边际收益（TTS-GAP-REVIEW）。
```

## 2. 分层技术栈（当前状态标注）

| 层 | 选型 | 状态 | 说明 |
|---|---|---|---|
| 写稿层 | 提示词 + （规划）QLoRA 微调 4B | 提示词版在用 | 微调方案已评审（`FINETUNE-PLAN.md`），等 45 章数据铺完（M2） |
| TTS 层 | **VoxCPM2（定稿）** | **唯一在用** | 原生 48kHz，CFG 1.5，独立 `venv_voxcpm`（torch≥2.5）；发布走零样本合规参考音，gdg LoRA 仅本地试听 |
| TTS 层（旧） | CosyVoice2 / CosyVoice3 | **已全量归档** | 2026-11-23 用户决定不用 CV：权重/仓库/代码/产物 → `_archive/sc_tts_cosyvoice_2026-11-23/`，可还原；AB 结论见归档内 `CV2-VS-CV3-AB.md` |
| TTS 层（备选） | PilotTTS（情绪标签最强）、GPT-SoVITS、IndexTTS2 | 验证未选中 | PilotTTS 与 CosyVoice 共用 `.venv` |
| 编排层 | `synth_duo.py` 时间轴 | **最大瓶颈** | 裁首尾静音、抢话叠音、观众反应轨（§4.1/4.2）未做 |
| 评测层 | `style_profile.py` + 盲听 | 基线缺失 | 先量相声原声的目标值（重叠率/间隙分布），再调参 |
| 变声层 | RVC WebUI `81eed5e` | 仅线 B | 6+ 自训音色；线 A 不用 |
| 唱歌层 | SoulX-Singer-SVC | 仅线 B | 零样本 30s 参考音，已取代 RVC 成唱歌主线 |
| 口型层 | Wav2Lip（有 NaN 坑）、MuseTalk 待接 | 仅线 B | 8GB 显存分时复用 |
| 分发层 | 静态 m4a + 前端播放器 | **r151 已上线**（播放器 + 听听入口 + nginx `/audio/`）；入口真源 `/audio/index.json`（索引驱动），生产因素材未授权显示「素材筹备中」态，素材上线=服务器放文件零发版；**全量流水线 `make_audio.py` 四阶段打通**（plan 185/185 过闸，synth 等合规参考音）——所有文字都有音频、新知识同链路（RELEASE-DATA-SOP §9） | 48kbps ≈8KB/s，3M 带宽不构成瓶颈（C6） |

## 3. 当前基线（素材与产物盘点，2026-11-23）

| 资产 | 位置 | 内容 | 约束/风险 |
|---|---|---|---|
| VoxCPM2 参考音 | `_tts/dataset/slices/ep3-0386.wav` | gdg（郭）切片，窄带 8k | **法律红线**：不得用于公开发布（§5） |
| VoxCPM2 成品 | `_tts/out_voxcpm_solo` | 4 节 243.7s | 未挂 LoRA，只依赖 `--vox-ref` |
| ~~CosyVoice 成品~~ | `_archive/sc_tts_cosyvoice_2026-11-23/artifacts/` | 12 节 842s（已归档） | 参考音授权存疑；前端已改指向 VoxCPM2 LoRA 版本地试听产物 |
| LoRA `gdg_v1` | `_tts/voxcpm_lora/gdg_v1` | 1718 条 gdg 数据，step_100；样片 `scripts/tts/out/lora_gdg_v1/` | **仅本地试听，禁止公开发布/进产品**（名人声音） |
| LoRA 训练集 | `_tts/voxcpm_ds/train.jsonl` | 1718 条 gdg + ref_16k | 换音色重训时需换数据源 |
| 诊断用逐字稿 | gdg/于逐字稿 | 仅供 2×2 内部诊断 | 不进产品、不留发布痕迹 |
| manifest 元数据 | `out_voxcpm_solo/*/manifest.json` | voice.model 写错（CosyVoice2） | 已由 `build_spoken_plan.py` 根治（按实际后端写）；历史 plans 重跑 build 即修正 |

## 4. 里程碑路线

### P0 · 编排修复（最高优先，半天~1 天）
1. `style_profile.py` 量出相声原声基线（重叠率、间隙分布）——**没有目标值，后面全是猜**
2. 时间轴从「串行」改「可重叠」：裁首尾静音 + 抢话叠音（实测收益最大的一项）
3. 观众反应轨（笑声/掌声垫底，情绪在制作期烘焙，符合 C3）

### P1 · 去郭换开源音色（半天~1 天，档 A）
- 选 8–15s 开源参考音（Common Voice CC0 / LibriTTS CC-BY / Emilia CC-BY，`_tts/emilia` 需重新下载）
- 换 `--vox-ref` + 重调 CFG（宽带参考音下 1.5 不一定最优，回音表现会变）
- 重合成 4 节 + cue 复核 + 盲听 → 过了再全量 12 节（档 A+，+1h）
- **禁挂 `gdg_v1` LoRA**；代码改动 ≤10 行（`synthesize.py`/README/`eval_voxcpm_lora.py`/`build_voxcpm_dataset.py` 默认值）
- **于谦（捧哏）音色**（用户已立项，2026-11-23）：找干净（宽带、无话筒杂声）参考音，或对现有素材加预处理（去混响/带限扩展）后再用；用户原话「等后面搞于谦的时候 找一下比较干净的 或者加一些预处理步骤」

### P2 · 数据成熟后的微调（M2 之后）
- 写稿模型：QLoRA 微调（`scripts/finetune/spoken_sft_qlora.yaml` 已就绪，185 条 × 8 轮 ≈ 368 步）
- **seed 冒烟已完成**（2026-11-22 00:09，llm-finetune-lab `outputs/spoken_sft_seed/v1`）：
  16/16 步、1 分 51 秒、峰值显存 4.5GiB（8GB 卡安全）；loss 1.84→1.10、eval_loss 1.27、token_acc ≈0.75，
  **链路已打通**。但 12 条数据下生成质量有典型小样本症状：
  长输出被截断（#1 2975 / rep11 版 6316 字符）、死循环复读（#4「这事儿得查」×17）；
  仅 #2 结构完整闭合。符合预期——**真实效果等 185 条数据（M2），seed 只验链路不判效果**。
- **决策门已测（2026-11-23）**：40 节抽审样人工改稿（Agent 代改，产出 `out/review_sample-edited.jsonl`，
  质量闸 40/40 全过）后，加权修改率 **5.0%**（≤20%）→ 判定「提示词版够用，微调属过度工程」。
  用户拍板**两条并行**：生产走提示词版；微调以学习为目的继续。
- **v2 训练已启动**（2026-11-23 12:02，`outputs/spoken_sft_qwen3_4b/v0-20261123-120224`）：
  47 训练（8 黄金 + 39 定稿）+ 5 评估（mw-observability 整章按章切分），96 步，
  数据双自检 100% 过闸。待观察：数据铺量后复读/截断是否缓解。
- 音色 LoRA（可选，档 B）：开源音频 30min–2h → 切片/转写 → 150 iters → `eval_voxcpm_lora.py` 评估，1–1.5 天
  - `gdg_v1`（郭，1718 条）已完成重训（2026-11-23，150 步），AB 对比听感通过；仅技术验证，不进发布产物

### P3 · 素材成熟 → 公开发布
- 换**本人素材**（录音规范见线 B roadmap §3：48kHz 单声道 WAV、零样本 10s / 微调 30min–2h）
- 素材清单 `assets/manifest.json`（source/license/hash），素材 hash ↔ 产物绑定，换素材只改配置
- 发布合规：AI 生成内容显式+隐式标识（《标识办法》）；只用本人或书面授权声音

### 插入式决策点（随时可做，成本半天）
- **2×2 交叉诊断**：我的稿×我的 TTS / 郭于稿×我的 TTS / 我的稿×真人 / 郭于原声——一次回答「文本还是配音在拖后腿」
- **真人录 3 章验证需求**（¥500–1000）：若真人版都没人听完，省下后续几十小时 TTS 工程

### 线 B（alt_cunningham，独立推进）
- MIRROR：RVC 实时变声 + 换脸，已在 8GB 笔记本跑通（30s teeth、peak 0.815）
- AVATAR：LLM+TTS+口型驱动串联，等本人形象/声音素材到位后启动
- 训练全部上云租卡（4090 ¥2–4/h，总成本 <¥50），本地只推理

## 5. 法律红线（不变）

- 效果可以接近，**声音不行**：《民法典》1023 条 2 款 + 北京互联网法院 AI 声音侵权第一案
- gdg 参考音、gdg LoRA 及其衍生产物**仅限技术验证**，不得发布
- 「京味儿」正确路径 = 授权/本人参考音 + 文本层儿化口语词

## 6. 资源与环境地图

| 环境 | 路径 | 用途 |
|---|---|---|
| `_tts/.venv` | Python 3.12 + torch 2.3.1+cu121 | CosyVoice / PilotTTS / GPT-SoVITS |
| `_tts/venv_voxcpm` | torch 2.5.1+cu121 | VoxCPM2（与上互斥，不能合并） |
| alt_cunningham `.venv-ml` | Python 3.11.16 + torch 2.6.0+cu124 | RVC / SoulX-Singer / 口型 |
| 本机 GPU | RTX 4070 Laptop 8GB | 推理 + QLoRA 训练；RVC 全量训练上云 |
| 生产机 | 2 vCPU / 3.6GB / 无 GPU | **只播放静态资产，绝不跑 TTS**（C5） |

## 7. 文档索引

| 文档 | 内容 |
|---|---|
| `VERSION-PLAN.md` | M1–M4 功能版本规划（硬约束 C1–C9） |
| `TECHNICAL.md` | M1 已落地部分（数据模型、质量闸、黄金稿） |
| `TTS-GAP-REVIEW.md` | TTS 差距量化 + 编排诊断 + 建议顺序 |
| `FINETUNE-PLAN.md` | 写稿模型 QLoRA 微调方案 |
| `RVC-FRAMEWORK-NOTES.md` | RVC 与 TTS 框架对照、`_tts`/`alt_cunningham` 盘点 |
| `RELEASE-DATA-SOP.md` | 可发布音频数据制作 SOP：音色合规替换、溯源清单、AI 标识、发布批次 |
| ~~`CV2-VS-CV3-AB.md`~~ | 已随 CosyVoice 归档 → `_archive/sc_tts_cosyvoice_2026-11-23/artifacts/`（CV2 情绪更好但 CV3 中英混排不跳音色） |
| 线 B `ldt-mvp/docs/digital-twin-roadmap.md` | MIRROR/AVATAR、素材采集清单、显存分时 |
