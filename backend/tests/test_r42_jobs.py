"""r42 任务化与断连恢复：幂等受理、卡死清扫、图片识别异步链路、HEIC 兜底。

覆盖四件事：
1. 同一简历 / 同一批图片重复提交复用同一条 running 任务（不产生重复任务）；
2. 长期无进展的 running 行会被读路径惰性标记 failed（不留永远「进行中」）；
3. `POST /api/resumes/images/async` 受理 → 轮询 → completed 带 `ResumeMeta`，正文已入库；
4. HEIC 按真实字节识别，给专用中文提示（复用 `UNSUPPORTED_TYPE`，不新增错误码）。
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import repository
from app.core.config import get_settings
from app.core.db import connection
from app.core.errors import AI_UNAVAILABLE, AppError
from app.schemas import ResumeMeta
from app.services.ai.ai import AIClient

WAIT_TIMEOUT_S = 5.0

#: 最小合法 PNG 头（后端只按真实字节嗅探格式，不解析像素；视觉调用被替身截断）。
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"r42-fake-png-payload"

#: HEIC 头：`ftyp` + major brand `heic` + 兼容品牌 `mif1`（iPhone 默认格式的真实字节特征）。
HEIC_BYTES = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic"

#: 识别正文替身：≥60 字，绕过 `MIN_IMAGE_CHARS` 的质量门槛。
VISION_TEXT = (
    "教育经历\n2019-2023 计算机科学与技术 本科\n"
    "工作经历\n2023-2026 前端开发工程师，负责组件库与构建提速\n"
    "技能\nReact TypeScript Python SQLite 共 68 个字符的转写样例"
)


def _vision_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """打开视觉档：`resolve_vision()` 要求**主档就绪**，所以主档三项也要给值。

    只填配置、不真出网 —— 视觉调用由用例替换成替身（零网络）。
    """
    monkeypatch.setenv("AI_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_API_KEY", "sk-test-not-a-real-secret")
    monkeypatch.setenv("AI_VISION_MODEL", "test-vision-model")
    monkeypatch.setenv("AI_VISION_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setenv("AI_VISION_API_KEY", "sk-test-not-a-real-secret")
    get_settings.cache_clear()


def _patch_vision(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[list[str]], str],
) -> None:
    calls: list[list[str]] = []

    async def fake_complete_vision(
        self: AIClient,
        system: str,
        user: str,
        image_data_urls: list[str],
        *,
        timeout_s: float | None = None,
        retry_unavailable: bool = False,
    ) -> str:
        calls.append(image_data_urls)
        return handler(image_data_urls)

    monkeypatch.setattr(AIClient, "complete_vision", fake_complete_vision)


def _wait_resume_terminal(client: TestClient, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/resume-jobs/{job_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] in {"completed", "failed"}:
            return last
        time.sleep(0.05)
    pytest.fail(f"图片识别任务在 {WAIT_TIMEOUT_S}s 内未到终态，最后状态：{last}")


def _post_images(client: TestClient, *, path: str = "/api/resumes/images/async") -> Any:
    return client.post(
        path,
        files=[("files", ("resume.png", PNG_BYTES, "image/png"))],
    )


# --- 幂等 --------------------------------------------------------------------


def test_profile_job_reuses_running_job(client: TestClient, resume_text: str) -> None:
    """同一简历已有在途任务时，重复提交返回同一个 job_id（不新建行）。"""
    repository.insert_document(
        ResumeMeta(resume_id="res-r42", file_name="resume.txt", chars=len(resume_text), sections=3),
        resume_text,
    )
    repository.insert_profile_job("job-existing", "res-r42", "resume.txt", len(resume_text), 3)

    first = client.post("/api/resumes/res-r42/profile/async")
    assert first.status_code == 200, first.text
    assert first.json()["job_id"] == "job-existing"

    second = client.post("/api/resumes/res-r42/profile/async")
    assert second.json()["job_id"] == "job-existing"

    with connection() as conn:
        rows = conn.execute(
            "SELECT id FROM profile_jobs WHERE document_id = 'res-r42' AND status = 'running'"
        ).fetchall()
    assert [row["id"] for row in rows] == ["job-existing"]


def test_resume_job_reuses_running_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同一批图片字节已有在途识别任务时，重复提交返回同一个 job_id。"""
    _vision_ready(monkeypatch)
    content_hash = hashlib.sha256(PNG_BYTES).hexdigest()
    repository.insert_resume_job("resume-job-existing", "resume.png", 1, content_hash)

    response = _post_images(client)
    assert response.status_code == 200, response.text
    assert response.json()["job_id"] == "resume-job-existing"


