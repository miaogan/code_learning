"""r115：内网 / 气隙部署 —— 放行私网 AI 端点 + 零遥测守卫。

两条独立的诉求，分成两组用例：

1. **能连上内网的模型**：`AI_ALLOW_PRIVATE_ENDPOINTS=true` 时用户自带端点可以填
   `http://10.x.x.x:8000/v1` / `http://localhost:11434/v1`；但**云元数据地址与链路本地段
   永远拒绝** —— 内网机器常常就是云主机，这是 r99 SSRF 防护里最不能丢的一条。
   默认（关）时 r99 的公网口径原样保留，回归在 `test_r99_ssrf_guard.py`。

2. **不能有任何遥测**：把「没有遥测」从口头承诺变成可复跑的断言 ——
   - 扫描前端入口 / 源码 / 配置与后端源码，禁止出现统计 SDK 与遥测域名；
   - 入口 HTML 必须完全自包含（不引任何外部 `src` / `href` 资源）；
   - 后端「出网点」是一份**登记制清单**：新增任何 `httpx` 出网调用都会让这条用例变红，
     逼迫作者来解释这个新出网点是干什么的（而不是悄悄多一条数据外流通道）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any

import pytest

from app import main
from app.core.config import get_settings
from app.core.errors import AppError
from app.services.ai.user_ai import (
    normalize_ai_settings,
    test_connection as run_test_connection,
    validate_ai_base_url,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND = _REPO_ROOT / "frontend"
_BACKEND_APP = _REPO_ROOT / "backend" / "app"

#: 内网环境里合法、公网档非法的端点。含环回（模型与后端同机）、RFC1918、
#: 链路本地以外的保留段（CGNAT 在 `ipaddress` 里算 private）与 IPv6 ULA / 环回。
_INTRANET_OK_URLS = (
    "http://10.0.0.5:8000/v1",
    "http://172.16.31.7/v1",
    "http://192.168.1.20:11434/v1",
    "http://127.0.0.1:8000/v1",
    "http://localhost:1234/v1",
    "http://[::1]:8000/v1",
    "http://llm.corp.internal/v1",
)

#: 放行内网也必须拒绝的：云元数据（含两大国内云的元数据地址）。
_METADATA_URLS = (
    "http://169.254.169.254/latest/meta-data",
    "http://metadata.google.internal/v1",
    "http://100.100.100.200/v1",
    "http://[fd00:ec2::254]/v1",
)


@pytest.fixture()
def intranet_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """打开内网放行档；`get_settings` 是 `lru_cache`，改 env 必须清缓存。"""
    monkeypatch.setenv("AI_ALLOW_PRIVATE_ENDPOINTS", "true")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_switch_defaults_to_off() -> None:
    """默认关：公网部署不该因为升级就悄悄放开内网探测。"""
    assert get_settings().ai_allow_private_endpoints is False


@pytest.mark.usefixtures("intranet_env")
@pytest.mark.parametrize("url", _INTRANET_OK_URLS)
def test_intranet_mode_allows_private_endpoints(url: str) -> None:
    assert validate_ai_base_url(url) == url


@pytest.mark.usefixtures("intranet_env")
@pytest.mark.parametrize("url", _METADATA_URLS)
def test_metadata_targets_stay_blocked_in_intranet_mode(url: str) -> None:
    """放行内网 ≠ 放行元数据：这是刻意保留的硬边界，不是漏网。"""
    with pytest.raises(AppError) as exc:
        validate_ai_base_url(url)
    assert exc.value.status == 422
    assert "内网放行模式也不例外" in exc.value.message


@pytest.mark.usefixtures("intranet_env")
def test_scheme_still_validated_in_intranet_mode() -> None:
    with pytest.raises(AppError) as exc:
        validate_ai_base_url("ftp://10.0.0.5/v1")
    assert "http:// 或 https://" in exc.value.message


@pytest.mark.usefixtures("intranet_env")
def test_save_settings_accepts_private_endpoint() -> None:
    base_url, model, json_mode = normalize_ai_settings(
        base_url="http://10.0.0.5:8000/v1/", model="qwen2.5-32b", api_key="k", json_mode="none"
    )
    assert base_url == "http://10.0.0.5:8000/v1"
    assert (model, json_mode) == ("qwen2.5-32b", "none")


@pytest.mark.usefixtures("intranet_env")
def test_test_connection_reaches_private_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """「测试连接」同样吃这个开关：否则会出现「保存能过、测试照挂」的割裂。"""
    seen: dict[str, str] = {}

    class _FakeClient:
        def __init__(self, runtime: Any) -> None:
            seen["base_url"] = runtime.base_url

        async def ping(self) -> None:
            return None

    monkeypatch.setattr("app.services.ai.user_ai.AIClient", _FakeClient)
    ok, message = asyncio.run(
        run_test_connection(
            base_url="http://192.168.1.20:11434/v1",
            model="qwen",
            api_key="k",
            json_mode="none",
            stored_key="",
        )
    )
    assert (ok, message) == (True, "连接成功")
    assert seen["base_url"] == "http://192.168.1.20:11434/v1"


@pytest.mark.parametrize("raw", ("", "  ", " true ", "\ttrue\n", "True", "1", "on"))
def test_switch_tolerates_blank_and_padded_values(
    raw: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`.env` 里写空的 / 带空白的值都不许把进程打挂。

    真实踩点：运维照 `.env.example` 抄完顺手清空一行（`AI_ALLOW_PRIVATE_ENDPOINTS=`），
    或从文档复制时把 `" true "` 的空白一起带进来 —— pydantic 的 bool 解析不做 trim，
    两种都会在 `Settings()` 构造期抛 `ValidationError`，服务直接起不来。
    """
    monkeypatch.setenv("AI_ALLOW_PRIVATE_ENDPOINTS", raw)
    get_settings.cache_clear()
    try:
        value = get_settings().ai_allow_private_endpoints
    finally:
        get_settings.cache_clear()
    assert value is (raw.strip() != "")


