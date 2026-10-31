"""上传守卫（AC-1）：白名单 / 空文件 / 失败不写库。"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

RESUME_TEXT = (
    "教育经历\n2019-2023 计算机科学与技术\n"
    "工作经历\n2023-2026 前端开发工程师\n"
    "项目经历\n组件库与性能优化\n"
    "技能\nReact TypeScript Python SQLite"
)


DB_FILE = Path(__file__).resolve().parent.parent / ".test-scaffold.db"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DB_PATH", str(DB_FILE))
    get_settings.cache_clear()
    DB_FILE.unlink(missing_ok=True)
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()
    DB_FILE.unlink(missing_ok=True)


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
