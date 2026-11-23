#!/usr/bin/env python3
"""VoxCPM2 训练入口 shim：补掉 transformers 5.x 对 torch>=2.6 的硬性要求。

问题：venv_voxcpm 是 torch 2.5.1（VoxCPM2 要求 >=2.5，而 GPT-SoVITS 那套锁 2.3.1，
所以选了 2.5.1）。但 transformers 5.20 里写死了
`version.parse(torch_version) >= version.parse("2.6.0")` 才启用 PyTorch 后端，
没有环境变量可绕过。于是 `from transformers import get_cosine_schedule_with_warmup`
拿到的是个 dummy，一调用就报 "requires the PyTorch library"。

为什么不直接降级 transformers：它在 site-packages 里有数千个文件，
`pip uninstall` 会触发环境的批量删除守卫（之前 `rm -rf torch` 3645 个文件就被拦了）。

为什么 shim 是安全的：训练路径里 transformers 只被用到两类东西——
    1. `LlamaTokenizerFast` / `PreTrainedTokenizer`（纯 tokenizer，不依赖 torch）
    2. `get_cosine_schedule_with_warmup`（唯一真正要 torch 的）
所以只要在官方脚本 import 之前把第 2 个换成等价实现，其余完全不受影响。
实现与 HuggingFace 官方一致（LambdaLR + 余弦退火 + 线性 warmup）。

用法（由 train_voxcpm_lora.py 调用）：
    python scripts/tts/_voxcpm_train_entry.py --config_path <yaml>
"""

from __future__ import annotations

import math
import runpy
import sys
from pathlib import Path

REPO = Path(r'D:/work_space/_tts/VoxCPM-main')


def patch_transformers_scheduler() -> None:
    import transformers
    from torch.optim.lr_scheduler import LambdaLR

    def get_cosine_schedule_with_warmup(optimizer, num_warmup_steps: int,
                                        num_training_steps: int,
                                        num_cycles: float = 0.5,
                                        last_epoch: int = -1):
        def lr_lambda(current_step: int) -> float:
            if current_step < num_warmup_steps:
                return float(current_step) / float(max(1, num_warmup_steps))
            progress = float(current_step - num_warmup_steps) / float(
                max(1, num_training_steps - num_warmup_steps)
            )
            return max(0.0, 0.5 * (1.0 + math.cos(math.pi * float(num_cycles) * 2.0 * progress)))

        return LambdaLR(optimizer, lr_lambda, last_epoch)

    transformers.get_cosine_schedule_with_warmup = get_cosine_schedule_with_warmup


def main() -> int:
    patch_transformers_scheduler()
    target = REPO / 'scripts' / 'train_voxcpm_finetune.py'
    if not target.exists():
        sys.exit(f'找不到官方训练脚本：{target}')
    # 交给官方脚本自己的 `if __name__ == "__main__":`，参数原样透传
    sys.argv = [str(target)] + sys.argv[1:]
    runpy.run_path(str(target), run_name='__main__')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
