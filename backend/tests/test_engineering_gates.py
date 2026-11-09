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
import random
import re
import subprocess
from pathlib import Path
from typing import get_args

from app.schemas import ExamKind, Profile
from app.services.ai.ai import AIClient
from app.services.assessment import exam_selector, question_bank
from app.services.interview import interview as interview_service
from app.services.profile import profile as profile_service
from app.services.report import rules
from app.services.resume import resume_polish as resume_polish_service

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


def test_ai_call_sites_use_unified_timeout() -> None:
    """超时统一在 config（600s）：调用点不得再各自覆写，也不允许签名反射兜底。"""
    for module in (interview_service, profile_service, resume_polish_service):
        source = inspect.getsource(module)
        assert "timeout_s=" not in source, f"{module.__name__} 仍在调用点覆写超时"
        assert "inspect.signature" not in source, f"{module.__name__} 不允许用签名反射兜底超时"


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


# --- r6（AC-15）：题库入库 / 熟练度阈值 / 组卷台阶的静态门禁 ------------------
#
# 本轮把「题库读写」「熟练度判定」「选池与 6 层阶梯」拆成三个新服务模块，最容易漂移的三处
# 各有一条常驻断言：DDL/SQL 单源、阈值只住 config、`_usable` 与结构闸门各一份。
# 这些断言按 `TECHNICAL §2.1/§2.4/§3` 写成，改动相关实现时不要放宽。

#: r6 改动面（TECHNICAL §1 白名单的后端子集）。路径一律**仓库根相对**（含 `backend/` 前缀）：
#: `_r6_ast()` / `test_direction_literals_not_duplicated` 都按 `REPO_ROOT / rel` 解析，
#: 漏掉前缀会在 pytest 的 cwd=`backend/` 下解析成 `<repo>/app/...` 而 FileNotFoundError（QA D-1，
#: 常驻回归见 `test_r6_touched_paths_resolve`）。
R6_TOUCHED = (
    "backend/app/core/db.py",
    "backend/app/core/repository.py",
    "backend/app/core/config.py",
    "backend/app/schemas.py",
    "backend/app/services/report/rules.py",
    "backend/app/services/assessment/question_bank.py",
    "backend/app/services/assessment/proficiency.py",
    "backend/app/services/assessment/exam_selector.py",
    "backend/app/services/assessment/exam.py",
    "backend/app/main.py",
)

#: 方向闭集（rules.DIRECTIONS 的期望值；散落即漂移）。
DIRECTIONS = ("前端", "后端", "算法与数据结构", "计算机基础", "AI 工程", "中间件与运维", "SQL 与数据库", "研发工程实践")

SERVICES = APP_DIR / "services"


def _r6_ast(rel: str) -> ast.Module:
    """读 r6 模块的 AST；`rel` 必须是**仓库根相对**路径（如 `backend/app/schemas.py`）。"""
    path = REPO_ROOT / rel
    assert path.is_file(), f"{rel} 未落地（r6 架构蓝图要求的模块；路径应为仓库根相对）"
    return ast.parse(path.read_text(encoding="utf-8"))


def test_r6_touched_paths_resolve() -> None:
    """QA D-1 回归：改动面清单 / AST 读取的路径必须按仓库根相对解析成功。

    本用例在修复前必然失败（清单里 10 条全缺 `backend/` 前缀），修复后通过；
    将来新增条目漏前缀会在这里以「路径不可解析」直接报出，而不是等到别的用例 FileNotFoundError。
    """
    missing = [rel for rel in R6_TOUCHED if not (REPO_ROOT / rel).is_file()]
    assert not missing, f"R6_TOUCHED 路径不可解析（应为仓库根相对，含 backend/ 前缀）：{missing}"


def _ddl_block(source: str, table: str) -> str:
    marker = f"CREATE TABLE IF NOT EXISTS {table}"
    assert marker in source, f"db.py 未声明 {table} 表（TECHNICAL §2.1）"
    return source.split(marker, 1)[1].split(");", 1)[0]


def _python_defs() -> dict[str, list[str]]:
    """`app/` 下所有函数名（含嵌套）→ 定义所在文件（仓库根相对）。"""
    defs: dict[str, list[str]] = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - app 代码不会语法错误
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs.setdefault(node.name, []).append(str(path.relative_to(REPO_ROOT)).replace("\\", "/"))
    return defs


def _literal_values(tree: ast.Module, name: str) -> set[str]:
    """取 `name = Literal["a", "b"]` / `name: tuple[str, ...] = ("a", "b")` 的取值集合。"""
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets, value = [node.target], node.value
        elif isinstance(node, ast.Assign) and node.value is not None:
            targets, value = list(node.targets), node.value
        if not any(isinstance(t, ast.Name) and t.id == name for t in targets) or value is None:
            continue
        if isinstance(value, ast.Subscript):  # Literal[...]
            value = value.slice
        elements = getattr(value, "elts", None)
        if elements is None:
            continue
        return {elt.value for elt in elements if isinstance(elt, ast.Constant) and isinstance(elt.value, str)}
    return set()


def _class_annotations(tree: ast.Module, model: str) -> dict[str, ast.expr | None]:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == model:
            return {
                child.target.id: child.value
                for child in node.body
                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name)
            }
    return {}


def test_ddl_lives_only_in_db_module() -> None:
    """DDL 只允许住 `db.py`（无迁移框架：CREATE TABLE IF NOT EXISTS 即升级）。"""
    offenders: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        if path.name == "db.py":
            continue
        source = path.read_text(encoding="utf-8")
        if "CREATE TABLE" in source or "CREATE INDEX" in source:
            offenders.append(str(path.relative_to(REPO_ROOT)).replace("\\", "/"))
    assert not offenders, f"DDL 越过唯一出处 db.py：{offenders}"


def test_question_tables_declared_in_db() -> None:
    """`questions`（11 列）+ `question_attempts`（6 列 + 唯一约束）必须幂等建表。"""
    source = (APP_DIR / "core" / "db.py").read_text(encoding="utf-8")
    questions = _ddl_block(source, "questions")
    attempts = _ddl_block(source, "question_attempts")
    for column in ("id", "direction", "kind", "difficulty", "essentiality", "prompt", "options", "answer", "source"):
        assert re.search(rf"\b{column}\b", questions), f"questions 缺列 {column}"
    for column in ("question_id", "run_id", "correct", "answered_at"):
        assert re.search(rf"\b{column}\b", attempts), f"question_attempts 缺列 {column}"
    assert re.search(r"UNIQUE\s*\(\s*question_id\s*,\s*run_id\s*\)", attempts), (
        "question_attempts 缺 UNIQUE(question_id, run_id) 幂等兜底"
    )
    assert re.search(r"CREATE INDEX IF NOT EXISTS idx_\w+ ON questions", source), "questions 缺池查询索引"


