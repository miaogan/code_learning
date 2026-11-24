# TTS 外部依赖登记（r151 · 2026-11-24）

> 口径：本仓库只包含音频流水线的**编排与入口**（`scripts/tts/make_audio.py`、`synthesize.py`、
> `scripts/finetune/` 的质量闸与起草脚本）。真正的合成能力（模型权重 / 运行环境 / 参考音 /
> LoRA）都在开发机本地，**不进仓库**——体积、第三方许可与音色授权三条原因。
>
> **发布前脱敏提示**：本文件与 `RELEASE-DATA-SOP.md` 中所有「受限音色」字样指代的是
> 未获授权公开发布的名人声音素材（身份信息只保留在本地 SOP 与训练记录里）。
> 对外发布本仓库前，需把受限音色的所有指代替换为通用描述或整体移除相关条目。

## 1. 外部依赖清单（丢哪条链路就断哪段）

| 路径（开发机本地） | 用途 | 来源 / 版本 | 断了怎么重建 | 红线 |
|---|---|---|---|---|
| `D:/work_space/_tts/VoxCPM/pretrained_models/` | VoxCPM2 主权重（~4GB，48kHz TTS） | 开源模型官方发布（HuggingFace/ModelScope 离线下载） | 重新下载并核对 `config.json` 的 `architecture=voxcpm2`；`synthesize.py --vox-model-dir` 指过去即可 | 无 |
| `D:/work_space/_tts/VoxCPM-main/` | VoxCPM 推理代码（`from voxcpm import VoxCPM`） | 第三方开源仓库克隆 | 重新 clone；`sys.path.insert` 由 `synthesize.py` 自动处理 | 无 |
| `D:/work_space/_tts/venv_voxcpm/` | Python 运行环境（torch≥2.5.1+cu121、voxcpm、numpy） | 官方 torch wheel + VoxCPM 依赖安装 | `python -m venv` 重建后按 README 装依赖；注意 transformers 声称需要 torch≥2.6 的告警可忽略（推理正常） | 无 |
| `D:/work_space/_tts/dataset/slices/*.wav` | 零样本参考音（`--vox-ref`） | 内部切片（**受限音色**） | 不可重建，须换成合规参考音（本人录制 / CC0 素材 / 授权录制，见 RELEASE-DATA-SOP §2 三条路径） | **法律红线：不得公开** |
| `D:/work_space/_tts/voxcpm_lora/` | 受限音色 LoRA（`--vox-lora`，仅本地试听） | 本地训练（训练栈在另一项目 `llm-finetune-lab`，ms-swift QLoRA） | 换合规音色后无需重建（不挂 LoRA 即零样本） | **仅本地试听，禁公开发布** |
| `D:\work_space\llm-finetune-lab\` | 写稿模型训练栈（ms-swift 4.5 + QLoRA 4bit）与 checkpoint v2 | 本地训练产物 | 训练数据在仓库 `scripts/finetune/out/`（jsonl 可复现），配置见其 `configs/spoken_sft_qlora.yaml` | 无 |
| `scripts/tts/out/audio_full/` | 当前全量合成产物（45 章，**受限音色**） | 本地合成 | 产物不入库；换合规音色后 `make_audio.py synth` 重跑（plans 已提交，断点续跑） | **产物不得 deploy/提交** |

## 2. 硬编码路径的落点（换机器要改的地方）

- `synthesize.py`：`--vox-model-dir`（默认 `D:/work_space/_tts/VoxCPM/pretrained_models`）、
  `--vox-repo`（默认 `D:/work_space/_tts/VoxCPM-main`）、`--vox-ref` 必填、`--vox-lora` 可选；
- `make_audio.py watch/synth`：`--python`（voxcpm venv 解释器）；
- 其余（plan / index / deploy）均为仓库相对路径，无机器依赖。

## 3. 换机重建 checklist

1. clone 本仓库 → `frontend/`、`backend/` 按各自 README 装依赖；
2. 下载 VoxCPM2 权重 + clone 推理代码 → 建 `venv_voxcpm`；
3. 准备**合规参考音**（过 RELEASE-DATA-SOP §1 四必要条件）；
4. 创建 `scripts/tts/voice_compliant.marker`（内容一行：音色说明 + 日期）——这是
   `watch` 自动发布的唯一开关，不存在时产物只留本地；
5. `make_audio.py plan → synth → deploy`（或直接 `watch` 常驻）。

## 4. 自动发布守卫（watch 的合规红线）

`make_audio.py watch` 会自动「新章合成 → 聚合索引 → deploy → git 提交」，但**发布被双重闸住**：

1. `voice_compliant.marker` 不存在 → 只合成，不 deploy、不提交；
2. `--deploy-dir` 非 `audio`（仓库目录）→ 只拷贝到试验目录，不做 git 操作。

受限音色（gdg 等）跑出的产物因此**永远不可能被自动带进仓库**——除非有人手工创建标记，
而创建标记这个动作本身就是「确认音色合规」的签字。
