"""管理员命令行（r23：注册不开放，账号由管理员创建）。

用法（在 `backend/` 下执行）：

    python -m app.admin_cli create-user --email a@b.com --name 小王 --mode own
    python -m app.admin_cli create-user --email a@b.com --id default   # 接管 r23 前的存量数据
    python -m app.admin_cli adopt-default --email a@b.com              # 把存量数据改挂到已有账号
    python -m app.admin_cli set-mode --email a@b.com --mode shared
    python -m app.admin_cli disable --email a@b.com      # --undo 启用
    python -m app.admin_cli reset-password --email a@b.com
    python -m app.admin_cli list
"""

import argparse
import secrets
import sys
import uuid

from app.core import repository
from app.core.auth import hash_password, normalize_email
from app.core.db import init_db
from app.services.ai.user_ai import KEY_MODE_OWN, KEY_MODE_SHARED

_MODES = (KEY_MODE_OWN, KEY_MODE_SHARED)


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

    args = parser.parse_args(argv)
    init_db()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
