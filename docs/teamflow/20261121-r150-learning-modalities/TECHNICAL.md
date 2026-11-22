# 学习多形态化 · M1-1 技术变更单（r150）

> 需求来源：同目录 `VERSION-PLAN.md`（2026-11-21 评审通过，M1 → M2 → M3 → M4）。
> 本轮只交付 **M1 的第一块**：口播稿数据模型 + 脚本质量闸 + 3 章黄金稿。
> 播放器、TTS 工具链、音频资产分发**刻意不在本轮**（清单见 §6）。

## 1. 本轮做了什么

| 交付 | 位置 | 说明 |
|---|---|---|
| 口播稿数据结构 | `frontend/src/lib/spokenTypes.ts` | `SpokenChapter` / `SpokenSection` / `SpokenSegment` / `SpokenVoice`，以及生成期产物 `SpokenCue` / `SpokenTrack` |
| 纯函数层与质量闸 | `frontend/src/lib/spoken.ts` | 7 类情绪表（含停顿与表演提示）、展平、时长估算、章节摘要、**脚本质检** |
| 3 章黄金稿 | `frontend/src/content/spoken/{be-distributed-consistency,mw-cache-strategy,mw-observability}.ts` | A 类最抽象 / A+B 混合 / B 类纯场景，三种最难形态各一章 |
| 内容索引 | `frontend/src/content/spoken/index.ts` | `SPOKEN_SCRIPTS` + `spokenChapterById()`，听入口将来只认这一处查找 |
| 门禁测试 | `frontend/src/test/spoken.test.ts` | 18 条：结构一致性、黄金稿零 issue、每条硬约束的负面样例、派生函数 |

零后端改动：口播稿是构建期内置内容，不进 HTTP 契约、不进数据库、不产生运行期出网（`test_r115_intranet.py` 的 5 处登记不变）。

## 2. 数据结构的关键取舍

1. **不存音频，只存文本 + 情绪 + 停顿**。音频是离线发布资产（C1），前端只负责「按句高亮」；`SpokenTrack` / `SpokenCue` 是离线工具链的产物类型，运行期只读。
2. **停顿按情绪给，不给逐句覆盖**。逐句 `pauseAfterMs` 会让「情绪表」和「内容文件」两处口径打架；真要细调，改情绪表一处即可（VERSION-PLAN §5.2 的停顿表）。
3. **混合章用「章级形态 + 小节覆盖」表达**。`mw-cache-strategy` 章级是 `duo`，`where` 小节显式 `solo`：这样既保留章级缺省（决定目录页标签、音色是否要第二个），又能按 §5.7 的分派规则逐小节切单口 / 对口。
4. **字段用 camelCase**。它不在 HTTP 契约里；将来若要下发（进度、断点），按 AGENTS.md 改 snake_case 并两侧同步，届时 `heard` / `listen_section_id` / `listen_position_ms` 才进 `schema.py` ↔ `types.ts`。
5. **`scriptVersion` 是音频过期判据的锚点**：内容一改就升版本，与 §5.5 的「内容 hash 绑定音频」同源，等离线工具链落地后由 CI 比对。

## 3. 脚本质量闸（写进代码的硬约束）

规则全部来自 VERSION-PLAN §5.7「不靠人工约定」清单，`validateSpokenChapter()` 逐条返回中文原因与改法：

| code | 规则 | 阈值出处 |
|---|---|---|
| `dou_turn_too_long` | 逗哏一次连续发言 ≤5 句（按「中间有没有捧哏插话」切分，不按情绪段） | §5.7 硬约束 |
| `peng_filler_ratio` | 对口小节里捧哏「纯附和」占比 ≤1/3（去标点后 <4 字且不含疑问词即纯附和） | §5.7「捧哏每次插话必须推进」 |
| `duo_missing_peng` | 对口小节必须逗哏、捧哏都开口 | §5.7 分派规则 |
| `clause_too_long` | 小句 ≤20 字（按逗号级切分，不按整行） | §5.6「一句话不超过 20 字，超过就拆」 |
| `punch_count` | 每章 `punch` 2–6 次 | §5.7 硬约束 |
| `recap_missing` | 每 5 分钟至少一个「说白了」小结（向上取整，最少 1 个） | §5.7 + M2 验收 ≥3 处 |
| `speaker_solo` | 单口小节只允许 narrator | §5.7 分派规则 |
| `duo_missing_voice` | 对口章必须给捧哏音色 `support` | §5.7 + §5.3 |
| `emotion_gain` | 情绪强度 0.4–0.7 | §5.6 三道闸 |
| `section_missing` / `section_unknown` / `section_order` | 小节 id 与教程逐节对齐且同序 | §5.1「听模式与原文严格对应」 |
| `unknown_tutorial` | 章 id 必须能对到教程章 | 同上 |

