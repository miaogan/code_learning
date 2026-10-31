"""零网络测试基座：每例独立临时 SQLite + FakeAI 替身（TECHNICAL §6.1）。

约定：
- `tmp_db` 用 `DB_PATH` 环境变量把 SQLite 指到临时目录，并 `get_settings.cache_clear()`，
  让 `app.db.connection()` 每次重读配置；用例之间互不污染。
- 所有 AI 调用走 `FakeAI`（服务层 `client=` 注入）或 `patch_ai`（类级补丁，覆盖
  「路由层不注入 client」的真实链路），因此整轮测试**不产生任何外网请求**。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import init_db
from app.main import app
from app.schemas import Profile, ProfileProject, ProfileSkill
from app.services.ai import AIClient

SEED_PATH = Path(__file__).resolve().parent.parent / "app" / "seed" / "questions.json"

#: 临时库落点：**不用 pytest 的 tmp_path** —— 本机沙箱拒写系统 Temp 目录
#: （`PermissionError: [WinError 5]` on `pytest-of-user`），所以退到工作区内的一处 scratch 目录。
SCRATCH_DIR = Path(__file__).resolve().parent / ".tmp"

#: 供画像 / 报告用例共用的简历正文：每一段都可被 `source_quote` 原样命中。
RESUME_TEXT = (
    "教育经历\n2019-2023 计算机科学与技术 本科\n"
    "工作经历\n2023-2026 前端开发工程师，负责组件库与构建提速\n"
    "项目经历\n数据看板项目：主导表格虚拟滚动与缓存策略\n"
    "技能\nReact TypeScript Python SQLite"
)

#: 与 `RESUME_TEXT` 逐条对应的画像草稿（模型原始产出的 5 维度）。
DRAFT_PAYLOAD: dict[str, Any] = {
    "skills": [
        {"name": "React", "source_quote": "React TypeScript Python SQLite"},
        {"name": "TypeScript", "source_quote": "React TypeScript Python SQLite"},
    ],
    "tech_stack": ["React", "TypeScript", "Python", "SQLite"],
    "years_experience": 3.0,
    "projects": [
        {
            "name": "数据看板",
            "role": "前端主力",
            "period": "2025-2026",
            "bullets": ["表格虚拟滚动", "查询结果缓存"],
            "source_quote": "数据看板项目：主导表格虚拟滚动与缓存策略",
        }
    ],
    "target_role": "前端开发工程师",
}

Responder = Callable[[type[Any], str], dict[str, Any]]


@pytest.fixture()
def tmp_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """把 SQLite 指到临时文件并建表；用例结束删库、清配置缓存。"""
    SCRATCH_DIR.mkdir(exist_ok=True)
    db_file = SCRATCH_DIR / f"{uuid4().hex}.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    monkeypatch.setenv("AI_API_KEY", "")
    get_settings.cache_clear()
    init_db()
    try:
        yield db_file
    finally:
        get_settings.cache_clear()
        db_file.unlink(missing_ok=True)


@pytest.fixture()
def client(tmp_db: Path) -> Iterator[TestClient]:
    """与生产同一份 `app`（含 lifespan），只是数据库是临时的。"""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def resume_text() -> str:
    return RESUME_TEXT


@pytest.fixture()
def draft_payload() -> dict[str, Any]:
    """画像草稿的深拷贝：用例改写它不影响其他用例。"""
    return json.loads(json.dumps(DRAFT_PAYLOAD, ensure_ascii=False))


@pytest.fixture()
def profile_factory(resume_text: str) -> Callable[..., Profile]:
    """造一份可溯源的 Profile（可直接走 repository 落库）。"""

    def _make(
        profile_id: str = "prof-1",
        resume_id: str = "res-1",
        *,
        tech_stack: list[str] | None = None,
        target_role: str = "前端开发工程师",
    ) -> Profile:
        return Profile(
            id=profile_id,
            resume_id=resume_id,
            updated_at="2026-10-31T05:00:00+00:00",
            skills=[
                ProfileSkill(name="React", source_quote="React TypeScript Python SQLite"),
                ProfileSkill(name="Python", source_quote="React TypeScript Python SQLite"),
            ],
            tech_stack=tech_stack or ["React", "TypeScript", "Python", "SQLite"],
            years_experience=3.0,
            projects=[
                ProfileProject(
                    name="数据看板",
                    role="前端主力",
                    period="2025-2026",
                    bullets=["表格虚拟滚动"],
                    source_quote="数据看板项目：主导表格虚拟滚动与缓存策略",
                )
            ],
            target_role=target_role,
        )

    return _make


@pytest.fixture()
def seed_questions() -> list[dict[str, Any]]:
    """静态题库原文（含仅服务端可见的 `answer` / `difficulty`）。"""
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, list) and payload, "题库必须是题目数组"
    return payload


class FakeAI:
    """零网络 AI 替身：按调用方传入的 `model_cls` 校验预置 payload 并返回模型实例。

    保留真实 `AIClient` 的口径 —— 预置 payload 仍要过目标模型的校验，
    因此「分数越界」「缺 source_quote」这类契约用例能照常被 schema 拦下。
    """

    def __init__(self, responder: Responder | None = None) -> None:
        self.responder = responder
        self.calls: list[tuple[str, str, float | None]] = []

    async def complete_model(
        self,
        system: str,
        user: str,
        model_cls: type[Any],
        *,
        timeout_s: float | None = None,
    ) -> Any:
        self.calls.append((system, user, timeout_s))
        if self.responder is None:
            raise AssertionError("FakeAI 未配置 responder：用例必须注入预置响应")
        return model_cls.model_validate(self.responder(model_cls, user))


@pytest.fixture()
def fake_ai() -> FakeAI:
    return FakeAI()


@pytest.fixture()
def patch_ai(monkeypatch: pytest.MonkeyPatch) -> Callable[[Responder], None]:
    """类级打补丁：路由层未注入 `client` 时也会命中 FakeAI（端到端用例零网络）。"""

    def _install(responder: Responder) -> None:
        async def fake_complete_model(
            self: AIClient,
            system: str,
            user: str,
            model_cls: type[Any],
            *,
            timeout_s: float | None = None,
        ) -> Any:
            return model_cls.model_validate(responder(model_cls, user))

        monkeypatch.setattr(AIClient, "complete_model", fake_complete_model)

    return _install


@pytest.fixture()
def ai_outage(monkeypatch: pytest.MonkeyPatch, tmp_db: Path) -> None:
    """把 AI 出网口整体打成 500：验证降级与错误 envelope 形状（AC-8 的反面用例）。

    两个前置：① `AI_API_KEY` 必须非空，否则 `complete_model` 在「未配置」分支就短路 503，
    根本走不到被补丁的 httpx 500 分支；② 依赖 `tmp_db` 保证本 fixture 在它之后执行
    （`tmp_db` 会把 key 置空），且 `get_settings` 是 `@lru_cache`，改完 env 必须清缓存，
    否则 lifespan 启动时那次读到的空 key 会一直沿用。
    """
    monkeypatch.setenv("AI_API_KEY", "test-key-not-a-real-secret")
    get_settings.cache_clear()

    class _Response:
        status_code = 500

        def json(self) -> dict[str, Any]:  # pragma: no cover - 500 分支不解析内容
            return {}

    class _Client:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_exc: Any) -> None:
            return None

        async def post(self, *_args: Any, **_kwargs: Any) -> _Response:
            return _Response()

    monkeypatch.setattr("app.services.ai.httpx.AsyncClient", _Client)


@pytest.fixture()
def assert_chinese() -> Callable[[str], None]:
    """错误 message 必须是中文（AGENTS §4 错误形态约定）。"""

    def _assert(text: str) -> None:
        assert any("\u4e00" <= char <= "\u9fff" for char in text), f"提示必须是中文：{text}"

    return _assert
