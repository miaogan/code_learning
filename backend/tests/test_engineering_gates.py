"""工程门禁（QA D-1/D-2/D-3 的常驻回归）。

D-1：`repository.py` 是唯一 SQL 出口 —— 除它和 `db.py`（建表）外，`app/` 下不得直写 SQL。
D-2：`AIClient.complete_model` 必须接受 `timeout_s`（TECHNICAL §5），且调用方直接传参，
     不允许再用 `inspect.signature` 反射探测签名兜底（那会把生产分支降级成死代码）。
D-3：`frontend/package-lock.json` 必须存在、与 `package.json` 声明同步、且条目带
     `resolved` + `integrity`，CI 的 `npm ci` 才谈得上可复现。

这些断言在修复前必然失败，修复后通过；改动相关代码时请不要放宽。
"""

from __future__ import annotations

import ast
import inspect
import json
import re
from pathlib import Path

from app.services.ai import AIClient
from app.services import interview as interview_service

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = REPO_ROOT / "backend" / "app"
FRONTEND = REPO_ROOT / "frontend"

SQL_ALLOWED = {"repository.py", "db.py"}
SQL_MARKERS = (
    "INSERT INTO",
    "DELETE FROM",
    "UPDATE ",
    "SELECT ",
)


def _sql_executions(source: str) -> list[str]:
    """AST 层面找 `*.execute(...)` / `*.executescript(...)` 调用。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover - app 代码不会语法错误
        return []
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in {"execute", "executescript"}:
            hits.append(f"line {node.lineno}: {func.attr}(")
    return hits


def test_sql_only_through_repository() -> None:
    offenders: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        if path.name in SQL_ALLOWED:
            continue
        source = path.read_text(encoding="utf-8")
        hits = _sql_executions(source)
        markers = [m for m in SQL_MARKERS if m in source]
        if hits or markers:
            offenders.append(f"{path.relative_to(REPO_ROOT)}: {hits or markers}")
    assert not offenders, f"裸 SQL 越过了唯一出口 repository.py：{offenders}"


def test_complete_model_accepts_timeout() -> None:
    params = inspect.signature(AIClient.complete_model).parameters
    assert "timeout_s" in params, f"complete_model 缺少 timeout_s：{list(params)}"
    assert params["timeout_s"].kind is inspect.Parameter.KEYWORD_ONLY, "timeout_s 必须为 keyword-only"


def test_interview_passes_timeout_without_reflection() -> None:
    source = inspect.getsource(interview_service)
    assert "timeout_s=SCORING_TIMEOUT_S" in source, "单题评分未把 14s 预算交给客户端"
    assert "inspect.signature" not in source, "不再允许用签名反射兜底超时"


def test_frontend_lockfile_is_reproducible() -> None:
    lock_path = FRONTEND / "package-lock.json"
    assert lock_path.is_file(), "缺少 frontend/package-lock.json，CI 的 npm ci 无法执行"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    root = lock.get("packages", {}).get("")
    assert isinstance(root, dict), "lockfile 缺少根 package 条目"
    assert root.get("dependencies") == package.get("dependencies"), "dependencies 与 package.json 不同步"
    assert root.get("devDependencies") == package.get("devDependencies"), "devDependencies 不同步"
    assert int(lock.get("lockfileVersion", 0)) >= 2, "lockfileVersion 过低"
    unresolved = [
        key
        for key, entry in lock["packages"].items()
        if key and entry.get("version") and not (entry.get("resolved") and entry.get("integrity"))
    ]
    assert not unresolved, f"{len(unresolved)} 个条目缺 resolved/integrity：{unresolved[:3]}"


def test_ci_uses_npm_ci() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert re.search(r"run:\s*npm ci\b", workflow), "CI 未使用 npm ci"
    assert "frontend/package-lock.json" in workflow, "CI 未引用 lockfile 作为缓存键"


def test_no_raw_colors_outside_tokens() -> None:
    """QA D-4：颜色只走 tokens.css 变量（AGENTS §4）。"""
    offenders: list[str] = []
    for css in sorted((FRONTEND / "src").rglob("*.css")):
        if css.name == "tokens.css":
            continue
        hits = re.findall(r"rgba?\(|#[0-9a-fA-F]{3,8}", css.read_text(encoding="utf-8"))
        if hits:
            offenders.append(f"{css.relative_to(REPO_ROOT)}: {len(hits)} 处")
    assert not offenders, f"非 tokens.css 出现裸色值：{offenders}"


#: 项目根只允许团队文档；其余命令输出 / scratch 必须留在 logs/（已被 gitignore 挡住）。
ROOT_FILES_ALLOWED = {"AGENTS.md", "README.md"}
DUMP_SUFFIXES = {".log", ".out", ".txt", ".dump", ".tmp"}


def test_no_command_output_dumps_in_repo_root() -> None:
    """r5 QA D-4：dev 轮次的命令输出 dump 不得散落项目根（收口提交会连带入库）。"""
    offenders = [
        path.name
        for path in REPO_ROOT.iterdir()
        if path.is_file()
        and path.name not in ROOT_FILES_ALLOWED
        and not path.name.startswith(".git")
        and (path.suffix in DUMP_SUFFIXES or path.name.startswith("_"))
    ]
    assert not offenders, f"项目根散落命令输出 dump（请移到 logs/teamflow/<runId>/）：{offenders}"


def test_run_logs_stay_out_of_git() -> None:
    """运行日志是 transient scratch：`logs/teamflow/` 必须被 gitignore 挡住。"""
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert re.search(r"^logs/teamflow/$", ignored, re.MULTILINE), "运行日志未纳入 gitignore"


