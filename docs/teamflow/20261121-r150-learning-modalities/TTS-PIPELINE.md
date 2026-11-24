# TTS 业务逻辑与处理逻辑（r151 · 2026-11-24 定稿）

> 定位：这一份讲**为什么这么做、每一步在算什么**——把散在代码注释、TECHNICAL、SOP 里的
> 设计决策串成一条完整叙事。操作命令看 `scripts/tts/README.md`，合规看 `RELEASE-DATA-SOP.md`，
> 机器依赖看 `TTS-EXTERNAL-DEPS.md`，过程记录看同目录 `TECHNICAL.md`。

## 0. 一句话业务口径

**站内所有文字都要有可听的版本，之后新增的知识自动走同一条链**（用户 2026-11-23 拍板）。
形态定为「科普相声」：用单口/对口的节奏讲技术知识点——不是把文档念出来，而是有铺垫、
有包袱、有留白的口播。

## 1. 漏斗总览（内容 → 可听资产）

```text
教程章节（60 章，frontend/src/content/tutorial）
  ① 分层筛选   coverage.ts：A 单口 29 / B 对口 16 / C 不可听 15 → 可听 45 章 185 节
  ② 口播稿     draft_spoken.py（LLM 起草）→ validate_spoken.py（质量闸）→ 人工修稿
  ③ 音频计划   build_spoken_plan.py + make_audio.py plan → plans_full/<章>.json
  ④ 合成       synthesize.py（VoxCPM2）→ wav + timeline + manifest
  ⑤ 聚合分发   index.json → deploy → nginx /audio/ → 前端索引驱动入口
```

每一层都有质量闸：②管「稿子好不好念」，④管「音频可不可用」，⑤管「入口不骗人」。

## 2. 业务规则：什么稿子才「像相声」

写进代码的硬约束（`lib/spokenSft.ts` 前端口径 = `scripts/finetune/validate_spoken.py`
Python 镜像，两边同步改）：

| 规则 | 阈值 | 为什么 |
|---|---|---|
| 逗哏连续说话 | ≤5 句 | 单人连说超过 5 句就成讲课了，必须有互动呼吸 |
| 捧哏附和占比 | ≤1/3 | 纯「嗯啊这是」太多次 = 捧哏是背景噪音 |
| 小句长度 | ≤20 字（中文按字，拉丁词按 1） | 长句没有口播节奏；TTS 长句易丢韵律 |
| 包袱（punch） | 2–6 处/节 | 少了平、多了闹；早期用「区间」措辞被模型读成下限，v2 提示词改硬上限 |
| 「说白了」小结 | 每 ~5 分钟一处 | 有声书听众需要阶段性落点 |
| 情绪强度 | 0.4–0.7 | 太低没有表演性，太高 TTS 不稳 |
| 单口/对口说话人 | solo 只能 narrator；duo 必须 dou+peng | 结构约束，合成器靠它校验 |

两个校验器踩过的坑（已修，别再踩）：punch 数按**情绪段**数不按行数；小句长度对拉丁词
（如 `requestAnimationFrame`）按 1 个词不算 21 个字母。

## 3. 稿子怎么来（两条腿）

1. **提示词版（在用）**：`draft_spoken.py` 走 deepseek-chat 生成 → `--retries N` 把校验
   错误塞回对话重试（45.4% → 98.4%，重试 +7.6pp 是真实收益）→ `sample_review.py` 按
   问题码分桶抽样 40 节人工修稿 → `score_edits.py` 算加权修改率。
2. **微调版（v2 已训成）**：QLoRA 4B 写稿模型（eval_loss 1.240，JSON 全合法），剩余
   偏差（爱多抖包袱）靠微调 + 负向样本，是 M2 方向。

草稿源：`scripts/finetune/out/drafts_final2.jsonl`（185 节全过闸）+ `review_sample-edited.jsonl`
（40 节人工定稿，plan 阶段覆盖草稿）。

## 4. 处理逻辑：从稿子到合成单元（plan）

**合成单元 = 情绪段（unit）**，不是句子：一段同情绪的台词一次合成，段内停顿由模型自然
产生，段间停顿取自情绪表（`PAUSE_SCALE` 按情绪缩放：铺垫 0.95 稳、翻包袱 1.0、收尾 1.25 拖）。

solo 章合成前做**制作期归一化**（`normalize_solo_plan`）：
- 合并相邻同人情绪段（≤8 行）：写稿模型按情绪切 unit 会把一个知识点切进两段、
  段间停顿叠到 600–900ms，听感像每句话都喘气；
- 段间停顿压到 ≤300ms；
- punch 段后加 **900ms 留白**——单口没有捧哏接话，这个留白就是「观众笑声」的位置，
  不留白等于把笑点踩过去。

duo 章不动归一化：换人停顿与抢话（`--overlap-ratio`，换人 10–25% 触发、提前 180ms
压上句尾音）是表演的一部分。

## 5. 处理逻辑：合成与时间轴（synth）

后端：`mock`（等长静音，验契约用，产物结构与真合成逐字段一致）与 `voxcpm`（唯一真后端）。