def test_public_mode_message_says_how_to_enable() -> None:
    """默认档拒绝时必须给出下一步 —— 只报「不允许」会让内网用户无从判断是没设对还是没生效。"""
    with pytest.raises(AppError) as exc:
        validate_ai_base_url("http://10.0.0.5:8000/v1")
    assert "AI_ALLOW_PRIVATE_ENDPOINTS" in exc.value.message


@pytest.mark.usefixtures("intranet_env")
def test_startup_logs_policy_when_enabled(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="app.security"):
        main._report_ai_endpoints(get_settings())
    assert any("security.ai_private_endpoints=on" in record.getMessage() for record in caplog.records)
    # 内网放开了、雷达还在联外：必须顺手提醒（这是气隙环境最容易漏的一条）。
    assert any("RADAR_OFFLINE" in record.getMessage() for record in caplog.records)


def test_startup_logs_policy_when_disabled(caplog: pytest.LogCaptureFixture) -> None:
    """关闭态也要打印：用户设了却没生效时，这是唯一能一眼看出来的地方。"""
    with caplog.at_level(logging.INFO, logger="app.security"):
        main._report_ai_endpoints(get_settings())
    messages = [record.getMessage() for record in caplog.records]
    assert any("security.ai_private_endpoints=off" in text for text in messages)
    assert any("AI_ALLOW_PRIVATE_ENDPOINTS=true" in text for text in messages)


# --- 零遥测守卫 -----------------------------------------------------------------

#: 统计 / 崩溃上报 / 外部静态资源域名。命中即失败 —— 内网气隙环境里这些请求
#: 只会超时重试，既拖慢页面又是明确的信息外流嫌疑。
_TELEMETRY_URL_RE = re.compile(
    r"https?://[^\s\"'()<>]*("
    r"google-analytics\.com|googletagmanager\.com|doubleclick\.net|"
    r"sentry\.io|sentry-cdn\.com|posthog\.com|mixpanel\.com|amplitude\.com|"
    r"hotjar\.com|clarity\.ms|bugsnag\.com|datadoghq\.com|newrelic\.com|"
    r"umami\.is|plausible\.io|hm\.baidu\.com|cnzz\.com|"
    r"fonts\.googleapis\.com|fonts\.gstatic\.com|unpkg\.com|cdn\.jsdelivr\.net"
    r")",
    re.IGNORECASE,
)

#: 遥测 SDK 的 import 形态（Python / TS 都覆盖）。
_TELEMETRY_IMPORT_RE = re.compile(
    r"(?m)^\s*(?:import|from)\s+[\"']?"
    r"(?:sentry_sdk|posthog|mixpanel|amplitude|bugsnag|raven|@sentry/\S*)"
    r"\b"
)

