"""r9 供应商档位的行为用例（TECH-CHANGE §3 / §5）。

口径分三层断言：**解析结果**（`Settings.resolve_ai()`）、**请求体形状**（装配后的
`model` / `response_format` / `Authorization` / 超时）、**状态码与中文**（配置错 → 503）。

全部 **零网络**：`httpx.AsyncClient` 被换成记录器；真实链路单独用 `AI_LIVE=1` 开关跳过，
所以本文件在任何没装 LM Studio、也没有云端 Key 的机器上都确定通过。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.config import (
    DEFAULT_JSON_MODE,
    JSON_MODES,
    UNIFIED_AI_TIMEOUT_S,
    Settings,
    get_settings,
)
from app.core.errors import AI_UNAVAILABLE, AppError
from app.main import app
from app.services.ai.ai import JSON_RETRY_HINT, AIClient

LMSTUDIO_BASE = "http://localhost:1234/v1"
DEEPSEEK_BASE = "https://api.deepseek.com/v1"


class _Payload(BaseModel):
    """最小结构化返回体：只为验证「能取到对象」，不参与业务校验。"""

    answer: str


def _chinese(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


# --- 基座：环境中性化 + 离线传输层 ---------------------------------------------


@pytest.fixture()
def ai_env(monkeypatch: pytest.MonkeyPatch, neutral_ai_env: None) -> Callable[..., Settings]:
    """在中性环境（`neutral_ai_env`）之上按用例追加设定，返回新解析的 `Settings`。"""

    def _apply(**values: str) -> Settings:
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()
        return get_settings()

    return _apply


class _Transport:
    """记录每次出网的 `url / headers / json / timeout`，并按队列返回模型内容。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.contents: list[str] = []
        self.status_code = 200

    def will_answer(self, *contents: str) -> _Transport:
        self.contents = list(contents)
        return self

    def next_content(self) -> str:
        if not self.contents:
            return "{}"
        if len(self.contents) > 1:
            return self.contents.pop(0)
        return self.contents[0]


@pytest.fixture()
def ai_transport(monkeypatch: pytest.MonkeyPatch) -> _Transport:
    transport = _Transport()

    class _Response:
        def __init__(self, status_code: int, content: str) -> None:
            self.status_code = status_code
            self._content = content

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"content": self._content}}]}

    class _Client:
        def __init__(self, *_args: Any, **kwargs: Any) -> None:
            self._timeout = kwargs.get("timeout")

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_exc: object) -> bool:
            return False

        async def aclose(self) -> None:
            """池化客户端的关停钩子（lifespan 退出时会调用）。"""
            return None

        async def post(
            self,
            url: str,
            *,
            headers: dict[str, str] | None = None,
            json: dict[str, Any] | None = None,
            timeout: float | None = None,
        ) -> _Response:
            transport.calls.append(
                {
                    "url": url,
                    "headers": headers or {},
                    "json": json or {},
                    # 池化后超时按请求覆写：显式传入优先，否则用客户端构造时的默认值。
                    "timeout": timeout if timeout is not None else self._timeout,
                }
            )
            return _Response(transport.status_code, transport.next_content())

    monkeypatch.setattr("app.services.ai.ai.httpx.AsyncClient", _Client)
    return transport


def _complete(settings: Settings, timeout_s: float | None = None) -> _Payload:
    return asyncio.run(
        AIClient(settings).complete_model("系统提示", "用户问题", _Payload, timeout_s=timeout_s)
    )


def _failure(settings: Settings) -> AppError:
    with pytest.raises(AppError) as excinfo:
        _complete(settings)
    return excinfo.value


# --- 1. 解析：legacy / 具名档 / 未知 / 缺字段 / 闭集外 ---------------------------


def test_legacy_resolution_unchanged(ai_env: Callable[..., Settings]) -> None:
    """`AI_PROVIDER` 为空时与 r8 逐字一致：直读全局四项，就绪仍是「Key 非空」。"""
    settings = ai_env(
        AI_BASE_URL="https://api.example.com/v1",
        AI_MODEL="m-legacy",
        AI_API_KEY="k-legacy",
        AI_TIMEOUT_S="33",
    )

    runtime = settings.resolve_ai()

    assert runtime.provider == "legacy"
    assert runtime.base_url == "https://api.example.com/v1"
    assert runtime.model == "m-legacy"
    assert runtime.api_key == "k-legacy"
    assert runtime.json_mode == DEFAULT_JSON_MODE
    assert runtime.timeout_s == 33.0
    assert runtime.max_retries == settings.ai_max_retries
    assert runtime.ready is True


