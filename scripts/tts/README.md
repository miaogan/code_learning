# 口播稿音频合成链（r150 / M1 制作工具链）

> 定位：**离线生产工具**。音频是发布资产，运行期零 TTS、零新增出网（VERSION-PLAN C1/C4）。
> 合成在制作机（RTX 4070 Laptop 8GB）跑，产物走 `/audio/` 静态分发，不进 Git、不进镜像。

> **当前口径（2026-11-23）**：音频生产**唯一后端是 VoxCPM2**，CosyVoice（CV2/CV3）
> 已全量归档到 `D:/work_space/_archive/sc_tts_cosyvoice_2026-11-23/`。
> 主线两种方式：零样本 `--vox-ref`（发布用合规音），或挂 `--vox-lora`（gdg 音色仅本地试听）。
> `out/audio/` 原 12 节 CV2 产物也已归档，前端音源改指向 VoxCPM2 LoRA 样片。

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

## 3. 音频生产（VoxCPM2）

主线只有 VoxCPM2；零样本用 `--vox-ref`，可选用 `--vox-lora` 挂音色 LoRA
（**gdg 系素材及 LoRA 仅供本地试听，不得发布**）。

```bash
D:/work_space/_tts/venv_voxcpm/Scripts/python.exe scripts/tts/synthesize.py \
  --backend voxcpm --vox-ref <合规参考音> --plan-dir scripts/tts/out/plans_gen
```

> **CosyVoice 已全量归档（2026-11-23）**：CV2/CV3 权重、仓库、后端代码、12 节产物、
> AB 评测全部移到 `D:/work_space/_archive/sc_tts_cosyvoice_2026-11-23/`（不删除，可还原）。
> 原因：主线定稿 VoxCPM2；AB 实测 CV2 情绪相对变异 27.3% vs CV3 9.1%，
> 但 CV2 参考音授权存疑、CV3 带宽不合格。命令与踩坑记录见归档 `INDEX.md`
> 和 `code/synthesize_cv_backup.py`。发布合规口径见 `RELEASE-DATA-SOP.md`。

## VoxCPM2 工具链（r150 后期新增）

四个脚本，覆盖「拿权重 → 验环境 → 挑参考音 → 合成 → 量质感」：

| 脚本 | 作用 | 典型用法 |
|---|---|---|
| `fetch_weights.py` | 从 **ModelScope** 并行分块下载 + sha256 校验；也支持直给 URL | `--repo OpenBMB/VoxCPM2 --out <dir>` |
| `smoke_voxcpm.py` | 30 秒环境冒烟：能加载、能出声、带宽正常 | 换机器后先跑这个 |
| `screen_dry_refs.py` | 扫切片库按「最干」排序，直接给 `--ref` 路径 | `--dir <slices> --top 12` |
| `infer_voxcpm.py` | 正式推理：参考音只编码一次、多句复用、可开音色延续 | `--ref X --text-file L --out Y` |
| `measure_echo.py` | 回音体检：衰减斜率 / t20 / 谷底 | 判断「有回音」到底来自哪 |

**下载一定要走对源**（这是本次最大的时间黑洞）：

- HF / hf-mirror 实测 **0.2–0.8MB/s**（4.4GB 要 6 小时）；同一份模型在 **ModelScope
  是 12–40MB/s**。国内团队（OpenBMB / 阿里 / 智谱）优先去魔搭。
- PyTorch 轮子：官方源 0.25MB/s；**阿里云 `mirrors.aliyun.com/pytorch-wheels/cu121/`
  配 12 路分块是 20MB/s**。单连接会被限速，并行才有用。
- **Windows 上别用 `os.open` + `os.write` 写二进制**：缺 `O_BINARY` 时 fd 是文本模式，
  `\n` 会被翻成 `\r\n`，整块数据错位——文件大小对、开头魔数对，但内容全坏。
  用 `open(path, 'r+b')`。而且**只校验大小抓不到这种损坏，必须校验 sha256**。

**CFG 的正确用法**（实测反直觉）：

- `cfg_value` 调高能补高频，但**同时把衰减尾巴拉长**（1.5→4.5 时 186ms→363ms），
  听感就是回音加重。所以默认 1.5，需要补高频时小步上调并端到端复测。
- 想解决回音，优先级是「**换更干的参考音**」> 调 CFG。混响是参考音频谱包络的一部分，
  模型会一起克隆（输出 t20 186ms ≈ 参考音 174ms）。
- 但「参考音最干」≠「输出最干」：`ep2-0253`（73ms，最干）配 cfg2.0 输出 244ms，
  `ep3-0386`（110ms）配 cfg1.5 才 100ms。**必须测输出，不能只看参考音指标。**

## 单口相声流水线（r150 当前主线）

用户决定先做单口，对口搁置。入口只有一个：

```bash
# 单口章（默认只跑 form=solo，duo 章自动跳过并打印提示）
D:/work_space/_tts/venv_voxcpm/Scripts/python.exe scripts/tts/synthesize.py \
    --backend voxcpm --vox-ref D:/work_space/_tts/dataset/slices/ep3-0386.wav
```

**为什么必须用 `venv_voxcpm` 的解释器**：VoxCPM2 要 torch≥2.5，CosyVoice 那套是 2.3.1，
两者不能共存。用错解释器会在 import 阶段报错，脚本会提示正确路径。

单口相比对口只改节奏，不改模型（详见 TTS-GAP-REVIEW §2.14）：

| 参数 | 作用 |
|---|---|
| `--punch-hold-ms 900` | 包袱落地后的留白（= 给观众笑声留位置）。单口最像「说相声」的一下 |
| `--no-pace-scale` | 关闭按情绪缩放停顿（默认开：铺垫 0.95 收、收尾 1.25 拖） |
| `--only-form all` | 连 duo 章一起跑（抢话逻辑仍生效，但当前不做） |
| `--recue-only` | 只重算句级时间轴，不重跑 TTS（秒级） |

**两个质量闸，改切分逻辑前先读**：

1. **`trim_edges` 不能用固定阈值**。VoxCPM2 句首静音的底噪偶尔会短暂越过 −44dB，
   固定门限会停在那里留下 0.5–1s 静音。现在按包络分位数自适应（底噪 10 分位、
   语音 90 分位、门限在两者之间 8% 处）。
2. **`build_cues` 不能按字数摊句长**。实测 41.5% 的 cue 起点落在静音里，播放器高亮会提前跳。
   现在从音频检测内部停顿（`split_lines()`），并且：
   - 切点放在**停顿结束处**（下一句开口），不是停顿中点
   - **首段要对齐到真正开口**，单句 unit 也不例外（这里踩过一次：`n_lines<=1` 早退绕过了对齐）

改完用 `--recue-only` 重算即可验证，不必重跑 6 分钟的合成。
**对齐的验收指标：cue 起点落在有声处的比例应 = 100%**（当前 82/82）。
