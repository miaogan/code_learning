"""零网络测试基座：每例独立临时 SQLite + FakeAI 替身（TECHNICAL §6.1）。

约定：
- `tmp_db` 用 `DB_PATH` 环境变量把 SQLite 指到临时目录，并 `get_settings.cache_clear()`，
  让 `app.db.connection()` 每次重读配置；用例之间互不污染。
- 所有 AI 调用走 `FakeAI`（服务层 `client=` 注入）或 `patch_ai`（类级补丁，覆盖
  「路由层不注入 client」的真实链路），因此整轮测试**不产生任何外网请求**。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import repository
from app.auth import COOKIE_NAME, hash_password, new_session_token, session_expiry
from app.config import get_settings
from app.db import init_db
from app.main import app
from app.schemas import Evidence, Profile, ProfileProject, ProfileSkill, SkillStatus
from app.services import user_ai
from app.services.ai import AIClient, reset_ai_pool

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

#: 第二份**差异化**简历（r3 增量合并用）：保留 React（小写变体，考归一判同），
#: 去掉 SQLite（考「消失项转历史」），新增 Go / Kubernetes（考「新增项」）。
SECOND_RESUME_TEXT = """
教育经历
2019-2023 计算机科学与技术 本科
工作经历
2023-2026 前端开发工程师，负责组件库与构建提速
项目经历
数据看板项目：主导表格虚拟滚动与缓存策略
服务端项目：用 Go 实现导出服务
技能
react TypeScript Python Go Kubernetes
""".strip()

#: 与 `SECOND_RESUME_TEXT` 逐条对应、可逐字溯源的画像草稿（第二次上传用）。
SECOND_DRAFT_PAYLOAD: dict[str, Any] = {
    "skills": [
        {"name": "React", "source_quote": "react TypeScript Python Go Kubernetes"},
        {"name": "Go", "source_quote": "react TypeScript Python Go Kubernetes"},
        {"name": "Kubernetes", "source_quote": "react TypeScript Python Go Kubernetes"},
    ],
    "tech_stack": ["React", "TypeScript", "Go", "Kubernetes"],
    "years_experience": 3.5,
    "projects": [
        {
            "name": "数据看板",
            "role": "前端主力",
            "period": "2025-2026",
            "bullets": ["表格虚拟滚动", "查询结果缓存"],
            "source_quote": "数据看板项目：主导表格虚拟滚动与缓存策略",
        },
        {
            "name": "导出服务",
            "role": "服务端开发",
            "period": "2026",
            "bullets": ["批量导出"],
            "source_quote": "服务端项目：用 Go 实现导出服务",
        },
    ],
    "target_role": "后端开发工程师",
}

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

#: 润色建议模板：`original_text` 逐字取自 `RESUME_TEXT`（反幻觉校验的真实输入口径）。
#: 五条覆盖 4 个 section；第 3 条与第 2 条区间重叠，是 `compose_full` 去重的天然用例。
POLISH_CASES: tuple[dict[str, Any], ...] = (
    {
        "section": "experience",
        "original_text": "2023-2026 前端开发工程师，负责组件库与构建提速",
        "suggested_text": "2023-2026 前端开发工程师，主导组件库建设与构建流程提速",
        "reason": "把「负责」改成「主导」，让职责与影响力可读",
    },
    {
        "section": "project",
        "original_text": "数据看板项目：主导表格虚拟滚动与缓存策略",
        "suggested_text": "数据看板项目：主导大表格虚拟滚动与查询结果缓存，降低渲染开销",
        "reason": "补充技术场景与收益，避免只有名词堆叠",
    },
    {
        "section": "project",
        "original_text": "表格虚拟滚动",
        "suggested_text": "大表格虚拟滚动",
        "reason": "同一区间的更短表述（与上一条重叠，成稿只取一条）",
    },
    {
        "section": "education",
        "original_text": "2019-2023 计算机科学与技术 本科",
        "suggested_text": "2019-2023 计算机科学与技术 本科，专业课程与工程实践并重",
        "reason": "教育背景补一句侧重，信息量更足",
    },
    {
        "section": "summary",
        "original_text": "React TypeScript Python SQLite",
        "suggested_text": "React TypeScript Python SQLite（按目标岗位顺序排列）",
        "reason": "技能清单按岗位优先级排序，便于快速匹配",
    },
)

#: 反幻觉用例的「伪输出」：新增数字（8000 万）与新增专名（GMV）都必须被拦下。
HALLUCINATED_CASE: dict[str, Any] = {
    "section": "project",
    "original_text": "数据看板项目：主导表格虚拟滚动与缓存策略",
    "suggested_text": "数据看板项目：2023 年 GMV 8000 万，主导表格虚拟滚动与缓存策略",
    "reason": "补充业务结果（这条应当被降级为〈待补充〉或整条丢弃）",
}


def polish_payload(*, hallucinated: bool = False) -> dict[str, Any]:
    """润色草稿响应的模板（服务层 `_SuggestDraft` 的**超集**：多余的键被 pydantic
    默认的 `extra="ignore"` 忽略，因此**不绑定**模型的确切字段名）。

    用法：`patch_ai(lambda *_: polish_payload())` 或 `FakeAI(responder=...)`，零网络。
    `hallucinated=True` 时追加 `HALLUCINATED_CASE`，覆盖 AC-9 的降级 / 丢弃路径。
    """
    cases = [*POLISH_CASES, *([HALLUCINATED_CASE] if hallucinated else [])]
    return {
        "suggestions": [
            {
                **case,
                "id": f"ps-{index}",
                "target_role": None,
                "flags": [],
                "start": 0,
                "end": 0,
            }
            for index, case in enumerate(cases, start=1)
        ],
        "dropped_count": 0,
    }


#: 测试期一律置空的 AI 环境变量（字符串类型）。行为口径见 TECHNICAL §3.1：
#: `AI_PROVIDER` 空＝legacy、`AI_JSON_MODE` 空＝闭集缺省、各档端点/模型/Key 空＝未配置。
#: **只碰字符串字段**——数值型档位（`*_TIMEOUT_S`）绝不能 `setenv("")`：空串进 `float`
#: 字段会在 `Settings()` 构造期抛校验错，连带 `lru_cache` 与整批用例崩；需要改就用 0＝继承全局。
_NEUTRAL_AI_ENV: dict[str, str] = {
    "AI_PROVIDER": "",
    "AI_JSON_MODE": "",
    "AI_API_KEY": "",
    "AI_DEEPSEEK_BASE_URL": "",
    "AI_DEEPSEEK_MODEL": "",
    "AI_DEEPSEEK_API_KEY": "",
    "AI_DEEPSEEK_JSON_MODE": "",
    "AI_LMSTUDIO_BASE_URL": "",
    "AI_LMSTUDIO_MODEL": "",
    "AI_LMSTUDIO_API_KEY": "",
    "AI_LMSTUDIO_JSON_MODE": "",
}


@pytest.fixture(autouse=True)
def _isolate_ai_pool() -> Iterator[None]:
    """AI 出网口已池化：用例之间清空连接池，避免打补丁的假客户端跨用例串用。

    httpx 连接池按事件循环分桶，而用例里的 `asyncio.run` 每次都是一个新 loop；
    不清空的话，上一个用例创建假客户端会滞留在池里，导致后一个用例「没有出网记录」。
    """
    reset_ai_pool()
    yield
    reset_ai_pool()


@pytest.fixture()
def neutral_ai_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """把 AI 相关环境变量清成「未配置」，让用例与本机 `backend/.env` 解耦（r9 单一出口）。

    r8 及之前，环境中性化散落两处（`tmp_db` 只清 `AI_API_KEY`、`test_resume_hints._no_ai_key`
    再清一次），r9 每多一个 `AI_*` 变量就要改 N 处，漏一处即「宿主 `.env` 一设就集体变红」。
    置空后必须 `cache_clear()`（`get_settings` 是 `@lru_cache`），teardown 再清一次避免串味。
    """
    for name, value in _NEUTRAL_AI_ENV.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.fixture()
def tmp_db(monkeypatch: pytest.MonkeyPatch, neutral_ai_env: None) -> Iterator[Path]:
    """把 SQLite 指到临时文件并建表；用例结束删库、清配置缓存。

    `neutral_ai_env` 是显式依赖：任何拿到 `tmp_db`（或 `client`）的用例都自动获得环境中性化。
    """
    SCRATCH_DIR.mkdir(exist_ok=True)
    db_file = SCRATCH_DIR / f"{uuid4().hex}.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    get_settings.cache_clear()
    init_db()
    try:
        yield db_file
    finally:
        get_settings.cache_clear()
        db_file.unlink(missing_ok=True)


#: 测试登录用户：固定 id = `DEFAULT_USER_ID`，让「服务层无认证上下文时写入的默认归属」
#: 与路由层登录用户一致（用例里绕过 repository 的直接 SQL 插入同样归它所有）。
TEST_USER_ID = "default"
TEST_USER_EMAIL = "member@example.com"
TEST_USER_PASSWORD = "test-password-123"
TEST_USER_KEY = "sk-test-not-a-real-secret"
TEST_SECRET_KEY = "test-secret-key-for-r23"


@pytest.fixture()
def auth_user(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """建一个「own 模式 + 已存 Key」的登录用户：路由用例无需自己处理 AI 闸门。"""
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET_KEY)
    get_settings.cache_clear()
    repository.create_user(
        user_id=TEST_USER_ID,
        email=TEST_USER_EMAIL,
        password_hash=hash_password(TEST_USER_PASSWORD),
        display_name="测试用户",
        role="member",
        key_mode="own",
    )
    repository.update_user_ai(
        TEST_USER_ID,
        base_url="https://api.example.test/v1",
        model="test-model",
        api_key_enc=user_ai.encrypt_key(TEST_USER_KEY),
        json_mode="json_object",
        updated_at="2026-11-03T00:00:00+00:00",
    )
    user = repository.get_user_by_id(TEST_USER_ID)
    assert user is not None
    return user


@pytest.fixture()
def client(tmp_db: Path, auth_user: dict[str, Any]) -> Iterator[TestClient]:
    """与生产同一份 `app`（含 lifespan），数据库是临时的，且已带上登录会话 Cookie。"""
    raw, digest = new_session_token()
    repository.create_session(
        token_hash=digest, user_id=TEST_USER_ID, expires_at=session_expiry()
    )
    with TestClient(app) as test_client:
        test_client.cookies.set(COOKIE_NAME, raw)
        yield test_client


@pytest.fixture()
def resume_text() -> str:
    return RESUME_TEXT


@pytest.fixture()
def second_resume_text() -> str:
    """第二份差异化简历正文（与 `resume_text` 形成「同技能 / 消失项 / 新增项」对照）。"""
    return SECOND_RESUME_TEXT


@pytest.fixture()
def second_draft_payload() -> dict[str, Any]:
    return json.loads(json.dumps(SECOND_DRAFT_PAYLOAD, ensure_ascii=False))


@pytest.fixture()
def draft_payload() -> dict[str, Any]:
    """画像草稿的深拷贝：用例改写它不影响其他用例。"""
    return json.loads(json.dumps(DRAFT_PAYLOAD, ensure_ascii=False))


@pytest.fixture()
def profile_factory(resume_text: str) -> Callable[..., Profile]:
    """造一份可溯源的 Profile（可直接走 repository 落库）。

    默认 `with_evidence=True`：r3 起每个能力项天生带一条 `Evidence`（`resume_id` /
    `file_name` / `captured_at` 指向本画像的来源），这是「证据链熬过 DB 往返」的基座。
    要造**存量（r1）画像**——只有 `source_quote`、没有证据链——显式传 `with_evidence=False`；
    `status="historical"` 可直接造「已消失的能力项」。
    """

    def _make(
        profile_id: str = "prof-1",
        resume_id: str = "res-1",
        *,
        tech_stack: list[str] | None = None,
        target_role: str = "前端开发工程师",
        status: SkillStatus = "active",
        with_evidence: bool = True,
        file_name: str = "简历.txt",
        captured_at: str = "2026-10-31T05:00:00+00:00",
    ) -> Profile:
        def _evidence(quote: str) -> list[Evidence]:
            if not with_evidence:
                return []
            return [
                Evidence(
                    quote=quote,
                    resume_id=resume_id,
                    file_name=file_name,
                    captured_at=captured_at,
                )
            ]

        return Profile(
            id=profile_id,
            resume_id=resume_id,
            updated_at="2026-10-31T05:00:00+00:00",
            skills=[
                ProfileSkill(
                    name="React",
                    source_quote="React TypeScript Python SQLite",
                    source_quotes=_evidence("React TypeScript Python SQLite"),
                    status=status,
                ),
                ProfileSkill(
                    name="Python",
                    source_quote="React TypeScript Python SQLite",
                    source_quotes=_evidence("React TypeScript Python SQLite"),
                    status=status,
                ),
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
                    source_quotes=_evidence("数据看板项目：主导表格虚拟滚动与缓存策略"),
                    status=status,
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
        retry_unavailable: bool = False,
    ) -> Any:
        self.calls.append((system, user, timeout_s))
        if self.responder is None:
            raise AssertionError("FakeAI 未配置 responder：用例必须注入预置响应")
        return model_cls.model_validate(self.responder(model_cls, user))


@pytest.fixture()
def fake_ai() -> FakeAI:
    return FakeAI()


@pytest.fixture()
def polish_responder() -> Responder:
    """润色链路的零网络 responder 模板（现成的 `Responder`，可直接给 `FakeAI` / `patch_ai`）。

    断言口径：五条建议的 `original_text` 都能在 `RESUME_TEXT` 里逐字命中；
    需要反幻觉用例时改用自己的 responder 并复用 `polish_payload(hallucinated=True)`。
    """

    def _responder(_model_cls: type[Any], _user: str) -> dict[str, Any]:
        return polish_payload()

    return _responder


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
            retry_unavailable: bool = False,
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

        async def aclose(self) -> None:
            """池化客户端的关停钩子（lifespan 退出时会调用）。"""
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


def drive_session(
    run: Any,
    client: Any = None,
    *,
    answer: str = "补充说明",
    rounds: int = 40,
    on_turn: Callable[[Any], None] | None = None,
) -> list[Any]:
    """把一场面试按 r5 契约推进到结束（一次只投放一条发言），返回每轮的 `InterviewTurn`。

    r5 起 `InterviewRun` 只带第 1 条发言（`run.question`），后续发言从上一轮的 `next_question`
    取；**不能**再像 r1 那样遍历 `run.questions`（那个字段已随破坏性契约移除）。
    重放已答旧题会被服务端拒绝（QA D-2），所以这里只按 `current_id` 单向推进。
    `on_turn` 给需要在「每一轮之后」断言的用例留钩子（例如时间线不得提前写事件）。
    """
    from app.services import interview as interview_service

    turns: list[Any] = []
    question_id = run.question.id
    while question_id is not None and len(turns) < rounds:
        turn = asyncio.run(
            interview_service.score_answer(run.run_id, question_id, answer, client=client)
        )
        turns.append(turn)
        if on_turn is not None:
            on_turn(turn)
        question_id = turn.next_question.id if turn.next_question is not None else None
    return turns