def test_proficiency_thresholds_only_from_config() -> None:
    """30 / 2 / 3 三个阈值只在 `config.Settings`（可环境变量覆盖），服务层不得写字面量。"""
    from app.core.config import Settings

    fields = Settings.model_fields
    for name, default in (
        ("proficiency_window_days", 30),
        ("proficiency_correct_threshold", 2),
        ("recent_paper_exclude", 3),
    ):
        assert name in fields, f"config.Settings 缺 {name}"
        assert fields[name].default == default, f"{name} 默认值应为 {default}"

    offenders: list[str] = []
    for path in sorted(SERVICES.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and type(node.value) is int and node.value == 30:
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"窗口天数须来自 config.get_settings()，服务层出现 30 字面量：{offenders}"

    rules_source = (SERVICES / "report" / "rules.py").read_text(encoding="utf-8")
    assert not re.search(r"PROFICIENCY|WINDOW_DAYS|RECENT_PAPER", rules_source), (
        "阈值常量漂回 rules.py（阈值与闭集分工，阈值只住 config.py）"
    )


def test_single_usable_and_structure_gate() -> None:
    """`_usable` 只在 question_bank.py；结构闸门 build_paper 只在 exam_selector.py。"""
    defs = _python_defs()
    assert defs.get("_usable") == ["backend/app/services/assessment/question_bank.py"], (
        f"_usable 必须唯一一份且住 question_bank.py，实际：{defs.get('_usable')}"
    )
    assert defs.get("build_paper") == ["backend/app/services/assessment/exam_selector.py"], (
        f"结构闸门必须唯一一份且住 exam_selector.py，实际：{defs.get('build_paper')}"
    )
    # QA D-2：这两条只钉「exam.py 不得复活第二份」，**不是**全 `app/` 范围的命名禁令 ——
    # 其它模块的同名私有助手（如 `proficiency._ordered` 的作答排序）是合法实现，不得误伤。
    exam_py = "backend/app/services/assessment/exam.py"
    assert exam_py not in defs.get("_compose", []), "exam.py 不得保留第二份结构拼装 _compose"
    assert exam_py not in defs.get("_ordered", []), (
        "exam.py 不得复活确定性排序 _ordered（已由 exam_selector.rank_pool 取代）"
    )


def test_closed_sets_single_source() -> None:
    """闭集只在 rules.py，且与 schemas.py 的 Literal 逐字相等。"""
    rules_tree = _r6_ast("backend/app/services/report/rules.py")
    schemas_tree = _r6_ast("backend/app/schemas.py")
    for rule_name, literal_name in (
        ("DIFFICULTIES", "ExamDifficulty"),
        ("ESSENTIALITIES", "QuestionEssentiality"),
    ):
        declared = _literal_values(rules_tree, rule_name)
        expected = _literal_values(schemas_tree, literal_name)
        assert declared, f"rules.{rule_name} 未定义（闭集单一出处）"
        assert expected, f"schemas.{literal_name} 未定义（闭集单一出处）"
        assert declared == expected, f"rules.{rule_name}={sorted(declared)} 与 schemas.{literal_name}={sorted(expected)} 不一致"
    assert _literal_values(rules_tree, "DIRECTIONS") == set(DIRECTIONS), "rules.DIRECTIONS 与四方向闭集不一致"
    assert _literal_values(rules_tree, "PAPER_STAGES") == {"L1", "L2", "L3", "L4", "L5", "L6"}, "PAPER_STAGES 应为 L1..L6"


#: 题型 / 必备度闭集成员（从闭集本身推导，不另写字面量表）。
CLOSED_SET_MEMBERS = frozenset(get_args(ExamKind)) | frozenset(rules.ESSENTIALITIES)


def test_closed_set_members_not_rebound() -> None:
    """QA D-4 回归：kind / 必备度闭集成员不得在 `rules.py` 之外再以字面量绑一次。

    `_X = "must_know"` 这种「物理副本」在闭集改档时会静默失效（L2 回流档位指错地方），
    所以闭集成员只在 `rules.py` 定义（`rules.TEXT_KIND` / `rules.MUST_KNOW`）、别处引用常量。
    payload 的键名（如 `{"must_know": n}`）不是闭集成员赋值，不在本门禁范围。
    """
    allowed = {"rules.py", "schemas.py"}
    offenders: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        if path.name in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                continue
            value = node.value
            if isinstance(value, ast.Constant) and value.value in CLOSED_SET_MEMBERS:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert not offenders, f"闭集成员在 rules.py 之外被字面量重绑（应引用 rules 常量）：{offenders}"


def test_direction_literals_not_duplicated() -> None:
    """r6 改动面内除 rules.py 外不得再写字面方向（防止第二份闭集）。"""
    offenders: list[str] = []
    for rel in R6_TOUCHED:
        if rel.endswith("services/report/rules.py"):
            continue
        source = (REPO_ROOT / rel).read_text(encoding="utf-8")
        offenders += [f"{rel}: {direction}" for direction in DIRECTIONS if f'"{direction}"' in source]
    assert not offenders, f"方向字面量散落 rules.py 之外：{offenders}"


def test_contract_mirror_filtered_count() -> None:
    """`ExamRun.filtered_count` / `reintroduced_count` 双侧同步，且 `answer` 不进响应模型（AC-4）。"""
    schemas_tree = _r6_ast("backend/app/schemas.py")
    run_fields = _class_annotations(schemas_tree, "ExamRun")
    expected = {"run_id", "questions", "filtered_count", "reintroduced_count"}
    assert set(run_fields) == expected, f"ExamRun 字段应为 {sorted(expected)}，实际 {sorted(run_fields)}"
    for field in ("filtered_count", "reintroduced_count"):
        default = run_fields[field]
        if isinstance(default, ast.Call):  # Field(default=0)
            defaults = [kw.value for kw in default.keywords if kw.arg == "default"]
            default = defaults[0] if defaults else None
        assert isinstance(default, ast.Constant) and default.value == 0, (
            f"{field} 旧客户端兼容默认值必须为 0"
        )

    assert "answer" not in _class_annotations(schemas_tree, "ExamQuestion"), "ExamQuestion 不得暴露 answer"

    types_ts = (FRONTEND / "src/api/types.ts").read_text(encoding="utf-8")
    union = re.search(r"export type ExamDifficulty\s*=\s*([^\n;]+)", types_ts)
    assert union, "types.ts 缺 ExamDifficulty"
    assert set(re.findall(r"'([^']+)'", union.group(1))) == _literal_values(schemas_tree, "ExamDifficulty"), (
        "types.ts ExamDifficulty 与 schemas.py Literal 不同步"
    )
    essentiality = re.search(r"export type QuestionEssentiality\s*=\s*([^\n;]+)", types_ts)
    assert essentiality, "types.ts 缺 QuestionEssentiality"
    assert set(re.findall(r"'([^']+)'", essentiality.group(1))) == _literal_values(
        schemas_tree, "QuestionEssentiality"
    ), "types.ts QuestionEssentiality 与 schemas.py Literal 不同步"
    block = re.search(r"export interface ExamRun\s*\{([^}]*)\}", types_ts)
    assert block, "types.ts 缺 interface ExamRun"
    assert re.search(r"filtered_count\s*:\s*number", block.group(1)), "types.ts ExamRun.filtered_count 必须必填 number"
    assert re.search(r"reintroduced_count\s*:\s*number", block.group(1)), (
        "types.ts ExamRun.reintroduced_count 必须必填 number（r43 兜底回流计数）"
    )


def test_frontend_filtered_notice_single_source() -> None:
    """一行文案的唯一出处 `filteredNotice()`，ExamPage 不自行解释 `filtered_count`。"""
    notice = FRONTEND / "src/lib/examNotice.ts"
    assert notice.is_file(), "缺 src/lib/examNotice.ts（AC-12 文案唯一出处）"
    source = notice.read_text(encoding="utf-8")
    assert "本次已过滤 ${count} 道你已熟练掌握的题" in source, "filteredNotice 文案与 AC-12 不逐字"
    page = (FRONTEND / "src/pages/ExamPage.tsx").read_text(encoding="utf-8")
    assert "filteredNotice(run.filtered_count" in page, "ExamPage 未把 run.filtered_count 交给 filteredNotice"
    assert "sc-meta-line" in page, "ExamPage 未复用既有 .sc-meta-line"
    assert not re.search(r"filtered_count\s*[<>]=?\s*[\d-]", page), "ExamPage 内自行比较 filtered_count（语义须唯一）"


def test_style_baseline_append_only() -> None:
    """r7 AC-16：样式基座只允许 append（新增 token / 新增类），既有声明不得改动或删除。

    取代 r6 的 `test_style_baseline_untouched`（原断言是「这两个文件不得出现在 git status」，
    与 AC-16 直接互斥）。语义在这里是**更强**而不是更松：新增整段照样通过，但只要出现一行
    删除/修改就立即失败。TECHNICAL r7 §8.2 的升格理由见任务夹。

    r22 例外（任务夹 `docs/teamflow/20261103-r22-mobile-shell/TECH-CHANGE.md` 已列明）：
    安全区与视口高度必须改写既有声明，`env()` 在无刘海/手势条设备上取 0，计算结果与 r21
    基线一致；`100dvh` 只作为第二行回退、首行保留原值。仅放行下面这 4 行字面量。
    """
    r22_allowed = {
        "-  height: var(--topbar-h);",
        "-  padding: 0 var(--sp-6);",
        "-  min-height: calc(100vh - var(--topbar-h));",
        "-  padding: var(--sp-3);",
    }
    proc = subprocess.run(
        ["git", "diff", "--unified=0", "--", "frontend/src/styles/tokens.css",
         "frontend/src/styles/base.css"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, f"git diff 不可用：{proc.stderr[:200]}"
    removed = [
        line
        for line in proc.stdout.splitlines()
        if line.startswith("-") and not line.startswith("---") and line not in r22_allowed
    ]
    assert not removed, f"样式基座出现删除/修改行：{removed[:5]}"


def _string_literals(source: str) -> set[str]:
    """源文件里的**代码**字符串字面量（注释里的闭集提及不算，避免误伤说明文字）。"""
    tree = ast.parse(source)
    return {
        str(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def test_r7_contract_mirror() -> None:
    """AC-13 / 门禁 39：`Report` 的四个 r7 字段名必须逐字出现在 `types.ts`。"""
    schemas_py = (APP_DIR / "schemas.py").read_text(encoding="utf-8")
    types_ts = (FRONTEND / "src/api/types.ts").read_text(encoding="utf-8")
    fields = ("weakness_map", "resume_pointers", "resume_pointers_notice", "role_fit")
    for name in fields:
        assert re.search(rf"\b{name}\s*:", schemas_py), f"schemas.py 缺字段 {name}"
        assert re.search(rf"\b{name}\s*:", types_ts), f"types.ts 缺镜像字段 {name}"
    for model in ("WeaknessItem", "WeaknessSample", "ResumePointer", "RoleFitItem", "RoleFit"):
        assert f"class {model}" in schemas_py, f"schemas.py 缺模型 {model}"
        assert f"interface {model} " in types_ts or f"interface {model}{{" in types_ts, (
            f"types.ts 缺镜像 interface {model}"
        )


def test_r7_closed_sets_not_duplicated() -> None:
    """门禁 40：闭集（方向/难度/必备级别）只能来自 `rules.py`，新服务不得复制字面量。"""
    closed = set(rules.DIRECTIONS) | set(rules.DIFFICULTIES) | set(rules.ESSENTIALITIES)
    for name in ("weakness.py", "role_fit.py"):
        literals = _string_literals((SERVICES / "report" / name).read_text(encoding="utf-8"))
        assert not (literals & closed), f"{name} 复制了闭集字面量：{sorted(literals & closed)}"


def test_r7_copy_parity() -> None:
    """门禁 42：`coach_copy.py` 的 6 条中文文案必须逐字出现在 `lib/coach.ts`（同源不漂移）。"""
    backend = (SERVICES / "resume" / "coach_copy.py").read_text(encoding="utf-8")
    frontend = (FRONTEND / "src/lib/coach.ts").read_text(encoding="utf-8")
    names = (
        "LEGACY_BLOCK_NOTICE",
        "WEAKNESS_EMPTY",
        "RESUME_NO_TEXT",
        "RESUME_AI_FALLBACK",
        "ROLE_NO_MODEL",
        "ROLE_NO_MODEL_HINT",
    )
    for name in names:
        matched = re.search(rf'{name} = "([^"]+)"', backend)
        assert matched, f"coach_copy.py 缺常量 {name}"
        assert matched.group(1) in frontend, f"lib/coach.ts 未逐字镜像 {name}"


def test_r7_markdown_single_source() -> None:
    """门禁 43：三块的 .md 只在 `markdown.py` 里拼；页面与 lib 不得自行拼 markdown。"""
    targets = [FRONTEND / "src/pages/ReportPage.tsx", *sorted((FRONTEND / "src/lib").glob("*.ts"))]
    headings = ("# 能力诊断报告", "## 知识薄弱地图", "## 简历改进要点", "## 市场竞争力对标")
    offenders = [
        path.name
        for path in targets
        if path.is_file()
        for heading in headings
        if heading in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"前端自行拼 markdown 标题：{offenders}"


def test_r7_style_tokens_defined() -> None:
    """DESIGN r7 §0.7：5 个新尺寸 token 必须定义在 `tokens.css` 且被 `base.css` 使用。"""
    tokens = (FRONTEND / "src/styles/tokens.css").read_text(encoding="utf-8")
    base = (FRONTEND / "src/styles/base.css").read_text(encoding="utf-8")
    for name in ("weak-rank-w", "weak-rate-w", "role-level-w", "role-gap-w", "prio-dot"):
        assert f"--{name}:" in tokens, f"tokens.css 缺 --{name}"
        assert f"var(--{name})" in base, f"base.css 未使用 --{name}（定义了却没人用等于死 token）"


def _py_class_block(source: str, class_name: str) -> str:
    """取 `class_name` 的类体源码（到下一个顶格行为止，含装饰器/注释）。

    必须按块取，不能全文正则：`role:` 这类断言一旦全文匹配，`target_role: str | None = None`
    会把门禁喂绿 —— 那正是「门禁写了但拦不住回退」的经典空转（T6 的变异自检就抓到过）。
    """
    header = f"class {class_name}"
    start = source.index(header)
    tail = source[start:]
    stop = re.search(r"\n(?=\S)", tail[1:])
    return tail if stop is None else tail[: 1 + stop.start()]


def _ts_interface_block(source: str, name: str) -> str:
    """按花括号配平取 `interface name { ... }` 的完整片段（体内可能有嵌套对象字面量）。"""
    start = source.index(f"interface {name}")
    brace = source.index("{", start)
    depth = 0
    for offset in range(brace, len(source)):
        depth += (source[offset] == "{") - (source[offset] == "}")
        if depth == 0:
            return source[start : offset + 1]
    raise AssertionError(f"types.ts 的 {name} 接口未闭合")


def test_r8_profile_nullable_mirror() -> None:
    """门禁 46：`role` / `period` 的三层口径（提示词 / schemas.py / types.ts）必须同向。

    r8 的缺陷就是这三层不同向：提示词允许 `null`，`schemas.py` 要 `str`，`types.ts` 要
    `string` —— 真实模型按提示词给 `null`，画像生成必 502。只改其中一层（无论哪层）都会
    重新造出一个「契约说 A、提示词说 B」的缝隙，因此这条门禁一次性钉住三处：
    - 后端契约可空 + 列表维度 null 归一存在 + 未用 `extra="allow"` 换绿；
    - 前端镜像 `string | null` + 空值归一单点（`lib/profileText.ts`）；
    - 提示词仍允许 `null`（若有人把提示词改成「必须输出字符串」，契约的可空就成死代码）。
    反向自检：把 `role` 改回 `str` 后本用例必须红（`logs/.../scripts/check_r8_contract_mutation.py`）。
    """
    schemas_py = (APP_DIR / "schemas.py").read_text(encoding="utf-8")
    types_ts = (FRONTEND / "src/api/types.ts").read_text(encoding="utf-8")
    profile_py = (SERVICES / "profile" / "profile.py").read_text(encoding="utf-8")
    merge_py = (SERVICES / "profile" / "profile_merge.py").read_text(encoding="utf-8")
    profile_text_ts = (FRONTEND / "src/lib/profileText.ts").read_text(encoding="utf-8")

    project_cls = _py_class_block(schemas_py, "ProfileProject")
    project_iface = _ts_interface_block(types_ts, "ProfileProject")
    # 区块提取的越界自检：两个块都不该含 `target_role`（同名子串会让断言空转）。
    assert "target_role" not in project_cls and "target_role" not in project_iface

    py_pattern = r"^\s+{field}:\s*str\s*\|\s*None\s*=\s*None\s*$"
    ts_pattern = r"^\s+{field}:\s*string\s*\|\s*null\s*$"
    for field in ("role", "period"):
        assert re.search(py_pattern.format(field=field), project_cls, re.MULTILINE), (
            f"schemas.py 的 ProfileProject.{field} 不再是 str | None = None"
        )
        assert re.search(ts_pattern.format(field=field), project_iface, re.MULTILINE), (
            f"types.ts 的 ProfileProject.{field} 少了 string | null 镜像"
        )
    assert "_normalize_null_lists" in schemas_py, "列表维度的 null→[] 归一丢了"
    assert "_null_bullets" in schemas_py, "bullets 的 null→[] 归一跳了"
    assert 'extra="allow"' not in schemas_py, "不得用 extra=allow 换绿（闸门不放松）"
    assert "无法判断填 null" in profile_py, "提示词不再允许 null：契约的可空成了死代码"
    assert "_prefer_text" in merge_py, "合并的「空值不覆盖」必须走单点 _prefer_text"
    assert "export function textOrEmpty" in profile_text_ts, (
        "前端空值归一必须单点收敛在 lib/profileText.ts 的 textOrEmpty"
    )
    assert "export function joinMeta" in profile_text_ts


def test_interview_prompt_paper_feasible() -> None:
    """门禁 47：开局提示词的题量声明必须装得下「技术下限 + 项目下限 + 挑战题」。

    QA D-1（r8 轮次确认）：`INTERVIEW_SYSTEM` 规则 1 曾写「共 8 道题：technical ≥5、
    project ≥3，challenge ≤2」，而 `_check_structure` 要求 `project ≥ 3` ——
    5 + 3 + 1 = 9 > 8，三条同时成立在算术上不可能；真实模型稳定给 technical 5 /
    project 2 / challenge 1，于是开局被闸门拦成 502（AC-9 闭环断在第一步）。

    判据：提示词声明的最小合规卷（技术下限 + 项目下限 + 至少 1 道挑战）必须装进它自己
    声明的总题量，且这份卷真的能过同一份结构闸门。任一侧回退（提示词改回「共 8 道题」
    或闸门常量上调）本用例即红。
    """
    match = re.search(r"共\s*(\d+)\s*道题", interview_service.INTERVIEW_SYSTEM)
    assert match is not None, "INTERVIEW_SYSTEM 必须声明总题量（形如「共 N 道题」）"
    stated_total = int(match.group(1))

    minimum_paper = (
        ["technical"] * rules.MIN_TECHNICAL_QUESTIONS
        + ["project"] * rules.MIN_PROJECT_QUESTIONS
        + ["challenge"]
    )
    assert stated_total >= len(minimum_paper), (
        f"提示词声明共 {stated_total} 道题，装不下最小合规卷 {len(minimum_paper)} 道"
        f"（technical {rules.MIN_TECHNICAL_QUESTIONS} + project "
        f"{rules.MIN_PROJECT_QUESTIONS} + challenge 1）"
    )
    assert stated_total >= rules.MIN_INTERVIEW_QUESTIONS
    # 同一份最小合规卷必须真的能过结构闸门：提示词与闸门同向，而不是各说一套。
    interview_service._check_structure(
        minimum_paper,
        [f"第 {index} 题：请说明做法、取舍与结果" for index in range(len(minimum_paper))],
    )

    # 门禁 48（r8 D-4 / r20）：题量一改，**轮次上限必须同步派生**。上一轮把题量 8 → 9 时只改了
    # 提示词，轮次上限仍是标准卷的 8 + 4 = 12，于是 9 正题 + 4 追问走到第 13 条发言、且
    # `quota.turns_left` 提前报 0 —— 本用例钉住「上限 ≥ 计划题量」「上限随题量增长」两条；
    # r20 再钉住「9 题卷开局追问额度必须仍为 4 次」（只取 max(12, 计划题量) 时它会掉到 3）。
    assert rules.max_turns(stated_total) >= stated_total, (
        f"轮次上限 {rules.max_turns(stated_total)} 装不下 {stated_total} 道计划正题（会溢出越界）"
    )
    assert rules.max_turns(stated_total) >= rules.MAX_INTERVIEW_TURNS, "上限不得低于标准卷预算"
    assert rules.max_turns(rules.MAX_INTERVIEW_TURNS + 1) > rules.MAX_INTERVIEW_TURNS, (
        "轮次上限必须由计划题量派生，不能写死 MAX_INTERVIEW_TURNS（D-4 的类）"
    )
    # 开局额度自洽：turns_left = 剩余计划正题 + 可追问轮次（D-4 的「turns_left 与实际剩余不符」）。
    opener_follow_ups = rules.follow_ups_left(stated_total, 1, 0)
    assert rules.max_turns(stated_total) - 1 == (stated_total - 1) + opener_follow_ups, (
        f"开局额度不自洽：上限 {rules.max_turns(stated_total)} - 已问 1 ≠ "
        f"剩余正题 {stated_total - 1} + 可追问 {opener_follow_ups}"
    )
    assert opener_follow_ups == rules.MAX_FOLLOW_UPS, (
        f"开局只剩 {opener_follow_ups} 次追问（应为 {rules.MAX_FOLLOW_UPS}）："
        "轮次上限又在压缩追问额度（r8 D-5 的类）"
    )


# --- r9：AI 供应商档位（门禁 49-52）---------------------------------------------------
#: `ai.py` 只允许有一处 `{"type": "json_object"}` 投影；第二处就是第二条事实来源。
_JSON_OBJECT_FORMAT = '"type": "json_object"'

#: r9 起 `ai.py` 只认 `AiRuntime`，裸配置字段一个都不许出现（否则与 `resolve_ai` 成二维真相）。
_NAKED_AI_FIELDS = (
    "ai_base_url",
    "ai_model",
    "ai_api_key",
    "ai_timeout_s",
    "ai_max_retries",
    "ai_json_mode",
    "ai_provider",
)


def _dict_items(tree: ast.Module, name: str) -> dict[str, ast.expr | None]:
    """取 `name = {"a": ..., "b": ...}` 的「字符串键 → 值表达式」（r9 的 `json_mode` 投影表）。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and node.value is not None:
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in targets):
            continue
        if isinstance(value, ast.Dict):
            return {
                key.value: item
                for key, item in zip(value.keys, value.values, strict=False)
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
    return {}


def test_r9_health_contract_mirror() -> None:
    """门禁 49：`/health` 的运维白名单三字段必须后端契约与前端镜像逐字同形（AC-7）。

    r9 把「当前解析成哪套端点 / 模型 / JSON 模式」暴露成探活字段。三字段是**白名单**而不是
    `AiRuntime` 直出：多半列一个字段＝多一个泄密面，所以这里同时钉住「三字段在」与「任何
    key 形状的字段都不在」。前端 `types.ts` 必须镜像（AGENTS §4 硬约束），否则下一次读
    `Health` 的代码会缺字段。反向自检：删掉 `HealthResponse.ai_model` 或 `types.ts` 的
    镜像行，本用例必须红（`scripts/check_r9_gate_sensitivity.py`）。
    """
    schemas_tree = _r6_ast("backend/app/schemas.py")
    fields = _class_annotations(schemas_tree, "HealthResponse")
    assert {"status", "version", "ai_configured", "db"} <= set(fields), (
        f"HealthResponse 丢了既有字段：{sorted(fields)}"
    )
    assert {"ai_provider", "ai_model", "ai_json_mode"} <= set(fields), (
        f"HealthResponse 缺 r9 运维白名单三字段（实际 {sorted(fields)}）"
    )
    leaked = sorted(name for name in fields if "key" in name.lower() or "secret" in name.lower())
    assert not leaked, f"/health 契约面混进了密钥类字段：{leaked}"

    types_ts = (FRONTEND / "src/api/types.ts").read_text(encoding="utf-8")
    health_iface = _ts_interface_block(types_ts, "Health")
    for name in ("ai_provider", "ai_model", "ai_json_mode"):
        assert re.search(rf"^\s+{name}\?:?\s*string\s*$", health_iface, re.MULTILINE), (
            f"types.ts 的 Health 缺镜像字段 {name}（后端加了字段必须同步 TS）"
        )
    assert not re.search(r"^\s+\w*key\w*\??\s*:", health_iface, re.MULTILINE | re.IGNORECASE), (
        "types.ts 的 Health 混进了密钥类字段镜像"
    )


def test_r9_json_mode_closed_set_single_source() -> None:
    """门禁 50：`json_mode` 闭集只在 `config.py`，`ai.py` 只许留一张等键集的投影表（AC-8）。

    三处自然漂移点一次钉住：
    - 闭集来源：`JsonMode` 的取值集合 == `JSON_MODES` == `get_args(JsonMode)`，且 `JSON_MODES`
      必须由 `get_args` 派生（手写第二份 tuple ＝ 二维真相，迟早漂）；
    - 投影表键集：`_RESPONSE_FORMAT_BY_MODE` 的键必须与闭集相等（`none` 的语义是**整键不发**，
      值必须字面 `None`；LM Studio 实测发 `{"type":"text"}` 也不等价）；
    - 请求体形状：`{"type": "json_object"}` 与 `"response_format"` 在 `ai.py` 里各只出现一次
      （第二次注入 `response_format` ＝ 绕过投影表）。
    """
    from app.core.config import DEFAULT_JSON_MODE, JSON_MODES, JsonMode

    config_tree = _r6_ast("backend/app/core/config.py")
    literal_values = _literal_values(config_tree, "JsonMode")
    assert literal_values == {"json_object", "none"}, (
        f"JsonMode 闭集变成了 {sorted(literal_values)}（只允许 json_object / none）"
    )
    assert set(get_args(JsonMode)) == literal_values
    assert frozenset(get_args(JsonMode)) == JSON_MODES, (
        f"JSON_MODES {sorted(JSON_MODES)} 不再等于 get_args(JsonMode)"
    )
    assert DEFAULT_JSON_MODE in JSON_MODES
    config_source = (APP_DIR / "core" / "config.py").read_text(encoding="utf-8")
    assert re.search(r"JSON_MODES[^\n]*=\s*frozenset\(\s*get_args\(", config_source), (
        "JSON_MODES 必须由 get_args(JsonMode) 派生，不能另写一份同义字面量"
    )

    ai_source = (SERVICES / "ai" / "ai.py").read_text(encoding="utf-8")
    projection = _dict_items(_r6_ast("backend/app/services/ai/ai.py"), "_RESPONSE_FORMAT_BY_MODE")
    assert set(projection) == set(JSON_MODES), (
        f"投影表键集 {sorted(projection)} != json_mode 闭集 {sorted(JSON_MODES)}"
    )
    none_value = projection.get("none")
    assert isinstance(none_value, ast.Constant) and none_value.value is None, (
        "`none` 的投影值必须是字面 None（整键不发），不是 {'type': 'text'}"
    )
    assert ai_source.count(_JSON_OBJECT_FORMAT) == 1, (
        f"ai.py 出现了 {ai_source.count(_JSON_OBJECT_FORMAT)} 处 json_object 投影，只允许 1 处（投影表）"
    )
    response_format_hits = ai_source.count('"response_format"')
    assert response_format_hits == 1, (
        f"ai.py 出现了 {response_format_hits} 处 response_format 键，只允许 1 处（投影表之外的第二次注入）"
    )


def test_r9_ai_uses_runtime_not_naked_fields() -> None:
    """门禁 51：`ai.py` 不得再读裸配置字段，配置口径只有 `Settings.resolve_ai()` 一处。

    r9 之前 `_chat` 直接读 `settings.ai_base_url / ai_model / ai_api_key / ai_timeout_s`，
    与 `resolve_ai()` 构成两条事实来源：解析器说「切到 lmstudio」，传输层照旧把云端端点 +
    云端 Key 发出去。判据是「结构上无从直读」：源码里不出现这批字段名、AST 里也没有任何
    `*.ai_*` 属性访问；此外 `resolve_ai()` 在 `ai.py` 只能出现一次（构造期快照），
    每请求现读会让一次请求内的模型 / 超时口径前后不一致。
    """
    ai_source = (SERVICES / "ai" / "ai.py").read_text(encoding="utf-8")
    offenders = [name for name in _NAKED_AI_FIELDS if re.search(rf"\b{name}\b", ai_source)]
    assert not offenders, f"ai.py 又在直读裸配置字段：{offenders}（请改读 self._runtime）"
    ai_tree = _r6_ast("backend/app/services/ai/ai.py")
    attributes = {
        node.attr for node in ast.walk(ai_tree) if isinstance(node, ast.Attribute)
    }
    sneaky = sorted(attributes & set(_NAKED_AI_FIELDS))
    assert not sneaky, f"ai.py 通过属性访问绕过了 runtime 快照：{sneaky}"
    resolve_calls = [
        node
        for node in ast.walk(ai_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "resolve_ai"
    ]
    assert len(resolve_calls) == 1, (
        f"ai.py 有 {len(resolve_calls)} 处 resolve_ai() 调用，只允许构造期快照一次（每请求现读会漂）"
    )
    assert "self._runtime" in ai_source, "AIClient 必须持有构造期快照 self._runtime"


def test_r9_env_example_lists_provider_keys() -> None:
    """门禁 52：`.env.example` 必须覆盖 `Settings` 的每个 `ai_*` 字段，且永不含真实 Key。

    `.env.example` 是配置档的第二份「人肉文档」：新增一个档位字段只改代码不改示例，运维照示例
    抄完仍然起不来。这里反向从 `Settings` 的注解枚举字段名，要求大写键逐字出现在示例里；
    同时钉住两条实测硬约束（`AI_LMSTUDIO_JSON_MODE=none`、`TIMEOUT_S`）与「密钥示例留空」。

    D-1（r9 QA）：`TIMEOUT_S` 不再钉字面量，改成钉两件事 —— ①示例数值必须等于
    `Settings.ai_lmstudio_timeout_s` 的字段默认值（两份手写清单互锁：只改代码不改示例、
    只改示例不改代码都会红）；②该默认值不得低于实测下限 300s（本机 qwen3.5-9b 单次画像
    实测 201.25s，旧默认 180s 会把该链路掐成 503 `AI_UNAVAILABLE`）。
    """
    env_path = REPO_ROOT / "backend" / ".env.example"
    assert env_path.is_file(), ".env.example 是配置示例的唯一出处，不得删除"
    env_text = env_path.read_text(encoding="utf-8")

    settings_fields = _class_annotations(_r6_ast("backend/app/core/config.py"), "Settings")
    ai_fields = sorted(name for name in settings_fields if name.startswith("ai_"))
    assert {"ai_provider", "ai_json_mode", "ai_deepseek_model", "ai_lmstudio_model"} <= set(
        ai_fields
    ), f"Settings 的 r9 档位字段缺失（实际 {ai_fields}）"
    missing = [name.upper() for name in ai_fields if name.upper() not in env_text]
    assert not missing, f".env.example 缺 Settings 的 ai_* 键：{missing}（改代码必须同步示例）"

    for line in env_text.splitlines():
        match = re.match(r"^(AI_\w*API_KEY)\s*=(.*)$", line.strip())
        if match:
            assert not match.group(2).strip(), (
                f".env.example 的 {match.group(1)} 不是空值（示例一旦带值＝密钥进了版本库）"
            )
    assert not re.search(r"\bsk-[A-Za-z0-9_\-]{8,}", env_text), ".env.example 出现了真实密钥样式"
    assert re.search(r"^AI_LMSTUDIO_JSON_MODE=none$", env_text, re.MULTILINE), (
        "本地端点实测拒绝 json_object，示例必须给 none（否则照抄就 400）"
    )

    # D-1：示例数值 ⇄ `Settings` 默认值互锁，且不得低于实测下限。
    example_match = re.search(r"^AI_LMSTUDIO_TIMEOUT_S=(\d+(?:\.\d+)?)$", env_text, re.MULTILINE)
    assert example_match, (
        "示例的 AI_LMSTUDIO_TIMEOUT_S 必须给可照抄的数值（留空/写 0 ＝继承全局 20s，本地画像必 503）"
    )
    example_timeout = float(example_match.group(1))
    config_source = (REPO_ROOT / "backend" / "app" / "core" / "config.py").read_text(encoding="utf-8")
    config_match = re.search(
        r"^    ai_lmstudio_timeout_s: float = (\d+(?:\.\d+)?)$", config_source, re.MULTILINE
    )
    assert config_match, "Settings.ai_lmstudio_timeout_s 必须给显式数值默认值（不靠继承全局）"
    config_timeout = float(config_match.group(1))
    assert example_timeout == config_timeout, (
        f"示例 TIMEOUT_S={example_timeout}s 与 Settings 默认 {config_timeout}s 不一致"
        "（改一处忘了另一处，运维照抄就会超时）"
    )
    assert config_timeout >= 300.0, (
        f"lmstudio 档默认超时 {config_timeout}s 低于实测下限 300s"
        "（qwen3.5-9b 单次画像实测 201.25s，旧默认 180s 必 503）"
    )


# ---------------------------------------------------------------------------
# r11 · 在线练习题库与练习页（TECHNICAL §2.5「单一出处」/ §4.3「单一判分」/ §4.4 降级开关）
#
# 五个门禁的共同理由：r11 新增的每一条口径（语言闭集、语言→方向归属、练习
# scope/limit、客观题判分）都**跨侧、跨模块**被消费，且两侧无共享代码。少一处静态
# 断言，下一轮就会有人就地写第二种实现（第二份判分 / 第二份语言表），而且不会报错。
# ---------------------------------------------------------------------------

#: r11 改动面（仓库根相对）。蓝图 34 模块里的**产品文件**，逐条必须可解析。
R11_TOUCHED = (
    "backend/app/services/report/rules.py",
    "backend/app/schemas.py",
    "backend/app/core/db.py",
    "backend/app/core/repository.py",
    "backend/app/services/assessment/question_backfill.py",
    "backend/app/services/assessment/question_bank.py",
    "backend/app/services/assessment/practice.py",
    "backend/app/routers/practice.py",
    "backend/app/main.py",
    "backend/app/seed/questions.json",
    "frontend/src/api/types.ts",
    "frontend/src/api/client.ts",
    "frontend/src/pages/PracticePage.tsx",
    "frontend/src/components/practice/PracticeFilters.tsx",
    "frontend/src/components/practice/PracticeProgress.tsx",
    "frontend/src/components/practice/Explanation.tsx",
    "frontend/src/components/practice/PracticeSummary.tsx",
    "frontend/src/components/practice/WrongBookList.tsx",
    "frontend/src/lib/practice.ts",
    "frontend/src/lib/promptCode.ts",
    "frontend/src/components/exam/ExamQuestionCard.tsx",
    "frontend/src/components/polish/SegTabs.tsx",
    "frontend/src/App.tsx",
    "frontend/src/styles/tokens.css",
    "frontend/src/styles/base.css",
    "backend/tests/test_r11_data_layer.py",
    "backend/tests/test_r11_contract.py",
    "backend/tests/test_question_backfill.py",
    "backend/tests/test_question_bank_quality.py",
    "backend/tests/test_r11_practice_service.py",
    "backend/tests/test_r11_practice_api.py",
    "frontend/src/test/practice.test.ts",
    "frontend/src/test/promptCode.test.ts",
    "backend/tests/test_engineering_gates.py",
)

#: r11 闭集的期望值（TECHNICAL §2.6 逐字）。门禁是**唯一断言点**，故此处允许字面量。
R11_LANGUAGES = ("", "python", "java", "go", "html", "css", "js", "ts", "vue3", "react")
R11_FRONTEND_LANGUAGES = ("html", "css", "js", "ts", "vue3", "react")
R11_BACKEND_LANGUAGES = ("python", "java", "go")
R11_PRACTICE_SCOPES = ("all", "unseen", "wrong")
R11_PRACTICE_LIMITS = (10, 20, 0)

#: 第二套判分比较的**历史白名单**：exam.py 是唯一判分实现，proficiency.py 只累计次数。
SET_COMPARE_ALLOWED = {"exam.py", "proficiency.py"}


def _int_literal_values(tree: ast.Module, name: str) -> set[int]:
    """取 `name = Literal[10, 20, 0]` 的**整型**取值集合（`_literal_values` 只管字符串）。"""
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets, value = [node.target], node.value
        elif isinstance(node, ast.Assign) and node.value is not None:
            targets, value = list(node.targets), node.value
        if not any(isinstance(t, ast.Name) and t.id == name for t in targets) or value is None:
            continue
        if isinstance(value, ast.Subscript):  # Literal[...]
            value = value.slice
        elements = getattr(value, "elts", None)
        if elements is None:
            continue
        return {elt.value for elt in elements if isinstance(elt, ast.Constant) and isinstance(elt.value, int)}
    return set()


def _ts_union_terms(source: str, name: str) -> str:
    """`export type Name = ...` 的右值整段文本（含以 `|` 开头的续行成员）。"""
    lines = source.split("\n")
    for index, line in enumerate(lines):
        match = re.match(rf"export type {name}\s*=\s*(.*)$", line)
        if match is None:
            continue
        terms = match.group(1)
        cursor = index + 1
        while cursor < len(lines) and re.match(r"^\s*\|", lines[cursor]):
            terms += " " + lines[cursor].strip()
            cursor += 1
        return terms
    return ""


def _ts_string_union(source: str, name: str) -> set[str]:
    """`types.ts` 里字符串字面量并集的成员集合（类型别名引用不展开，故只取引号成员）。"""
    return set(re.findall(r"'([^']*)'", _ts_union_terms(source, name)))


def _ts_number_union(source: str, name: str) -> set[int]:
    return {int(number) for number in re.findall(r"\b(\d+)\b", _ts_union_terms(source, name))}


def test_r11_single_grading_function() -> None:
    """AC-6 / §4.3：全库只有一个客观题判分函数，第二套「比较答案」的写法不得复活。

    练习与笔试共用 `exam.grade_objective()`：任何就地 `set(answer) == set(correct)` 都会
    让「少选/多选算错」在练习与笔试之间漂移，而且两处都「看起来对」。
    """
    graders = {name: files for name, files in _python_defs().items() if name.startswith("grade_")}
    assert set(graders) == {"grade_objective"}, (
        f"客观题判分函数必须恰好一个（实际 {sorted(graders)}）：练习与笔试共用 exam.grade_objective"
    )
    files = graders["grade_objective"]
    assert len(files) == 1 and files[0].endswith("services/assessment/exam.py"), (
        f"grade_objective 必须唯一一份且住 services/assessment/exam.py，实际 {files}"
    )

    offenders: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        if path.name in SET_COMPARE_ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            operands = [node.left, *node.comparators]
            for position, operator in enumerate(node.ops):
                if not isinstance(operator, ast.Eq):
                    continue
                pair = (operands[position], operands[position + 1])
                if all(
                    isinstance(side, ast.Call)
                    and isinstance(side.func, ast.Name)
                    and side.func.id == "set"
                    for side in pair
                ):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert not offenders, f"出现第二套集合相等判分（应调 exam.grade_objective）：{offenders}"

    blanks = [
        str(path.relative_to(REPO_ROOT))
        for path in sorted(APP_DIR.rglob("*.py"))
        if '"blank"' in path.read_text(encoding="utf-8")
        or "'blank'" in path.read_text(encoding="utf-8")
    ]
    assert not blanks, f"题库出现了 blank 题型（本版只有选择/判断，填空不在范围）：{blanks}"

    assert rules.OBJECTIVE_KINDS == ("single", "multiple", "judge"), (
        f"客观题闭集应为 single/multiple/judge，实际 {rules.OBJECTIVE_KINDS}"
    )
    assert rules.is_objective_kind("judge") is True, "judge 必须算客观题（否则判断题不判分、不计熟练度）"


def test_r11_language_direction_single_source() -> None:
    """AC-1 / AC-12：语言闭集与「语言→方向归属」只在 `rules.py`，两侧镜像逐字一致。"""
    rules_tree = _r6_ast("backend/app/services/report/rules.py")
    schemas_tree = _r6_ast("backend/app/schemas.py")

    declared = _literal_values(rules_tree, "LANGUAGES")
    assert declared == set(R11_LANGUAGES), f"rules.LANGUAGES 与十一成员闭集不一致：{sorted(declared)}"
    assert rules.LANGUAGES == R11_LANGUAGES, (
        "rules.LANGUAGES 的顺序即契约（``''`` 在最前）：改顺序等于改前端 chip 顺序与题库分布口径"
    )

    mirror = _literal_values(schemas_tree, "QuestionLanguage")
    assert mirror == declared, f"schemas.QuestionLanguage={sorted(mirror)} 与 rules.LANGUAGES 不一致"
    types_ts = (FRONTEND / "src/api/types.ts").read_text(encoding="utf-8")
    assert _ts_string_union(types_ts, "QuestionLanguage") == declared, (
        "types.ts 的 QuestionLanguage 与 rules.LANGUAGES 不同步（改一处忘另一侧）"
    )

    frontend = set(_literal_values(rules_tree, "FRONTEND_LANGUAGES"))
    backend = set(_literal_values(rules_tree, "BACKEND_LANGUAGES"))
    assert frontend == set(R11_FRONTEND_LANGUAGES), f"FRONTEND_LANGUAGES 不一致：{sorted(frontend)}"
    assert backend == set(R11_BACKEND_LANGUAGES), f"BACKEND_LANGUAGES 不一致：{sorted(backend)}"
    assert not frontend & backend, f"同一语言同时被登记为前端与后端：{sorted(frontend & backend)}"
    assert frontend | backend == declared - {""}, (
        "前端 + 后端必须恰好覆盖具体语言（``''`` 通用题不归属任何方向）"
    )
    expected_map = {**{lang: "前端" for lang in frontend}, **{lang: "后端" for lang in backend}}
    assert expected_map == rules.LANGUAGE_DIRECTION, (
        f"LANGUAGE_DIRECTION 必须由两份语言元组派生，实际 {rules.LANGUAGE_DIRECTION}"
    )

    assert rules.languages_for_direction("前端") == rules.FRONTEND_LANGUAGES
    assert rules.languages_for_direction("后端") == rules.BACKEND_LANGUAGES
    assert rules.languages_for_direction(rules.FILTER_ANY) == rules.LANGUAGES
    assert rules.languages_for_direction("不存在的方向") == ()
    assert rules.direction_of_language("python") == "后端"
    assert rules.direction_of_language("react") == "前端"
    assert rules.direction_of_language("") is None, "通用题（``''``）不归属任何方向"
    assert rules.direction_of_language("cobol") is None
    assert rules.is_language_allowed("", "前端") is True, "通用题恒放行（不归属方向不等于不合法）"
    assert rules.is_language_allowed("python", "后端") is True
    assert rules.is_language_allowed("python", "前端") is False, "语言与方向必须自洽（后端语言不得出现在前端方向）"
    assert rules.is_language_allowed("js", rules.FILTER_ANY) is True

    # 不得出现第二份语言闭集（元组/列表/集合里全是语言成员，且至少两个）。
    allowed = {"rules.py", "schemas.py"}
    offenders: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        if path.name in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                continue
            elements = getattr(node.value, "elts", None) or []
            members = {
                element.value
                for element in elements
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
            if len(members) >= 2 and members <= set(R11_LANGUAGES):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert not offenders, f"语言闭集在 rules.py 之外被重写了一份（应引用 rules.LANGUAGES）：{offenders}"


def test_r11_practice_closed_sets() -> None:
    """AC-9 / §2.5：练习 scope / limit / 语言筛选闭集单一出处，两侧镜像逐字一致。

    特别钉住 r11 的**语义不对称**：`language` 的「全部」是 `"all"`，而 `""` 是「通用题」
    这个**闭集成员**——任何地方拿 `""` 表示「全部」都会让通用题筛不出来。
    """
    rules_tree = _r6_ast("backend/app/services/report/rules.py")
    schemas_tree = _r6_ast("backend/app/schemas.py")
    types_ts = (FRONTEND / "src/api/types.ts").read_text(encoding="utf-8")

    assert _literal_values(rules_tree, "PRACTICE_SCOPES") == set(R11_PRACTICE_SCOPES), (
        "rules.PRACTICE_SCOPES 应为 all/unseen/wrong"
    )
    assert tuple(rules.PRACTICE_LIMITS) == R11_PRACTICE_LIMITS, (
        f"rules.PRACTICE_LIMITS 应为 (10, 20, 0)（0 = 全部），实际 {rules.PRACTICE_LIMITS}"
    )
    assert rules.DEFAULT_PRACTICE_LIMIT == 10, "默认题量必须与 PracticePaperRequest.limit 默认值同口径"

    assert _literal_values(schemas_tree, "PracticeScope") == set(R11_PRACTICE_SCOPES)
    assert _int_literal_values(schemas_tree, "PracticeLimit") == set(R11_PRACTICE_LIMITS), (
        "schemas.PracticeLimit 的整型闭集与 rules.PRACTICE_LIMITS 不一致（0 = 全部）"
    )
    assert _literal_values(schemas_tree, "PracticeLanguageFilter") == set(R11_LANGUAGES) | {
        rules.FILTER_ANY
    }, "schemas.PracticeLanguageFilter 应为 语言闭集 + 「全部」，缺一个就有一类题筛不到"
    assert _literal_values(schemas_tree, "PracticeDifficultyFilter") == set(rules.DIFFICULTIES) | {
        rules.FILTER_ANY
    }
    assert _literal_values(schemas_tree, "PracticeEssentialityFilter") == set(
        rules.ESSENTIALITIES
    ) | {rules.FILTER_ANY}

    assert _ts_string_union(types_ts, "PracticeScope") == set(R11_PRACTICE_SCOPES), (
        "types.ts PracticeScope 与 schemas.PracticeScope 不同步"
    )
    assert _ts_number_union(types_ts, "PracticeLimit") == set(R11_PRACTICE_LIMITS), (
        "types.ts PracticeLimit 与 schemas.PracticeLimit 不同步"
    )
    for name, alias in (
        ("PracticeLanguageFilter", "QuestionLanguage"),
        ("PracticeDifficultyFilter", "ExamDifficulty"),
        ("PracticeEssentialityFilter", "QuestionEssentiality"),
    ):
        assert re.search(
            rf"export type {name}\s*=\s*'{rules.FILTER_ANY}'\s*\|\s*{alias}\b", types_ts
        ), f"types.ts 的 {name} 应为 「全部」 + {alias}（与 schemas.py 镜像）"

    assert "" in R11_LANGUAGES, "``''`` 是语言闭集成员（通用 / 算法题）"
    assert rules.FILTER_ANY == "all", "筛选「全部」的唯一字面量必须是 all"
    assert rules.FILTER_ANY not in rules.LANGUAGES, "all 不是语言成员（否则通用题与全部混为一谈）"
    assert rules.FILTER_ANY in rules.PRACTICE_SCOPES
    assert "" not in rules.PRACTICE_SCOPES, "范围闭集不得用空串表示「全部」（与语言语义冲突）"

    empty_holders: set[str] = set()
    for node in ast.walk(schemas_tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Subscript):
            continue
        elements = getattr(node.value.slice, "elts", [])
        if not any(isinstance(element, ast.Constant) and element.value == "" for element in elements):
            continue
        empty_holders |= {target.id for target in node.targets if isinstance(target, ast.Name)}
    assert empty_holders == {"QuestionLanguage", "PracticeLanguageFilter"}, (
        f"``''`` 只允许出现在语言闭集里（实际 {sorted(empty_holders)}）：别处拿空串当「全部」= 语义二义"
    )


def test_r11_exam_excluded_kinds_default_empty() -> None:
    """§4.4：进笔试卷面的降级开关默认不触发，且「半个开关」不得静默存在。

    `EXAM_EXCLUDED_KINDS` 非空时组卷侧必须真的消费它（`exam_selector` 走
    `is_exam_objective_kind`），否则是把判断题挪出笔试的开关拨了一半：常量改了、
    卷面没变，而且看不出来。
    """
    assert rules.EXAM_EXCLUDED_KINDS == (), (
        "EXAM_EXCLUDED_KINDS 默认必须是空元组（判断题进制）；非空意味着本版走了「不进制」降级路径"
    )
    assert "judge" not in rules.EXAM_EXCLUDED_KINDS
    assert rules.is_exam_objective_kind("judge") is True
    for kind in (*get_args(ExamKind), ""):
        assert rules.is_exam_objective_kind(kind) is rules.is_objective_kind(kind), (
            f"默认档下组卷口径必须与客观题口径逐字等价（kind={kind!r}）"
        )

    if rules.EXAM_EXCLUDED_KINDS:
        selector = (APP_DIR / "services" / "assessment" / "exam_selector.py").read_text(encoding="utf-8")
        assert "is_exam_objective_kind" in selector, (
            "EXAM_EXCLUDED_KINDS 非空但 exam_selector 仍用 is_objective_kind：开关是死的，卷面不会变"
        )


def test_r11_judge_reachable_in_exam_paper(monkeypatch) -> None:
    """判断题必须**结构可达**地进笔试卷面（QA D1 的常驻回归）。

    修复前的真实缺陷：`build_paper()` 只做方向轮转，取到的 8 道客观题全是 basic 档；
    r11 的 36 道 judge 恒为 intermediate/challenge，于是「判断题进制」这条 PRD 决策在卷面上
    结构不可达（30 卷 / 300 题抽样 0 道 judge），而静态看代码一切正常。
    另外 `EXAM_EXCLUDED_KINDS` 的降级开关此前无消费点（D2），置 `("judge",)` 卷面也不会变。
    """
    profile = Profile(
        id="gate-prof-judge", resume_id="gate-res-judge",
        updated_at="2026-11-01T00:00:00+00:00",
        skills=[], tech_stack=["Python", "React"], years_experience=3,
        projects=[], target_role="后端开发工程师",
    )
    questions = question_bank.load_seed()
    available = {
        str(question.get("kind"))
        for question in questions
        if rules.is_exam_objective_kind(str(question.get("kind") or ""))
    }
    assert {"single", "multiple", "judge"} <= available, "种子必须同时含单选/多选/判断（题型覆盖前提）"

    # 1) 单次 L1 组卷即可取到判断题（不依赖随机种子碰运气）
    for seed in (0, 1, 2, 7, 42):
        paper = exam_selector.build_paper(
            exam_selector.rank_pool(questions, profile, rng=random.Random(seed)),
            require_directions=2,
        )
        assert paper is not None, f"seed={seed} 组卷失败（结构闸门过不去）"
        kinds = [str(question.get("kind")) for question in paper]
        assert "judge" in kinds, f"seed={seed} 卷面无判断题：题型结构不可达（QA D1 回归）"
        assert available <= set(kinds), (
            f"seed={seed} 卷面缺题型 {sorted(available - set(kinds))}：每种可用客观题型必须各 ≥1"
        )
        assert sum(kind in ("single", "multiple", "judge") for kind in kinds) >= 8

    # 2) 走完整 6 层阶梯同样取得到（真实出卷路径不是 build_paper 单独调用）
    ladder = exam_selector.select_paper(questions, profile, proficient=set(), recent=[])
    assert ladder is not None
    assert "judge" in [str(question.get("kind")) for question in ladder.questions]

    # 3) 降级开关一键生效：置 ("judge",) 后卷面不得再出现判断题，且结构依旧达标
    monkeypatch.setattr(rules, "EXAM_EXCLUDED_KINDS", ("judge",))
    for seed in (0, 3):
        degraded = exam_selector.build_paper(
            exam_selector.rank_pool(questions, profile, rng=random.Random(seed)),
            require_directions=2,
        )
        assert degraded is not None, "降级后仍必须能组出结构达标的卷（否则降级路径是死路）"
        degraded_kinds = [str(question.get("kind")) for question in degraded]
        assert "judge" not in degraded_kinds, "EXAM_EXCLUDED_KINDS=('judge',) 但卷面仍有判断题"
        assert sum(k in ("single", "multiple") for k in degraded_kinds) >= 8

    # 4) 组卷侧必须真的消费组卷口径（不是只把常量拨了一半）
    selector_src = (APP_DIR / "services" / "assessment" / "exam_selector.py").read_text(encoding="utf-8")
    assert "is_exam_objective_kind" in selector_src
    assert "is_objective_kind" not in selector_src.replace("is_exam_objective_kind", ""), (
        "exam_selector 仍残留裸 is_objective_kind：取池与计数会绕开降级开关"
    )

    # 5) 测试侧不得再抄一份客观题闭集字面量：本地副本 `{"single","multiple"}` 正是 D1 的帮凶
    #    （judge 进制后同一份卷面被算成「7 道客观题」，于是组卷闸门与判分断言同时失真）。
    duplicated = [
        path.name
        for path in sorted((REPO_ROOT / "backend" / "tests").glob("*.py"))
        if re.search(r"^OBJECTIVE_KINDS\s*=\s*[\{\[]", path.read_text(encoding="utf-8"), re.M)
    ]
    assert not duplicated, (
        f"测试里重复定义客观题闭集：{duplicated}（必须从 `rules.OBJECTIVE_KINDS` 派生）"
    )


def test_r11_touched_paths_resolve() -> None:
    """r11 改动面必须按**仓库根相对**解析成功（r6 D-1「漏 `backend/` 前缀」的 r11 版）。

    这条同时是 T3/T4 的交付面探针：backfill / practice 服务与路由、对应的四个测试文件
    任何一件没落地，这里会直接点名，而不是等到别的用例 FileNotFoundError。
    """
    mislabelled = [rel for rel in R11_TOUCHED if not rel.startswith(("backend/", "frontend/"))]
    assert not mislabelled, f"R11_TOUCHED 路径必须带 backend/ 或 frontend/ 前缀：{mislabelled}"
    missing = [rel for rel in R11_TOUCHED if not (REPO_ROOT / rel).is_file()]
    assert not missing, f"r11 改动面未落地（应为仓库根相对且文件存在）：{missing}"


# ---------------------------------------------------------------------------
# r12 · 题库素材合并（260 → 1088）
#
# 三条门禁把 r12 的三条口头约定变成机器断言：
# 1. 改动面逐条可解析 —— 任何一件没落地就点名，而不是等别的用例 FileNotFoundError；
# 2. 离线合并工具**不得被运行时导入** —— 依赖单向：运行时 → rules/repository，
#    工具 → rules/repository/question_bank；反向引用会让「离线、零 AI、零网络」失效，
#    也会让一个只在 CI 里跑的工具意外变成启动路径的一部分；
# 3. `source` 是**导入期**元数据，不得进 HTTP 契约 —— 前端不该看到它，契约也不该为它改版。
# ---------------------------------------------------------------------------

#: r12 改动面（仓库根相对）：6 个代码/数据文件 + 2 件任务夹产物（许可 NOTICE、导入报表）。
R12_TOUCHED = (
    "backend/app/services/assessment/question_merge.py",
    "backend/app/core/repository.py",
    "backend/app/seed/questions.json",
    "backend/tests/test_r12_question_merge.py",
    "backend/tests/test_question_bank_quality.py",
    "backend/tests/test_engineering_gates.py",
    "docs/question-bank-staging/NOTICE-fe-interview.md",
    "docs/teamflow/20261102-r12-question-bank-merge/QUESTION-BANK-MERGE-REPORT.md",
)

#: 离线合并工具本身（不是运行时模块：门禁 2 的依据）。
R12_MERGE_TOOL = "backend/app/services/assessment/question_merge.py"

#: r13 打乱库（同样只在离线跑；它委托合并工具写盘，故两件工具互为合法引用对象）。
R13_SHUFFLE_TOOL = "backend/app/services/assessment/question_shuffle.py"

#: 离线工具白名单：运行时不得把其中任何一个拉进启动路径，工具间互引则允许。
OFFLINE_TOOLS = (R12_MERGE_TOOL, R13_SHUFFLE_TOOL)

#: r12 来源枚举（`source` 列的业务取值；存量行缺省 `'seed'` 不在此列）。
R12_SOURCES = ("tiji", "local100", "iq380", "fe-interview")


def test_r12_touched_paths_resolve() -> None:
    """r12 改动面按仓库根相对解析：代码、种子、两个测试文件、许可与报表产物。"""
    mislabelled = [
        rel for rel in R12_TOUCHED if not rel.startswith(("backend/", "frontend/", "docs/"))
    ]
    assert not mislabelled, f"R12_TOUCHED 路径必须带 backend/ 或 frontend/ 或 docs/ 前缀：{mislabelled}"
    missing = [rel for rel in R12_TOUCHED if not (REPO_ROOT / rel).is_file()]
    assert not missing, f"r12 改动面未落地（应为仓库根相对且文件存在）：{missing}"


def test_r12_merge_tool_not_imported_by_runtime() -> None:
    """合并工具只在离线跑：运行时不得 `import question_merge`（它读 staging、写文件）。

    白名单从「合并工具单独豁免」放宽为「两件离线工具成对豁免」：工具**之间**的委托是
    合法的（打乱库 `--write` 委托合并工具写盘，保住单一序列化出口）。黑名单的「打乱库」
    那一侧由 `test_r13_shuffle_tool_not_imported_by_runtime` 独立断言，两条分开才好归因。
    """
    offenders: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative in OFFLINE_TOOLS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or "", *(alias.name for alias in node.names)]
            else:
                continue
            if any("question_merge" in name for name in names):
                offenders.append(f"{relative}:{node.lineno}")
    assert not offenders, (
        f"运行时模块 import 了离线合并工具（它会读 staging、写文件，绝不能进启动路径）：{offenders}"
    )

    tree = _r6_ast(R12_MERGE_TOOL)
    imported: set[str] = set()
    for node in ast.walk(tree):
        # 兼容两种写法：相对导入（node.level 非 0）与 app 内部的绝对导入；标准库/三方不纳入。
        if isinstance(node, ast.ImportFrom) and (
            node.level or (node.module or "").split(".")[0] == "app"
        ):
            imported.update(alias.name for alias in node.names)
    assert imported == {"repository", "question_bank", "question_shuffle", "rules"}, (
        "合并工具只允许依赖这三处（唯一 SQL 出口 / 种子读口径 / 闭集与方向归属）"
        "加上离线工具互引（question_shuffle），"
        f"实际：{sorted(imported)}"
    )


def test_r13_shuffle_tool_not_imported_by_runtime() -> None:
    """r13 反向断言：打乱库同样只在离线跑，运行时模块不得 `import question_shuffle`。

    与上面 r12 那条分开断言，是为了让失败可归因：合并工具被拉进启动路径、打乱库被拉进
    启动路径是两条独立的回归（两者都属于 `OFFLINE_TOOLS`，工具**之间**的委托仍合法）。
    """
    offenders: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative in OFFLINE_TOOLS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or "", *(alias.name for alias in node.names)]
            else:
                continue
            if any("question_shuffle" in name for name in names):
                offenders.append(f"{relative}:{node.lineno}")
    assert not offenders, (
        "运行时模块 import 了离线打乱库（它只该由合并工具的离线流水线调用，"
        f"不许进启动路径）：{offenders}"
    )


def test_r12_source_not_in_http_contract() -> None:
    """`source` 只住在库里：`schemas.py` 与 `types.ts` 都不得出现该字段，也不得泄漏来源枚举。"""
    schemas_tree = _r6_ast("backend/app/schemas.py")
    leaked = [
        f"{node.name}.source"
        for node in ast.walk(schemas_tree)
        if isinstance(node, ast.ClassDef)
        for item in node.body
        if isinstance(item, ast.AnnAssign)
        and isinstance(item.target, ast.Name)
        and item.target.id == "source"
    ]
    assert not leaked, f"HTTP 契约泄漏了题库 `source` 字段：{leaked}"

    schemas_text = (REPO_ROOT / "backend" / "app" / "schemas.py").read_text(encoding="utf-8")
    types_ts = (FRONTEND / "src" / "api" / "types.ts").read_text(encoding="utf-8")
    for text, label in ((schemas_text, "schemas.py"), (types_ts, "types.ts")):
        assert not re.search(r"^\s*(?:readonly\s+)?source\??\s*:", text, re.M), (
            f"{label} 出现 `source` 字段：题库来源是导入期元数据，不进契约（前端也不该依赖它）"
        )
        for token in R12_SOURCES:
            assert token not in text, f"{label} 出现来源枚举值 {token!r}：契约不得为素材来源改版"



