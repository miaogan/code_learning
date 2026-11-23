# 可发布音频数据制作 SOP（r150 · 2026-11-23）

> 回答一个问题：**当前链路里哪些产物能发布、怎么把「内部验证产物」变成「可发布资产」。**
> 上游依据：`VERSION-PLAN.md` C1–C9、`TTS-GAP-REVIEW.md` §4.3/§5、`TECH-ROADMAP.md` P3。
> 一句话口径：**当前所有含 gdg 音色的产物都是技术验证，不是发布候选；可发布数据 = 合规音色 + 过闸稿件 + 完整溯源 + AI 标识。**

## 0. 先判：现有产物能不能发？

| 产物 | 音色来源 | 能否发布 | 原因 |
|---|---|---|---|
| `scripts/tts/out/audio/` 12 节 | ⚠️ **不是内置 SFT 音色**：CV2 的 `spk2info` 为空，实际是官方仓库演示音 `asset/zero_shot_prompt.wav` 零样本克隆（plans 里的 `solo-adult-male` 只是标签） | ⚠️ **音质可发、授权存疑** | 成品带宽合格（6-8k 2.78%，CV2 有超分）；但参考音是官方 example.py 演示真人录音，README Disclaimer 说「some examples are sourced from the internet」，无明确商用授权 → **不建议作为正式发布音色**，除非确认该演示音授权。发布前另需：①音频许可口径拍板 ②AI 生成标识 |
| `_tts/out_voxcpm_solo/` 4 节 | gdg 参考音 `ep3-0386`（8k 窄带） | ❌ 不可发 | 名人声音，《民法典》1023 条 2 款 + 北京互联网法院 AI 声音侵权第一案 |
| `out/release_v1/` 4 节（AISHELL 参考音） | AISHELL-3（Apache-2.0） | ⚠️ 许可可发、音质不可发 | 许可干净但 6-8k 带宽仅 0.21–0.45%（门槛 1%），成品闷；仅流程验证 |
| `out/verify_v2/` 样片 | gdg_v1 LoRA（gdg 数据训练） | ❌ 不可发 | 名人声音衍生；仅内部验证，不进 `audio/` |
| `out/ab*/`、`duo*`、gdg LoRA 权重 | gdg / 合成参考音 | ❌ 不可发 | 已归档到 `_archive/sc_tts_out_2026-11-23/`，标注合规 |

**结论**：**当前没有「零风险、马上可发」的音色**。`out/audio/` 音质合格但参考音授权存疑；
正式发布仍建议走 A/B/C 路径拿明确授权的参考音。**稿件和编排链路两者通用。**

### 0.1 「默认音色」的真相与许可保留意见（2026-11-23 查证，已修正一次误判）

- **真相**：CosyVoice2-0.5B 没有 SFT 音色表（`spk2info` 实测为空），`synthesize.py::_make_prompt` 的注释明确写「必须给参考 wav」。
  `out/audio/` 实际用官方仓库 `asset/zero_shot_prompt.wav`（example.py 演示真人录音）做零样本克隆；
  plans 里的 `solo-adult-male` 只是**标签名**，不是内置 SFT spk_id。
- **音质不受影响**：参考音带宽 6-8k 仅 0.05%，但成品 `concept.wav` 达 2.78%（CV2 有超分能力）→ 音质合格。
- **授权存疑**：官方 README Disclaimer「Some examples are sourced from the internet」涵盖该演示音，无明确商用授权 → **不建议直接发布**，除非确认授权。
- **保留意见**：ModelScope `iic/CosyVoice2-0.5B` 模型页 License 字段为空（API 查询），代码 Apache-2.0 不自动等于权重许可；发布时应在致谢/版权声明写明模型来源。

## 1. 可发布数据的四个必要条件（缺一不可）

```text
① 音色合规  →  本人授权 / CC0 / CC-BY（可商用且署名）+ 模型权重许可放行
② 稿件合格  →  validate_spoken 门禁 + 人工抽检修改率 ≤35%（当前实测 5%）
③ 溯源完整  →  素材 manifest（source/license/author/url/hash）+ 产物 hash 绑定
④ 标识合规  →  AI 生成内容显式标识 + 隐式元数据（《标识办法》）
```

## 2. 音色替换：三条合规路径（按推荐度）

### 路径 A · 本人素材（推荐，发布最干净）
- **零样本**：8–15 秒，16bit/48kHz 单声道 WAV，安静环境、正常语速、带停顿笑意，首尾留 30–50ms
- **微调**（可选，相似度最高）：30 分钟–2 小时，同一麦克风/房间，每段 5–15 秒、段间 0.5s 静音
- 留**本人授权书**（即使自用也留档，平台申诉时用）
- 用法：换 `--vox-ref` 指向本人参考音；LoRA 若要训，用本人数据重训（`gdg_v1` 禁用）

