"""OpenAI 兼容模型调用（ARCHITECTURE §3.6）。

单一入口：超时 / 重试一次 / JSON 结构校验 / 中文错误。密钥只在这里出现，且永不回传前端。
"""

import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ..config import Settings, get_settings
from ..errors import AI_SCHEMA_INVALID, AI_UNAVAILABLE, AppError

ModelT = TypeVar("ModelT", bound=BaseModel)

JSON_RETRY_HINT = "上一次输出不是合法 JSON。请只输出一个 JSON 对象，不要代码围栏，不要解释。"


class AIClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def complete_model(
        self,
        system: str,
        user: str,
        model_cls: type[ModelT],
        *,
        timeout_s: float | None = None,
    ) -> ModelT:
        """结构化补全。`timeout_s` 缺省走 `settings.ai_timeout_s`（TECHNICAL §5）。"""
        settings = self._settings
        if not settings.ai_configured:
            raise AppError(
                AI_UNAVAILABLE,
                "AI 服务尚未配置（服务端缺少 AI_API_KEY），请配置 backend/.env 后重启服务",
                status=503,
            )
        attempts = max(1, settings.ai_max_retries + 1)
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

    async def _chat(self, system: str, user: str, timeout_s: float | None = None) -> str:
        settings = self._settings
        timeout = settings.ai_timeout_s if timeout_s is None else timeout_s
        url = f"{settings.ai_base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": settings.ai_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {settings.ai_api_key}",
            "Content-Type": "application/json",
        }
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
            raise AppError(
                AI_UNAVAILABLE, "AI 调用被拒绝，请检查服务端账号与额度", status=502, retryable=False
            )
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
