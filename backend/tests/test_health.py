"""探活与错误 envelope 的冒烟测试（AC-8）。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "sqlite"
    assert body["ai_configured"] is False


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
