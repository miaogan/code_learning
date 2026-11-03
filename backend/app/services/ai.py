"""OpenAI 兼容模型调用（ARCHITECTURE §3.6）。

单一入口：超时 / 重试一次 / JSON 结构校验 / 中文错误。密钥只在这里出现，且永不回传前端。

r9 起口径收敛：构造时快照 `Settings.resolve_ai()` 得到的 `AiRuntime`，请求体 / 鉴权头 / 超时 /
重试次数**全部取自该快照**，本模块不再读任何裸配置字段（`config.py` 是开关的唯一出处）。
"""

import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ..config import AiRuntime, Settings, get_settings
from ..errors import AI_SCHEMA_INVALID, AI_UNAVAILABLE, AppError

ModelT = TypeVar("ModelT", bound=BaseModel)

JSON_RETRY_HINT = "上一次输出不是合法 JSON。请只输出一个 JSON 对象，不要代码围栏，不要解释。"

#: `json_mode` → 请求体 `response_format` 投影。键集必须与 `config.JSON_MODES` 相等（静态门禁互锁）。
#: `none` 的语义是**整键不发**，而不是发 `{"type":"text"}`（LM Studio 实测只接受后者以外的形态）。
_RESPONSE_FORMAT_BY_MODE: dict[str, dict[str, Any] | None] = {
    "json_object": {"type": "json_object"},
    "none": None,
}

#: `ready=False` 且 `reason` 缺省时的兜底文案（配置错一律 503 + 中文说明，绝不 500）。
_UNCONFIGURED_REASON = "AI 服务尚未配置，请检查 backend/.env 后重启服务"


def _response_format(mode: str) -> dict[str, Any] | None:
    """查投影表。闭集外的值不会到这里：`resolve_ai` 已回落缺省并置 `ready=False`。"""
    return _RESPONSE_FORMAT_BY_MODE.get(mode)


class AIClient:
    def __init__(self, settings: Settings | None = None, *, runtime: AiRuntime | None = None) -> None:
        #: 构造即快照：一次请求内 模型 / 超时 / JSON 模式 / 重试口径一致，不在 `_chat` 里现读配置。
        #: r23：显式 `runtime`（用户自己的 Key）优先，否则回落到服务端配置解析。
        self._runtime: AiRuntime = runtime or (settings or get_settings()).resolve_ai()

    async def complete_model(
        self,
        system: str,
        user: str,
        model_cls: type[ModelT],
        *,
        timeout_s: float | None = None,
    ) -> ModelT:
        """结构化补全。`timeout_s` 缺省走 `runtime.timeout_s`（已合并档内/全局，TECHNICAL §5）。"""
        runtime = self._runtime
        if not runtime.ready:
            # 配置错只表现成带中文说明的 503，文案由 `config.resolve_ai` 提供，此处不另拼第二份。
            raise AppError(AI_UNAVAILABLE, runtime.reason or _UNCONFIGURED_REASON, status=503)
        attempts = max(1, runtime.max_retries + 1)
        prompt = user
        last_error: Exception | None = None
        for attempt in range(attempts):
            content = await self._chat(system, prompt, timeout_s)
            payload = _extract_json_object(content)
            if payload is None:
                last_error = ValueError("模型未返回 JSON 对象")
            else:
                try:
                    return model_cls.model_validate(payload)
                except ValidationError as exc:
                    last_error = exc
            if attempt + 1 < attempts:
                prompt = f"{user}\n\n{JSON_RETRY_HINT}"
        raise AppError(
            AI_SCHEMA_INVALID,
            "AI 返回的结构不符合预期，请重试一次",
            status=502,
            retryable=True,
        ) from last_error

    async def ping(self) -> None:
        """最小连通性探测（设置页「测试连接」）：只验证端点 / Key / 模型可用。"""
        await self._chat("你是 API 连通性检测助手。", "请只回复 OK 两个字母。")

    async def _chat(self, system: str, user: str, timeout_s: float | None = None) -> str:
        runtime = self._runtime
        if not runtime.ready:
            # 双重短路：绕过 `complete_model` 的直接调用同样得到中文 503，绝不带病出网。
            raise AppError(AI_UNAVAILABLE, runtime.reason or _UNCONFIGURED_REASON, status=503)
        # 优先级在 `resolve_ai` 已合并为「档内 > 全局」，这里只剩一次「调用点显式 > 档内」比较。
        timeout = runtime.timeout_s if timeout_s is None else timeout_s
        url = f"{runtime.base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": runtime.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        response_format = _response_format(runtime.json_mode)
        if response_format is not None:
            payload["response_format"] = response_format
        headers = {"Content-Type": "application/json"}
        api_key = runtime.api_key.strip()
        if api_key:
            # 本地端点无鉴权；空 `Bearer` 会被部分实现判 401，所以 key 为空时整键不发。
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise AppError(
                AI_UNAVAILABLE, "AI 服务响应超时，请稍后重试", status=503, retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                AI_UNAVAILABLE, "AI 服务连接失败，请稍后重试", status=503, retryable=True
            ) from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise AppError(
                AI_UNAVAILABLE, "AI 服务暂时不可用，请稍后重试", status=503, retryable=True
            )
        if response.status_code >= 400:
            message = (
                "AI 调用被拒绝，请检查你在设置页填写的 API Key 与额度"
                if runtime.provider == "user"
                else "AI 调用被拒绝，请检查服务端账号与额度"
            )
            raise AppError(AI_UNAVAILABLE, message, status=502, retryable=False)
        try:
            return str(response.json()["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AppError(
                AI_UNAVAILABLE, "AI 返回内容无法解析", status=502, retryable=True
            ) from exc


def _extract_json_object(text: str) -> object | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(
            line for line in cleaned.splitlines() if not line.strip().startswith("```")
        ).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
