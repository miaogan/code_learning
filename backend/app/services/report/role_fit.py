"""市场竞争力对标（AC-7/8/9/10/20）：内置岗位能力模型的加载校验 + 目标岗位来源 + 纯函数差距计算。

为什么要单独立模块：这块内容**全是既有数据的投影**——画像给出 `user_level`，`seed/role_models.json`
给出 `required`，差距只是 `max(0, required-user_level)` 的减法。放在 `diagnosis.build_report`
里会和「短板/薄弱地图」的聚合逻辑搅在一起，也没法在没有 HTTP、没有 AI 的情况下单测。
拆出来后 `build_role_fit(profile, target_role)` 是**纯函数**（唯一副作用是查一次 lru_cache 的内存表），
因此 AC-8 的「空画像不抛」「全 gap=required」可以直接断言。

口径三条（改动前先读，别在别处重算）：
1. `required` 只来自内置模型数据（AI 不参与任何数值，anti-goal 4「差距像 AI 编的」在数据层就不成立）；
2. `user_level` 只由 `user_level_of()` 的确定性四档规则产出（见下），历史技能（`historical`）按 0 计；
3. `missing_must` 定义为「`gap > 0` 的必备技能」——缺 ⇔ 未达标，与 `items` 完全同源。

加载失败（缺文件 / 坏 JSON / 缺字段 / 数量或闭集不达标）一律 `AppError(VALIDATION_ERROR, 中文)`
向上抛：message 不含路径、不含堆栈、不含「seed」字样（AC-7）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.core.errors import VALIDATION_ERROR, AppError
from app.schemas import InterviewSettings, Profile, RoleFit, RoleFitItem, RoleModelRef
from app.services.report import rules
from app.services.resume import coach_copy

SEED_PATH = Path(__file__).resolve().parents[2] / "seed" / "role_models.json"

#: 档位闭集：`required` / `user_level` 都落在 0..4（0 = 画像里没有这项能力）。
ROLE_LEVELS: tuple[int, ...] = (1, 2, 3, 4)
#: 模型级别标签闭集，顺序即「从低到高」；`level` 字段必须取其中之一且在同一岗位内唯一。
LEVEL_ORDER: tuple[str, ...] = ("初级", "中级", "高级", "专家")
#: 单级能力的数量区间与必备技能下限（AC-7 断言的是这三条数据契约）。
MIN_SKILLS = 6
MAX_SKILLS = 8
MIN_MUST_HAVE = 3
#: 内置模型必须覆盖的方向数与每个岗位的级别数（4 方向 × 4 级）。
MIN_ROLES = 4
LEVELS_PER_ROLE = len(LEVEL_ORDER)
#: 「先补 1/2/3」取前三条（AC-20：序号由本列表顺序决定，前端绝不重排）。
FIRST_FIX_LIMIT = 3

VALIDATION_MESSAGE = "内置岗位能力模型数据有误，请检查后重启服务"


class _RoleSkill(BaseModel):
    """模型里的一项能力要求：`required` 是档位（1..4），不是分数。"""

    model_config = {"extra": "ignore"}

    name: str = Field(min_length=1)
    required: int = Field(ge=ROLE_LEVELS[0], le=ROLE_LEVELS[-1])


class _RoleModelLevel(BaseModel):
    """一个岗位的一个级别：`must_have` 是 `skills` 里的子集，级别由工作年数区间选中。"""

    model_config = {"extra": "ignore"}

    role: str = Field(min_length=1)
    direction: str = ""
    level: str
    years_min: float
    years_max: float
    must_have: list[str] = Field(default_factory=list)
    skills: list[_RoleSkill] = Field(default_factory=list)


class _RoleModelsFile(BaseModel):
    """`seed/role_models.json` 的顶层结构：`{"models": [...]}`（与 courses.json 同级同风格）。"""

    model_config = {"extra": "ignore"}

    models: list[_RoleModelLevel]


#: 目标岗位来源闭集（与 `RoleFit.role_source` 逐字一致，标签取自 `coach_copy`）。
RoleSource = Literal["interview", "profile"]
_SOURCE_INTERVIEW: RoleSource = "interview"
_SOURCE_PROFILE: RoleSource = "profile"


@dataclass(frozen=True)
class TargetRole:
    """目标岗位 + 来源：`source` 是 `RoleFit.role_source` 的闭集（AC-9），`label` 是中文来源标签。"""

    role: str | None
    source: RoleSource | None
    label: str | None


def _fail(_reason: str) -> AppError:
    """统一的坏数据出口：中文 message + 错误码，且**不带**原因细节里的文件路径。

    细节写日志没意义（本产品没有日志设施），真正的定位手段是 `tests/test_role_fit.py`
    里那几条坏文件用例；用户侧只需要知道「模型数据坏了，找研发」。
    """
    return AppError(VALIDATION_ERROR, VALIDATION_MESSAGE, status=500, retryable=False)


def _check_level(entry: _RoleModelLevel) -> None:
    """单级模型的数据契约校验（数量 / 闭集 / 必备子集 / 年数区间）。"""
    if entry.level not in LEVEL_ORDER:
        raise _fail("level 越出闭集")
    if entry.direction and entry.direction not in rules.DIRECTIONS:
        raise _fail("direction 越出闭集")
    if not MIN_SKILLS <= len(entry.skills) <= MAX_SKILLS:
        raise _fail("skills 数量越界")
    names = [skill.name for skill in entry.skills]
    if len(set(names)) != len(names):
        raise _fail("skills 重名")
    if len(entry.must_have) < MIN_MUST_HAVE:
        raise _fail("must_have 少于下限")
    if len(set(entry.must_have)) != len(entry.must_have):
        raise _fail("must_have 重名")
    if not set(entry.must_have) <= set(names):
        raise _fail("must_have 不是 skills 子集")
    if not entry.years_min < entry.years_max:
        raise _fail("years 区间反了")


def _parse(path: Path) -> dict[str, tuple[_RoleModelLevel, ...]]:
    """读文件 + pydantic 校验 + 结构校验，任一不达标即 `VALIDATION_ERROR`。"""
    try:
        raw: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:  # 缺文件 / 无权限 / 坏 JSON 统一一个出口
        raise _fail("模型文件读不出来") from exc
    try:
        payload = _RoleModelsFile.model_validate(raw)
    except ValidationError as exc:  # 缺字段 / 类型不符 / required 越界
        raise _fail("模型文件字段不完整") from exc

    if len(payload.models) < MIN_ROLES * LEVELS_PER_ROLE:
        raise _fail("模型条数不足")
    for entry in payload.models:
        _check_level(entry)

    grouped: dict[str, list[_RoleModelLevel]] = {}
    for entry in payload.models:
        grouped.setdefault(entry.role, []).append(entry)
    if len(grouped) < MIN_ROLES:
        raise _fail("岗位数不足")

    directions = {entry.direction for entry in payload.models}
    if set(rules.DIRECTIONS) - directions:
        raise _fail("方向覆盖不全")

    result: dict[str, tuple[_RoleModelLevel, ...]] = {}
    for role, entries in grouped.items():
        if len(entries) != LEVELS_PER_ROLE:
            raise _fail("岗位级别数不对")
        levels = sorted(entries, key=lambda item: item.years_min)
        if len({item.level for item in levels}) != LEVELS_PER_ROLE:
            raise _fail("同级重复")
        if [item.level for item in levels] != list(LEVEL_ORDER):
            raise _fail("级别顺序与年数区间不一致")
        result[role] = tuple(levels)
    return result


@lru_cache(maxsize=1)
def load_role_models() -> dict[str, tuple[_RoleModelLevel, ...]]:
    """岗位名 → 按 `years_min` 升序的级别元组（进程内只解析一次，`cache_clear()` 供测试复位）。

    返回的是**只读投影**，调用方不得就地修改（`_RoleModelLevel` 是 pydantic 模型，
    `build_role_fit` 只读它的字段）。键是文件里的原始岗位名，匹配时由 `_role_key` 归一。
    """
    return _parse(SEED_PATH)


def _role_key(role: str) -> str:
    """岗位名归一：去空白、忽略大小写（「前端工程师」与「 前端工程师 」视为同一岗位）。"""
    return "".join(role.split()).lower()


def _model_levels(role: str | None) -> tuple[_RoleModelLevel, ...] | None:
    """按归一后的岗位名查内置模型；未命中返回 `None`（AC-10 的降级由调用方渲染）。"""
    if not role:
        return None
    key = _role_key(role)
    if not key:
        return None
    for name, levels in load_role_models().items():
        if _role_key(name) == key:
            return levels
    return None


def resolve_target_role(
    *, interview_settings: InterviewSettings | None, profile: Profile | None
) -> TargetRole:
    """目标岗位来源优先级（AC-9）：本次面试设定 > 简历画像 > 无。

    「两处都为空不补默认值」是刻意的：报告页显示「本次面试设定」标签时，
    若拿 `rules.DEFAULT_TARGET_ROLE` 兜底，用户会看到一场从未配置过岗位的面试被标成
    「目标岗位：通用软件工程师」。宁可 `None` 走 AC-10 的降级文案。
    """
    if interview_settings is not None:
        role = (interview_settings.target_role or "").strip()
        if role:
            label = coach_copy.ROLE_SOURCE_LABEL[_SOURCE_INTERVIEW]
            return TargetRole(role, _SOURCE_INTERVIEW, label)
    if profile is not None:
        role = (profile.target_role or "").strip()
        if role:
            return TargetRole(role, _SOURCE_PROFILE, coach_copy.ROLE_SOURCE_LABEL[_SOURCE_PROFILE])
    return TargetRole(None, None, None)


def level_for_years(
    levels: tuple[_RoleModelLevel, ...], years: float | None
) -> _RoleModelLevel | None:
    """按工作年数选级别：落在 `[years_min, years_max)`；`None` / 越界取最近一端。

    `None` 取**最低级**而不是默认中级：没有年数信息时按最保守的一档要求来对标，
    给出的是「先补哪几项」，不会因为猜高了而虚报一个更好的竞争力结论。
    """
    if not levels:
        return None
    if years is None:
        return levels[0]
    for entry in levels:
        if entry.years_min <= years < entry.years_max:
            return entry
    return levels[0] if years < levels[0].years_min else levels[-1]


def _name_hits(needle: str, haystack: str) -> bool:
    """能力名命中判定：大小写不敏感 + 双向包含（模型名/画像名任一包含即可，AC-7）。"""
    left = needle.strip().lower()
    right = haystack.strip().lower()
    if not left or not right:
        return False
    return left in right or right in left


def _project_mentions(skill: str, profile: Profile) -> bool:
    """`projects[].bullets` 里是否出现过该能力名（决定 level 4：有落地证据）。"""
    return any(
        _name_hits(skill, bullet) for project in profile.projects for bullet in project.bullets
    )


def user_level_of(skill: str, profile: Profile | None) -> int:
    """画像里某项能力的当前档位 0..4（确定性规则，报告页与测试都按它复算）：

    - `0`：画像不含该能力（`skills[].name` 与 `tech_stack` 都不命中）；
    - `1`：仅 `tech_stack` 命中（会用但无证据）；
    - `2`：`skills[].name` 命中且证据 ≤1 条；
    - `3`：`skills[].name` 命中且 `len(source_quotes) >= 2`（`source_quote` 回填后算 1 条）；
    - `4`：在 3 的基础上，某个 `projects[].bullets` 文本里出现该能力名。

    `historical` 状态的技能按 0 计：已消失的能力不能算当前水平，否则「换过技术栈」的人
    会在报告里显得比实际更强（这是本块唯一会「虚报竞争力」的口子）。
    """
    if profile is None or not skill.strip():
        return 0
    active = [
        entry
        for entry in profile.skills
        if entry.status != "historical" and _name_hits(skill, entry.name)
    ]
    if not active:
        tech_hit = any(_name_hits(skill, item) for item in profile.tech_stack)
        return 1 if tech_hit else 0
    evidence = max(len(entry.source_quotes) for entry in active)
    if evidence < 2:
        return 2
    return 4 if _project_mentions(skill, profile) else 3


def _conclusion(label: str, first_fix: list[str]) -> str:
    """模板结论（AI 可替换的那一句）：全达标说「已经够」，有缺口点名前两项。

    只在 `model` 非空时产出；`_enrich_coach` 拿不到 AI 文案时原样保留它，
    因此降级路径绝不会出现「结论为空」的卡片（anti-goal 5）。
    """
    if not first_fix:
        return f"按「{label}」的要求，当前能力已基本达标，可以把精力放到更复杂的项目上"
    if len(first_fix) == 1:
        return f"按「{label}」的要求，最该先补的是「{first_fix[0]}」"
    return f"按「{label}」的要求，最该先补的是「{first_fix[0]}」，其次是「{first_fix[1]}」"


def _as_target(target: str | TargetRole | None, profile: Profile | None) -> TargetRole:
    """把调用方给的 `TargetRole` 或裸岗位名归一成 `TargetRole`。

    编排层（`diagnosis.build_report`）**应该**传 `resolve_target_role(...)` 的结果，来源标签才精确；
    只传岗位名时用「与画像岗位名相同 ⇒ 简历画像，否则 ⇒ 本次面试设定」兜底推断，
    这是能自洽的唯一推断方式（无法区分「面试设定恰好与画像相同」这一种情形，已记在交付说明里）。
    `target` 为空且画像里有岗位时回落画像（与 `resolve_target_role` 的优先级一致，不另立第三套规则）。
    """
    if isinstance(target, TargetRole):
        if target.role:
            return target
        target = None
    role = (target or "").strip()
    profile_role = (profile.target_role or "").strip() if profile is not None else ""
    if not role:
        if profile_role:
            return TargetRole(
                profile_role, _SOURCE_PROFILE, coach_copy.ROLE_SOURCE_LABEL[_SOURCE_PROFILE]
            )
        return TargetRole(None, None, None)
    source: RoleSource = (
        _SOURCE_PROFILE
        if profile_role and _role_key(profile_role) == _role_key(role)
        else _SOURCE_INTERVIEW
    )
    return TargetRole(role, source, coach_copy.ROLE_SOURCE_LABEL[source])


def build_role_fit(
    profile: Profile | None, target_role: str | TargetRole | None
) -> RoleFit:
    """差距表纯函数（AC-8 签名固定为 `(profile, target_role)`，另兼容传 `TargetRole`）。

    - 行内容：`gap = max(0, required - user_level)`；
    - 排序：`(必备优先, 差距大优先, 名称稳定)`——用户先看到「必备且差得多」的那几项；
    - `missing_must`：`gap > 0` 的必备技能（定义与 `items` 同源，不会出现「必备却已满足」）；
    - `first_fix`：`items` 顺序里前 3 个 `gap > 0` 的项，序号即优先级（AC-20 前端不重排）；
    - 无匹配模型 / 无目标岗位：`model=None` + `notice=ROLE_NO_MODEL`，**不抛异常**（AC-10）；
    - 空画像：全部 `user_level=0`、`gap=required`、`missing_must=must_have`，不抛（AC-8）。
    """
    resolved = _as_target(target_role, profile)
    fit = RoleFit(
        target_role=resolved.role,
        role_source=resolved.source,
        role_source_label=resolved.label,
    )
    levels = _model_levels(resolved.role)
    if not levels:
        fit.notice = coach_copy.ROLE_NO_MODEL
        return fit

    years = profile.years_experience if profile is not None else None
    level = level_for_years(levels, years)
    if level is None:  # pragma: no cover - levels 非空时不会发生
        fit.notice = coach_copy.ROLE_NO_MODEL
        return fit

    fit.model = RoleModelRef(
        level=level.level,
        label=f"{level.role} · {level.level}",
        direction=level.direction or None,
    )
    must = set(level.must_have)
    items: list[RoleFitItem] = []
    for skill in level.skills:
        user_level = user_level_of(skill.name, profile)
        items.append(
            RoleFitItem(
                name=skill.name,
                required=skill.required,
                user_level=user_level,
                gap=max(0, skill.required - user_level),
                must=skill.name in must,
            )
        )
    items.sort(key=lambda item: (0 if item.must else 1, -item.gap, item.name))

    fit.items = items
    fit.missing_must = [item.name for item in items if item.must and item.gap > 0]
    fit.first_fix = [item.name for item in items if item.gap > 0][:FIRST_FIX_LIMIT]
    fit.conclusion = _conclusion(fit.model.label, fit.first_fix)
    return fit
