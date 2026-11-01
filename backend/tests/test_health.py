"""探活与错误 envelope 的冒烟测试（AC-8 / r9 探活契约）。

两条 envelope 用例用模块级 `client`（import 期构造的 `app`）：它们不读配置、不进 lifespan。
`/health` 用例改走 `client` fixture（连 `tmp_db` → `neutral_ai_env`）：r9 之前那条裸断言
「`ai_configured is False`」等于断言「本机恰好没配 Key」，宿主 `.env` 一设就红。
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import JSON_MODES, get_settings
from app.main import app

client = TestClient(app)


def test_health_returns_ok(client: TestClient) -> None:
    """探活契约（r9）：legacy 未配置 + 三个只读字段，且响应体不含 key 的任何痕迹。"""
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert body["db"] == "sqlite"
    assert body["ai_configured"] is False
    assert body["ai_provider"] == "legacy"
    assert isinstance(body["ai_model"], str) and body["ai_model"]
    assert body["ai_json_mode"] in JSON_MODES
    # 白名单：`/health` 永不回传密钥的任何片段。
    lowered = response.text.lower()
    assert "key" not in lowered
    assert "sk-" not in lowered


def test_health_reflects_live_env(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """r9 去闭包的证据：env 改动 + 清缓存后，**同一个 app**（import 期构造）的 /health 立刻反映新档位。"""
    monkeypatch.setenv("AI_PROVIDER", "lmstudio")
    monkeypatch.setenv("AI_LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("AI_LMSTUDIO_MODEL", "qwen3.5-9b")
    monkeypatch.setenv("AI_LMSTUDIO_JSON_MODE", "none")
    get_settings.cache_clear()

    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["ai_provider"] == "lmstudio"
    assert body["ai_model"] == "qwen3.5-9b"
    assert body["ai_json_mode"] == "none"
    # 具名档就绪＝端点+模型齐备（本地无鉴权，key 可空）。
    assert body["ai_configured"] is True


def test_unknown_path_returns_error_envelope() -> None:
    response = client.get("/api/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_missing_body_answers_validation_error_envelope() -> None:
    """缺请求体走统一 envelope（ARCHITECTURE §3.3）。

    脚手架期此处断言的是「501 NOT_IMPLEMENTED」占位；5 个占位路由接通后（TECHNICAL §2），
    同一路径的真实契约是 422 + VALIDATION_ERROR（`profile_id` 已由 query 改为 body 模型）。
    """
    response = client.post("/api/interviews", json={})
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    assert body["retryable"] is False
    assert any("\u4e00" <= char <= "\u9fff" for char in body["message"])
