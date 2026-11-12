"""r97 公网部署：启动期安全校验（生产档 blockers / warnings）。

口径：
- 只在 `APP_ENV=production` 生效，开发与测试档 **零影响**（默认值一分不改）；
- `blockers` 是「配置组合让公网失去一条安全边界」→ 启动直接失败；
- `warnings` 是「能跑但加固被关」→ 只记日志，不拦人（排障时关限流是合理操作）；
- 校验只读配置，不碰数据库、不发网络请求。

测试必须**与运行环境无关**：`_env_file=None` 关掉 `backend/.env`，且把参与判定的字段
全部显式传入（init kwargs 优先级最高）——否则本机 .env / CI 环境变量会让断言随机翻脸。
"""

from app.core.config import Settings

READY: dict[str, object] = {
    "app_env": "production",
    "cookie_secure": True,
    "cors_origins": "https://escape.example.com",
    "rate_limit_enabled": True,
    "breaker_enabled": True,
    "secret_key": "0" * 64,
    "ai_provider": "deepseek",
    "ai_deepseek_base_url": "https://api.deepseek.com/v1",
    "ai_deepseek_model": "deepseek-chat",
    "ai_deepseek_api_key": "sk-test",
}


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**READY, **overrides})  # type: ignore[arg-type]


def test_development_env_is_never_checked() -> None:
    """开发档：即使 cookie_secure=false、CORS 含 *，也不产生任何阻断或告警。"""
    dev = _settings(app_env="development", cookie_secure=False, cors_origins="*")

    assert dev.is_production is False
    assert dev.production_blockers() == []
    assert dev.production_warnings() == []


def test_production_ready_config_has_no_blockers() -> None:
    ready = _settings()

    assert ready.is_production is True
    assert ready.production_blockers() == []
    assert ready.production_warnings() == []


def test_insecure_cookie_blocks_startup() -> None:
    problems = _settings(cookie_secure=False).production_blockers()

    assert len(problems) == 1
    assert "COOKIE_SECURE" in problems[0]


def test_wildcard_cors_blocks_startup() -> None:
    problems = _settings(cors_origins="*").production_blockers()

    assert any("CORS_ORIGINS" in item and "*" in item for item in problems)


def test_empty_cors_blocks_startup() -> None:
    problems = _settings(cors_origins="  ").production_blockers()

    assert any("CORS_ORIGINS" in item for item in problems)


def test_prod_env_alias_is_accepted() -> None:
    """`APP_ENV=prod` 与 `APP_ENV=PRODUCTION` 都按生产档处理（大小写与简写不设坑）。"""
    assert _settings(app_env="PROD").is_production is True
    assert _settings(app_env=" Production ").is_production is True


def test_localhost_origin_only_warns() -> None:
    """本机来源不算「不安全」，但公网部署确实是配错了 → 告警不阻断。"""
    settings = _settings(cors_origins="https://escape.example.com,http://127.0.0.1:5173")

    assert settings.production_blockers() == []
    assert any("CORS_ORIGINS" in item and "本机" in item for item in settings.production_warnings())


def test_disabled_protections_warn_but_do_not_block() -> None:
    settings = _settings(rate_limit_enabled=False, breaker_enabled=False, secret_key="")

    assert settings.production_blockers() == []
    warnings = " ".join(settings.production_warnings())
    assert "RATE_LIMIT_ENABLED" in warnings
    assert "BREAKER_ENABLED" in warnings
    assert "SECRET_KEY" in warnings


def test_missing_ai_warns_with_reason() -> None:
    """AI 未配置不拦启动：容器要能起来、/health 如实报未就绪（与 r9 口径一致）。"""
    settings = _settings(ai_provider="", ai_deepseek_api_key="", ai_api_key="")

    assert settings.production_blockers() == []
    assert any("AI 未就绪" in item for item in settings.production_warnings())


# --- 生产档不暴露 API 文档 ---------------------------------------------------


def test_production_hides_api_docs(monkeypatch: object) -> None:
    """公网不挂 /docs、/redoc、/openapi.json：少一份可被扫描的接口清单。"""
    from fastapi.testclient import TestClient

    from app import main as main_module

    monkeypatch.setattr(main_module, "get_settings", lambda: _settings())  # type: ignore[attr-defined]
    client = TestClient(main_module.create_app())

    assert client.get("/openapi.json").status_code == 404
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404


def test_development_keeps_api_docs(monkeypatch: object) -> None:
    """开发档照旧有 /openapi.json：本地联调与前端类型对照都依赖它。"""
    from fastapi.testclient import TestClient

    from app import main as main_module

    monkeypatch.setattr(  # type: ignore[attr-defined]
        main_module, "get_settings", lambda: _settings(app_env="development")
    )
    client = TestClient(main_module.create_app())

    assert client.get("/openapi.json").status_code == 200