### 路径 B · 开源素材（CC0 / CC-BY）
- 来源（2026-11-23 查证，**以官方许可为准**）：
  - **Common Voice**：CC0（Mozilla 官方条款），最干净；中文需 MDC/HF 获取
  - **LibriTTS**：CC-BY 4.0，英文，仅适合验证链路
  - **Emilia 主体：CC-BY-NC 4.0 → ❌ 不可用于可发布数据**（2025 年数据集卡明确；
    作者回复中仅 **Emilia-YODAS 子集是 CC-BY**，但其中文仅 0.3k 小时且需 HF 授权同意条款）
  - **StoryTTS**（ModelScope `CantabileKwok/StoryTTS`，60h 专业评书、表现力最强）、
    **da-fei-yu-girl-voice-zh**（52 条、44.1kHz）：均为 **CC-BY-NC → 仅技术验证可听，不可发布**
  - **矛盾点（2026-11-23 实测）**：CC 许可源里，AISHELL-3（Apache-2.0）中性朗读且带宽不合格；
    可发布的「CC-BY + 中文 + 高表现力 + 免注册直链」源**尚未找到**。可作为技术验证参照用 NC 源，
    正式发布仍需 Common Voice/WenetSpeech（需账号/密码）或本人/授权录制
  - **不要**：CC-BY-NC 任何素材用于带收益发布；数据集「原音频版权归原作者」的二次授权风险仍需自查
- 选带起伏的有声书/评书/播客片段，**不要新闻播报**、不要 ACG 角色音
- CC-BY 必须署名 + 附许可声明；**CC-BY-NC 不能用于带广告/收益的发布**
- 模型权重许可另核：CosyVoice2 / VoxCPM 代码 Apache-2.0，ChatTTS 是 CC-BY-NC（已排除）

### 路径 C · 外包授权录制（效果最好，成本几千元）
- 相声/评书演员录 30 分钟，形成**自有资产**，同时解决「京味儿」与授权

## 3. 制作流程（把当前工作流切到「发布模式」）

```text
[稿件] 写稿模型 v2 / 提示词版 → validate_spoken 门禁（当前 v2 20%，需桥接切长段）
        → 人工抽检 ≥20% → out/spoken_sft_train/eval（已就绪 47+5）
        ↓ build_spoken_plan.py
[计划] out/plans_gen/<chapter>.json（voice.model 必须如实写 VoxCPM2，不再写 CosyVoice2）
        ↓ synthesize.py --backend voxcpm --vox-ref <合规参考音> [--vox-lora <合规LoRA>]
[音频] out/release_v1/<chapter>/<section>.wav + timeline.json + manifest.json
        ↓ 质检
[质检] validate_manifest 300/300 + 响度 −23±2 LUFS + peak <0.95 + 音色盲听一致
        ↓ 打包
[发布] audio-pack-vX.tar.zst（版本号 ↔ 章节内容 hash 绑定，CI 检查）
        → AI 标识（显式角标 + 隐式元数据）→ 独立分发通道（不进 git，C7）
```

### 当前链路的三个「发布前必改」点
1. **manifest 元数据错误**：`out_voxcpm_solo` 的 `voice.model` 仍写 `CosyVoice2-0.5B`，与实际 backend 不符
   → 发布版改为从 `--backend` + `--vox-ref` 派生
2. **响度归一化（已实现，待发布复核）**：`synthesize.py::normalize_loudness` 已把每节归一到 −22.0 LUFS 并做峰值保护，结果写入 manifest `loudnessLufs`（2026-11-23 VoxCPM 路径实测已触发）；TTS-GAP-REVIEW §4.6 记录的 −25.4~−22.0 是早期 CosyVoice 路径，发布前复核实际 manifest 值即可
3. **src 前缀**：验证版用 `/verify`，发布版必须是 `/audio/<章>/<节>.m4a`（前端 `spokenAudioPlan.ts` 固定）

## 4. 溯源清单（`assets/manifest.json`，每条一个素材）

```json
{
  "id": "ref_voice_01",
  "type": "voice_ref",
  "source": "self-recorded | common-voice | licensed-actor",
  "license": "CC0 | CC-BY-4.0 | owned-with-consent",
  "author": "<姓名或 ID>",
  "url": "<来源链接，自有素材留空>",
  "hash": "sha256:<文件哈希>",
  "usage": "voxcpm-ref",
  "expires": null
}
```
- 素材一换，hash 变化 → 自动判定音频过期并重跑（避免「图换了口型还是旧的」）
- A/B 对照固定：同一文本、同一参数，只换参考音/底图，量化 + 盲听

