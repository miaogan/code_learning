"""r8 回归：画像契约的 null 口径（AC-1/2/4/6/7/8/11 的可执行证据）。

这个文件存在的理由：提示词（`PROFILE_SYSTEM`）明确允许模型对「无法判断」给 `null`，
而 r8 之前的 `ProfileProject.role/period` 要求 `str`，于是真实模型下画像生成必 502。
修复把口径统一到「可空」，本文件用**真实模型形状** fixture `REAL_MODEL_DRAFT`
钉住这份事实 —— 下一个人把 `role` 改回 `str` 时，这里先红，不必等线上 502。

五组断言：
- 契约：真实形状草稿 / 响应落地 / 存量 payload 三条路径都能通过（AC-1/AC-8）；
- 归一：整个维度给 `null` 或直接缺键 ⇒ `[]`；`bullets: null` ⇒ `[]`（AC-2）；
- 下游：润色白名单（`_allowed_numbers`）、面试开局输入（`_plan_input`）、
  润色路由在 null 画像下都不崩，且不会把 `null` 喂给模型（AC-4）；
- 合并：新简历没写角色/时间 ≠ 写过又删掉，空值不覆盖旧值（AC-6）；
- 闸门不放松：`name` / `source_quote` 仍必填非空，编造内容仍抛 `AI_SCHEMA_INVALID`（AC-7）。

零网络：润色链路走 conftest 的 `patch_ai`（类级补丁），其余用例全是纯函数。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import schemas
from app.core import repository
from app.core.errors import AI_SCHEMA_INVALID, AppError
from app.schemas import (
    InterviewSettings,
    Profile,
    ProfileDraft,
    ProfileProject,
    ProfileSkill,
    ResumeMeta,
)
from app.services.interview import interview as interview_service
from app.services.profile import profile_merge
from app.services.profile.profile import PROFILE_SYSTEM, verify_quotes
from app.services.report import role_fit, rules
from app.services.resume import resume_polish

#: 数据看板项目的溯源片段：与 conftest 的 `RESUME_TEXT` 逐字对应（`verify_quotes` 用）。
DASHBOARD_QUOTE = "数据看板项目：主导表格虚拟滚动与缓存策略"

#: **真实模型形状**（r8 缺陷的现场）：项目里 `role` / `period` 为 `null`，
#: `years_experience` / `target_role` 也无法判断 ⇒ `null`。修复前这份 payload 直接 502。
REAL_MODEL_DRAFT: dict[str, Any] = {
    "skills": [{"name": "React", "source_quote": "React TypeScript Python SQLite"}],
    "tech_stack": ["React", "TypeScript"],
    "years_experience": None,
    "projects": [
        {
            "name": "数据看板",
            "role": None,
            "period": None,
            "bullets": ["表格虚拟滚动"],
            "source_quote": DASHBOARD_QUOTE,
        }
    ],
    "target_role": None,
}


def _as_profile(draft: dict[str, Any]) -> Profile:
    """给草稿形状补上落库三件套，得到响应/存量读回用的 `Profile`。"""
    return Profile.model_validate(
        {
            **draft,
            "id": "p-r8",
            "resume_id": "res-r8",
            "updated_at": "2026-11-01T00:00:00Z",
        }
    )


def _project_payload(
    *, name: str = "数据看板", role: str | None = None, period: str | None = None,
    bullets: list[str] | None = None, quote: str = DASHBOARD_QUOTE,
) -> dict[str, Any]:
    return {
        "name": name,
        "role": role,
        "period": period,
        "bullets": [] if bullets is None else bullets,
        "source_quote": quote,
    }


def _draft(*projects: dict[str, Any]) -> dict[str, Any]:
    return {
        "skills": [],
        "tech_stack": [],
        "years_experience": None,
        "projects": list(projects),
        "target_role": None,
    }


# --- 契约：真实模型形状必须能通过（AC-1）------------------------------------


def test_role_null_draft_validates() -> None:
    """AC-1：真实模型形状（`role` / `period` 为 `null`）必须能通过草稿契约。"""
    draft = ProfileDraft.model_validate(REAL_MODEL_DRAFT)

    assert draft.projects[0].role is None, "role=null 表示「简历没写」，不能被迫填空串"
    assert draft.projects[0].period is None
    assert draft.target_role is None
    assert draft.years_experience is None


def test_role_null_profile_roundtrip() -> None:
    """AC-1：响应落地（`Profile`）与 JSON 往返都必须保住 `None`，不能退化成 `""`。"""
    profile = _as_profile(REAL_MODEL_DRAFT)
    dumped = json.loads(profile.model_dump_json())

    assert dumped["projects"][0]["role"] is None
    assert dumped["projects"][0]["period"] is None
    assert Profile.model_validate(dumped) == profile, "落库 JSON 读回必须逐字段等价"


# --- 归一：null / 缺键都归一为 []（AC-2）-------------------------------------


@pytest.mark.parametrize("field", ["skills", "tech_stack", "projects"])
@pytest.mark.parametrize("mode", ["null", "missing"])
def test_null_lists_normalized(field: str, mode: str) -> None:
    """AC-2：整个维度给 `null` 与直接缺键同解 —— 草稿与响应两条路径都归一为 `[]`。"""
    payload = {**REAL_MODEL_DRAFT}
    if mode == "null":
        payload[field] = None
    else:
        payload.pop(field)

    draft = ProfileDraft.model_validate(payload)
    assert getattr(draft, field) == [], f"草稿的 {field}（{mode}）未归一为 []"

    profile = _as_profile(payload)
    assert getattr(profile, field) == [], f"响应的 {field}（{mode}）未归一为 []"


def test_null_bullets_normalized() -> None:
    """AC-2：项目的 `bullets: null` 归一为 `[]`，不牵连元素级校验。"""
    project = _project_payload()
    project["bullets"] = None

    draft = ProfileDraft.model_validate(_draft(project))
    assert draft.projects[0].bullets == []

    kept = _project_payload(bullets=["表格虚拟滚动"])
    assert ProfileProject.model_validate(kept).bullets == ["表格虚拟滚动"]


# --- 闸门不放松：必填字段与反幻觉（AC-7）------------------------------------


def test_gate_fields_stay_required() -> None:
    """AC-7：放宽的只有 `role/period/bullets` 的缺省值；`name` / `source_quote` 仍必填非空。

    注意每个坏 payload 都带着 `bullets: null` + `role: null`：用来说明「空值归一」不会
    顺手把元素级闸门也一起放宽。
    """
    base: dict[str, Any] = {
        "name": "数据看板",
        "role": None,
        "period": None,
        "bullets": None,
        "source_quote": DASHBOARD_QUOTE,
    }
    for broken in ({"name": None}, {"source_quote": None}, {"source_quote": ""}):
        with pytest.raises(ValidationError):
            ProfileProject.model_validate({**base, **broken})

    with pytest.raises(ValidationError):
        ProfileSkill.model_validate({"name": "React", "source_quote": ""})


def test_verify_quotes_still_rejects_invented(resume_text: str) -> None:
    """AC-7：契约可空之后，「无源之词」仍被拒 —— 正例通过、编造条目抛 `AI_SCHEMA_INVALID`。"""
    good = ProfileDraft.model_validate(
        _draft(_project_payload(role=None, period=None))
        | {"skills": [{"name": "React", "source_quote": "React TypeScript Python SQLite"}]}
    )
    verify_quotes(good, resume_text)  # 不抛：null 的 role/period 不影响溯源判定

    invented = ProfileDraft.model_validate(
        _draft(_project_payload(role=None, quote="在字节跳动主导推荐系统重构"))
    )
    with pytest.raises(AppError) as excinfo:
        verify_quotes(invented, resume_text)
    assert excinfo.value.code == AI_SCHEMA_INVALID


def test_no_schema_loosening_in_schemas() -> None:
    """AC-7 静态位：不许用 `extra="allow"` 之类的「放开校验」来换绿。"""
    source = Path(schemas.__file__).read_text(encoding="utf-8")

    assert 'extra="allow"' not in source, "契约不得整段放开未知字段"
    assert ProfileDraft.model_config.get("extra") == "ignore", "未知字段仍按 ignore 语义处理"
    assert ProfileProject.model_fields["name"].is_required()
    assert ProfileProject.model_fields["source_quote"].is_required()


# --- 提示词与契约互锁（AC-11 的运行时侧）------------------------------------


def test_prompt_shape_matches_contract() -> None:
    """AC-11：提示词仍允许 `null`，且契约的 `role` / `period` 注解确实接受 `None`。

    两条断言必须同时成立 —— 只改一边就是 r8 缺陷的重演（提示词说 null、契约说 str）。
    """
    assert "无法判断填 null" in PROFILE_SYSTEM
    assert "若某个维度无信息，给空数组（或 null）" in PROFILE_SYSTEM
    for field in ("role", "period"):
        annotation = ProfileProject.model_fields[field].annotation
        assert type(None) in get_args(annotation), f"ProfileProject.{field} 不再接受 None"
    assert "_normalize_null_lists" in Path(schemas.__file__).read_text(encoding="utf-8")


# --- 存量兼容（AC-8）--------------------------------------------------------


def test_legacy_payload_without_role_period() -> None:
    """AC-8：r8 之前入库的 payload 没有 `role/period` 键，读回必须靠缺省值通过。"""
    legacy = _draft({"name": "数据看板", "bullets": ["表格虚拟滚动"], "source_quote": DASHBOARD_QUOTE})

    profile = _as_profile(legacy)
    assert profile.projects[0].role is None
    assert profile.projects[0].period is None


def test_legacy_payload_with_str_fields() -> None:
    """AC-8：已写入字符串的老 payload 值必须原样保留（不能被归一逻辑抹掉）。"""
    legacy = _draft(_project_payload(role="前端主力", period="2025-2026"))

    profile = _as_profile(legacy)
    assert profile.projects[0].role == "前端主力"
    assert profile.projects[0].period == "2025-2026"


def test_repository_none_roundtrip(tmp_db: str) -> None:
    """AC-4③：落库 → 读回，`None` 仍是 `None`；库里存的也是 `null`，不是 `""`。

    r98：判据从「读 SQLite 文件字节」换成「读 PG 里的 payload 文本列」—— 要验证的东西
    没变（落库的 JSON 里是 `null` 而非空串），只是不再有库文件可读。
    """
    repository.insert_profile(_as_profile(REAL_MODEL_DRAFT))

    stored = repository.get_profile("p-r8")
    assert stored is not None
    assert stored.projects[0].role is None
    assert stored.projects[0].period is None

    with repository.connection() as conn:
        raw = conn.execute(
            "SELECT payload FROM profiles WHERE id = ?", ("p-r8",)
        ).fetchone()["payload"]
    assert '"role":null' in raw, "JSON 里必须是 null，不得用空串伪装已知"
    assert '"period":null' in raw


# --- 下游空值防护（AC-4 ①~④）-----------------------------------------------


def test_allowed_numbers_tolerates_null_period() -> None:
    """AC-4①：`period=None` 不得让润色白名单采集抛错，bullet 内数字仍要收进来。"""
    profile = _as_profile(
        _draft(_project_payload(period=None, bullets=["渲染耗时降低 30%", "支持 10 万行"])),
    )

    numbers = resume_polish._allowed_numbers(profile)

    assert 30.0 in numbers and 10.0 in numbers, "bullet 内数字必须仍进白名单"
    assert resume_polish._allowed_numbers(None) == set()


def test_profile_brief_omits_none() -> None:
    """AC-4②：开局输入里不能出现 `"role": null` / `"period": null`（未知不等于已知）。"""
    profile = _as_profile(
        _draft(
            _project_payload(role=None, period=None),
            _project_payload(name="导出服务", role="服务端开发", period="2026", quote="服务端项目：用 Go 实现导出服务"),
        )
    )

    text = interview_service._plan_input(InterviewSettings(), {}, profile)

    assert not re.search(r'"role"\s*:\s*null', text), f"开局输入仍喂 null：{text[:200]}"
    assert not re.search(r'"period"\s*:\s*null', text)
    # D-3：顶层未知维度同口径 —— 「未知」不投喂 null，键整体省略。
    assert not re.search(r'"target_role"\s*:\s*null', text), "顶层 target_role=null 仍进提示词"
    assert not re.search(r'"years_experience"\s*:\s*null', text), "顶层 years_experience=null 仍进提示词"
    assert '"role": "服务端开发"' in text, "有值的项目维度必须保留"
    assert '"period": "2026"' in text


def test_polish_route_with_null_period(
    client: TestClient,
    patch_ai: Any,
    polish_responder: Any,
    resume_text: str,
) -> None:
    """AC-4④：路由级润色在「period 为 null 的画像」下必须 200（修复前是 AttributeError→500）。"""
    patch_ai(polish_responder)
    repository.insert_profile(
        _as_profile(_draft(_project_payload(period=None, bullets=["渲染耗时降低 30%"])))
    )
    repository.insert_document(
        ResumeMeta(resume_id="res-r8", file_name="简历.txt", chars=len(resume_text), sections=4),
        resume_text,
    )

    response = client.post("/api/resumes/res-r8/polish", json={"target_role": None})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["resume_text"] == resume_text
    assert body["dropped_count"] == 0
    assert body["suggestions"], "空值画像下仍应产出建议（不是静默降级为空）"


# --- 合并：空值不覆盖旧值（AC-6）--------------------------------------------


def test_merge_keeps_known_role() -> None:
    """AC-6：旧项目有角色/时间，新简历没写 ⇒ 沿用旧值（没写 ≠ 删掉）。"""
    old = _as_profile(_draft(_project_payload(role="前端主力", period="2025-2026", bullets=["表格虚拟滚动"])))
    draft = ProfileDraft.model_validate(_draft(_project_payload(role=None, period=None)))

    merged, _summary = profile_merge.merge_profile(old, draft, resume_id="res-2")

    project = merged.projects[0]
    assert project.role == "前端主力"
    assert project.period == "2025-2026"


def test_merge_fills_from_new() -> None:
    """AC-6：旧值是空的，新简历补上了 ⇒ 取新值（空值单向不覆盖，不是永久钉死）。"""
    old = _as_profile(_draft(_project_payload(role=None, period=None)))
    draft = ProfileDraft.model_validate(_draft(_project_payload(role="服务端开发", period="2026")))

    merged, _summary = profile_merge.merge_profile(old, draft, resume_id="res-2")

    assert merged.projects[0].role == "服务端开发"
    assert merged.projects[0].period == "2026"


def test_merge_both_none() -> None:
    """AC-6：两侧都空 ⇒ `None`（不写 `""`）、不抛，`profile_id` 不变。"""
    old = _as_profile(_draft(_project_payload(role=None, period=None)))
    draft = ProfileDraft.model_validate(_draft(_project_payload(role=None, period=None)))

    merged, _summary = profile_merge.merge_profile(old, draft, resume_id="res-2")

    assert merged.projects[0].role is None
    assert merged.projects[0].period is None
    assert merged.id == old.id, "同一 profile 增量合并不得换 id"


def test_merge_bullets_not_lost() -> None:
    """§2.3：新简历没写要点时 `bullets=[]` 不得抹掉旧要点（与 role/period 同源）。"""
    old = _as_profile(_draft(_project_payload(bullets=["表格虚拟滚动", "查询结果缓存"])))
    draft = ProfileDraft.model_validate(_draft(_project_payload(bullets=[])))

    merged, _summary = profile_merge.merge_profile(old, draft, resume_id="res-2")

    assert merged.projects[0].bullets == ["表格虚拟滚动", "查询结果缓存"]


# --- r9 D-2 口径：本地档 `target_role` 允许为 null，下游默认值必须有出口 -------------


def test_target_role_null_is_accepted_and_downstream_defaults_hold() -> None:
    """r9 D-2（本地 LM Studio + qwen3.5-9b 实测）：画像 `target_role` 允许落库为 null。

    真机取证：`logs/teamflow/<runId>/scripts/check_r9_local_target_role.py` 打印的模型**原始 JSON**
    就是 `"target_role": null`，`ProfileDraft` → `Profile` → `profile_merge` 三段零改写 ⇒ 这是
    「本地小模型按提示词第 1/3 条保守产出」（宁缺毋滥、不推断目标岗位），**不是代码丢值**。
    因此 TECH-CHANGE §5-1 的「target_role 有值」在本地档降级为观察项（口径记录于任务夹
    `docs/teamflow/20261101-r9-ai-provider-switch/FIX-NOTE.md`），本条钉住降级后仍然安全：
    ① 契约接受 null；② 面试开局输入回落 `DEFAULT_TARGET_ROLE` 而不是把 `null` 喂给模型；
    ③ 诊断的对标走 `TargetRole(None)` 降级文案，不崩、也不伪造一次「通用软件工程师」配置。
    """
    profile = _as_profile(_draft())

    assert profile.target_role is None
    assert interview_service._role_text(profile.target_role) == rules.DEFAULT_TARGET_ROLE
    resolved = role_fit.resolve_target_role(interview_settings=None, profile=profile)
    assert (resolved.role, resolved.source, resolved.label) == (None, None, None)
