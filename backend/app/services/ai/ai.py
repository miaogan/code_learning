"""OpenAI 兼容模型调用（ARCHITECTURE §3.6）。

单一入口：超时 / 重试一次 / JSON 结构校验 / 中文错误。密钥只在这里出现，且永不回传前端。

r9 起口径收敛：构造时快照 `Settings.resolve_ai()` 得到的 `AiRuntime`，请求体 / 鉴权头 / 超时 /
重试次数**全部取自该快照**，本模块不再读任何裸配置字段（`config.py` 是开关的唯一出处）。
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core import repository
from app.core.config import UNIFIED_AI_TIMEOUT_S, AiRuntime, Settings, get_settings
from app.core.errors import AI_SCHEMA_INVALID, AI_UNAVAILABLE, AppError
from app.core.observability import get_request_id
from app.services.ai import reliability

ModelT = TypeVar("ModelT", bound=BaseModel)

logger = logging.getLogger("app.ai")

JSON_RETRY_HINT = "上一次输出不是合法 JSON。请只输出一个 JSON 对象，不要代码围栏，不要解释。"

#: `json_mode` → 请求体 `response_format` 投影。键集必须与 `config.JSON_MODES` 相等（静态门禁互锁）。
#: `none` 的语义是**整键不发**，而不是发 `{"type":"text"}`（LM Studio 实测只接受后者以外的形态）。
_RESPONSE_FORMAT_BY_MODE: dict[str, dict[str, Any] | None] = {
    "json_object": {"type": "json_object"},
    "none": None,
}

#: `ready=False` 且 `reason` 缺省时的兜底文案（配置错一律 503 + 中文说明，绝不 500）。
_UNCONFIGURED_REASON = "AI 服务尚未配置，请检查 backend/.env 后重启服务"

#: 「测试连接」的探测语（2026-11-14 实测修复）。
#: DeepSeek / OpenAI 在 `response_format={"type":"json_object"}` 下要求消息里出现 "json"
#: 字样，否则直接 400：`Prompt must contain the word 'json' in some form`。
#: 旧的「请只回复 OK」不带该字样，导致 Key 完全正确也报「被拒绝」，看起来像 Key 填错了。
#: 两处都写成小写 json，让 `json_object` 与 `none` 两种模式都能一次通过。
PING_SYSTEM = "你是 API 连通性检测助手。请只输出一个 json 对象，不要其它内容。"
PING_USER = '请只回复这个 json 对象：{"ok": true}'


def _rejected_message(runtime: AiRuntime, status_code: int) -> str:
    """上游 4xx 的中文归因（单一出处；`_request` 与流式路径共用）。

    旧文案对所有 4xx 一律说「请检查 API Key 与额度」，把 400 参数错误也甩给 Key，
    用户会反复怀疑自己的 Key。这里按状态码分流，文案仍不含端点 / Key 值 / 堆栈。
    """
    owner = (
        "你在设置页填写的 API Key" if runtime.provider == "user" else "服务端配置的 API Key"
    )
    if status_code in (401, 403):
        return f"API Key 无效或没有权限，请检查{owner}"
    if status_code in (402, 429):
        return "账户额度不足或调用过于频繁，请稍后再试"
    if status_code == 400:
        return "请求参数不被模型接受，请检查模型名、API 地址与 JSON 模式"
    return f"AI 调用被拒绝，请检查{owner}与额度"


def _persist_call_log(
    runtime: AiRuntime,
    *,
    kind: str,
    elapsed_ms: int = 0,
    status_code: int | None = None,
    attempt: int = 1,
    prompt_chars: int = 0,
) -> None:
    """r51：结构化日志落库。**best-effort** —— 写库失败只记 warning，绝不改变主链路返回 / 异常。

    只传元数据（provider / model / kind / 耗时 / 状态码 / 字数 / trace id），
    Key / Prompt 正文 / 简历片段 / 图片 data URL 一律不进库。
    """
    try:
        repository.insert_ai_call_log(
            provider=runtime.provider,
            model=runtime.model,
            kind=kind,
            elapsed_ms=elapsed_ms,
            status_code=status_code,
            attempt=attempt,
            prompt_chars=prompt_chars,
            request_id=get_request_id(),
        )
    except Exception as exc:
        logger.warning("ai.log.persist_failed kind=%s error=%s", kind, type(exc).__name__)


def _response_format(mode: str) -> dict[str, Any] | None:
    """查投影表。闭集外的值不会到这里：`resolve_ai` 已回落缺省并置 `ready=False`。"""
    return _RESPONSE_FORMAT_BY_MODE.get(mode)


#: 连接池：进程内复用同一个 `httpx.AsyncClient`（keep-alive / 连接上限都在这里配一次）。
#: 按事件循环分桶——httpx 的连接池绑定创建时的 loop；uvicorn 生产环境只有一个 loop，
#: 等价于全局单例；测试里每个 `asyncio.run` 各起一个 loop，也不会互相串用已关闭的池。
_POOL: dict[asyncio.AbstractEventLoop, httpx.AsyncClient] = {}


def _shared_client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    client = _POOL.get(loop)
    if client is None:
        client = httpx.AsyncClient(
            timeout=UNIFIED_AI_TIMEOUT_S,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        _POOL[loop] = client
    return client


def reset_ai_pool() -> None:
    """清空连接池（测试隔离用；生产由 lifespan 的 `close_ai_pool` 负责释放）。"""
    _POOL.clear()


async def close_ai_pool() -> None:
    """释放全部池化连接（应用关停时调用）。"""
    clients = list(_POOL.values())
    _POOL.clear()
    for client in clients:
        try:
            await client.aclose()
        except RuntimeError:
            # 该连接池所属的 loop 已关闭（测试场景）：没有可释放的连接，忽略即可。
            continue


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
        retry_unavailable: bool = False,
    ) -> ModelT:
        """结构化补全。`timeout_s` 缺省走 `runtime.timeout_s` —— 所有调用点统一 600s
        （`config.UNIFIED_AI_TIMEOUT_S`），调用方不再各自覆写超时。

        `retry_unavailable`（r34）：仅在**后台任务 / 非同步等待**的调用点开启 —— 超时、
        5xx、429 这类 `retryable` 失败自动重来一次；前台交互调用不开启，避免用户等待翻倍。
        """
        runtime = self._runtime
        if not runtime.ready:
            # 配置错只表现成带中文说明的 503，文案由 `config.resolve_ai` 提供，此处不另拼第二份。
            logger.warning(
                "ai.skipped provider=%s reason=%s", runtime.provider, runtime.reason
            )
            _persist_call_log(runtime, kind="skipped")
            raise AppError(AI_UNAVAILABLE, runtime.reason or _UNCONFIGURED_REASON, status=503)
        attempts = max(1, runtime.max_retries + 1)
        prompt = user
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                content = await self._chat(system, prompt, timeout_s)
            except AppError as exc:
                # 不可重试的失败（鉴权 / 额度 / 参数）直接抛，重试只会重复扣配额。
                if not (retry_unavailable and exc.retryable) or attempt + 1 >= attempts:
                    raise
                last_error = exc
                logger.warning(
                    "ai.retry attempt=%s/%s code=%s",
                    attempt + 1,
                    attempts,
                    exc.code,
                )
                # r53：指数退避 + 抖动，避免上游抖动时重试风暴对齐。
                await asyncio.sleep(reliability.backoff_delay(attempt + 1))
                continue
            payload = _extract_json_object(content)
            if payload is None:
                # r53：只在原本会失败时兜底修复尾随逗号 / 单引号 / 行注释，成功路径不变。
                payload = reliability.repair_json_object(content)
            if payload is None:
                last_error = ValueError("模型未返回 JSON 对象")
            else:
                try:
                    return model_cls.model_validate(payload)
                except ValidationError as exc:
                    # 只记异常类型：Pydantic 的 details 会带出模型返回内容（简历正文片段），不进日志。
                    last_error = exc
                    logger.warning(
                        "ai.schema_invalid attempt=%s/%s error=%s",
                        attempt + 1,
                        attempts,
                        type(exc).__name__,
                    )
                    _persist_call_log(
                        runtime,
                        kind="schema_invalid",
                        attempt=attempt + 1,
                        prompt_chars=len(system) + len(prompt),
                    )
            if attempt + 1 < attempts:
                prompt = f"{user}\n\n{JSON_RETRY_HINT}"
        raise AppError(
            AI_SCHEMA_INVALID,
            "AI 返回的结构不符合预期，请重试一次",
            status=502,
            retryable=True,
        ) from last_error

    async def complete_vision(
        self,
        system: str,
        user: str,
        image_data_urls: list[str],
        *,
        timeout_s: float | None = None,
        retry_unavailable: bool = False,
    ) -> str:
        """图片理解补全：把 base64 data URL 以内容块数组发往视觉模型，返回纯文本。

        运行期口径来自构造时的 `AiRuntime`（r41 由 `Settings.resolve_vision()` 装配，
        因此 `json_mode=none`、模型名 = `AI_VISION_MODEL`）。重试口径与 `complete_model`
        一致：仅后台 / 可重复场景开 `retry_unavailable`，前台交互不翻倍等待。

        隐私：图片只在请求体内流转，日志只记**张数**，不打印 data URL。
        """
        runtime = self._runtime
        if not runtime.ready:
            logger.warning(
                "ai.skipped provider=%s model=%s reason=%s",
                runtime.provider,
                runtime.model,
                runtime.reason,
            )
            _persist_call_log(runtime, kind="skipped")
            raise AppError(AI_UNAVAILABLE, runtime.reason or _UNCONFIGURED_REASON, status=503)
        blocks: list[dict[str, Any]] = []
        if user:
            blocks.append({"type": "text", "text": user})
        blocks.extend(
            {"type": "image_url", "image_url": {"url": url}} for url in image_data_urls
        )
        attempts = max(1, runtime.max_retries + 1)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return await self._request(
                    system,
                    blocks,
                    timeout_s=timeout_s,
                    image_count=len(image_data_urls),
                )
            except AppError as exc:
                if not (retry_unavailable and exc.retryable) or attempt + 1 >= attempts:
                    raise
                last_error = exc
                logger.warning(
                    "ai.retry attempt=%s/%s code=%s images=%s",
                    attempt + 1,
                    attempts,
                    exc.code,
                    len(image_data_urls),
                )
                await asyncio.sleep(reliability.backoff_delay(attempt + 1))
        raise AppError(
            AI_UNAVAILABLE, "图片识别失败，请稍后重试", status=503, retryable=True
        ) from last_error

    async def ping(self) -> None:
        """最小连通性探测（设置页「测试连接」）：只验证端点 / Key / 模型可用。

        探测语取模块常量，必须自带 `json` 字样 —— 详见 `PING_SYSTEM` 的注释，
        否则上游的 `json_object` 模式会直接 400，把好 Key 报成坏 Key。
        """
        await self._chat(PING_SYSTEM, PING_USER)

    async def stream_chat(
        self,
        system: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        timeout_s: float | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """流式补全：逐事件产出 `text` / `tool_call`，结束时给一个 `done`。

        r83：与 `_request` 共用同一套就绪检查、鉴权头、错误映射与调用日志，
        区别只在传输方式 —— 这里是 `stream()` + 逐行 SSE，不是等整包 JSON。

        **不重试**：正文已经流给用户之后再重来一遍，会让人看到重复内容；
        流式失败一律往上抛，由路由层提示「重问一次」。

        上游不支持 SSE 时（自建端点常见）退回整包解析，把 content 与 tool_calls
        摊成同样形状的事件 —— 调用方不必区分两种上游。
        """
        runtime = self._runtime
        if not runtime.ready:
            logger.warning("ai.skipped provider=%s reason=%s", runtime.provider, runtime.reason)
            _persist_call_log(runtime, kind="skipped")
            raise AppError(AI_UNAVAILABLE, runtime.reason or _UNCONFIGURED_REASON, status=503)
        timeout = runtime.timeout_s if timeout_s is None else timeout_s
        url = f"{runtime.base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": runtime.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": 0.2,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        # 流式不带 `response_format`：这里产出的是自然语言正文，JSON mode 只对结构化补全有意义。
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        api_key = runtime.api_key.strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        prompt_chars = len(system) + sum(
            len(str(item.get("content") or "")) for item in messages
        )
        logger.info(
            "ai.stream provider=%s model=%s timeout_s=%s tools=%s prompt_chars=%s",
            runtime.provider,
            runtime.model,
            timeout,
            len(tools or []),
            prompt_chars,
        )
        started = time.perf_counter()
        first_at: float | None = None
        pending: dict[int, dict[str, Any]] = {}
        finish_reason = "stop"
        try:
            async with _shared_client().stream(
                "POST", url, headers=headers, json=payload, timeout=timeout
            ) as response:
                if response.status_code >= 400:
                    # 错误响应可能带正文（上游回显原因），读完即弃：状态码足够定位，正文含隐私不进日志。
                    await response.aread()
                    _raise_for_status(runtime, response.status_code, started, prompt_chars)
                if _is_event_stream(response):
                    async for chunk in _iter_sse_json(response):
                        choices = chunk.get("choices") or []
                        for choice in choices:
                            delta = choice.get("delta") or {}
                            content = delta.get("content")
                            if content:
                                if first_at is None:
                                    first_at = time.perf_counter()
                                yield {"kind": "text", "text": str(content)}
                            for call in delta.get("tool_calls") or []:
                                _absorb_tool_delta(pending, call)
                            if choice.get("finish_reason"):
                                finish_reason = str(choice["finish_reason"])
                else:
                    # 非 SSE：上游忽略了 stream=True，整包返回。行为对齐，不让调用方感知差异。
                    body = await response.aread()
                    message = _message_of(body, runtime, response.status_code, started, prompt_chars)
                    text = message.get("content")
                    if text:
                        if first_at is None:
                            first_at = time.perf_counter()
                        yield {"kind": "text", "text": str(text)}
                    for index, call in enumerate(message.get("tool_calls") or []):
                        _absorb_tool_delta(pending, {**call, "index": index})
        except httpx.TimeoutException as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.warning(
                "ai.stream.failed provider=%s model=%s kind=timeout elapsed_ms=%s",
                runtime.provider,
                runtime.model,
                elapsed_ms,
            )
            _persist_call_log(runtime, kind="timeout", elapsed_ms=elapsed_ms)
            raise AppError(
                AI_UNAVAILABLE, "AI 服务响应超时，请稍后重试", status=503, retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.warning(
                "ai.stream.failed provider=%s model=%s kind=connect error=%s",
                runtime.provider,
                runtime.model,
                type(exc).__name__,
            )
            _persist_call_log(runtime, kind="connect", elapsed_ms=elapsed_ms)
            raise AppError(
                AI_UNAVAILABLE, "AI 服务连接失败，请稍后重试", status=503, retryable=True
            ) from exc
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "ai.stream.done provider=%s model=%s elapsed_ms=%s first_ms=%s tool_calls=%s",
            runtime.provider,
            runtime.model,
            elapsed_ms,
            int((first_at - started) * 1000) if first_at else -1,
            len(pending),
        )
        _persist_call_log(
            runtime, kind="success", elapsed_ms=elapsed_ms, prompt_chars=prompt_chars
        )
        for index in sorted(pending):
            call = pending[index]
            if not call.get("name"):
                continue
            yield {
                "kind": "tool_call",
                "index": index,
                "id": call.get("id") or f"call_{index}",
                "name": call["name"],
                "arguments": call.get("arguments") or "{}",
            }
        yield {"kind": "done", "finish_reason": finish_reason}

    async def _chat(self, system: str, user: str, timeout_s: float | None = None) -> str:
        return await self._request(system, user, timeout_s=timeout_s)

    async def _request(
        self,
        system: str,
        user: str | list[dict[str, Any]],
        *,
        timeout_s: float | None = None,
        image_count: int = 0,
    ) -> str:
        runtime = self._runtime
        if not runtime.ready:
            # 双重短路：绕过 `complete_model` 的直接调用同样得到中文 503，绝不带病出网。
            logger.warning(
                "ai.skipped provider=%s reason=%s", runtime.provider, runtime.reason
            )
            _persist_call_log(runtime, kind="skipped")
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
        # 日志只记元数据：不记 Key、请求头、Prompt、图片 data URL 与简历正文（隐私边界与错误文案一致）。
        prompt_chars = len(system) + (
            len(user)
            if isinstance(user, str)
            else sum(len(str(block.get("text", ""))) for block in user)
        )
        logger.info(
            "ai.request provider=%s model=%s timeout_s=%s json_mode=%s prompt_chars=%s images=%s",
            runtime.provider,
            runtime.model,
            timeout,
            runtime.json_mode,
            prompt_chars,
            image_count,
        )
        started = time.perf_counter()
        try:
            # 池化出网：连接复用由模块级 `_shared_client()` 统一管理，不再每次调用新建客户端。
            response = await _shared_client().post(
                url, headers=headers, json=payload, timeout=timeout
            )
        except httpx.TimeoutException as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.warning(
                "ai.failed provider=%s model=%s kind=timeout elapsed_ms=%s timeout_s=%s",
                runtime.provider,
                runtime.model,
                elapsed_ms,
                timeout,
            )
            _persist_call_log(runtime, kind="timeout", elapsed_ms=elapsed_ms)
            raise AppError(
                AI_UNAVAILABLE, "AI 服务响应超时，请稍后重试", status=503, retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.warning(
                "ai.failed provider=%s model=%s kind=connect elapsed_ms=%s error=%s",
                runtime.provider,
                runtime.model,
                elapsed_ms,
                type(exc).__name__,
            )
            _persist_call_log(runtime, kind="connect", elapsed_ms=elapsed_ms)
            raise AppError(
                AI_UNAVAILABLE, "AI 服务连接失败，请稍后重试", status=503, retryable=True
            ) from exc
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code == 429 or response.status_code >= 500:
            logger.warning(
                "ai.failed provider=%s model=%s kind=upstream status=%s elapsed_ms=%s",
                runtime.provider,
                runtime.model,
                response.status_code,
                elapsed_ms,
            )
            _persist_call_log(
                runtime,
                kind="upstream",
                elapsed_ms=elapsed_ms,
                status_code=response.status_code,
                prompt_chars=prompt_chars,
            )
            raise AppError(
                AI_UNAVAILABLE, "AI 服务暂时不可用，请稍后重试", status=503, retryable=True
            )
        if response.status_code >= 400:
            # 拒绝原因（鉴权 / 额度 / 参数）只在日志里带状态码，响应体可能回显细节，不落日志。
            logger.warning(
                "ai.failed provider=%s model=%s kind=rejected status=%s elapsed_ms=%s",
                runtime.provider,
                runtime.model,
                response.status_code,
                elapsed_ms,
            )
            _persist_call_log(
                runtime,
                kind="rejected",
                elapsed_ms=elapsed_ms,
                status_code=response.status_code,
                prompt_chars=prompt_chars,
            )
            raise AppError(
                AI_UNAVAILABLE,
                _rejected_message(runtime, response.status_code),
                status=502,
                retryable=False,
            )
        logger.info(
            "ai.response provider=%s model=%s status=%s elapsed_ms=%s",
            runtime.provider,
            runtime.model,
            response.status_code,
            elapsed_ms,
        )
        _persist_call_log(
            runtime,
            kind="success",
            elapsed_ms=elapsed_ms,
            status_code=response.status_code,
            prompt_chars=prompt_chars,
        )
        try:
            return str(response.json()["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            logger.warning(
                "ai.failed provider=%s model=%s kind=malformed_response status=%s elapsed_ms=%s",
                runtime.provider,
                runtime.model,
                response.status_code,
                elapsed_ms,
            )
            _persist_call_log(
                runtime,
                kind="malformed",
                elapsed_ms=elapsed_ms,
                status_code=response.status_code,
                prompt_chars=prompt_chars,
            )
            raise AppError(
                AI_UNAVAILABLE, "AI 返回内容无法解析", status=502, retryable=True
            ) from exc


def _is_event_stream(response: httpx.Response) -> bool:
    """上游是否真按 SSE 回了。自建端点常忽略 `stream: true`，要靠这个分支兜住。"""
    return "text/event-stream" in response.headers.get("content-type", "")


async def _iter_sse_json(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    """逐行读 SSE，只挑 `data:` 行解析成 JSON；空行、注释行、非 JSON 行一律跳过。

    宽容解析是必需的：部分实现在心搏（keep-alive）里塞注释、在末尾补空 `data:`。
    这些都不该让整轮回答失败。
    """
    async for line in response.aiter_lines():
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if not raw:
            continue
        if raw == "[DONE]":
            return
        try:
            payload = json.loads(raw)
        except ValueError:
            continue
        if isinstance(payload, dict):
            yield payload


def _absorb_tool_delta(pending: dict[int, dict[str, Any]], call: dict[str, Any]) -> None:
    """把流式分片的 tool_calls 按 `index` 拼回完整调用。

    `id` 与 `name` 只在首片出现，后续片只有 `arguments` 增量；
    覆盖而非追加（同一字段重复下发时追加会把函数名拼成两遍）。
    """
    index = int(call.get("index") or 0)
    slot = pending.setdefault(index, {"id": "", "name": "", "arguments": ""})
    call_id = call.get("id")
    if call_id:
        slot["id"] = str(call_id)
    function = call.get("function") or {}
    name = function.get("name")
    if name:
        slot["name"] = str(name)
    arguments = function.get("arguments")
    if arguments:
        slot["arguments"] += str(arguments)


def _raise_for_status(
    runtime: AiRuntime,
    status_code: int,
    started: float,
    prompt_chars: int,
) -> None:
    """流式路径的状态码错误映射：逐条对齐 `_request`，保证两种出网方式文案一致。"""
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if status_code == 429 or status_code >= 500:
        logger.warning(
            "ai.stream.failed provider=%s model=%s kind=upstream status=%s elapsed_ms=%s",
            runtime.provider,
            runtime.model,
            status_code,
            elapsed_ms,
        )
        _persist_call_log(
            runtime,
            kind="upstream",
            elapsed_ms=elapsed_ms,
            status_code=status_code,
            prompt_chars=prompt_chars,
        )
        raise AppError(AI_UNAVAILABLE, "AI 服务暂时不可用，请稍后重试", status=503, retryable=True)
    logger.warning(
        "ai.stream.failed provider=%s model=%s kind=rejected status=%s elapsed_ms=%s",
        runtime.provider,
        runtime.model,
        status_code,
        elapsed_ms,
    )
    _persist_call_log(
        runtime,
        kind="rejected",
        elapsed_ms=elapsed_ms,
        status_code=status_code,
        prompt_chars=prompt_chars,
    )
    raise AppError(
        AI_UNAVAILABLE,
        _rejected_message(runtime, status_code),
        status=502,
        retryable=False,
    )


def _message_of(
    body: bytes,
    runtime: AiRuntime,
    status_code: int,
    started: float,
    prompt_chars: int,
) -> dict[str, Any]:
    """非 SSE 回退路径：从整包里取 `choices[0].message`。"""
    try:
        payload = json.loads(body)
        message = payload["choices"][0]["message"]
        if not isinstance(message, dict):
            raise TypeError("message 不是对象")
        return message
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.warning(
            "ai.stream.failed provider=%s model=%s kind=malformed status=%s elapsed_ms=%s",
            runtime.provider,
            runtime.model,
            status_code,
            elapsed_ms,
        )
        _persist_call_log(
            runtime,
            kind="malformed",
            elapsed_ms=elapsed_ms,
            status_code=status_code,
            prompt_chars=prompt_chars,
        )
        raise AppError(AI_UNAVAILABLE, "AI 返回内容无法解析", status=502, retryable=True) from exc


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