def test_named_profile_does_not_fall_back_to_global(ai_env: Callable[..., Settings]) -> None:
    """具名档只读该档三项，**绝不回落全局**（否则会把云端 Key 发给本地端点）。"""
    settings = ai_env(
        AI_PROVIDER="lmstudio",
        AI_BASE_URL=DEEPSEEK_BASE,
        AI_MODEL="global-model",
        AI_API_KEY="sk-cloud-must-not-be-sent",
        AI_LMSTUDIO_BASE_URL=LMSTUDIO_BASE,
        AI_LMSTUDIO_MODEL="qwen3.5-9b",
        AI_LMSTUDIO_API_KEY="",
    )

    runtime = settings.resolve_ai()

    assert runtime.provider == "lmstudio"
    assert runtime.base_url == LMSTUDIO_BASE
    assert runtime.model == "qwen3.5-9b"
    assert runtime.api_key == ""  # 安全边界：云端 Key 不随档位漂移
    assert runtime.ready is True


def test_unknown_provider_is_503_chinese(ai_env: Callable[..., Settings]) -> None:
    settings = ai_env(AI_PROVIDER="openai-compatible")

    runtime = settings.resolve_ai()

    assert runtime.ready is False
    assert "deepseek" in runtime.reason and "lmstudio" in runtime.reason
    error = _failure(settings)
    assert error.code == AI_UNAVAILABLE
    assert error.status == 503
    assert _chinese(error.message)


def test_missing_base_url_or_model_is_503_chinese(ai_env: Callable[..., Settings]) -> None:
    settings = ai_env(AI_PROVIDER="lmstudio", AI_LMSTUDIO_MODEL="")

    runtime = settings.resolve_ai()

    assert runtime.ready is False
    assert "AI_LMSTUDIO" in runtime.reason
    error = _failure(settings)
    assert error.code == AI_UNAVAILABLE
    assert error.status == 503
    assert _chinese(error.message)


def test_json_mode_outside_closed_set_is_503(ai_env: Callable[..., Settings]) -> None:
    """闭集外的模式回落缺省 + `ready=False`，绝不让它流进投影表；错误仍是 503 中文。"""
    settings = ai_env(
        AI_PROVIDER="lmstudio",
        AI_LMSTUDIO_BASE_URL=LMSTUDIO_BASE,
        AI_LMSTUDIO_MODEL="qwen3.5-9b",
        AI_LMSTUDIO_JSON_MODE="json_schema",
    )

    runtime = settings.resolve_ai()

    assert runtime.ready is False
    assert runtime.json_mode in JSON_MODES
    assert "json_schema" in runtime.reason
    error = _failure(settings)
    assert error.code == AI_UNAVAILABLE
    assert error.status == 503
    assert _chinese(error.message)


def test_ai_configured_delegates_to_runtime_ready(ai_env: Callable[..., Settings]) -> None:
    """`ai_configured` 是 `resolve_ai().ready` 的唯一委托（禁止第二处就绪判定）。"""
    missing = ai_env(
        AI_PROVIDER="lmstudio", AI_LMSTUDIO_BASE_URL=LMSTUDIO_BASE, AI_LMSTUDIO_MODEL=""
    )
    assert missing.ai_configured is False
    assert missing.ai_configured is missing.resolve_ai().ready

    ready = ai_env(
        AI_PROVIDER="lmstudio", AI_LMSTUDIO_BASE_URL=LMSTUDIO_BASE, AI_LMSTUDIO_MODEL="qwen3.5-9b"
    )
    assert ready.ai_configured is True
    assert ready.ai_configured is ready.resolve_ai().ready


# --- 2. 请求体：鉴权头 / response_format 矩阵 / 超时优先级 ----------------------


def test_blank_key_omits_authorization_header(
    ai_env: Callable[..., Settings], ai_transport: _Transport
) -> None:
    settings = ai_env(
        AI_PROVIDER="lmstudio",
        AI_LMSTUDIO_BASE_URL=LMSTUDIO_BASE,
        AI_LMSTUDIO_MODEL="qwen3.5-9b",
        AI_LMSTUDIO_API_KEY="",
    )
    ai_transport.will_answer('{"answer": "ok"}')

    _complete(settings)

    call = ai_transport.calls[0]
    assert "Authorization" not in call["headers"]  # 空 Bearer 会被部分实现判 401
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["url"] == f"{LMSTUDIO_BASE}/chat/completions"
    assert call["json"]["model"] == "qwen3.5-9b"


