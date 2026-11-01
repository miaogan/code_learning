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
import subprocess
from pathlib import Path
from typing import get_args

from app.schemas import ExamKind
from app.services.ai import AIClient
from app.services import interview as interview_service
from app.services import rules

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
    "backend/app/db.py",
    "backend/app/repository.py",
    "backend/app/config.py",
    "backend/app/schemas.py",
    "backend/app/services/rules.py",
    "backend/app/services/question_bank.py",
    "backend/app/services/proficiency.py",
    "backend/app/services/exam_selector.py",
    "backend/app/services/exam.py",
    "backend/app/main.py",
)

#: 方向闭集（rules.DIRECTIONS 的期望值；散落即漂移）。
DIRECTIONS = ("前端", "后端", "算法与数据结构", "计算机基础")

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
    source = (APP_DIR / "db.py").read_text(encoding="utf-8")
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
    from app.config import Settings

    fields = Settings.model_fields
    for name, default in (
        ("proficiency_window_days", 30),
        ("proficiency_correct_threshold", 2),
        ("recent_paper_exclude", 3),
    ):
        assert name in fields, f"config.Settings 缺 {name}"
        assert fields[name].default == default, f"{name} 默认值应为 {default}"

    offenders: list[str] = []
    for path in sorted(SERVICES.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and type(node.value) is int and node.value == 30:
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"窗口天数须来自 config.get_settings()，服务层出现 30 字面量：{offenders}"

    rules_source = (SERVICES / "rules.py").read_text(encoding="utf-8")
    assert not re.search(r"PROFICIENCY|WINDOW_DAYS|RECENT_PAPER", rules_source), (
        "阈值常量漂回 rules.py（阈值与闭集分工，阈值只住 config.py）"
    )


def test_single_usable_and_structure_gate() -> None:
    """`_usable` 只在 question_bank.py；结构闸门 build_paper 只在 exam_selector.py。"""
    defs = _python_defs()
    assert defs.get("_usable") == ["backend/app/services/question_bank.py"], (
        f"_usable 必须唯一一份且住 question_bank.py，实际：{defs.get('_usable')}"
    )
    assert defs.get("build_paper") == ["backend/app/services/exam_selector.py"], (
        f"结构闸门必须唯一一份且住 exam_selector.py，实际：{defs.get('build_paper')}"
    )
    # QA D-2：这两条只钉「exam.py 不得复活第二份」，**不是**全 `app/` 范围的命名禁令 ——
    # 其它模块的同名私有助手（如 `proficiency._ordered` 的作答排序）是合法实现，不得误伤。
    exam_py = "backend/app/services/exam.py"
    assert exam_py not in defs.get("_compose", []), "exam.py 不得保留第二份结构拼装 _compose"
    assert exam_py not in defs.get("_ordered", []), (
        "exam.py 不得复活确定性排序 _ordered（已由 exam_selector.rank_pool 取代）"
    )


def test_closed_sets_single_source() -> None:
    """闭集只在 rules.py，且与 schemas.py 的 Literal 逐字相等。"""
    rules_tree = _r6_ast("backend/app/services/rules.py")
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
        if rel.endswith("services/rules.py"):
            continue
        source = (REPO_ROOT / rel).read_text(encoding="utf-8")
        offenders += [f"{rel}: {direction}" for direction in DIRECTIONS if f'"{direction}"' in source]
    assert not offenders, f"方向字面量散落 rules.py 之外：{offenders}"


def test_contract_mirror_filtered_count() -> None:
    """`ExamRun.filtered_count` 双侧同步，且 `answer` 不进响应模型（AC-4）。"""
    schemas_tree = _r6_ast("backend/app/schemas.py")
    run_fields = _class_annotations(schemas_tree, "ExamRun")
    assert set(run_fields) == {"run_id", "questions", "filtered_count"}, f"ExamRun 字段应为 run_id/questions/filtered_count，实际 {sorted(run_fields)}"
    default = run_fields["filtered_count"]
    if isinstance(default, ast.Call):  # Field(default=0)
        defaults = [kw.value for kw in default.keywords if kw.arg == "default"]
        default = defaults[0] if defaults else None
    assert isinstance(default, ast.Constant) and default.value == 0, "filtered_count 旧客户端兼容默认值必须为 0"

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
    """
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
        if line.startswith("-") and not line.startswith("---")
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
        literals = _string_literals((SERVICES / name).read_text(encoding="utf-8"))
        assert not (literals & closed), f"{name} 复制了闭集字面量：{sorted(literals & closed)}"


def test_r7_copy_parity() -> None:
    """门禁 42：`coach_copy.py` 的 6 条中文文案必须逐字出现在 `lib/coach.ts`（同源不漂移）。"""
    backend = (SERVICES / "coach_copy.py").read_text(encoding="utf-8")
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


