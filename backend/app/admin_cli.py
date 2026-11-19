"""管理员命令行（r23：注册不开放，账号由管理员创建）。

用法（在 `backend/` 下执行）：

    python -m app.admin_cli create-user --email a@b.com --name 小王 --mode own
    python -m app.admin_cli create-user --email a@b.com --id default   # 接管 r23 前的存量数据
    python -m app.admin_cli adopt-default --email a@b.com              # 把存量数据改挂到已有账号
    python -m app.admin_cli set-mode --email a@b.com --mode shared
    python -m app.admin_cli disable --email a@b.com      # --undo 启用
    python -m app.admin_cli reset-password --email a@b.com
    python -m app.admin_cli list
    python -m app.admin_cli doctor      # 只读自查：配置来源 / 数据层 / AI 端点策略（无副作用）
    python -m app.admin_cli rebuild-index --kind question|tutorial|all   # 重建 RAG 索引
"""

import argparse
import secrets
import sys
import uuid
from pathlib import Path

from app.core import db, repository
from app.core.auth import hash_password, normalize_email
from app.services.ai.user_ai import KEY_MODE_OWN, KEY_MODE_SHARED

_MODES = (KEY_MODE_OWN, KEY_MODE_SHARED)

#: 会改库的子命令；跑完必须补一次副本重建，否则服务进程仍会报 `db_replica=ready`。
_MUTATING_COMMANDS = (
    "create-user",
    "adopt-default",
    "set-mode",
    "disable",
    "reset-password",
    # r140：重建索引会写 `rag_chunks` / `rag_index_state`，同样是非服务进程的旁路写入，
    # 必须补副本，否则 SQLite 模式下服务进程察觉不到、/health 仍报 ready。
    "rebuild-index",
)


def _generate_password() -> str:
    return secrets.token_urlsafe(12)


def _fail(message: str) -> int:
    print(f"错误：{message}", file=sys.stderr)
    return 1


def _create_user(args: argparse.Namespace) -> int:
    email = normalize_email(args.email)
    if not email or "@" not in email:
        return _fail("邮箱格式不正确")
    if repository.get_user_by_email(email) is not None:
        return _fail(f"用户已存在：{email}")
    user_id = (args.id or "").strip() or uuid.uuid4().hex
    if not all(char.isalnum() or char in "-_" for char in user_id):
        return _fail("用户 id 只能包含字母、数字、连字符与下划线")
    if repository.get_user_by_id(user_id) is not None:
        return _fail(f"用户 id 已存在：{user_id}")
    password = _generate_password()
    display_name = (args.name or email.split("@")[0]).strip()
    repository.create_user(
        user_id=user_id,
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        key_mode=args.mode,
    )
    print(f"已创建用户：{email}（{display_name}，Key 模式 {args.mode}）")
    print(f"初始密码：{password}")
    print("以上密码只显示这一次，请转交用户并提醒其登录后修改。")
    if user_id == repository.DEFAULT_USER_ID:
        print("提示：该账号 id 为 default，登录后即可看到 r23 之前的存量数据。")
    return 0


def _adopt_default(args: argparse.Namespace) -> int:
    email = normalize_email(args.email)
    user = repository.get_user_by_email(email)
    if user is None:
        return _fail(f"用户不存在：{email}")
    target = str(user["id"])
    if target == repository.DEFAULT_USER_ID:
        return _fail("该账号 id 已是 default，无需迁移")
    migrated = repository.adopt_default_data(target)
    total = sum(migrated.values())
    if total == 0:
        print("没有发现 user_id='default' 的存量数据，无需迁移。")
        return 0
    print(f"已把 {total} 行存量数据改挂到 {email}：")
    for table, count in migrated.items():
        print(f"  {table}: {count}")
    return 0


def _set_mode(args: argparse.Namespace) -> int:
    email = normalize_email(args.email)
    if repository.get_user_by_email(email) is None:
        return _fail(f"用户不存在：{email}")
    repository.update_user_key_mode(repository.get_user_by_email(email)["id"], args.mode)
    print(f"已把 {email} 的 Key 模式改为 {args.mode}")
    return 0


def _disable(args: argparse.Namespace) -> int:
    email = normalize_email(args.email)
    user = repository.get_user_by_email(email)
    if user is None:
        return _fail(f"用户不存在：{email}")
    disabled = not args.undo
    repository.set_user_disabled(str(user["id"]), disabled)
    print(f"已{'停用' if disabled else '启用'} {email}")
    return 0


def _reset_password(args: argparse.Namespace) -> int:
    email = normalize_email(args.email)
    user = repository.get_user_by_email(email)
    if user is None:
        return _fail(f"用户不存在：{email}")
    password = _generate_password()
    repository.update_user_password(str(user["id"]), hash_password(password))
    repository.delete_user_sessions(str(user["id"]))
    print(f"已重置 {email} 的密码，旧会话已全部失效。")
    print(f"新密码：{password}")
    return 0