def test_response_format_matrix(ai_env: Callable[..., Settings], ai_transport: _Transport) -> None:
    """`json_object` 发送同名对象；`none` **整键不发**（也不发 `{"type":"text"}`）。"""
    for mode, expected in (("json_object", {"type": "json_object"}), ("none", None)):
        settings = ai_env(
            AI_PROVIDER="deepseek",
            AI_DEEPSEEK_BASE_URL=DEEPSEEK_BASE,
            AI_DEEPSEEK_MODEL="deepseek-chat",
            AI_DEEPSEEK_API_KEY="k-deepseek",
            AI_DEEPSEEK_JSON_MODE=mode,
        )
        ai_transport.calls.clear()
        ai_transport.will_answer('{"answer": "ok"}')

        _complete(settings)

        payload = ai_transport.calls[-1]["json"]
        assert payload["model"] == "deepseek-chat"
        assert payload.get("response_format") == expected
        assert ("response_format" in payload) is (expected is not None)


def test_profile_timeout_overrides_global_and_call_site_wins(
    ai_env: Callable[..., Settings], ai_transport: _Transport
) -> None:
    """超时优先级：调用点显式 > 档内 > 全局；档内 `0` 是「继承全局」的哨兵。"""
    settings = ai_env(
        AI_PROVIDER="lmstudio",
        AI_LMSTUDIO_BASE_URL=LMSTUDIO_BASE,
        AI_LMSTUDIO_MODEL="qwen3.5-9b",
        AI_LMSTUDIO_TIMEOUT_S="450",
        AI_TIMEOUT_S="20",
    )
    assert settings.resolve_ai().timeout_s == 450.0

    ai_transport.will_answer('{"answer": "ok"}', '{"answer": "ok"}')
    _complete(settings)
    assert ai_transport.calls[-1]["timeout"] == 450.0

    _complete(settings, timeout_s=14.0)  # 显式覆写仍作为底层能力保留（生产调用点已统一不传）
    assert ai_transport.calls[-1]["timeout"] == 14.0

    inherit = ai_env(AI_LMSTUDIO_TIMEOUT_S="0", AI_TIMEOUT_S="25")
    assert inherit.resolve_ai().timeout_s == 25.0


def test_lmstudio_profile_defaults_json_mode_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """`Settings` 字段缺省：lmstudio 档默认 `json_mode=none`、档内超时给足本地实测预算。

    直接构造 `Settings(_env_file=None, ...)`：既不读宿主 `.env`，也不受本文件其它用例的
    `monkeypatch` 影响，钉的是字段缺省值本身（「空则继承全局」另有用例覆盖）。

    D-1（r9 QA）：默认超时不写死字面量（旧值 180s < 本机实测 201.25s，会把本地画像掐成 503），
    改为断言「等于字段默认值」+「不低于实测下限 300s」，标定变更只需改 `config.py` 一处。
    """
    monkeypatch.delenv("AI_LMSTUDIO_JSON_MODE", raising=False)
    monkeypatch.delenv("AI_LMSTUDIO_TIMEOUT_S", raising=False)
    monkeypatch.delenv("AI_JSON_MODE", raising=False)
    settings = Settings(
        _env_file=None,
        ai_provider="lmstudio",
        ai_lmstudio_base_url=LMSTUDIO_BASE,
        ai_lmstudio_model="qwen3.5-9b",
    )

    runtime = settings.resolve_ai()

    assert runtime.ready is True
    assert runtime.json_mode == "none"
    assert runtime.timeout_s == settings.ai_lmstudio_timeout_s  # 档内缺省＝字段默认值
    assert runtime.timeout_s >= 300.0, "本地档默认超时须≥300s（qwen3.5-9b 单次画像实测 201s）"


def test_blank_profile_json_mode_inherits_global(
    ai_env: Callable[..., Settings], ai_transport: _Transport
) -> None:
    """档内 `json_mode` 置空＝继承全局（与「字段缺省 none」是两条不同规则）。"""
    settings = ai_env(
        AI_PROVIDER="lmstudio",
        AI_LMSTUDIO_BASE_URL=LMSTUDIO_BASE,
        AI_LMSTUDIO_MODEL="qwen3.5-9b",
        AI_LMSTUDIO_JSON_MODE="",
        AI_JSON_MODE="json_object",
    )
    assert settings.resolve_ai().json_mode == "json_object"

    ai_transport.will_answer('{"answer": "ok"}')
    _complete(settings)
    assert ai_transport.calls[-1]["json"]["response_format"] == {"type": "json_object"}


# --- 3. 鲁棒性：围栏剥离 / none 下的重试 ---------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        '```json\n{"answer": "围栏包裹"}\n```',
        '先说明一下：\n{"answer": "中间有解释"}\n以上，请查收。',
        '{"answer": "纯 JSON"}',
    ],
)
def test_fence_and_prose_still_extracted(
    ai_env: Callable[..., Settings], ai_transport: _Transport, content: str
) -> None:
    """三种输出形态都要能剥离出 JSON 对象（小模型鲁棒性：只剥壳，不放松校验）。"""
    settings = ai_env(
        AI_PROVIDER="lmstudio",
        AI_LMSTUDIO_BASE_URL=LMSTUDIO_BASE,
        AI_LMSTUDIO_MODEL="qwen3.5-9b",
        AI_LMSTUDIO_JSON_MODE="none",
    )
    ai_transport.will_answer(content)

    payload = _complete(settings)

    assert payload.answer  # 取到对象即通过；内容随形态不同
    assert len(ai_transport.calls) == 1