#: 后端所有会**主动出网**的文件。新增出网点必须显式登记到这里 ——
#: 这条断言的作用不是抓错，而是让「多了一条数据外流通道」这件事无法悄悄发生。
_OUTBOUND_CALL_SITES = {
    # 自建 embedder 的健康探针（指向 AI_EMBED_BASE_URL，内网自建 TEI 即可）。
    "app/main.py",
    # 业务 LLM 调用（端点来自服务端配置或用户自带设置）。
    "app/services/ai/ai.py",
    # 可选远端 embedding（留空 AI_EMBED_MODEL 时走离线哈希，零出网）。
    "app/services/retrieval/embeddings.py",
    # 技术雷达采集（内网 / 气隙环境必须 RADAR_OFFLINE=true 或 RADAR_SCHEDULE=off）。
    "app/services/radar/sources.py",
}

_OUTBOUND_RE = re.compile(
    r"\bhttpx\.(?:get|post|put|patch|delete|request|stream|Client|AsyncClient)\b"
    r"|\brequests\.(?:get|post|put|patch|delete|request|Session)\b"
    r"|\burllib\.request\b"
    r"|\baiohttp\."
)


def _source_files() -> list[Path]:
    files: list[Path] = []
    for pattern in ("src/**/*.ts", "src/**/*.tsx", "src/**/*.js", "src/**/*.jsx", "src/**/*.css"):
        files.extend(sorted(_FRONTEND.glob(pattern)))
    files.extend([_FRONTEND / "index.html", _FRONTEND / "package.json", _FRONTEND / "vite.config.ts"])
    files.extend(sorted(_FRONTEND.glob("nginx*.conf")))
    files.extend(sorted(_FRONTEND.glob("security-headers.conf")))
    files.extend(sorted(_BACKEND_APP.rglob("*.py")))
    return [path for path in files if path.is_file()]


def test_no_telemetry_sdk_or_domain_in_sources() -> None:
    """源码里不许出现统计 SDK 与遥测域名（扫的是引用，不是文档里的解释文字）。"""
    offenders: list[str] = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in _TELEMETRY_URL_RE.finditer(text):
            offenders.append(f"{path.relative_to(_REPO_ROOT)}: {match.group(0)}")
        for match in _TELEMETRY_IMPORT_RE.finditer(text):
            offenders.append(f"{path.relative_to(_REPO_ROOT)}: {match.group(0).strip()}")
    assert not offenders, "发现遥测 / 统计引用（内网气隙部署不允许任何上报）：\n" + "\n".join(
        offenders
    )


def test_entry_html_is_self_contained() -> None:
    """入口 HTML 不许引任何外部资源：气隙环境里 CDN 只会白等，且属于隐性外联。"""
    html = (_FRONTEND / "index.html").read_text(encoding="utf-8")
    external = re.findall(r"(?:src|href)\s*=\s*[\"']https?://[^\"']+", html, re.IGNORECASE)
    assert not external, "index.html 引用了外部资源：" + "; ".join(external)


def test_frontend_production_dependencies_are_offline_safe() -> None:
    """生产依赖里不许有遥测包（devDependencies 不进产物，另由 eslint/vitest 兜住）。"""
    import json

    manifest = json.loads((_FRONTEND / "package.json").read_text(encoding="utf-8"))
    banned = ("sentry", "posthog", "mixpanel", "amplitude", "bugsnag", "raven", "datadog")
    hits = [
        name
        for name in (manifest.get("dependencies") or {})
        if any(token in name.lower() for token in banned)
    ]
    assert not hits, f"生产依赖出现遥测包：{hits}"


def test_outbound_call_sites_are_registered() -> None:
    """后端出网点必须是登记过的四类；新增出网调用必须更新本文件并说明用途。"""
    found = {
        str(path.relative_to(_BACKEND_APP.parent)).replace(os.sep, "/")
        for path in _BACKEND_APP.rglob("*.py")
        if _OUTBOUND_RE.search(path.read_text(encoding="utf-8", errors="ignore"))
    }
    assert found == _OUTBOUND_CALL_SITES, (
        "后端出网点与登记清单不一致（新增出网调用请说明用途并更新 _OUTBOUND_CALL_SITES）：\n"
        f"  多出：{sorted(found - _OUTBOUND_CALL_SITES)}\n"
        f"  少掉：{sorted(_OUTBOUND_CALL_SITES - found)}"
    )
