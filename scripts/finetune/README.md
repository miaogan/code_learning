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
然后跑上面的校验命令。

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
