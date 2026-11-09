"""r41 图片简历入口：端点级契约（张数 / 格式 / 体积 / 视觉未开通 / 多图合并 / 质量门槛）。

全部零网络：视觉调用一律打补丁成预置转写文本；图片字节只在内存里走一遍。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import repository
from app.core.config import get_settings
from app.services.ai.ai import AIClient

#: 三个最小合法文件头（只满足内容嗅探，不需要真实可解码图像）。
JPEG_BYTES = b"\xff\xd8\xff" + b"\x00" * 24
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
GIF_BYTES = b"GIF89a" + b"\x00" * 24
WEBP_BYTES = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 16

TRANSCRIPT_PAGE_1 = (
    "教育经历\n2019-2023 计算机科学与技术 本科\n"
    "工作经历\n2023-2026 前端开发工程师，负责组件库与构建提速\n"
    "个人简介\n三年半前端经验，擅长工程化与性能优化\n"
)
TRANSCRIPT_PAGE_2 = (
    "项目经历\n数据看板项目：主导表格虚拟滚动与缓存策略\n"
    "技能\nReact TypeScript Python SQLite\n"
)


def _enable_vision(monkeypatch: pytest.MonkeyPatch) -> None:
    """主档 + 视觉档同时就绪：视觉端点继承同一套 base_url / key，只换模型名。"""
    monkeypatch.setenv("AI_VISION_MODEL", "deepseek-flash")
    monkeypatch.setenv("AI_API_KEY", "test-key-not-a-real-secret")
    get_settings.cache_clear()


def _patch_vision(
    monkeypatch: pytest.MonkeyPatch, pages: list[str]
) -> list[dict[str, Any]]:
    """把 `complete_vision` 打成逐页返回预置文本；返回调用记录供断言。"""
    calls: list[dict[str, Any]] = []

    async def fake_complete_vision(
        self: AIClient,
        system: str,
        user: str,
        image_data_urls: list[str],
        *,
        timeout_s: float | None = None,
        retry_unavailable: bool = False,
    ) -> str:
        calls.append({"system": system, "user": user, "urls": image_data_urls})
        return pages[len(calls) - 1]

    monkeypatch.setattr(AIClient, "complete_vision", fake_complete_vision)
    return calls


def _assert_error(body: dict[str, Any], code: str, assert_chinese: Callable[[str], None]) -> str:
    error = body["error"]
    assert error["code"] == code
    assert error["retryable"] in {True, False}
    assert_chinese(error["message"])
    return str(error["message"])


def test_images_endpoint_reports_vision_not_configured(
    client: TestClient, assert_chinese: Callable[[str], None]
) -> None:
    """视觉未配置：明确报「图片识别未开通，请改用 PDF」，不静默降级。"""
    response = client.post(
        "/api/resumes/images",
        files=[("files", ("resume.jpg", JPEG_BYTES, "image/jpeg"))],
    )
    assert response.status_code == 503
    message = _assert_error(response.json(), "AI_UNAVAILABLE", assert_chinese)
    assert "图片识别未开通" in message
    assert "PDF" in message


def test_single_image_is_stored_as_image_resume(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    assert_chinese: Callable[[str], None],
) -> None:
    _enable_vision(monkeypatch)
    calls = _patch_vision(monkeypatch, [TRANSCRIPT_PAGE_1])

    response = client.post(
        "/api/resumes/images",
        files=[("files", ("photo.jpg", JPEG_BYTES, "image/jpeg"))],
    )
    assert response.status_code == 200
    meta = response.json()
    assert meta["source_type"] == "image"
    assert meta["image_count"] == 1
    assert meta["chars"] >= 60
    assert calls[0]["urls"][0].startswith("data:image/jpeg;base64,")

    document = repository.get_document(meta["resume_id"])
    assert document is not None
    assert TRANSCRIPT_PAGE_1.strip() in document["text"]


def test_multiple_images_merge_into_one_resume(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """多图按上传顺序拼接、共用同一个 resume_id（D2）。"""
    _enable_vision(monkeypatch)
    _patch_vision(monkeypatch, [TRANSCRIPT_PAGE_1, TRANSCRIPT_PAGE_2])

    response = client.post(
        "/api/resumes/images",
        files=[
            ("files", ("front.png", PNG_BYTES, "image/png")),
            ("files", ("back.webp", WEBP_BYTES, "image/webp")),
        ],
    )
    assert response.status_code == 200
    meta = response.json()
    assert meta["resume_id"]
    assert meta["image_count"] == 2
    assert meta["source_type"] == "image"

    document = repository.get_document(meta["resume_id"])
    assert document is not None
    assert "【第 1 页】" in document["text"]
    assert "【第 2 页】" in document["text"]


def test_more_than_three_images_rejected(
    client: TestClient, assert_chinese: Callable[[str], None]
) -> None:
    response = client.post(
        "/api/resumes/images",
        files=[("files", (f"p{index}.jpg", JPEG_BYTES, "image/jpeg")) for index in range(4)],
    )
    assert response.status_code == 400
    message = _assert_error(response.json(), "VALIDATION_ERROR", assert_chinese)
    assert "3 张" in message


def test_non_image_format_rejected(
    client: TestClient, assert_chinese: Callable[[str], None]
) -> None:
    """按文件真实内容判断格式：GIF 即便改名成 .jpg 也拒绝。"""
    response = client.post(
        "/api/resumes/images",
        files=[("files", ("resume.jpg", GIF_BYTES, "image/jpeg"))],
    )
    assert response.status_code == 415
    message = _assert_error(response.json(), "UNSUPPORTED_TYPE", assert_chinese)
    assert "JPG" in message and "PNG" in message


def test_oversized_single_image_rejected(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    assert_chinese: Callable[[str], None],
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    big = b"\xff\xd8\xff" + b"\x00" * (1024 * 1024 + 8)

    response = client.post(
        "/api/resumes/images",
        files=[("files", ("big.jpg", big, "image/jpeg"))],
    )
    assert response.status_code == 413
    _assert_error(response.json(), "FILE_TOO_LARGE", assert_chinese)


def test_too_few_chars_asks_for_retake(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    assert_chinese: Callable[[str], None],
) -> None:
    """识别不足（< 60 字）：给重拍指引，不落库。"""
    _enable_vision(monkeypatch)
    _patch_vision(monkeypatch, ["看不清"])

    response = client.post(
        "/api/resumes/images",
        files=[("files", ("blur.jpg", JPEG_BYTES, "image/jpeg"))],
    )
    assert response.status_code == 400
    message = _assert_error(response.json(), "VALIDATION_ERROR", assert_chinese)
    assert "重拍" in message


def test_document_endpoint_points_images_to_image_entry(
    client: TestClient, assert_chinese: Callable[[str], None]
) -> None:
    """旧文档端点保持原契约，但把图片后缀引导到新入口（不返回含糊错误）。"""
    response = client.post(
        "/api/resumes",
        files={"file": ("resume.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert response.status_code == 415
    message = _assert_error(response.json(), "UNSUPPORTED_TYPE", assert_chinese)
    assert "拍照" in message or "相册" in message