def test_retry_appends_hint_under_json_mode_none(
    ai_env: Callable[..., Settings], ai_transport: _Transport
) -> None:
    """重试与 `json_mode` 无关：`none` 下第二次同样追加 JSON 约束，且 `response_format` 仍不发。"""
    settings = ai_env(
        AI_PROVIDER="lmstudio",
        AI_LMSTUDIO_BASE_URL=LMSTUDIO_BASE,
        AI_LMSTUDIO_MODEL="qwen3.5-9b",
        AI_LMSTUDIO_JSON_MODE="none",
    )
    ai_transport.will_answer("这不是 JSON", '{"answer": "第二次成功"}')

    payload = _complete(settings)

    assert payload.answer == "第二次成功"
    assert len(ai_transport.calls) == 2
    first, second = (call["json"] for call in ai_transport.calls)
    assert "response_format" not in second
    assert JSON_RETRY_HINT not in first["messages"][1]["content"]
    assert JSON_RETRY_HINT in second["messages"][1]["content"]


# --- 4. 探活：三字段与零泄露 ---------------------------------------------------


def test_health_exposes_provider_without_key(ai_env: Callable[..., Settings]) -> None:
    """`/health` 暴露档位三字段；具名档缺 Key 也 ready（本地无鉴权，TECHNICAL §5.1 取舍）。"""
    ai_env(
        AI_PROVIDER="deepseek",
        AI_DEEPSEEK_BASE_URL=DEEPSEEK_BASE,
        AI_DEEPSEEK_MODEL="deepseek-chat",
        AI_DEEPSEEK_API_KEY="",
    )

    response = TestClient(app).get("/health")
    body = response.json()

    assert response.status_code == 200
    assert body["ai_provider"] == "deepseek"
    assert body["ai_model"] == "deepseek-chat"
    assert body["ai_json_mode"] == "json_object"  # 档内空 → 继承全局缺省
    assert body["ai_configured"] is True
    assert "key" not in response.text.lower()
    assert "sk-" not in response.text


# --- 4b. 空值数值档位不炸进程（交付自检补钉） ---------------------------------


def test_blank_numeric_profile_env_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`AI_*_TIMEOUT_S=` / `AI_MAX_RETRIES=` 写成空值时，`Settings()` 不得抛校验错。

    运维照 `.env.example` 抄完清空一行是常见操作；空串进 `float` / `int` 会在构造期抛
    `ValidationError`，把进程（与整批用例）打挂 —— 与 config.py 第 1 条不变量
    「解析永不 raise / 配置错只置 ready=False」冲突，故按「未设置」回落字段默认值。
    """
    for name in ("AI_TIMEOUT_S", "AI_MAX_RETRIES", "AI_DEEPSEEK_TIMEOUT_S", "AI_LMSTUDIO_TIMEOUT_S"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("AI_PROVIDER", "")  # 空＝legacy；不能用 delenv，否则宿主 .env 的档位会漏进来
    get_settings.cache_clear()

    settings = Settings()  # 关键：不抛 ValidationError

    assert settings.ai_timeout_s == UNIFIED_AI_TIMEOUT_S
    assert settings.ai_max_retries == 1
    assert settings.ai_deepseek_timeout_s == 0.0  # 0＝继承全局
    assert settings.ai_lmstudio_timeout_s >= 300.0  # 空值回落「字段默认值」，不是落到 0
    # 空值不改变解析结论：仍能正常解析出可用的 legacy 口径。
    assert settings.resolve_ai().timeout_s == UNIFIED_AI_TIMEOUT_S


# --- 5. 真实链路冒烟（默认跳过） ------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("AI_LIVE") != "1",
    reason="真实链路需 AI_LIVE=1 与本机 LM Studio / 云端 Key",
)
def test_live_profile_generation_smoke() -> None:
    """真实出网一次，证明「当前 env 解析出的档位」确实能拿到结构化返回（不进 CI）。"""
    get_settings.cache_clear()
    runtime = get_settings().resolve_ai()
    assert runtime.ready, runtime.reason

    payload: _Payload = asyncio.run(
        AIClient().complete_model(
            "你是结构化输出助手，只输出一个 JSON 对象，不要解释。",
            '请原样输出这样一个 JSON：{"answer": "ok"}',
            _Payload,
            timeout_s=max(runtime.timeout_s, 60.0),
        )
    )

    assert payload.answer