取舍说明：**「每 3–5 分钟小结」按估算时长折算成条数**（字数 ÷ 4.5 字/秒 + 情绪停顿），因为稿子阶段没有真实音频时长；真实时长落到 `SpokenTrack.durationMs` 后，门禁可以换成按时间轴判断（M2 再收紧）。

## 4. 黄金稿 v1 规格

| 章 | 层级 / 形态 | 小节 | 句数 | 字数 | 估算时长 | punch | 小结 |
|---|---|---|---|---|---|---|---|
| `be-distributed-consistency` | A 最抽象 / 单口 | 4 | 82 | 1026 | 4.5 min | 4 | 4 |
| `mw-cache-strategy` | A+B 混合 / 概念节单口 + 场景节对口 | 4 | 130 | 1514 | 6.6 min | 4 | 4 |
| `mw-observability` | B 纯场景 / 全对口 | 4 | 78 | 899 | 4.0 min | 4 | 4 |

- 三章都是**覆盖全部小节**的完整稿，不是节选：听模式切到任何一节都有内容。
- 情绪强度按章区分：`be-distributed-consistency` 0.4（抽象概念怕朗诵腔），两章场景稿 0.55（相声要表演性）。

## 5. 验证

| 项 | 结果 |
|---|---|
| `npx vitest run src/test/spoken.test.ts` | **18 passed**（含「三章零 issue」与 8 条负面样例） |
| 全量 `npx vitest run` | **51 files / 652 passed**（新增 1 文件 18 条，其余零回归） |
| `npm run typecheck` | 通过 |
| `npm run lint --max-warnings 0` | 通过 |
| `npm run build` | 通过（`dist` 903 kB / gzip 354 kB；chunk 体积告警为既有） |

环境备注：本机沙箱下 `node` 的 `spawn` 对 esbuild 子进程返回 `EPERM`（esbuild.exe 直接执行正常），跑 vitest / build 需把 `TMP`/`TEMP` 指到项目内目录并在放宽的沙箱下执行；这是环境限制，不是代码问题。

## 6. 本轮刻意未做（M1 其余部分）

1. **播放器**：播放/暂停、0.75–2.0 倍速、句级高亮（可关）、断点续听、MediaSession、泛听模式与跨章续播。
2. **离线 TTS 工具链** `scripts/tts/`：合成 → VAD 切句 → `timeline.json` → 质检报告。
3. **音频资产与分发**：`/audio/` 挂载、`deploy-audio.sh`、内网 `audio-pack-vX.tar.zst`、CI 的 hash 过期检查。
4. **学习进度契约**：`LearnChapterProgress` 的 `heard` / `listen_section_id` / `listen_position_ms`（等播放器落地时双侧同步，避免先改契约造成半成品字段）。
5. **入口与文案**：`/learn/:chapterId?mode=listen`、「听听」入口、目录页 C 类章节不出现听入口。

## 7. 偏差与已知限制

1. **黄金稿时长 4–6.6 分钟，短于 §5.7 的「每章 12–18 分钟」**。M1 验收门槛只有「3 章可完整听 + 音频 ≤10MB」，试听评审 4–7 分钟的样片足够判断音色与情绪；12–18 分钟是 M2 铺量的口径，扩写时同步升 `scriptVersion`。
2. **人工试听评审未做**（需要 GPU 环境与真实合成）。当前稿子只过了「文字层质量闸」，不过「好不好听」这一关。
3. **时长是估算值**（4.5 字/秒 + 情绪停顿），不是音频真实时长。
4. **3 章以外没有稿子**：`spokenChapterById()` 查不到即返回 `undefined`，听入口据此判断「这章还没做音频」，不会渲染空播放器。
5. 全量 `vitest` / `build` 已在提交前复跑通过；本机 Windows 下需把 `TMP`/`TEMP` 指到项目内目录，并在不限制进程创建的沙箱下执行（见 §5 环境备注）。