def _list(args: argparse.Namespace) -> int:
    users = repository.list_users()
    if not users:
        print("（还没有任何用户）")
        return 0
    print(f"{'邮箱':<32} {'姓名':<12} {'模式':<8} {'角色':<8} 状态")
    for user in users:
        status = "已停用" if user["disabled"] else "正常"
        print(
            f"{user['email']:<32} {user['display_name']:<12} "
            f"{user['key_mode']:<8} {user['role']:<8} {status}"
        )
    return 0


def _doctor(_args: argparse.Namespace) -> int:
    """只读自查：打印「这套部署实际会怎么跑」，并直接回答「能不能填内网地址」。

    内网部署者手里通常没有 docker / 观测平台，也没有人帮他看日志 —— 一条命令把
    配置来源、数据层选择、AI 端点策略、缓存形态和结论打全，比让他翻五个文件快得多。

    **刻意只读**：不连库、不建库、不改任何状态。自查命令一旦有副作用，
    它给出的结论就不可信了（比如顺手创建了一个空 SQLite 库，下次启动就会走单机）。
    """
    from app.core.config import get_settings

    settings = get_settings()
    env_file = Path(str(settings.model_config.get("env_file") or ".env")).resolve()

    print("== 部署自查 ==")
    print(f"工作目录        : {Path.cwd()}")
    print(f"Python          : {sys.version.split()[0]}")
    print(f"配置文件        : {env_file}（{'存在' if env_file.exists() else '不存在'}）")
    print("  · .env 按进程工作目录解析：必须在 backend/ 下启动才能读到它")
    print(f"DB_MODE         : {settings.db_mode}")

    pg_ok = db.probe_postgresql_quiet()
    marker = db.sqlite_marker("complete")
    sqlite_path = Path(settings.sqlite_path).resolve()
    if pg_ok:
        db_line = "PostgreSQL 可达 → 优先使用 PostgreSQL"
    elif marker == "1":
        db_line = f"SQLite 已有权威库 → {sqlite_path}"
    elif db.has_sqlite_data():
        db_line = "SQLite 有数据但缺权威标记 → 启动会被拒绝（需 DB_MODE=sqlite 显式声明）"
    else:
        db_line = f"无 PostgreSQL、SQLite 为空 → 首次启动新建单机库 {sqlite_path}"
    print(f"数据层          : {db_line}")

    runtime = settings.resolve_ai()
    print(f"服务端 AI 档位  : provider={runtime.provider or '(legacy)'} model={runtime.model or '(空)'}")
    print(f"                  端点={runtime.base_url or '(空)'} 就绪={'是' if runtime.ready else '否'}")
    if not runtime.ready and runtime.reason:
        print(f"                  原因：{runtime.reason}")
    print("                  注：服务端档位填内网地址不受 SSRF 门禁限制（管理员配置视为可信）")

    try:
        from app.core import redis_cache

        redis_state = redis_cache.status()
    except Exception as exc:  # noqa: BLE001 - 自查命令不能因为探活失败就没有输出
        redis_state = f"探活失败（{type(exc).__name__}）"
    print(f"缓存层          : {redis_state}（memory = 未配置 Redis，进程内缓存）")
    radar = "离线样本（不访问上游）" if settings.radar_offline else f"会访问公网（调度={settings.radar_schedule}）"
    print(f"雷达采集        : {radar}")

    print()
    if settings.ai_allow_private_endpoints:
        print("结论：用户自带 AI 端点【可以】填内网地址 ✅（私网 / 环回放行；云元数据仍拒绝）")
        return 0
    print("结论：用户自带 AI 端点【不能】填内网地址 ❌（只允许公网地址）")
    print(f"      要放行：在 {env_file} 里加一行 AI_ALLOW_PRIVATE_ENDPOINTS=true，然后重启后端进程")
    if not env_file.exists():
        print("      注意：这个文件还不存在 —— env_file 路径按工作目录解析，确认启动时 cwd 是 backend/")
    print("      不想改开关：把内网模型写进服务端档位（AI_BASE_URL 或 AI_PROVIDER 对应档），")
    print("      那条通道不受 SSRF 门禁约束。")
    return 0


