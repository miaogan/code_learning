"""r65 AI 学习教练：材料清洗 / 引用白名单 / 空材料短路 / 端点端到端。

重点口径：
- 模型给的 href 只要不在材料里 → 该 action 丢弃并计入 `dropped_citations`（防幻觉）；
- 材料为空不调用模型（零成本），只回中文说明；
- 用户没配 Key 时按既有 AI 能力闸门走 503 中文错误，不落到 500。
"""

from typing import Any

from fastapi.testclient import TestClient

from app.schemas import CoachMaterial
from app.services.coach import policy

MATERIALS: list[dict[str, str]] = [
    {
        "title": "连续批处理 · 部署与推理",
        "href": "/learn/ai-inference-serving#tutorial-s1",
        "direction": "AI 工程",
        "sub_direction": "部署与推理",
        "level": "高级",
        "detail": "吞吐与延迟的权衡",
    },
    {
        "title": "多 Agent 编排 · Agent",
        "href": "/learn/ai-multi-agent#tutorial-s2",
        "direction": "AI 工程",
        "sub_direction": "Agent",
        "level": "高级",
        "detail": "共享状态单写者",
    },
]


def _draft(**overrides: Any) -> policy.CoachDraft:
    payload: dict[str, Any] = {
        "summary": "先补部署与并发，再看多 Agent 编排。",
        "blocks": [
            {
                "title": "第一阶段",
                "reason": "部署是你最薄的一环",
                "actions": [
                    {
                        "label": "读连续批处理",
                        "href": MATERIALS[0]["href"],
                        "why": "把吞吐数字讲清楚",
                        "minutes": 30,
                    }
                ],
            }
        ],
    }
    payload.update(overrides)
    return policy.CoachDraft.model_validate(payload)


def test_sanitize_materials_drops_external_and_duplicates() -> None:
    cleaned = policy.sanitize_materials(
        [
            CoachMaterial(title="A", href="/learn/a#tutorial-s1"),
            CoachMaterial(title="重复", href="/learn/a#tutorial-s1"),
            CoachMaterial(title="外链", href="https://example.test/x"),
            CoachMaterial(title="相对", href="learn/b"),
            CoachMaterial(title="B", href="/learn/b#tutorial-s2"),
        ]
    )
    assert [item["href"] for item in cleaned] == [
        "/learn/a#tutorial-s1",
        "/learn/b#tutorial-s2",
    ]


def test_sanitize_materials_caps_count_and_truncates() -> None:
    cleaned = policy.sanitize_materials(
        [
            CoachMaterial(title=f"第 {index} 条", href=f"/learn/c{index}#tutorial-s1")
            for index in range(policy.MATERIAL_LIMIT + 5)
        ]
    )
    assert len(cleaned) == policy.MATERIAL_LIMIT

    long_detail = CoachMaterial(
        title="长摘要",
        href="/learn/d#tutorial-s1",
        detail="字" * (policy.MATERIAL_DETAIL_MAX + 50),
    )
    cleaned_long = policy.sanitize_materials([long_detail])
    assert len(cleaned_long[0]["detail"]) <= policy.MATERIAL_DETAIL_MAX + 1
    assert cleaned_long[0]["detail"].endswith("…")


def test_sanitize_advice_keeps_whitelisted_actions() -> None:
    advice = policy.sanitize_advice(_draft(), MATERIALS)
    assert advice["notice"] == ""
    assert advice["materials_used"] == len(MATERIALS)
    assert advice["dropped_citations"] == 0
    assert advice["blocks"][0]["actions"][0]["href"] == MATERIALS[0]["href"]


def test_sanitize_advice_drops_hallucinated_hrefs_and_counts() -> None:
    draft = policy.CoachDraft.model_validate(
        {
            "summary": "总览",
            "blocks": [
                {
                    "title": "第一阶段",
                    "reason": "",
                    "actions": [
                        {
                            "label": "编的链接",
                            "href": "/learn/not-exist#tutorial-s9",
                            "why": "",
                            "minutes": 30,
                        },
                        {
                            "label": "真实链接",
                            "href": MATERIALS[1]["href"],
                            "why": "",
                            "minutes": 30,
                        },
                    ],
                }
            ],
        }
    )
    advice = policy.sanitize_advice(draft, MATERIALS)
    assert advice["dropped_citations"] == 1
    assert [action["href"] for action in advice["blocks"][0]["actions"]] == [
        MATERIALS[1]["href"]
    ]