VoxCPM2 关键工程点：
- **参考音只编码一次**（`build_prompt_cache` 对全章复用）——逐句重编码又慢又让音色漂；
- CFG 1.5 / CFM timesteps 10（实测 1.5–2.0 尾巴最短；timesteps 是速度旋钮，10→8 约快 15–20%）；
- `seed` 固定才能复现；LoRA 按权重架构选 V1/V2 的 LoRAConfig 类（V2 多一个
  fusion_concat_proj 字段，用错类会丢配置）。

时间轴四步（播放器句级高亮的地基）：
1. **mix_clips 真实坐标**：每段按（前段末 + 停顿）落到混音轴，solo 严格串行、duo 允许负
   起点（抢话）；int32 累加防爆音；
2. **trim_edges 自适应裁静音**：模型句首尾自带 0.5–1s 静音，固定阈值会被底噪骗——
   改用包络 10/90 分位之间 8% 处做门限，两侧各留 40ms 起音；
3. **split_lines 找停顿不数汉字**：句级边界从音频的静音谷里量出来（切点放在停顿结束处
   即下一句开口，提前 40ms 吃进爆破音）——按字数比例摊时实测 22–55% 的 cue 起点落在
   静音里，高亮会提前跳；
4. **normalize_loudness −22 LUFS**：有声书响度区间 + 峰值 0.95 保护（不削顶）。

**AI 标识双保险**（SOP 红线 #4）：manifest 显式 `aiGenerated: true`（缺省运行期也兜底 true）+
wav 隐式 RIFF LIST/INFO（ICMT「AI-generated speech」/ISFT 模型名/ICRD 日期），随文件走。

## 6. 产物契约（前端只认这三样）

| 文件 | 内容 | 消费方 |
|---|---|---|
| `<章>/manifest.json` | chapterId / form / voice / aiGenerated / tracks（sectionId、src、title、durationMs、unitSpans、cues 句级时间轴） | 播放器探测（严格解析，半坏整体判废→素材缺失态） |
| `<节>.timeline.json` | 同 cues + unitSpans | recue-only 重算句级切分时免重合成 |
| `/audio/index.json` | 全部有音频章的聚合 | 「听听」入口与目录 chip 的唯一真源（新章部署零发版） |

**分发前必须转码**（`transcode_audio.py`）：wav 48kHz/16bit = 768kbps，转 **AAC 64k m4a** 后
体积压到 1/12（实测 578MB → 45MB），manifest 的 `src` 同步改写为 `.m4a`；
`upload_to_server.py` 按章增量推到服务器并清理旧 wav。缓存三档：index 60s / manifest no-cache / 媒体 1 天
（manifest 会随转码变化，长缓存会让浏览器去请求已删除的文件）。

听侧进度契约：`heard`（听过≠读过）+ `listen_section_id/listen_position_ms`（断点），
与 `seen` 并列不互相污染；后台同步字段服务端静默夹取、绝不 422。

## 7. 全量流水线与自动化（make_audio.py）

四阶段 `plan → synth → index → deploy` + 常驻触发器 `watch`（新章草稿 → 自动合成 →
守卫通过才发布）。吞吐实测（RTX 4070 Laptop 8GB）：单节合成 2–4 分钟（GPU 40–84% 脉冲
是自回归固有形态）、每章模型重载 ~30s（`--batch-size 8` 摊薄）、单节 CPU 后处理仅
0.3–0.4s（不值得做流水线）。合规守卫：`voice_compliant.marker` 不存在 → 只合成不发布。

## 8. 已知限制（M2 方向）

- 编排层：裁首尾静音已做，但**抢话叠音的音质**（duo 两端同音色）、观众反应轨未做；
- 单音色：duo 逗哏/捧哏目前同声，分角色参考音待 M2；
- 句级时间轴靠静音谷，语速极快无停顿的句群会退回等分；
- 写稿模型 v2 的偏好型偏差（爱多抖包袱）未用负向样本压制。

## 9. 音色与音质的现实边界（2026-11-24 实测）

**零样本换音色 ≠ 换风格**。VoxCPM2 零样本只能模仿参考音的音色与韵律：
- 官方演示参考音偏「平」（多半是英文演示音），中文成品听感不如 gdg LoRA 版；
- gdg 版自然的根本原因是 **LoRA（1718 条同音色数据微调）**，这条路受名人音色红线限制不可复制；
- 合规路径：①AISHELL-3 等开源中文音色（Apache-2.0，160 个可用）；
  ②本人录音/授权录制后自训 LoRA（最接近 gdg 效果）。

**「电音感」多半不是模型问题，是码率问题**：64kbps AAC 与源 wav 的 SNR 只有 19.5dB
（96k=26.1、128k=31.3），齿音与句尾会出现金属感/水声。若听感不佳优先提码率，
不必重跑合成（`transcode_audio.py --bitrate 128k` 即可）。

**混响指标**：本批成品语音衰减 190ms、噪声底 -120dB——没有额外的房间回声；
若主观仍听到「回声」，应检查播放设备/耳机的空间音效，而非模型输出。
