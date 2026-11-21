# 相声口播稿写稿模型：微调方案（r150 / M1 制作链）

> 需求：用户提出「参照 [llm-finetune-lab](https://github.com/miaogan/llm-finetune-lab) 训练一个编排相声脚本的模型」。
> 结论：**可行，且与 VERSION-PLAN §5.8 的微调轮廓一致**；本轮先打通「数据 → 训练 → 评估」的最小链路，
> 真实训练等 45 章数据铺完（M2）。
> 执行手册见 [`scripts/finetune/README.md`](../../../scripts/finetune/README.md)。

## 1. 为什么可行（对齐对方的实测能力）

| 维度 | llm-finetune-lab 的实测 | 我们的需求 | 判断 |
|---|---|---|---|
| 硬件 | RTX 4070 Laptop 8GB，QLoRA 4bit 训练占约 5GB | 本机 GPU（§7.2 待确认第 1 条） | ✅ 显存够，4B 可跑 |
| 框架 | ms-swift 4.5 + peft LoRA + bnb nf4 | 不想自建训练栈 | ✅ 直接复用 |
| 数据形态 | `dataset_info.json` + jsonl（`messages` 可用） | 结构化 JSON 输出 | ✅ 天然适配 |
| 已有产能 | 2091 条 3 轮 783 步 ≈ 80 分钟 | 185 条 × 8 轮 ≈ 368 步 | ✅ 单次 20–40 分钟量级 |
| 缺点 | 4B 参数小 | 需要稳定吐长 JSON + 情绪标签 | ⚠️ 靠 schema 重试兜底，见 §5 |

顺带解决了两件挂账：VERSION-PLAN §7.2 的「本机显卡型号与显存」= **RTX 4070 Laptop 8GB**；
§5.8 的「先微调还是先提示」不再是空谈——已有可跑的训练栈。

## 2. 任务定义（模型到底学什么）

- **输入**：章节信息（标题 / 方向 / 子方向 / 难度）+ 本章形态 + 本节标题 + **本节原文骨架**（教程该小节的文本块压平成要点行）
- **输出**：该小节的口播稿 JSON —— `{"form":"solo|duo","segments":[{"speaker","emotion","lines"}]}`
- **粒度**：**小节级**，不是整章级。理由：一份音频一个文件（§5.3）、4B 在 2048 token 内写不出整章、坏样本可定位。
- **学的是「怎么讲」**：输入里带原文、输出里是相声化转述，模型学到的是「这段技术内容怎样拆成逗捧结构」，
  不是背某三章的词。这也是为什么评估集必须**按章切分**。

## 3. 数据路线

| 阶段 | 规模 | 来源 | 人工投入 |
|---|---|---|---|
| seed（现在） | 12 条 = 3 章 × 4 节 | 3 章黄金稿 + 教程原文 | 0（只验证链路） |
| 真实训练 | **185 条 = 45 章（A/B 类）× 各自小节** | LLM 起草（同一写稿提示词）→ 人工修订 | 抽检 ≥20%，按 §5.8 统计修改率 |
| 增强（可选） | +60–100 条变体 + 负向样本 | 黄金稿各扩 3 个变体；「这样写不行」的对照 | 人工优选 |

- 切分：训练 37 章 / 评估 8 章（45 章可听子集）（**按章**，不是按样本随机）。
- 输出格式与 `lib/spoken.ts` 的质量闸同构——训练目标不是「一段好文本」，是「能过闸的结构」。

## 4. 训练配置（已落 `scripts/finetune/spoken_sft_qlora.yaml`）

| 项 | 值 | 理由 |
|---|---|---|
| 基座 | Qwen3-4B-Instruct-2507 | 对方仓库已就位；8GB 可 QLoRA 4bit |
| 方法 | LoRA（r=8, alpha=16, all-linear）+ bnb nf4 4bit | 小样本够用；数据过 500 条再升 16 |
| max_length | 2048 | 每条样本约 1300 token（输入 ~900 + 输出 ~450），1024 会截断 |
| batch | 1 × 梯度累积 4 | 8GB 显存 |
| epochs | 8 | 185 条 ÷ 4 ≈ 46 步/轮 × 8 = 368 步；默认 3 轮只有 120 步，LoRA 学不动 |
| lr | 1.5e-4 cosine + warmup 0.1 | 长结构化输出偏高一点更稳 |
| 验证 | `val_dataset` 显式指定 + `split_dataset_ratio: 0` | 防随机切跨章泄漏 |

## 5. 评估三关与决策门

| 关卡 | 指标 | 门槛 |
|---|---|---|
| 结构 | JSON 合法率 + 闭集字段 | ≥95% |
| 口径 | 质量闸通过率（`validate_spoken.py`） | ≥90% |
| 人评 | 人工修改率 | ≤35% |
| 人评 | 3 人盲听评分 | 不设硬门槛，做版本对比 |

**决策门沿用 §5.8**：先用**提示词版**（DeepSeek + 3 章 few-shot）在 45 章上测人工修改率；
若 >35% 且 top3 问题类型占修改量 60% 以上（系统性偏差），才值得把微调铺到全量；
若 <20% 或问题分散，微调是过度工程。

## 6. 与产品的关系（边界）

- 微调模型是**制作期工具**：不进产品、不进容器、不产生运行期出网（C1 / C4 不变）。
- 产物仍要写成 `frontend/src/content/spoken/*.ts` 并过 `spoken.test.ts` 的零 issue 门禁。
- 规则双源：`lib/spoken.ts`（真源）↔ `scripts/finetune/validate_spoken.py`（镜像）。改规则两边一起改。

## 7. 风险

| 风险 | 影响 | 处置 |
|---|---|---|
| 12 条 seed 过拟合三章的梗 | 误判能力 | seed 只验证链路，不产出结论 |
| 4B 漏 `emotion` / 少 `peng` / 截断 | 结构合法率不达标 | schema 重试（生成 → 校验 → 带错误重试一次），训练侧自建 |
| 「包袱」不好笑 | 人评不过 | 人评门槛 + 只做「可听」不做「好笑」的验收口径 |
| 训练/评估同章泄漏 | 指标虚高 | 按章切分（已落 exporter） |
| 微调过拟合导致泛化更差 | 不如提示词版 | §5.8 决策门 + 留 8 章盲测 |

## 8. 本轮已落地的文件

| 文件 | 作用 |
|---|---|
| `frontend/src/lib/spokenSft.ts` | 写稿任务定义：系统提示词、小节提示词、目标 JSON、样本构造与统计 |
| `frontend/src/lib/spokenSftExport.ts` | esbuild 打包入口（只给脚本用，不进运行时） |
| `scripts/export_spoken_sft.mjs` | 导出 jsonl（全量 / 训练 / 评估）+ dataset_info 条目 |
| `scripts/finetune/validate_spoken.py` | 结构与口径校验（`--strict` 可进 CI） |
| `scripts/finetune/spoken_sft_qlora.yaml` | ms-swift 训练配置模板 |
| `scripts/finetune/README.md` | 从导出到评估的完整执行手册 |

验证：12 条样本 100% 通过结构与口径检查；粗估每条 1346 token，2048 `max_length` 够用（见 README）。

## 9. 实测（2026-11-22 · RTX 4070 Laptop 8GB · ms-swift 4.5.2 · 本机）

数据与配置已直接写进用户本地仓库 `D:\work_space\llm-finetune-lab`（3 份 jsonl + `dataset_info.json` 三条注册 + 两份配置）。

| 环节 | 实测 |
|---|---|
| 训练（8 条 × 8 轮） | 16 步 / 111 秒 / 6.9 s/step / **显存峰值 4.5 GiB** |
| loss | train 1.385 · eval 1.275 · token_acc ≈ 0.73 |
| 推理（评估章 4 节） | A `1200`：494 s / 8.0 tok/s；B `2048`：729 s / 8.9 tok/s；C `2048 + repetition_penalty 1.1`：683 s / 8.9 tok/s |
| 校验 | **三试次均 4 条 0 通过**：A/B 三条截断（自我复读）、C 三条 `Extra data`（不知道在哪停）、另有逗哏 6 句 / 捧哏全「嗯」 |

**结论（重要）**：
- **格式在 16 步就学会了** —— 4/4 都吐出 `form` + `segments` + `emotion` 的合法骨架，说明「结构 + 情绪标签」是可学的，容器搭对了。
- **规则、去重与「知道在哪停」学不会** —— 抬上限到 2048 仍是同样 3 条截断；加 `repetition_penalty=1.1` 压住了复读，却换成「吐完第一个 JSON 继续写」。这不是长度问题，也不是 epoch 问题，而是**数据量问题**（8 条样本里规则句式占比太低），正好落在 §5.8 的「系统性偏差靠数据补」。
- 生成速度 8–9 tok/s：45 章 × 平均 4.1 节 ≈ 185 次生成 ≈ **7–8 小时**，M2 要考虑批推理或更小/更快的解码方案。

**上线前三道兜底（未做）**：生成侧 stop/长度约束 + 「只取第一个 JSON 对象」容错；校验失败带错误重试一次；185 条训练数据。

**两个工程坑（已修进代码与文档）**：
1. `dataset_info.json` 的 `dataset_path` 相对 `DATA_DIR` 解析，**不能带 `data/` 前缀**（否则 `data/data/xxx.jsonl` 直接 `FileNotFoundError`）——exporter 已改。
2. 生成长 JSON 必须显式给 `max_new_tokens`（≥2048），并加 `repetition_penalty`（1.05–1.1）；默认 1200 一定截断。

## 10. 可听分层与提示词版 baseline（2026-11-22 落地）

### 10.1 分层闭集（规划 → 代码）

- 单点：`frontend/src/content/spoken/coverage.ts`，**60 章**：A 29 / B 16 / C 11 / C′ 4，可听 **45 章 / 185 节**。
- 判据仍是 §3.1「能否脱离视觉独立成立」；纯函数在 `lib/spokenCoverage.ts`（`isListenable` / `spokenFormFor`：A → 单口、B → 对口，混合章可在条目上覆盖）。
- `spokenCoverage.test.ts` 拦两类错：教程新增章没分层（本轮真拦到了 4 章漏项）、C/C′ 混进起草队列。
- 顺带校准：规划里写「约 40 章 / 85–100MB」，实测 45 章 → 音频体量 95–115MB（VERSION-PLAN 已同步）。

### 10.2 流水线（不训练，只调模型）

| 步骤 | 命令 | 产物 |
|---|---|---|
| 1. 导出起草请求 | `cd frontend && node ../scripts/export_spoken_sft.mjs` | `out/spoken_drafts.jsonl`（185 节 prompt，无 assistant） |
| 2. 起草 | `python scripts/finetune/draft_spoken.py --live [--retries 2]` | `out/drafts_out.jsonl` + `out/drafts_review.md`（人工审阅用） |
| 2.5 抽样 | `python scripts/finetune/sample_review.py` | `out/review_sample.{md,jsonl}`：按问题分桶抽 40 节，确定性可复算 |
| 3. 人工改稿 | 按 review 改、另存 `edited.jsonl` | — |
| 4. 算修改率 | `python scripts/finetune/score_edits.py --draft … --edited …` | 加权修改率 + §5.8 判定 |

`draft_spoken.py` 的端点 / 模型 / Key 从 `backend/.env` 读（认同名环境变量），**不打印 Key**；先试 JSON 模式，400 时自动退回普通模式。

### 10.3 实测（deepseek-chat · 185 节，**修正口径**）

> 首轮报出的 45.4% / 77.8% 是校验器虚低：`punch_count` 按行数（一个 4 行包袱算 4 次）、
> 小句长度把 `requestAnimationFrame` 当 21 个字。修好口径后同一批数据重算：

| 试次 | 参数 | 自动过闸 | 剩余问题 |
|---|---|---|---|
| A | 不重试 | **168/185 = 90.8%** | `dou_turn_too_long`×25 · `clause_too_long`×2 |
| B | `--retries 2` | **182/185 = 98.4%** | `dou_turn_too_long`×4 |
| C | 拼接（B + v2 定向修好的残留） | **185/185 = 100%** | — |

**读法**：
1. **重试是真实收益**（+7.6pp），救回的主要是逗哏长段——这一环保留。
2. **v2「硬上限」实验被污染**：重测的 41 节里 38 节本是误判，「区间会被读成下限」的结论
   **未获证实**；措辞保留（不吃亏），但不引用收益。
3. 教训：**先校准校验器，再调提示词**，否则调的是噪声。
4. 100% 是拼接结果，不是单次全量跑。

**注意口径**：自动过闸率**不能替代** §5.8 的人工修改率。后者要人工改一轮再算：
若修改率 ≤20%，提示词版够用；≥35% 且问题集中（top3 占 60%+），才值得把 185 条喂给 4B。