def test_sanitize_advice_drops_empty_blocks_and_caps_limits() -> None:
    draft = policy.CoachDraft.model_validate(
        {
            "summary": "总览",
            "blocks": [
                {
                    "title": "全编的",
                    "reason": "",
                    "actions": [
                        {"label": "假", "href": "/learn/fake#tutorial-s1", "minutes": 30}
                    ],
                },
                {
                    "title": "真块",
                    "reason": "理由",
                    "actions": [
                        {
                            "label": f"动作 {index}",
                            "href": MATERIALS[0]["href"],
                            "minutes": 30,
                        }
                        for index in range(policy.ACTION_LIMIT + 2)
                    ],
                },
            ],
        }
    )
    advice = policy.sanitize_advice(draft, MATERIALS)
    assert len(advice["blocks"]) == 1
    assert len(advice["blocks"][0]["actions"]) == policy.ACTION_LIMIT
    assert advice["dropped_citations"] == 1


def test_sanitize_advice_clamps_minutes() -> None:
    draft = policy.CoachDraft.model_validate(
        {
            "summary": "总览",
            "blocks": [
                {
                    "title": "阶段",
                    "actions": [
                        {"label": "太短", "href": MATERIALS[0]["href"], "minutes": 1},
                        {"label": "太长", "href": MATERIALS[1]["href"], "minutes": 600},
                    ],
                }
            ],
        }
    )
    advice = policy.sanitize_advice(draft, MATERIALS)
    minutes = [action["minutes"] for action in advice["blocks"][0]["actions"]]
    assert minutes == [policy.MINUTES_MIN, policy.MINUTES_MAX]


def test_sanitize_advice_without_any_valid_action_returns_notice() -> None:
    draft = policy.CoachDraft.model_validate(
        {
            "summary": "只有总览",
            "blocks": [
                {
                    "title": "阶段",
                    "actions": [{"label": "假链接", "href": "https://x.test", "minutes": 30}],
                }
            ],
        }
    )
    advice = policy.sanitize_advice(draft, MATERIALS)
    assert advice["blocks"] == []
    assert advice["dropped_citations"] == 1
    assert advice["notice"] == policy.NO_CITATION_NOTICE


def test_prompt_lists_hrefs_and_falls_back_to_default_goal() -> None:
    prompt = policy.build_user_prompt(MATERIALS)
    for material in MATERIALS:
        assert material["href"] in prompt
    assert policy.DEFAULT_GOAL in prompt
    assert policy.DEFAULT_FOCUS in prompt


def _configure_user_ai(client: TestClient) -> None:
    saved = client.put(
        "/api/me/ai",
        json={
            "base_url": "https://api.example.test/v1",
            "model": "coach-model",
            "api_key": "sk-coach-test",
            "json_mode": "json_object",
        },
    )
    assert saved.status_code == 200, saved.text


def test_advice_empty_materials_never_calls_model(
    client: TestClient, patch_ai
) -> None:
    def _boom(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("材料为空时不应调用模型")

    patch_ai(_boom)
    response = client.post(
        "/api/coach/advice", json={"materials": [], "focus": "", "goal": ""}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["blocks"] == []
    assert body["materials_used"] == 0
    assert body["notice"] == policy.EMPTY_MATERIALS_NOTICE


def test_advice_requires_ai_key(client: TestClient) -> None:
    response = client.post(
        "/api/coach/advice", json={"materials": [{"title": "x", "href": "/learn/x"}]}
    )
    assert response.status_code == 503, response.text
    error = response.json()["error"]
    assert error["code"] == "AI_UNAVAILABLE"
    assert "AI" in error["message"]


def test_advice_filters_hallucinated_citations(client: TestClient, patch_ai) -> None:
    _configure_user_ai(client)
    patch_ai(
        lambda _model_cls, _user: {
            "summary": "先补部署",
            "blocks": [
                {
                    "title": "第一阶段",
                    "reason": "最薄的一环",
                    "actions": [
                        {
                            "label": "读连续批处理",
                            "href": MATERIALS[0]["href"],
                            "why": "把吞吐讲清楚",
                            "minutes": 30,
                        },
                        {
                            "label": "编造的小节",
                            "href": "/learn/hallucinated#tutorial-s1",
                            "why": "",
                            "minutes": 30,
                        },
                    ],
                }
            ],
        }
    )
    response = client.post(
        "/api/coach/advice",
        json={
            "materials": [
                {
                    "title": "连续批处理 · 部署与推理",
                    "href": MATERIALS[0]["href"],
                    "direction": "AI 工程",
                    "sub_direction": "部署与推理",
                    "level": "高级",
                    "detail": "吞吐与延迟的权衡",
                },
                {"title": "外链", "href": "https://example.test/x"},
            ],
            "focus": "AI 应用后端",
            "goal": "7 天内能讲清推理服务的关键取舍",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["materials_used"] == 1
    assert body["dropped_citations"] == 1
    assert [
        action["href"] for action in body["blocks"][0]["actions"]
    ] == [MATERIALS[0]["href"]]
    assert body["notice"] == ""