## 8. 下一步（M1 收尾顺序）

1. 播放器骨架 + `public/spoken/` 假时间轴（不依赖音频也能先把交互做对：倍速、句级高亮、断点）。
2. `scripts/tts/` 离线链路 + 本机显存实测（§7.2 待确认第 1 条）。
3. 3 章合成 → 人工盲听评审 → 定音色与情绪参数 → 再付音频资产。
4. 学习进度契约双改（`heard` 等三字段）与「听听」入口，最后接目录页。

## 9. 微调写稿模型（M1 制作链，2026-11-21 追加）

用户提供既有仓库 [`llm-finetune-lab`](https://github.com/miaogan/llm-finetune-lab)（ms-swift 4.5 + QLoRA 4bit + Qwen3-4B-Instruct-2507，RTX 4070 Laptop 8GB），要求参照它训练「编排相声脚本」的模型。
本轮打通「数据 → 训练 → 评估」的最小链路，**不产出训练结果**（seed 只有 12 条）：

| 文件 | 作用 |
|---|---|
| `frontend/src/lib/spokenSft.ts` | 写稿任务：系统提示词（与质量闸同口径）、小节提示词、目标 JSON、样本构造与统计 |
| `frontend/src/lib/spokenSftExport.ts` | esbuild 打包入口（只给脚本用，不进运行时） |
| `scripts/export_spoken_sft.mjs` | 导出全量 / 训练 / 评估三份 jsonl + `dataset_info` 条目，**评估集按章切分** |
| `scripts/finetune/validate_spoken.py` | 结构与口径校验（`spoken.ts` 的离线镜像，`--strict` 可进 CI） |
| `scripts/finetune/spoken_sft_qlora.yaml` | ms-swift 训练配置（`max_length` 2048 / 8 epochs / `split_dataset_ratio: 0`） |
| `scripts/finetune/README.md` | 从导出到评估的执行手册 |
| `FINETUNE-PLAN.md` | 方案、数据路线、评估三关、风险 |

关键取舍：**小节级**任务（一份音频一个文件、4B 在 2048 token 内写不出整章）、**按章切分**评估集（同章 4 节共享梗会泄漏）、**规则双源**（改了 `spoken.ts` 必须同改 `validate_spoken.py`）。
`VERSION-PLAN §7.2` 的「本机显卡型号与显存」由此确认为 8GB。

验证：12 条样本 100% 通过校验、粗估 1346 token/条；`typecheck` / `lint` / `build` 通过，全量 52 files / 658 passed。

## 10. 校验器口径修正（2026-11-22 追记）

收尾最后 2 节时发现质量闸自身判错，修正两处后历史数据全部重算：

| 项 | 错在哪 | 改法 |
|---|---|---|
| `punch_count` | 按**行**数（一个 4 行包袱算 4 次） | 按**情绪段**数（`countPunch()` 单点，`summarizeSpoken` 同源） |
| 小句长度 | 按字符数（`requestAnimationFrame` = 21 字） | 中文按字 + 拉丁词按 1 个（`spokenClauseLength()`） |

影响：同一批 185 节只重跑校验 → 不重试 **90.8%**、重试 2 次 **98.4%**、拼接最终 **100%**；
此前 45.4% / 77.8% 的结论作废。v2「硬上限」实验因只重测误判样本而**被污染**，其收益不引用。
新增 `spoken.test.ts` 两条口径测试，全量 53 files / 671 passed。

## 11. 音频合成链路（2026-11-22 落地）

口播稿 → 音频计划 → 合成 → 时间轴 → 质检，四条命令串起来，唯一真源仍是口播稿：

| 步骤 | 命令 | 产物 |
|---|---|---|
| 1. 计划 | `cd frontend && node ../scripts/export_spoken_audio.mjs` | `scripts/tts/out/plans/*.json`（合成单元 = 情绪段，停顿取自情绪表） |
| 2. 合成（mock） | `python scripts/tts/synthesize.py --backend mock` | 静音占位 + 比例时间轴，用于播放器契约与 CI |
| 2. 合成（真） | `synthesize.py --backend cosyvoice --repo-dir … --model-dir … --prompt-wav …` | `out/audio/<章>/<节>.wav` + `.timeline.json` + `manifest.json` |
| 3. 质检 | 同上（自动写 `out/qa.json`） | duration / estimate / peak / silenceRatio / cues |

实测（RTX 4070 Laptop 8GB）：首节 `mw-cache-strategy/where` 14 单元 → **152.8 秒 / 32 cue / RTF 0.84–0.87**；
真实时长约为估算的 **1.55 倍**（估算按 4.5 字/秒，实测约 2.9 字/秒含停顿）。

环境：`D:/ProgramData/miniconda3/envs/cosyvoice/python.exe`（torch 2.3.1+cu121）+ 新克隆的 CosyVoice 代码 +
`models/CosyVoice2-0.5B` + 参考音 `alt_cunningham/.../da_feiyu/prompt.wav`；`wget` 用本地 stub。

已知限制：句级时间轴是**按字数比例摊分**（不是 VAD）、**单音色**（对口章两端同声）、cue 里没有响度归一化、
`estimateMs` 与真实时长差 1.55 倍待校准。

## 12. 首轮试听反馈与修复（2026-11-22）

用户听完第一节反馈「没有识别语气，直接把语气读出来了」。用 whisper 转写定位：

**根因是元数据 / 调用约定，不是 TTS 模型能力**——`inference_instruct2` 把 instruct 当 `prompt_text`
喂给 LLM，官方约定结尾必须带 `<|endofprompt|>`（`example.py:57`）。我们第一版：

- 缺结束符 → 模型把指令当正文继续念；
- 措辞是**描述性长句**（「就像跟朋友聊天，随便点儿…」）→ 即使加结束符也不符合官方「用…说这句话」的祈使句约定。

对照实验（同一句正文、同一参考音，whisper 转写）：

| 试法 | 转写开头 | 判断 |
|---|---|---|
| instruct 无结束符（首版） | 「就像跟朋友聊天随便点，语速偏快，别端着…」 | 指令被念 |
| 短祈使句 + 无结束符 | 「用开心的语气说这句话咱们今天聊缓存…」 | 仍被念 |
| 短祈使句 **+ `<|endofprompt|>`** | 「咱们今天聊缓存，不是聊怎么装 Redis…」 | 正常 |

修复：7 类 instruct 全部改成「用…的语气说这句话」+ 结束符，驱动里加「缺结束符直接退出」的防御。
同节时长 152.8s（含念指令）→ **88.1s**（正常，与估算同量级）。

## 13. 语气是否生效：从「念指令」到「模型代际」（2026-11-22）

修掉 `<|endofprompt|>` 后，音频不再念指令，但用户/量化都显示语气仍平。分两层定位：

| 层 | 证据 | 判断 |
|---|---|---|
| 调用约定 | whisper 转写：修前开头是「就像跟朋友聊天…」 | 元数据问题，已修（§12） |
| 模型能力 | 全量 12 节按句切段量基频：**类间极差 6.0 Hz**、能量 0.111–0.118 | CV2-0.5B 的 instruct 形同虚设 |
| 换模型 | 同四句反差指令：CV3 的「悲伤」10.2s vs 「平静」3.2s；CV2 全在 3.56–3.88s | **代际差异**，CV3 才跟得上 |

单节 CV3 复测：基频极差 6.0 → **16.6 Hz**，能量分层（deadpan 0.111 / wrap 0.147）。
驱动新增 `--model-kind auto|cv2|cv3`（按 `cosyvoice3.yaml` 自动识别），全量改用 CosyVoice3 重跑。

**读法**：`analyze_emotion.py` 的「类间基频极差」<10Hz 视作没区分、>25Hz 才可能听得出冷暖；
它只能证明"声学上有没有差别"，**好不好听仍要人耳**。