## 5. 合规红线（发布前逐条确认）

| # | 检查项 | 判据 |
|---|---|---|
| 1 | 声音权益 | 只用本人或书面授权声音；名人原声一律不碰 |
| 2 | 模型许可 | 代码许可 ≠ 权重许可；排除 CC-BY-NC 权重用于商用 |
| 3 | 数据集切片 | 原始数据集许可 + 是否允许再分发；数据集切片不能直接当参考音发布 |
| 4 | AI 标识 | 显式（界面角标）+ 隐式（文件元数据），符合《AI 生成合成内容标识办法》。**r151 已补**：manifest 落盘 `aiGenerated: true`（`synthesize.py`，旧产物已回补）；播放器常驻「AI 生成音频」角标 + 模型溯源 title；前端解析层对缺省字段按 `true` 兜底（宁可错标不可漏标）。隐式文件元数据（wav info chunk）仍待补 |
| 5 | 不进 git | 音频（约 95–115MB）走独立分发通道，`.gitignore` 已覆盖 `scripts/tts/out/`（C7） |
| 6 | 运行期零出网 | 发布的是静态文件；生产机不跑 TTS（C4/C5） |

## 6. 最小发布批次建议（先小后大）

1. **先做 1 章 3–4 节**：本人/CC0 参考音 → 走完 §3 全流程 → 内部盲听 + 合规检查
2. **盲听过了再扩 3 章**：验证音色跨章一致、情绪切换稳定
3. **最后全量 45 章 A/B 类**：打包 `audio-pack-v0.1.tar.zst`，CI 校验 hash 与覆盖率

## 7. 当前状态与下一步

- 写稿模型 v2 已训练完（eval_loss 1.240，eval 门禁 20%，JSON 全合法）；**生成正经 prompt 时 4/4 全过**（评估集 20% 是因为含章外泛化样本）
- 音色 LoRA `gdg_v1` **仅内部验证**，发布链路一律不挂 LoRA
- **发布链路已跑通**（2026-11-23）：写稿模型生成 → `build_spoken_plan.py` → VoxCPM2 零样本合成 → `out/release_v1/`
  - 参考音用 AISHELL-3 sample_192（Apache-2.0），但**带宽不合格**（6-8k 0.45%），成品同样闷——链路通、音质待换源
  - 换源只需改 `--vox-ref` 一个参数；Common Voice/WenetSpeech 需用户注册/拿密码
- AI 标识：**r151 已补**（manifest `aiGenerated: true` + 播放器角标），隐式文件元数据（wav info chunk）仍待补
- **平台分发层已就绪（r151）**：播放器 + 「听听」入口上线，当前生产因素材未上线渲染「素材筹备中」态；
  素材上线 = 合成产物放进服务器 `~/skillcoach/audio/<章>/`（nginx 只读挂载 `/audio/`），**前端零发版**
- 三个坑已解：`swift infer` 用 `--dataset` 会卡死须用 `--val_dataset`；桥接脚本 src 前缀不带斜杠传（绕开 Git Bash MSYS 转换）；`--id-map` 从正式 plans 取稳定 sectionId

## 8. 素材上线分发（r151，nginx /audio/）

部署形态（已落地，两份 nginx 配置逐字一致）：

| 项 | 值 |
|---|---|
| 挂载 | `docker-compose(.prod).yml`：`./audio:/usr/share/nginx/html/audio:ro`（服务器 `~/skillcoach/audio/`） |
| 路由 | `location /audio/ { try_files $uri =404; }`，缓存 `max-age=86400`；**绝不回落 index.html** |
| 目录结构 | `audio/<章>/manifest.json + <节>.wav + <节>.timeline.json`（`synthesize.py` 原产物直接拷） |
| 上线动作 | 产物放入目录 → 即时可见，前端零改动（播放器按 `manifest.json` 探测，404=素材缺失态） |
| 前端态 | 探测 `manifest.json`：ready=播放器 / missing=「音频素材筹备中」+ 口播稿浏览（不渲染空播放器） |

上线 checklist：①素材过本 SOP 四必要条件 → ②合成（`synthesize.py`，manifest 自动带 `aiGenerated: true`）→
③放入 `~/skillcoach/audio/<章>/` → ④浏览器打开 `/learn/<章>?mode=listen` 验证角标与播放 → ⑤把素材 hash 补进 `assets/manifest.json`。
