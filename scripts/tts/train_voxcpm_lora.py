#!/usr/bin/env python3
"""VoxCPM2 LoRA 微调包装（r150）：生成配置并启动官方训练脚本。

为什么不直接用官方 yaml：官方两套配置里全是 `/path/to/...` 占位，手改容易漏
（尤其 `sample_rate` 必须等于 16000，写错会在数据校验阶段直接失败）。
这个包装只做三件事：填路径、按显存挑默认值、把等价命令打印出来便于复现。

显存经验（RTX 4070 Laptop 8GB，2B 模型 bf16）：
    - 权重本身约 4.3GB，剩下的才给激活与梯度 → `batch_size=1` + 梯度累积
    - `max_batch_tokens` 是**按 token 数切批**的上限，4096 比官方 8192 稳
    - Windows 下 `num_workers` 必须 0：HF datasets + Windows 的多进程 DataLoader
      会死锁（GPT-SoVITS 那轮就卡在这，s2 没跑满 epoch）

用法：
    python scripts/tts/train_voxcpm_lora.py \\
        --dataset D:/work_space/_tts/voxcpm_ds \\
        --out     D:/work_space/_tts/voxcpm_lora/gdg_v1 \\
        --steps   1500
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(r'D:/work_space/_tts/VoxCPM-main')
DEFAULT_MODEL = Path(r'D:/work_space/_tts/VoxCPM/pretrained_models')


def main() -> int:
    ap = argparse.ArgumentParser(description='VoxCPM2 LoRA 微调')
    ap.add_argument('--dataset', required=True, help='build_voxcpm_dataset.py 的输出目录')
    ap.add_argument('--out', required=True, help='输出目录（放配置与 checkpoint）')
    ap.add_argument('--model', default=str(DEFAULT_MODEL))
    ap.add_argument('--steps', type=int, default=1500)
    ap.add_argument('--batch-size', type=int, default=1)
    ap.add_argument('--grad-accum', type=int, default=16)
    ap.add_argument('--lr', type=float, default=1e-4)
    ap.add_argument('--lora-r', type=int, default=32)
    ap.add_argument('--lora-alpha', type=int, default=32)
    ap.add_argument('--max-batch-tokens', type=int, default=4096)
    ap.add_argument('--save-interval', type=int, default=250)
    ap.add_argument('--valid-interval', type=int, default=250)
    ap.add_argument('--num-workers', type=int, default=0)
    ap.add_argument('--log-interval', type=int, default=10)
    ap.add_argument('--no-val', dest='use_val', action='store_false',
                    help='不挂验证集（注意：官方脚本在 step=0 就会跑一次验证，'
                         '验证是逐条自回归生成，很慢——冒烟测速时务必关掉）')
    ap.add_argument('--dry-run', action='store_true', help='只生成配置，不启动训练')
    args = ap.parse_args()

    ds = Path(args.dataset)
    train_manifest = ds / 'train.jsonl'
    if not train_manifest.exists():
        sys.exit(f'找不到 {train_manifest}；先跑 build_voxcpm_dataset.py')
    val_manifest = ds / 'val.jsonl'

    out = Path(args.out)
    ckpt = out / 'checkpoints'
    logs = out / 'logs'
    ckpt.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)

    n_train = sum(1 for ln in train_manifest.read_text(encoding='utf-8').splitlines() if ln.strip())
    epochs = args.steps * args.batch_size * args.grad_accum / max(n_train, 1)

    cfg = {
        'pretrained_path': str(args.model),
        'train_manifest': str(train_manifest),
        'val_manifest': str(val_manifest) if (val_manifest.exists() and args.use_val) else None,
        'sample_rate': 16000,        # 必须等于 audio_vae_config.sample_rate
        'out_sample_rate': 48000,
        'batch_size': args.batch_size,
        'grad_accum_steps': args.grad_accum,
        'num_workers': args.num_workers,
        'preprocessing_num_workers': 2,
        'num_iters': args.steps,
        'log_interval': args.log_interval,
        'valid_interval': args.valid_interval,
        'save_interval': args.save_interval,
        'learning_rate': args.lr,
        'weight_decay': 0.01,
        # 小步数冒烟/短训时固定 50 步 warmup 会吃掉 1/3 训练（lr 还没升起来就结束了）
        'warmup_steps': max(5, args.steps // 20),
        'max_steps': args.steps,
        'max_batch_tokens': args.max_batch_tokens,
        'max_grad_norm': 1.0,
        'save_path': str(ckpt),
        'tensorboard': str(logs),
        'lambdas': {'loss/diff': 1.0, 'loss/stop': 1.0},
        'lora': {
            'enable_lm': True,
            'enable_dit': True,
            'enable_proj': False,
            'r': args.lora_r,
            'alpha': args.lora_alpha,
            'dropout': 0.0,
            'target_modules_lm': ['q_proj', 'v_proj', 'k_proj', 'o_proj'],
            'target_modules_dit': ['q_proj', 'v_proj', 'k_proj', 'o_proj'],
        },
    }

    try:
        import yaml

        cfg_path = out / 'train_config.yaml'
        cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding='utf-8')
    except Exception:
        cfg_path = out / 'train_config.json'
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    print(f'配置: {cfg_path}')
    print(f'样本: train {n_train} 条 · 有效 batch {args.batch_size * args.grad_accum} '
          f'· 约 {epochs:.1f} 个 epoch')
    print(f'checkpoint -> {ckpt}（每 {args.save_interval} 步）')

    cmd = [sys.executable, str(Path(__file__).resolve().parent / '_voxcpm_train_entry.py'),
           '--config_path', str(cfg_path)]
    print('命令:', ' '.join(cmd))
    if args.dry_run:
        return 0

    return subprocess.call(cmd, cwd=str(REPO))


if __name__ == '__main__':
    raise SystemExit(main())
