"""r7 AC-12：`to_markdown` 三块单源渲染（薄弱地图 / 简历要点 / 竞争力对标）。

约定：本文件自带 payload 构造（不新建共享 helper 模块，保持文件所有权不相交），
断言全部落在 `to_markdown` 的**文本**上，因此不需要模型与业务库；唯一一条 HTTP 用例把
同一份 `Report` 存进临时库，验证 `GET /api/reports/{id}/markdown` 返回的正是
`to_markdown(report)`（页面「复制 Markdown」/ 导出 / 预览同源，AC-12）。
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

from app import repository
from app.schemas import Report
from app.services import coach_copy, markdown

# --- payload 构造（形状与 build_report 的真实产物一致）--------------------------------


def _shortfall_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "前端基础薄弱",
        "severity": "high",
        "evidence": "Q3 · 4/10",
        "diagnosis": "基础题连错，说明概念边界没打牢",
        "actions": ["重做 3 道基础题", "口述事件循环"],
        "courses": [],
        "question_ref": "fe-q1",
    }
    payload.update(overrides)
    return payload


def _weakness_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "key": "fe|basic,challenge|must_know",
        "point": "前端基础",
        "direction": "fe",
        "wrong": 5,
        "total": 8,
        "rate": 0.625,
        "avg": 5.0,
        "difficulty": ["basic", "challenge"],
        "essentiality": ["must_know"],
        "samples": [
            {"question_id": "fe-q1", "score": 4.0, "evidence": "Q1 · 4/10"},
            {"question_id": "fe-q2", "score": 5.5, "evidence": "Q2 · 5.5/10"},
        ],
        "summary": "「前端基础」方向 8 题里错 5 题，基础题还没打牢",
    }
    payload.update(overrides)
    return payload


def _pointer_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "section": "project",
        "location": "项目经历 · 第 12 行",
        "anchor_text": "数据看板项目：主导表格虚拟滚动与缓存策略",
        "issue": "只有职责没有收益，补一句量化结果",
        "focus_key": "数据看板项目：主导表格虚拟滚动与缓存策略",
    }
    payload.update(overrides)
    return payload


def _role_fit_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "target_role": "前端开发工程师",
        "role_source": "interview",
        "role_source_label": "本次面试设定",
        "model": {"level": "中级", "label": "前端开发工程师 · 中级"},
        "items": [
            {"name": "React", "required": 3, "user_level": 1, "gap": 2, "must": True},
            {"name": "TypeScript", "required": 2, "user_level": 2, "gap": 0, "must": True},
            {"name": "Node.js", "required": 2, "user_level": 0, "gap": 2, "must": False},
        ],
        "missing_must": ["React"],
        "first_fix": ["React", "工程化"],
        "conclusion": "先补 React 与工程化，再谈框架原理",
        "notice": None,
    }
    payload.update(overrides)
    return payload


def _base_payload(**overrides: object) -> dict[str, object]:
    """旧报告形态（无 r7 四字段）+ 本轮的短板块；overrides 用来切三块状态。"""
    payload: dict[str, object] = {
        "id": "rep-r7-0001",
        "run_ids": ["iv-r7-1", "ex-r7-1"],
        "interview_avg": 6.75,
        "exam_total": 88.0,
        "shortfalls": [_shortfall_payload()],
        "generated_at": "2026-11-01T12:00:00+00:00",
    }
    payload.update(overrides)
    return payload


def _report(**overrides: object) -> Report:
    """三块齐全的 r7 报告；测试按需要把某一块覆盖成 `None` / `[]`。"""
    payload = _base_payload(
        weakness_map=[_weakness_payload()],
        resume_pointers=[_pointer_payload()],
        role_fit=_role_fit_payload(),
    )
    payload.update(overrides)
    return Report.model_validate(payload)


def _uri(text: str) -> str:
    """与前端 `encodeURIComponent` 同口径：空格 `%20`、保留 `!'()*-._~`。"""
    return quote(text, safe="!'()*-._~")


def _block(text: str, heading: str) -> str:
    """取某一块的正文（到下一个二级标题为止）：让每条断言只看自己那块，互不串味。"""
    start = text.index(heading) + len(heading)
    rest = text[start:]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


# --- 顺序与骨架（AC-12 / AC-14：三块必须在短板之后）----------------------------------


def test_three_blocks_follow_shortfalls_in_report_field_order() -> None:
    text = markdown.to_markdown(_report())
    anchors = [
        "## 短板总览",
        "## 1. 前端基础薄弱（严重度：高）",
        "## 知识薄弱地图",
        "## 简历改进要点",
        "## 市场竞争力对标",
    ]
    positions = [text.index(anchor) for anchor in anchors]
    assert positions == sorted(positions), "顺序必须是 短板 → 薄弱地图 → 简历要点 → 竞争力"


def test_shortfall_section_is_byte_identical_to_before() -> None:
    """AC-14：短板块渲染零变更（三块只是追加在它之后）。"""
    text = markdown.to_markdown(_report())
    block = _block(text, "## 1. 前端基础薄弱（严重度：高）")
    assert "- 证据：Q3 · 4/10（题目 fe-q1）" in block
    assert "- 诊断：基础题连错，说明概念边界没打牢" in block
    assert "  1. 重做 3 道基础题" in block
    assert "  - 暂无课程" in block


def test_only_one_renderer_lives_in_the_module() -> None:
    """AC-12：不新增第二个渲染源（没有 `to_markdown_v2` 之类的旁路）。"""
    source = Path(markdown.__file__).read_text(encoding="utf-8")
    assert source.count("def to_markdown(") == 1
    assert "to_markdown_v2" not in source
    assert [name for name in vars(markdown) if name.startswith("to_markdown")] == ["to_markdown"]


def test_block_copy_comes_from_coach_copy_module() -> None:
    """文案单源：三块的降级/空态中文只存在于 `coach_copy.py`，markdown 内不得复制一份。"""
    source = Path(markdown.__file__).read_text(encoding="utf-8")
    for copy in (
        coach_copy.LEGACY_BLOCK_NOTICE,
        coach_copy.WEAKNESS_EMPTY,
        coach_copy.RESUME_NO_TEXT,
        coach_copy.RESUME_AI_FALLBACK,
        coach_copy.ROLE_NO_MODEL,
        coach_copy.ROLE_NO_MODEL_HINT,
    ):
        assert copy not in source


# --- A 薄弱地图 ---------------------------------------------------------------------


def test_weakness_table_rows_match_items_in_order() -> None:
    items = [
        _weakness_payload(),
        _weakness_payload(
            key="be|basic|advanced",
            point="后端进阶",
            direction="be",
            wrong=2,
            total=6,
            rate=0.333,
            avg=6.75,
            difficulty=[],
            essentiality=["advanced"],
            samples=[{"question_id": "be-q5", "score": 6.75, "evidence": "Q5 · 6.8/10"}],
        ),
    ]
    block = _block(markdown.to_markdown(_report(weakness_map=items)), "## 知识薄弱地图")

    assert "| 1 | 前端基础 | 基础、挑战 | 必备 | 5/8 | 63% | Q1 · 4/10；Q2 · 5.5/10 |" in block
    assert "| 2 | 后端进阶 | — | 进阶 | 2/6 | 33% | Q5 · 6.8/10 |" in block
    assert block.index("| 1 | 前端基础") < block.index("| 2 | 后端进阶")
    assert "（组内均分 5/10）" in block
    assert "（组内均分 6.8/10）" in block


def test_weakness_evidence_comes_verbatim_from_samples() -> None:
    """证据串由 `weakness.py` 用 `format_score` 生成，这里只拼接、不改写。"""
    sample = {"question_id": "fe-q9", "score": 7.0, "evidence": "Q9 · 7/10"}
    report = _report(weakness_map=[_weakness_payload(samples=[sample])])
    block = _block(markdown.to_markdown(report), "## 知识薄弱地图")
    assert "Q9 · 7/10" in block


def test_weakness_legacy_and_empty_are_two_different_copies() -> None:
    legacy = _block(markdown.to_markdown(_report(weakness_map=None)), "## 知识薄弱地图")
    empty = _block(markdown.to_markdown(_report(weakness_map=[])), "## 知识薄弱地图")

    assert coach_copy.LEGACY_BLOCK_NOTICE in legacy
    assert "| # |" not in legacy
    assert coach_copy.LEGACY_BLOCK_NOTICE not in empty
    assert coach_copy.WEAKNESS_EMPTY in empty
    assert "| # |" not in empty


def test_weakness_rate_is_integer_percent_with_js_half_up() -> None:
    """整数百分比，且与前端 `Math.round(rate*100)` 同口径（62.5% → 63%，不是 62%）。"""
    cases = (
        (0.625, "63%"),
        (0.5, "50%"),
        (0.875, "88%"),
        (0.333, "33%"),
        (1.0, "100%"),
        (0.0, "0%"),
    )
    for rate, expected in cases:
        assert markdown.format_percent(rate) == expected


def test_cells_escape_pipes_and_flatten_newlines() -> None:
    item = _weakness_payload(point="前端|基础", summary="第一行\n第二行")
    block = _block(markdown.to_markdown(_report(weakness_map=[item])), "## 知识薄弱地图")
    rows = [
        line
        for line in block.splitlines()
        if line.startswith("| ") and not line.startswith("| # |")
    ]

    assert len(rows) == 1, "转义失效会让一条记录把整张表拆成两行"
    assert "前端\\|基础" in block
    assert "第一行 第二行" in block


# --- B 简历要点 ---------------------------------------------------------------------


def test_resume_pointers_render_in_order_with_polish_link() -> None:
    pointers = [
        _pointer_payload(),
        _pointer_payload(
            section="experience",
            location="工作经历 · 第 8 行",
            anchor_text="2023-2026 前端开发工程师，负责组件库与构建提速",
            issue="把「负责」改成「主导」",
            focus_key="2023-2026 前端开发工程师，负责组件库与构建提速",
        ),
    ]
    block = _block(markdown.to_markdown(_report(resume_pointers=pointers)), "## 简历改进要点")

    assert block.index("1. **项目经历 · 第 12 行**") < block.index("2. **工作经历 · 第 8 行**")
    assert "原句：「数据看板项目：主导表格虚拟滚动与缓存策略」" in block
    assert "问题：只有职责没有收益，补一句量化结果" in block

    focus = _uri("数据看板项目：主导表格虚拟滚动与缓存策略")
    anchor = _uri("数据看板项目：主导表格虚拟滚动与缓存策略")
    href = f"/polish?focus={focus}&section=project&anchor={anchor}"
    assert href in block, "跳转串的参数名/顺序必须与前端 polishHref 一致"


def test_oversized_anchor_only_keeps_short_params() -> None:
    """`anchor_text` 超过 `ANCHOR_MAX_CHARS` 时与前端同规则：只带 focus + section。"""
    long_anchor = "技能" * 21  # 42 字 > 40
    pointer = _pointer_payload(anchor_text=long_anchor, focus_key=long_anchor)
    block = _block(markdown.to_markdown(_report(resume_pointers=[pointer])), "## 简历改进要点")

    assert f"focus={_uri(long_anchor)}&section=project" in block
    assert "&anchor=" not in block


def test_resume_empty_states_use_server_side_notice() -> None:
    no_text = _block(
        markdown.to_markdown(
            _report(resume_pointers=[], resume_pointers_notice=coach_copy.RESUME_NO_TEXT)
        ),
        "## 简历改进要点",
    )
    fallback = _block(
        markdown.to_markdown(_report(resume_pointers=[], resume_pointers_notice=None)),
        "## 简历改进要点",
    )
    legacy = _block(markdown.to_markdown(_report(resume_pointers=None)), "## 简历改进要点")

    assert coach_copy.RESUME_NO_TEXT in no_text
    assert "1. **" not in no_text
    assert coach_copy.RESUME_AI_FALLBACK in fallback
    assert coach_copy.LEGACY_BLOCK_NOTICE in legacy


# --- C 竞争力对标 -------------------------------------------------------------------


def test_role_fit_table_gap_labels_and_first_fix_order() -> None:
    block = _block(markdown.to_markdown(_report()), "## 市场竞争力对标")

    assert "- 目标岗位：前端开发工程师（来源：本次面试设定）" in block
    assert "- 匹配模型：前端开发工程师 · 中级" in block
    assert "| React（必备） | 3 | 1 | 2 |" in block
    assert "| TypeScript（必备） | 2 | 2 | 达标 |" in block, "gap=0 不写「0」"
    assert "| Node.js | 2 | 0 | 2 |" in block
    assert block.index("| React（必备）") < block.index("| TypeScript（必备）")
    assert "- 缺失必备技能：React" in block
    assert "  1. React" in block and "  2. 工程化" in block, "序号由 first_fix 顺序决定"
    assert "- 结论：先补 React 与工程化，再谈框架原理" in block


def test_role_source_label_falls_back_to_closed_set_dict() -> None:
    role = _role_fit_payload(role_source="profile", role_source_label=None)
    block = _block(markdown.to_markdown(_report(role_fit=role)), "## 市场竞争力对标")
    assert f"（来源：{coach_copy.ROLE_SOURCE_LABEL['profile']}）" in block


def test_role_no_model_degrades_to_two_notices_only() -> None:
    role = _role_fit_payload(
        target_role="区块链工程师",
        role_source="profile",
        role_source_label="简历画像",
        model=None,
        items=[],
        missing_must=[],
        first_fix=[],
        conclusion=None,
        notice=coach_copy.ROLE_NO_MODEL,
    )
    block = _block(markdown.to_markdown(_report(role_fit=role)), "## 市场竞争力对标")

    assert "- 目标岗位：区块链工程师（来源：简历画像）" in block
    assert coach_copy.ROLE_NO_MODEL in block
    assert coach_copy.ROLE_NO_MODEL_HINT in block
    assert f"\n\n> {coach_copy.ROLE_NO_MODEL}\n" in block, "引用块不得紧贴列表项（会被解析成列表续行）"
    assert block.count(coach_copy.ROLE_NO_MODEL) == 1, "服务端 notice 与常量相同时不得重复一遍"
    assert "| 能力项 |" not in block
    assert "缺失必备技能" not in block


def test_role_none_is_legacy_notice() -> None:
    block = _block(markdown.to_markdown(_report(role_fit=None)), "## 市场竞争力对标")
    assert coach_copy.LEGACY_BLOCK_NOTICE in block
    assert "目标岗位" not in block


# --- 兼容与同源 ---------------------------------------------------------------------


def test_legacy_payload_without_r7_fields_renders_three_notices() -> None:
    """AC-13：r1–r6 形态的旧 payload 反序列化后三块为 `None` → 三处「旧报告」提示。"""
    report = Report.model_validate(_base_payload())

    assert report.weakness_map is None
    assert report.resume_pointers is None
    assert report.role_fit is None

    text = markdown.to_markdown(report)
    assert text.count(coach_copy.LEGACY_BLOCK_NOTICE) == 3
    for heading in ("## 知识薄弱地图", "## 简历改进要点", "## 市场竞争力对标"):
        assert heading in text


def test_scores_follow_format_score() -> None:
    text = markdown.to_markdown(_report(interview_avg=6.75, exam_total=88.0))

    assert "- 面试均分：6.8/10" in text
    assert "- 笔试总分：88/100" in text


def test_empty_run_ids_render_placeholder() -> None:
    text = markdown.to_markdown(_report(run_ids=[]))
    assert "- 关联测评：—" in text


def test_http_markdown_endpoint_returns_the_single_source(client: TestClient) -> None:
    """AC-12：复制/导出取的端点文本 == `to_markdown(report)`，前端零拼串。"""
    report = _report(id="rep-r7-http")
    report.run_ids = []
    repository.insert_report(report)

    response = client.get(f"/api/reports/{report.id}/markdown")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text.strip() == markdown.to_markdown(report).strip()
    for heading in ("## 知识薄弱地图", "## 简历改进要点", "## 市场竞争力对标"):
        assert heading in response.text
