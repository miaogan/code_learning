# 相声口播稿写稿模型（SFT 制作链）

> r150 制作工具链。定位是**离线生产工具**（VERSION-PLAN §5.8）：只在制作期把教程小节改写成口播稿，
> 不进产品、不进容器、不接运行时、不产生运行期出网。训练在另一个仓库
> [`llm-finetune-lab`](https://github.com/miaogan/llm-finetune-lab)（ms-swift + QLoRA + Qwen3-4B，8GB 显存）。

## 1. 这条链路解决什么

教程小节原文 → 模型 → 口播稿 JSON（`form` + `segments[{speaker, emotion, lines}]`），
产物与前端 [`lib/spoken.ts`](../../frontend/src/lib/spoken.ts) 的质量闸**同一口径**。
换句话说：模型学的标准 = 门禁判的标准，产出不用再人工翻译成另一种结构。

## 2. 为什么是「小节级」而不是「整章级」

1. 一份音频就是一个文件（§5.3），小节天然是生成单位；
2. 4B 模型在 2048 token 内写不出整章 3000+ 字，整章只会被截断；
3. 坏样本能定位到具体小节，人工抽检成本低。

## 3. 数据：导出与格式

```bash
cd frontend && node ../scripts/export_spoken_sft.mjs
```

产物（`scripts/finetune/out/`，已 gitignore）：

| 文件 | 内容 |
|---|---|
| `spoken_sft.jsonl` | 全量样本（seed 阶段 12 条 = 3 章 × 4 节） |
| `spoken_sft_train.jsonl` | 训练集（默认排除评估章） |
| `spoken_sft_eval.jsonl` | 评估集（默认 `mw-observability` 整章） |
| `dataset_info_entry.json` | 要贴进 llm-finetune-lab `data/dataset_info.json` 的三条注册 |

每行一条 `{"messages":[system, user, assistant]}`，ms-swift 原生支持。
**评估集按章切分，不按样本随机切**：同一章 4 个小节共享梗与节奏，随机切会让训练见过的章泄漏进评估集，指标虚高。

目标结构（assistant 内容）：

```json
{"form":"duo","segments":[{"speaker":"dou","emotion":"banter","lines":["咱们今天聊缓存。"]}]}
```

## 4. 训练（在 llm-finetune-lab 里跑）

```bash
# 1) 数据
cp scripts/finetune/out/spoken_sft_{train,eval}.jsonl  <llm-finetune-lab>/data/
# 2) 注册：把 out/dataset_info_entry.json 的三条追加到 <lab>/data/dataset_info.json
# 3) 配置
cp scripts/finetune/spoken_sft_qlora.yaml  <llm-finetune-lab>/configs/
# 4) 训练
python scripts/py/train.py configs/spoken_sft_qlora.yaml
```

配置与仓库默认值的差异及理由写在 YAML 注释里（`max_length` 2048、epochs 8、`split_dataset_ratio: 0`）。

**seed 阶段只验证链路**：8 条训练样本 × 8 轮 ≈ 16 步，loss 应从 4.x 降到 3.x，模型能吐合法 JSON 就算打通。
真实效果要等 40 章 ≈ 160 条数据（M2 的铺量工作）。

## 5. 评估三关

```bash
python scripts/finetune/validate_spoken.py scripts/finetune/out/spoken_sft.jsonl --strict   # 数据自检
python scripts/finetune/validate_spoken.py out/eval.jsonl --strict                            # 模型输出
```

| 关卡 | 指标 | 门槛 | 怎么测 |
|---|---|---|---|
| 结构 | JSON 合法 + 闭集字段 | ≥95% | `validate_spoken.py` 的 `invalid_*` 计数 |
| 口径 | 质量闸通过率 | ≥90% | `validate_spoken.py` 逐条规则 |
| 人评 | 人工修改率 | ≤35% | 逐条对比黄金稿改字数 / 总字数 |
| 人评 | 盲听可听度 | 3 人评分 | 合成后盲听（与音色评审同批） |

模型输出批量推理可用 ms-swift 的 `swift infer --val_dataset spoken_sft_eval --result_path out/eval.jsonl`，
然后跑上面的校验命令。可直接复制的实测命令（在 llm-finetune-lab 根目录）：

```bash
.venv/Scripts/swift.exe infer \
  --adapters outputs/spoken_sft_seed/v1-20261122-000605/checkpoint-16 \
  --val_dataset spoken_sft_eval \
  --custom_dataset_info data/dataset_info.json \
  --max_new_tokens 2048 --temperature 0 --max_batch_size 1 \
  --result_path outputs/eval_seed.jsonl
```

输出的 jsonl 每行带 `response`（模型输出）与 `labels`（金标），`validate_spoken.py` 直接认 `response`。

## 6. 与产品门禁的关系（重要）

- **`frontend/src/lib/spoken.ts` 是规则真源**；`scripts/finetune/validate_spoken.py` 是离线镜像。
- 改任何一条规则（小句 20 字、逗哏 5 句、捧哏 1/3、punch 上限、每节「说白了」）**两边一起改**：
  否则模型学的是一套、门禁判的是另一套。
- 最终产物仍然要写进 `frontend/src/content/spoken/`，跑 `npm test`（`spoken.test.ts` 的零 issue 门禁）。

## 7. 已知限制

1. seed 的 12 条会过拟合到这三章的梗，不能拿它判断泛化。
2. 4B 生成长 JSON 有概率漏 `emotion`、少 `peng`、或直接截断；上线前需要「schema 重试」兜底（与产品侧 `reliability.py` 同思路，但训练侧另写）。
3. 负向样本（「这样写不行」的对照）暂缺，M2 补。
4. 「包袱好不好笑」这门指标目前只能人评，跑不了自动打分。

## 8. 实测记录（2026-11-22 · RTX 4070 Laptop 8GB · ms-swift 4.5.2）

**训练**（`configs/spoken_sft_seed.yaml`，8 条 × 8 轮）：

| 项 | 实测 |
|---|---|
| 步数 / 耗时 | 16 步 / 111 秒（6.9 s/step） |
| 显存峰值 | **4.5 GiB**（`max_length=2048` + 梯度检查点，8GB 卡有余量） |
| loss | train 1.385 · eval 1.275 · token_acc ≈ 0.73 |
| 产物 | `outputs/spoken_sft_seed/v1-20261122-000605/checkpoint-{8,16}` |

**推理**（评估章 4 个小节，温度 0，`--max_batch_size 1`）：

| 试次 | 参数 | 耗时 / 速度 | 生成 token | 通过 |
|---|---|---|---|---|
| A | `max_new_tokens=1200` | 494 s / 8.0 tok/s | 3956 | 0/4 |
| B | `max_new_tokens=2048` | 729 s / 8.9 tok/s | 6500 | 0/4 |
| C | 2048 + `repetition_penalty=1.1` | 683 s / 8.9 tok/s | 6086 | 0/4 |

**失败模式（比通过率更有信息量）**：

| 试次 | 现象 | 解释 |
|---|---|---|
| A / B | 3 条 JSON 截断 | 模型自我复读（「这事儿得查。」×N），撞上生成上限 |
| C | 3 条 `Extra data` | 复读被压住了，但模型**不知道在哪停**：吐完第一个 JSON 继续往下写 |
| A / B / C | 1 条逗哏连说 6 句 + 1 条捧哏全是「嗯」 | 规则没学会（8 条样本里这类句式占比太低） |

**关键结论**：16 步就学会了**格式**（4/4 都吐出 `form` + `segments` + `emotion` 的合法骨架），
但**规则、去重与「知道在哪停」学不会**——这不是多训几轮能解决的，是 §5.8 说的「系统性偏差靠数据补」。
seed 的定位不变：验证链路（数据 → 训练 → 推理 → 校验四环都通），不产出版本结论。

**因此上线前必须有的三道兜底**（都还没做）：
1. 生成侧 `stop`/`max_new_tokens` 约束 + 「只取第一个 JSON 对象」的解析容错；
2. 校验失败后带错误提示重试一次（schema retry）；
3. 40 章 ≈ 160 条训练数据（现在 8 条）。

生成速度 8–9 tok/s 也意味着：160 节 × 平均 1500 token ≈ **7–8 小时**，M2 要考虑批推理。

**两个工程坑（已在代码/文档里修正）**：
1. `dataset_info.json` 的 `dataset_path` 相对 `DATA_DIR`（即 `data/`）解析，**不能带 `data/` 前缀**，
   否则会拼成 `data/data/xxx.jsonl` 报 `FileNotFoundError`；
2. 生成长 JSON 要显式抬 `max_new_tokens`（≥2048），并按情况加 `repetition_penalty`（1.05–1.1）；
   但注意：惩罚解决的是复读，解决不了「不知道在哪停」。

## 9. 提示词版 baseline（先别训练，先测修改率）

§5.8 的决策门是：**先看强模型按同一套提示词写出来的初稿，人工要改多少**。
改得少（≤20%）→ 微调是过度工程；改得多且问题集中（≥35% 且 top3 问题占 60%+）→ 微调才划算。

所以先跑这条**不训练、只调模型**的链路：

```bash
cd frontend && node ../scripts/export_spoken_sft.mjs     # 产出起草请求 + 分层统计
python scripts/finetune/draft_spoken.py --dry-run        # 只统计，不出网
python scripts/finetune/draft_spoken.py --live --limit 3 # 真调前 3 节（省点钱）
python scripts/finetune/draft_spoken.py --live           # 全量 185 节
```

- 模型端点 / 模型名 / Key 从 `backend/.env` 读（也认同名环境变量），**不打印 Key**
- 产物：`out/drafts_out.jsonl`（逐节初稿 + 校验码）、`out/drafts_review.md`（人工审阅：原文骨架 + 初稿 + 问题）
- 人工按 review 改稿后另存 `edited.jsonl`，再算修改率：

```bash
python scripts/finetune/score_edits.py --draft out/drafts_out.jsonl --edited out/edited.jsonl
```

### 实测（2026-11-22 · deepseek-chat · 45 章 185 节）

| 项 | 结果 |
|---|---|
| 用时 | 608 秒（≈3.3 s/节，含重试） |
| 调用 | 185/185 成功，0 失败 |
| **自动过闸** | **84/185 = 45.4%** |
| 问题分布 | `punch_count`×75 · `clause_too_long`×31 · `dou_turn_too_long`×25 |

三条失败全是**结构性偏差**（包袱堆太多、小句超 20 字、逗哏连说太长），不是内容跑题——
这恰好落在「微调擅长解决系统性偏差」的那一档，但**是否值得微调仍取决于人工修改率**，
需要先把 `drafts_review.md` 改一轮再跑 `score_edits.py`。

> 注意：这里的「自动过闸率」**不能替代** §5.8 的人工修改率。前者量的是规则，
> 后者量的是「人要不要重写」——两个指标分开记，别混着用。