# --- 清扫 --------------------------------------------------------------------


def test_stale_profile_job_is_failed_on_read(client: TestClient, resume_text: str) -> None:
    """r32 语义不变、阈值上调：旧行仍会在读路径上被收敛成 failed。"""
    repository.insert_document(
        ResumeMeta(resume_id="res-stale", file_name="resume.txt", chars=len(resume_text), sections=3),
        resume_text,
    )
    repository.insert_profile_job("job-stale", "res-stale", "resume.txt", len(resume_text), 3)
    with connection() as conn:
        conn.execute(
            "UPDATE profile_jobs SET updated_at = '2026-01-01T00:00:00+00:00' WHERE id = 'job-stale'"
        )

    job = client.get("/api/profile-jobs/job-stale").json()
    assert job["status"] == "failed"
    assert "中断" in job["error"] or "重新" in job["error"]


def test_stale_resume_job_is_failed_on_read(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, assert_chinese: Callable[[str], None]
) -> None:
    """图片识别任务按「无进展」判死：心跳停 10 分钟以上即 failed + 中文原因。"""
    _vision_ready(monkeypatch)
    content_hash = hashlib.sha256(PNG_BYTES).hexdigest()
    repository.insert_resume_job("resume-job-stale", "resume.png", 1, content_hash)
    with connection() as conn:
        conn.execute(
            "UPDATE resume_jobs SET updated_at = '2026-01-01T00:00:00+00:00' "
            "WHERE id = 'resume-job-stale'"
        )

    job = client.get("/api/resume-jobs/resume-job-stale").json()
    assert job["status"] == "failed"
    assert_chinese(job["error"])
    assert "重新上传" in job["error"]


# --- 图片异步链路 -------------------------------------------------------------


def test_image_job_completes_and_stores_resume(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _vision_ready(monkeypatch)
    _patch_vision(monkeypatch, lambda _urls: VISION_TEXT)

    started = _post_images(client)
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "running"

    job = _wait_resume_terminal(client, started.json()["job_id"])
    assert job["status"] == "completed", job
    result = job["result"]
    assert result["source_type"] == "image"
    assert result["image_count"] == 1
    assert result["chars"] >= 60
    # 正文真的入库（不是只在任务结果里回显）；chars 是归一化后的字数，不逐字相等。
    stored = repository.get_document_text(result["resume_id"])
    assert stored is not None
    assert "React TypeScript Python SQLite" in stored


def test_image_job_failure_is_visible(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    assert_chinese: Callable[[str], None],
) -> None:
    _vision_ready(monkeypatch)

    def boom(_urls: list[str]) -> str:
        raise AppError(AI_UNAVAILABLE, "图片识别服务暂时不可用，请稍后重试", status=503, retryable=True)

    _patch_vision(monkeypatch, boom)

    started = _post_images(client)
    assert started.status_code == 200, started.text
    job = _wait_resume_terminal(client, started.json()["job_id"])
    assert job["status"] == "failed"
    assert_chinese(job["error"])
    assert "图片识别" in job["error"]


# --- HEIC --------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/resumes/images", "/api/resumes/images/async"])
def test_heic_gets_dedicated_message(
    client: TestClient, path: str, assert_chinese: Callable[[str], None]
) -> None:
    """HEIC 会被真实字节识别出来，给专用中文提示（错误码仍是闭集里的 UNSUPPORTED_TYPE）。"""
    response = client.post(
        path, files=[("files", ("IMG_0001.HEIC", HEIC_BYTES, "image/heic"))]
    )
    assert response.status_code == 415, response.text
    error = response.json()["error"]
    assert error["code"] == "UNSUPPORTED_TYPE"
    assert_chinese(error["message"])
    assert "HEIC" in error["message"]
    assert "兼容性最佳" in error["message"]
