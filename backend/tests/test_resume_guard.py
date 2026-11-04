"""上传守卫（AC-1）：白名单 / 空文件 / 体积上限 / 失败不写库。"""

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from app.config import get_settings

RESUME_TEXT = (
    "教育经历\n2019-2023 计算机科学与技术\n"
    "工作经历\n2023-2026 前端开发工程师\n"
    "项目经历\n组件库与性能优化\n"
    "技能\nReact TypeScript Python SQLite"
)


def test_txt_upload_returns_metadata(client: TestClient) -> None:
    response = client.post(
        "/api/resumes",
        files={"file": ("resume.txt", RESUME_TEXT.encode("utf-8"), "text/plain")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["resume_id"]
    assert body["chars"] > 0
    assert body["sections"] >= 3


def test_unsupported_type_reports_chinese_message(client: TestClient) -> None:
    response = client.post(
        "/api/resumes",
        files={"file": ("resume.md", b"# heading", "text/markdown")},
    )
    assert response.status_code == 415
    error = response.json()["error"]
    assert error["code"] == "UNSUPPORTED_TYPE"
    assert "仅支持" in error["message"]


def test_blank_file_never_creates_profile(client: TestClient) -> None:
    response = client.post(
        "/api/resumes",
        files={"file": ("resume.txt", b"   \n  ", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMPTY_FILE"

    latest = client.get("/api/profiles/latest")
    assert latest.status_code == 404
    assert latest.json()["error"]["code"] == "NOT_FOUND"


def test_oversize_file_is_rejected_by_parser(
    client: TestClient, monkeypatch: MonkeyPatch
) -> None:
    """体积校验单源在 services.parser：路由只按 max_upload_bytes() 截断读取。"""
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    try:
        response = client.post(
            "/api/resumes",
            files={"file": ("big.txt", b"a" * (1024 * 1024 + 1), "text/plain")},
        )
        assert response.status_code == 413
        error = response.json()["error"]
        assert error["code"] == "FILE_TOO_LARGE"
        assert "1MB" in error["message"]
    finally:
        monkeypatch.delenv("MAX_UPLOAD_MB")
        get_settings.cache_clear()