def _rebuild_index(args: argparse.Namespace) -> int:
    """重建 RAG 向量索引（题库 / 教程 / 全部），供无浏览器、无网的内网机器运维。

    与考工页两个按钮走同一套 `indexer` 实现（全量替换、幂等），只是换一个不需要登录
    与前端的入口；输出带 vector_mode / embedder / chunk 数，一条命令即可诊断。
    """
    from app.services.retrieval import indexer, tutorial_seed

    kind = args.kind
    try:
        if kind in ("question", "all"):
            summary = indexer.rebuild_question_index()
            print(
                f"题库索引已重建：{summary['question_chunks']} 条 chunk"
                f"（engine={summary['engine']} / vector_mode={summary['vector_mode']}，"
                f"embedder={summary['embedder']} 维度 {summary['dim']}）"
            )
        if kind in ("tutorial", "all"):
            items = tutorial_seed.load_items()
            if not items:
                print("没有教程种子：跳过教程索引（题库索引不受影响）")
            else:
                summary = indexer.ingest_tutorial_chunks(items)
                print(
                    f"教程索引已重建：{summary['tutorial_chunks']} 条 chunk"
                    f"（embedder={summary['embedder']}）"
                )
        status = indexer.index_status()
        print(
            f"当前状态：built={status['built']} vector_mode={status['vector_mode']} "
            f"vector_engine={status['vector_engine']} 共 {status['chunk_count']} 条 chunk"
        )
        if status["vector_notice"]:
            print(f"提示：{status['vector_notice']}")
        if status["notice"]:
            print(f"提示：{status['notice']}")
    except Exception as exc:  # noqa: BLE001 - CLI 要把真实原因打给人看，不能吞成静默成功
        return _fail(f"索引重建失败（{type(exc).__name__}）：{exc}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="产品管理员命令（r23）")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-user", help="创建账号并打印初始密码")
    create.add_argument("--email", required=True)
    create.add_argument("--name", default="")
    create.add_argument("--mode", choices=_MODES, default=KEY_MODE_OWN)
    create.add_argument("--id", default="", help="指定用户 id（如 default：接管存量数据）")
    create.set_defaults(func=_create_user)

    adopt = sub.add_parser("adopt-default", help="把 user_id='default' 的存量数据改挂到已有账号")
    adopt.add_argument("--email", required=True)
    adopt.set_defaults(func=_adopt_default)

    mode = sub.add_parser("set-mode", help="切换 own / shared Key 模式")
    mode.add_argument("--email", required=True)
    mode.add_argument("--mode", choices=_MODES, required=True)
    mode.set_defaults(func=_set_mode)

    disable = sub.add_parser("disable", help="停用账号（--undo 恢复）")
    disable.add_argument("--email", required=True)
    disable.add_argument("--undo", action="store_true")
    disable.set_defaults(func=_disable)

    reset = sub.add_parser("reset-password", help="重置密码并使其旧会话失效")
    reset.add_argument("--email", required=True)
    reset.set_defaults(func=_reset_password)

    listing = sub.add_parser("list", help="列出全部用户")
    listing.set_defaults(func=_list)

    # 只读自查：不建库、不写库，因此**不走** `_prepare_database()`（那会 bootstrap 并可能建库）。
    doctor = sub.add_parser("doctor", help="只读自查：配置来源 / 数据层 / AI 端点策略")
    doctor.set_defaults(func=_doctor)

    rebuild = sub.add_parser("rebuild-index", help="重建 RAG 向量索引（全量替换、幂等）")
    rebuild.add_argument(
        "--kind",
        choices=("question", "tutorial", "all"),
        default="all",
        help="重建范围：题库 / 教程 / 全部（默认 all）",
    )
    rebuild.set_defaults(func=_rebuild_index)

    args = parser.parse_args(argv)
    if args.command != "doctor":
        _prepare_database()
    code = args.func(args)
    if code == 0 and args.command in _MUTATING_COMMANDS:
        _sync_replica()
    return code


def _prepare_database() -> None:
    """把 CLI 这个**独立进程**接到正确的权威库上，再执行业务命令。

    直接复用 `db.bootstrap()` —— 与后端服务启动是**同一套判定**：优先 PostgreSQL，
    不可用则接管 SQLite（完整副本 / 单机库），空库则新建单机库。这里不再自己判断一次，
    否则「服务起来了、建号却连不上库」这种割裂会反复出现。
    """
    db.bootstrap()


def _sync_replica() -> None:
    """独立进程写过主库后补齐兜底副本。

    这是单进程约束下唯一诚实的做法：服务进程察觉不到别处的写入，副本会不会落后
    只能由写入方负责。失败不算命令失败——PG 已经是事实源，下一次后端恢复会整库重建。
    """
    if db.is_standalone():
        # 单机模式下 SQLite 本身就是权威库，没有「副本」要补；打印「已同步 0 张表」
        # 只会让人以为同步出了问题。
        return
    try:
        counts = db.refresh_replica()
    except Exception as exc:  # noqa: BLE001 - 副本同步失败不该把已完成的写库翻成失败
        print(
            f"警告：兜底副本同步失败（{type(exc).__name__}），"
            "`/health` 可能仍显示 db_replica=ready；重启后端会整库重建",
            file=sys.stderr,
        )
        return
    print(f"兜底副本已同步：{len(counts)} 张表、{sum(counts.values())} 行")


if __name__ == "__main__":
    raise SystemExit(main())
