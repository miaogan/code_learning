#!/usr/bin/env python3
"""有声书全量流水线（r151）：把「口播稿 → 音频 → 上线」从 3 章试点扩成全量固定链路。

业务口径（用户 2026-11-23 拍板）：**所有文字都要有音频素材，之后新增的知识也走同一条链**。
- 草稿源 = `scripts/finetune/out/drafts_final2.jsonl`（提示词版 185 节，生成→校验→重试后全过闸）；
  人工改过的节用 `--edits scripts/finetune/out/review_sample-edited.jsonl` 覆盖（40 节定稿）。
- 可听范围 = `frontend/src/content/spoken/coverage.ts` 的 A/B 层（唯一真源，新章登记即纳入）。
- 前端入口只认 `/audio/index.json`：新章部署后「听听」入口自动出现，零发版。

四个阶段（可单独跑，产物互相衔接）：

    # 1) 草稿 → plans（质量闸逐节把关，未过的节跳过并列出；已有 plan 的章不动）
    python scripts/tts/make_audio.py plan \
        --drafts scripts/finetune/out/drafts_final2.jsonl \
        --edits scripts/finetune/out/review_sample-edited.jsonl \
        --plans-dir scripts/tts/out/plans_full

    # 2) 合成（须在 voxcpm venv 的 python 下跑；已合成齐全的章自动跳过，断点续跑）
    #    批量单进程：模型每批只加载一次（默认 8 章/批，--batch-size 0 = 全部一批）；
    #    一批硬崩就拆成单章重试，坏章只影响自己。
    D:/work_space/_tts/venv_voxcpm/Scripts/python.exe scripts/tts/make_audio.py synth \
        --plans-dir scripts/tts/out/plans_full --out-audio scripts/tts/out/audio_full \
        --vox-ref D:/work_space/_tts/dataset/slices/<合规参考音>.wav \
        [--vox-lora <checkpoint>] [--batch-size 8] [--vox-timesteps 10] [--only <chapterId>]

    # 3) 索引（synthesize.py 每次合成后自动重建；本子命令用于不重跑合成的手动重建）
    python scripts/tts/make_audio.py index --out-audio scripts/tts/out/audio_full

    # 4) 部署（拷进仓库 audio/ 即 nginx 分发目录；服务器上则是 ~/skillcoach/audio/）
    python scripts/tts/make_audio.py deploy --audio-src scripts/tts/out/audio_full --deploy-dir audio

    # 5) 常驻触发器（新知识 → 音频自动补齐）：
    #    发现「有 plan 无 manifest」的章就自动合成 + 聚合；合规守卫通过才发布。
    #    守卫 = scripts/tts/voice_compliant.marker（内容：合规音色说明 + 日期）；
    #    标记不存在时产物只留本地（受限音色红线：绝不自动进仓库）。
    python scripts/tts/make_audio.py watch --interval 1800 \
        --python D:/work_space/_tts/venv_voxcpm/Scripts/python.exe \
        --vox-ref <合规参考音> --push

新知识接入路径（不新增任何环节）：登记 coverage 分层 → `draft_spoken.py` 出草稿 →
`make_audio.py plan/synth/deploy`。口播稿质量闸与 AI 标识在各阶段强制执行。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent / 'finetune'))
from build_spoken_plan import to_plan
from validate_spoken import validate

#: prompt 里「小节：标题（1/4）」与「章节：React 状态与渲染」的可读名提取。
_SECTION_TITLE = re.compile(r'^小节：(.+?)（\d+/\d+）\s*$')
_CHAPTER_TITLE = re.compile(r'^章节：(.+?)\s*$')


def _parse_titles(row: dict) -> tuple[str | None, str | None]:
    """从草稿行的 messages（user prompt）里解析（章节标题, 小节标题）。"""
    chapter_title: str | None = None
    section_title: str | None = None
    for message in row.get('messages') or []:
        if message.get('role') != 'user':
            continue
        for line in str(message.get('content') or '').splitlines():
            if chapter_title is None:
                match = _CHAPTER_TITLE.match(line)
                if match:
                    chapter_title = match.group(1)
            match = _SECTION_TITLE.match(line)
            if match:
                section_title = match.group(1)
    return chapter_title, section_title


def load_drafts(path: Path) -> dict[str, list[dict]]:
    """草稿按章分组（保持文件内首次出现的顺序）；行结构 {chapter, section, form, response}。"""
    chapters: dict[str, list[dict]] = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        chapter = str(row.get('chapter') or '')
        section = str(row.get('section') or '')
        if not chapter or not section:
            continue
        chapters.setdefault(chapter, []).append(row)
    return chapters


def load_edits(path: Path | None) -> dict[tuple[str, str], str]:
    """人工定稿覆盖表：{(chapter, section): response}——同节存在则优先于草稿。"""
    if path is None:
        return {}
    edits: dict[tuple[str, str], str] = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        key = (str(row.get('chapter') or ''), str(row.get('section') or ''))
        resp = row.get('response')
        if all(key) and resp is not None:
            edits[key] = str(resp)
    return edits


def load_title_index(path: Path | None) -> tuple[dict[tuple[str, str], str], dict[str, str]]:
    """从起草清单（spoken_drafts.jsonl，带 messages prompt）取可读标题。

    返回（{(chapter, section): 小节标题}, {chapter: 章标题}）。
    生成结果文件（drafts_final2 等）通常不带 messages，标题只能回到 prompt 源取；
    取不到的回落 id（不影响合成，只影响播放器 tab 的可读性）。
    """
    titles: dict[tuple[str, str], str] = {}
    chapter_titles: dict[str, str] = {}
    if path is None or not path.exists():
        return titles, chapter_titles
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        chapter = str(row.get('chapter') or '')
        section = str(row.get('section') or '')
        ct, st = _parse_titles(row)
        if chapter and section and st:
            titles[(chapter, section)] = st
        if chapter and ct:
            chapter_titles.setdefault(chapter, ct)
    return titles, chapter_titles


def stage_plan(args: argparse.Namespace) -> int:
    drafts = load_drafts(Path(args.drafts))
    edits = load_edits(Path(args.edits) if args.edits else None)
    titles, chapter_titles = load_title_index(Path(args.title_source) if args.title_source else None)
    plans_dir = Path(args.plans_dir)
    plans_dir.mkdir(parents=True, exist_ok=True)

    done = failed = skipped_chapters = 0
    for chapter, rows in drafts.items():
        plan_path = plans_dir / f'{chapter}.json'
        if plan_path.exists() and not args.force:
            skipped_chapters += 1
            continue

        # 人工定稿优先：同节覆盖草稿（质量闸仍按最终文本判）
        effective: list[dict] = []
        for row in rows:
            merged = dict(row)
            override = edits.get((chapter, str(row.get('section'))))
            if override is not None:
                merged['response'] = override
            effective.append(merged)

        # 质量闸逐节把关：未过的节跳过（不产 plan），给出可读清单——
        # 这是「全量铺量」下的口径：单节失败不阻塞其它节，修稿后重跑即补齐。
        passed_rows: list[dict] = []
        failed_rows: list[tuple[str, list[str]]] = []
        for row in effective:
            section = str(row.get('section'))
            issues = [f'{code} {msg}' for code, msg in validate({'response': str(row.get('response') or '')})]
            if issues:
                failed_rows.append((section, issues))
            else:
                passed_rows.append(row)
        done += len(passed_rows)
        if failed_rows:
            failed += len(failed_rows)
            print(f'[{chapter}] 质量闸未过 {len(failed_rows)} 节（已跳过，修稿后重跑补齐）：')
            for section, issues in failed_rows[:3]:
                print(f'    {section}: {issues[0]}')

        if not passed_rows:
            continue

        chapter_title: str | None = None
        title_map: dict[str, str] = {}
        for row in effective:
            section = str(row.get('section'))
            ct, st = _parse_titles(row)
            chapter_title = chapter_title or ct
            # 标题优先级：草稿行自带 > prompt 清单（title_source）> sectionId
            if st:
                title_map[section] = st
            elif titles.get((chapter, section)):
                title_map[section] = titles[(chapter, section)]

        form = next(
            (str(r.get('form')) for r in passed_rows if r.get('form') in {'solo', 'duo'}),
            'solo',
        )
        plan = to_plan(
            chapter,
            [(str(r.get('section')), str(r.get('response') or '')) for r in passed_rows],
            form,
            '/audio',
        )
        plan['title'] = chapter_title or chapter_titles.get(chapter) or chapter
        for section in plan['sections']:
            section['title'] = title_map.get(section['sectionId'], section['sectionId'])
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'[plan] {chapter}: {len(plan["sections"])} 节 plan → {plan_path.name}')

    print(f'\nplan 阶段完成：过闸 {done} 节 / 未过 {failed} 节 / 跳过已有 plan 的章 {skipped_chapters} 个')
    return 0


def _plan_sections(plans_dir: Path, chapter: str) -> set[str]:
    data = json.loads((plans_dir / f'{chapter}.json').read_text(encoding='utf-8'))
    return {str(s['sectionId']) for s in data.get('sections', [])}


def _chapters_todo(plans_dir: Path, out_audio: Path, only: str | None, force: bool) -> list[str]:
    """需要合成的章（已齐全的跳过=断点续跑）。"""
    plan_files = sorted(plans_dir.glob('*.json'))
    if only:
        plan_files = [p for p in plan_files if p.stem == only]
    todo: list[str] = []
    for plan_path in plan_files:
        chapter = plan_path.stem
        needed = _plan_sections(plans_dir, chapter)
        manifest_path = out_audio / chapter / 'manifest.json'
        if manifest_path.exists() and not force:
            existing: set[str] = set()
            try:
                data = json.loads(manifest_path.read_text(encoding='utf-8'))
                existing = {str(t.get('sectionId')) for t in data.get('tracks', [])}
            except (json.JSONDecodeError, OSError):
                pass
            if needed <= existing:
                print(f'[synth] {chapter}: 已齐全（{len(existing)} 节），跳过')
                continue
        todo.append(chapter)
    return todo


def _synth_cmd(args: argparse.Namespace, chapters: list[str], plans_dir: Path,
               out_audio: Path) -> list[str]:
    cmd = [
        args.python,
        str(HERE / 'synthesize.py'),
        '--backend', args.backend,
        '--plan-dir', str(plans_dir),
        '--out-audio', str(out_audio),
    ]
    for chapter in chapters:
        cmd += ['--chapter', chapter]
    if args.vox_ref:
        cmd += ['--vox-ref', args.vox_ref]
    if args.vox_lora:
        cmd += ['--vox-lora', args.vox_lora]
    # 形态开关：缺省不传（synthesize.py 默认只跑 solo）；跑对口章用 --only-form all
    if args.only_form:
        cmd += ['--only-form', args.only_form]
    # 速度/质量旋钮：不传就用 synthesize.py 的默认（timesteps=10 / cfg=1.5）
    if args.vox_timesteps is not None:
        cmd += ['--vox-timesteps', str(args.vox_timesteps)]
    if args.vox_cfg is not None:
        cmd += ['--vox-cfg', str(args.vox_cfg)]
    if args.anchor_prev:
        cmd += ['--anchor-prev']
    return cmd


def stage_synth(args: argparse.Namespace) -> int:
    """合成：**多章一个进程**（模型只加载一次）。

    为什么批量（2026-11-23 实测）：VoxCPM2 每启动一个进程都要重新加载 4GB 权重 +
    LoRA（约 30s），45 章逐章 spawn 光重载就 ~22 分钟；批量后随 --batch-size 摊薄。
    实测单节 CPU 后处理（裁静音/句切分/响度/写盘）合计仅 0.3–0.4s，而单节合成
    2–4 分钟——所以**不做**「CPU 后处理与 GPU 合成流水线」，收益 0.5% 属噪声。

    容错：一批失败（OOM/段错误等硬崩溃）就把这批拆成单章逐个重试，
    保住「坏一章不拖累其它章」；单章仍失败则记录并继续。
    """
    plans_dir = Path(args.plans_dir)
    out_audio = Path(args.out_audio)
    todo = _chapters_todo(plans_dir, out_audio, args.only, args.force)
    if not todo:
        print('没有需要合成的章（全部已齐全；--force 可强制重合成）')
        return 0

    batch = len(todo) if args.batch_size <= 0 else args.batch_size
    groups = [todo[i:i + batch] for i in range(0, len(todo), batch)]
    print(f'[synth] 待合成 {len(todo)} 章，分 {len(groups)} 批（每批 ≤{batch} 章，模型每批只加载一次）')

    failed: list[str] = []
    for index, group in enumerate(groups, 1):
        cmd = _synth_cmd(args, group, plans_dir, out_audio)
        print(f'[synth] 批 {index}/{len(groups)}：{", ".join(group)}')
        result = subprocess.run(cmd, check=False)
        if result.returncode == 0:
            continue
        # 硬崩溃兜底：拆成单章重试，隔离坏章
        print(f'[synth] 批 {index} 失败（exit {result.returncode}），逐章重试', file=sys.stderr)
        for chapter in group:
            single = _synth_cmd(args, [chapter], plans_dir, out_audio)
            if subprocess.run(single, check=False).returncode != 0:
                failed.append(chapter)
                print(f'[synth] {chapter}: 失败，跳过', file=sys.stderr)

    if failed:
        print(f'[synth] 未完成 {len(failed)} 章：{", ".join(failed)}（重跑本命令会断点续跑）',
              file=sys.stderr)
        return 1
    return 0


# ---- watch（自动触发器） ----

#: 合规音色守卫标记：存在且非空才允许 deploy 进仓库（内容 = 音色说明 + 日期）。
#: gdg 等受限音色产物只留在 out_audio 本地试听，绝不自动进入仓库/生产。
VOICE_COMPLIANT_MARKER = HERE / 'voice_compliant.marker'


def _voice_compliant() -> str | None:
    if VOICE_COMPLIANT_MARKER.exists():
        text = VOICE_COMPLIANT_MARKER.read_text(encoding='utf-8').strip()
        return text or None
    return None


def _watch_tick(args: argparse.Namespace) -> None:
    """一轮：plan → 找缺音频的章 → synth → index →（合规守卫通过才）deploy + 提交。"""
    # 1) 重跑 plan：新登记的草稿生成新 plans（已有 plan 的章自动跳过）
    plan_ns = argparse.Namespace(drafts=args.drafts, edits=args.edits,
                                 title_source=args.title_source,
                                 plans_dir=args.plans_dir, force=False)
    stage_plan(plan_ns)

    # 2) 找「有 plan 无 manifest」的章
    todo = _chapters_todo(Path(args.plans_dir), Path(args.out_audio), None, False)
    if todo:
        synth_ns = argparse.Namespace(plans_dir=args.plans_dir, out_audio=args.out_audio,
                                      backend=args.backend, python=args.python,
                                      vox_ref=args.vox_ref, vox_lora=args.vox_lora,
                                      only_form=args.only_form, only=None, force=False,
                                      batch_size=args.batch_size, vox_timesteps=args.vox_timesteps,
                                      vox_cfg=args.vox_cfg, anchor_prev=args.anchor_prev)
        stage_synth(synth_ns)

    # 3) 重建索引（含新章）
    build_index(Path(args.out_audio))

    # 4) 合规守卫：标记不存在 → 只留在本地试听目录，绝不进仓库
    compliant = _voice_compliant()
    if compliant is None:
        print(f'[watch] 未检测到合规音色标记（{VOICE_COMPLIANT_MARKER.name}），'
              '产物保留在本地目录，不 deploy / 不提交')
        return

    deploy_ns = argparse.Namespace(audio_src=args.out_audio, deploy_dir=args.deploy_dir)
    stage_deploy(deploy_ns)
    if args.deploy_dir != 'audio':
        return  # 非仓库目录（试验用），不做 git 操作

    status = subprocess.run(['git', 'status', '--porcelain', 'audio'],
                            capture_output=True, text=True, check=False)
    if not status.stdout.strip():
        print('[watch] audio/ 无新增变化，跳过提交')
        return
    subprocess.run(['git', 'add', 'audio'], check=False)
    commit = subprocess.run(['git', 'commit', '-m',
                             f'chore(audio): 新章音频素材上线（watch 自动，音色：{compliant}）'],
                            capture_output=True, text=True, check=False)
    print(f'[watch] 已提交 audio/（音色：{compliant}）')
    if args.push and commit.returncode == 0:
        subprocess.run(['git', 'push', 'origin', 'dev'], check=False)
        print('[watch] 已推送 dev → CI 双门禁 → nginx 分发')


def stage_watch(args: argparse.Namespace) -> int:
    """常驻轮询（或 --interval 0 单次）：新知识落地后音频自动补齐。

    链路：新章草稿 → plan（质量闸）→ synth（GPU）→ index → deploy → 提交。
    合规守卫：`voice_compliant.marker` 不存在时只合成不发布——受限音色产物
    （名人声音红线）永不被自动带进仓库。换合规音色后创建标记即解锁。
    """
    interval = max(0, args.interval)
    rounds = args.max_iterations if args.max_iterations > 0 else 10 ** 9
    if args.backend == 'voxcpm' and not args.vox_ref:
        sys.exit('watch 合成需要 --vox-ref（或 --backend mock 做链路验证）')
    for round_no in range(1, rounds + 1):
        print(f'\n===== watch 第 {round_no} 轮（{datetime.now().strftime("%H:%M:%S")}） =====')
        try:
            _watch_tick(args)
        except (OSError, json.JSONDecodeError, subprocess.SubprocessError, ValueError) as exc:
            # 单轮失败不退出，下一轮重试（watch 是常驻进程，不能让一次故障杀掉守护）
            print(f'[watch] 本轮异常（{exc!r}），{interval}s 后重试', file=sys.stderr)
        if interval == 0:
            break
        time.sleep(interval)
    return 0


def build_index(out_audio: Path) -> int:
    """聚合 out_audio 下所有章的 manifest → index.json（与 synthesize.py 收尾逻辑同口径）。"""
    chapters_index = []
    for chapter_manifest in sorted(out_audio.glob('*/manifest.json')):
        try:
            data = json.loads(chapter_manifest.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            continue
        tracks_idx = [
            {'sectionId': t.get('sectionId'), 'title': t.get('title') or t.get('sectionId'),
             'durationMs': t.get('durationMs', 0)}
            for t in data.get('tracks', []) if isinstance(t, dict) and t.get('sectionId')
        ]
        if not tracks_idx:
            continue
        chapters_index.append({
            'chapterId': data.get('chapterId', chapter_manifest.parent.name),
            'title': data.get('title') or data.get('chapterId', chapter_manifest.parent.name),
            'form': data.get('form', 'solo'),
            'aiGenerated': data.get('aiGenerated', True),
            'sections': tracks_idx,
            'totalMs': sum(t['durationMs'] for t in tracks_idx),
        })
    index_path = out_audio / 'index.json'
    index_path.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    index_path.write_text(
        json.dumps({'generatedAt': datetime.now().isoformat(timespec='seconds'),
                    'chapters': chapters_index},
                   ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    print(f'音频索引 → {index_path}（{len(chapters_index)} 章 / '
          f'{sum(c["totalMs"] for c in chapters_index) / 60000:.1f} 分钟）')
    return 0


def stage_index(args: argparse.Namespace) -> int:
    return build_index(Path(args.out_audio))


def stage_deploy(args: argparse.Namespace) -> int:
    src = Path(args.audio_src)
    dst = Path(args.deploy_dir)
    if not src.exists():
        print(f'来源不存在：{src}')
        return 1
    dst.mkdir(parents=True, exist_ok=True)
    copied = 0
    for chapter_dir in sorted(src.iterdir()):
        if not chapter_dir.is_dir():
            continue
        shutil.copytree(chapter_dir, dst / chapter_dir.name, dirs_exist_ok=True)
        copied += 1
    index_src = src / 'index.json'
    if index_src.exists():
        shutil.copy2(index_src, dst / 'index.json')
    print(f'deploy：{copied} 个章目录 + index.json → {dst.resolve()}')
    if args.deploy_dir == 'audio':
        print('（仓库 audio/ 即 nginx 挂载目录：commit 后随 CI 上线；服务器放 ~/skillcoach/audio/ 则免发版）')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description='有声书全量流水线：plan → synth → index → deploy')
    sub = ap.add_subparsers(dest='stage', required=True)

    p_plan = sub.add_parser('plan', help='草稿 → plans（质量闸逐节把关）')
    p_plan.add_argument('--drafts', default='scripts/finetune/out/drafts_final2.jsonl')
    p_plan.add_argument('--edits', default=None, help='人工定稿覆盖表（review_sample-edited.jsonl）')
    p_plan.add_argument('--title-source', default='scripts/finetune/out/spoken_drafts.jsonl',
                        help='可读标题来源（带 messages 的起草清单）；传空串禁用')
    p_plan.add_argument('--plans-dir', default='scripts/tts/out/plans_full')
    p_plan.add_argument('--force', action='store_true', help='已有 plan 的章也重建')
    p_plan.set_defaults(func=stage_plan)

    p_synth = sub.add_parser('synth', help='plans → 音频（须在 voxcpm venv 下跑）')
    p_synth.add_argument('--plans-dir', default='scripts/tts/out/plans_full')
    p_synth.add_argument('--out-audio', default='scripts/tts/out/audio_full')
    p_synth.add_argument('--backend', default='voxcpm', choices=['voxcpm', 'mock'])
    p_synth.add_argument('--python', default=sys.executable, help='synthesize.py 用的解释器（合成须 voxcpm venv）')
    p_synth.add_argument('--vox-ref', default=None, help='参考音路径（voxcpm 必填）')
    p_synth.add_argument('--vox-lora', default=None)
    p_synth.add_argument('--only', default=None, help='只合成指定章')
    p_synth.add_argument('--force', action='store_true', help='已齐全的章也重合成')
    p_synth.add_argument('--batch-size', type=int, default=8,
                         help='每批章数（一个进程=一次模型加载；0 或负数 = 全部一批）')
    # 速度/质量旋钮（透传给 synthesize.py；不传走其默认 timesteps=10 / cfg=1.5）
    p_synth.add_argument('--vox-timesteps', type=int, default=None,
                         help='VoxCPM2 CFM 采样步数（10 默认；降到 8 约快 15-20%%，音质轻微下降）')
    p_synth.add_argument('--vox-cfg', type=float, default=None, help='VoxCPM2 引导强度（默认 1.5）')
    p_synth.add_argument('--anchor-prev', action='store_true',
                         help='VoxCPM2：把上一句并进缓存当 continuation 锚（长文音色更稳）')
    p_synth.add_argument('--only-form', choices=['solo', 'duo', 'all'], default=None,
                         help='形态过滤（缺省不传 = synthesize 默认只跑 solo；对口章用 all）')
    p_synth.set_defaults(func=stage_synth)

    p_index = sub.add_parser('index', help='重建 /audio/index.json（不重跑合成）')
    p_index.add_argument('--out-audio', default='scripts/tts/out/audio_full')
    p_index.set_defaults(func=stage_index)

    p_deploy = sub.add_parser('deploy', help='拷贝到分发目录（仓库 audio/ 或服务器 audio 卷）')
    p_deploy.add_argument('--audio-src', default='scripts/tts/out/audio_full')
    p_deploy.add_argument('--deploy-dir', default='audio')
    p_deploy.set_defaults(func=stage_deploy)

    p_watch = sub.add_parser('watch', help='常驻轮询：新章自动合成（合规守卫通过才发布）')
    p_watch.add_argument('--interval', type=int, default=1800,
                         help='轮询间隔秒（默认 30 分钟；0 = 只跑一轮）')
    p_watch.add_argument('--max-iterations', type=int, default=0, help='最多轮数（0 = 不限）')
    p_watch.add_argument('--drafts', default='scripts/finetune/out/drafts_final2.jsonl')
    p_watch.add_argument('--edits', default=None, help='人工定稿覆盖表')
    p_watch.add_argument('--title-source', default='scripts/finetune/out/spoken_drafts.jsonl')
    p_watch.add_argument('--plans-dir', default='scripts/tts/out/plans_full')
    p_watch.add_argument('--out-audio', default='scripts/tts/out/audio_full')
    p_watch.add_argument('--backend', default='voxcpm', choices=['voxcpm', 'mock'])
    p_watch.add_argument('--python', default=sys.executable, help='synthesize.py 用的解释器')
    p_watch.add_argument('--vox-ref', default=None)
    p_watch.add_argument('--vox-lora', default=None)
    p_watch.add_argument('--only-form', choices=['solo', 'duo', 'all'], default='all',
                         help='watch 场景默认 all（新知识两类形态都要覆盖）')
    p_watch.add_argument('--batch-size', type=int, default=8)
    p_watch.add_argument('--vox-timesteps', type=int, default=None)
    p_watch.add_argument('--vox-cfg', type=float, default=None)
    p_watch.add_argument('--anchor-prev', action='store_true')
    p_watch.add_argument('--deploy-dir', default='audio', help='发布目录（仓库 audio/ 由 nginx 挂载）')
    p_watch.add_argument('--push', action='store_true', help='提交后推送 dev（触发 CI 上线）')
    p_watch.set_defaults(func=stage_watch)

    args = ap.parse_args()
    return int(args.func(args))


if __name__ == '__main__':
    sys.exit(main())
