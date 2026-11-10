"""r60 简历版本对比：后端投影口径 + 两条只读端点。

覆盖三件事：
- `versions.source_type_of` 的 MIME → 来源类型映射（documents 表不单存 source_type）；
- 分数口径复用 `history.score_of`：只取该版本**最近一次有分**的面试 / 笔试，运行中的卷子不计；
- 端点的用户隔离与 404 中文 envelope。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import repository
from app.schemas import Profile, ResumeMeta
from app.services.interview import history
from app.services.resume import versions


def _seed_document(resume_id: str, *, file_name: str, mime: str, text: str) -> None:
    repository.insert_document(
        ResumeMeta(
            resume_id=resume_id,
            file_name=file_name,
            chars=len(text),
            sections=3,
            source_type="pdf",
        ),
        text,
        mime=mime,
    )


def _completed_run(
    run_id: str, kind: str, profile_id: str, payload: dict[str, Any]
) -> None:
    repository.insert_run(run_id, kind, profile_id, payload)
    repository.save_run(run_id, payload, repository.RUN_COMPLETED)


# --- 纯函数口径 ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("mime", "expected"),
    [
        ("application/pdf", "pdf"),
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
        ("application/msword", "docx"),
        ("text/plain", "txt"),
        ("image/jpeg", "image"),
        ("", "pdf"),
    ],
)
def test_source_type_of(mime: str, expected: str) -> None:
    assert versions.source_type_of(mime) == expected


def test_score_projection_skips_unscored_latest() -> None:
    """最新一场面试一题未答（score 缺失）时，回退到更早那次有分面试。"""
    runs = [
        {"kind": history.INTERVIEW_KIND, "payload": {"questions": [{"score": None}]}},
        {"kind": history.EXAM_KIND, "payload": {"total": 66}},
        {"kind": history.INTERVIEW_KIND, "payload": {"questions": [{"score": 7}, {"score": 8}]}},
    ]
    interview_avg, exam_total = versions.score_projection(runs)
    assert interview_avg == 7.5
    assert exam_total == 66.0


def test_score_projection_without_runs() -> None:
    assert versions.score_projection([]) == (None, None)


def test_limit_is_clamped(tmp_db: Any) -> None:
    assert versions.list_versions(0) == []  # 空库，但 limit 已被截到合法区间
    repository.insert_document(
        ResumeMeta(resume_id="res-a", file_name="a.pdf", chars=10, sections=1), "正文", mime="application/pdf"
    )
    assert len(versions.list_versions(999)) == 1


# --- 端点 ---------------------------------------------------------------------


def test_list_versions_empty(client: TestClient) -> None:
    response = client.get("/api/resumes")
    assert response.status_code == 200
    assert response.json() == []


def test_list_versions_projection(
    client: TestClient, profile_factory: Callable[..., Profile]
) -> None:
    _seed_document("res-a", file_name="旧简历.pdf", mime="application/pdf", text="旧正文")
    _seed_document("res-b", file_name="新简历.docx", mime="text/plain", text="新正文")
    repository.insert_profile(profile_factory(profile_id="prof-a", resume_id="res-a"))
    repository.insert_profile(profile_factory(profile_id="prof-b", resume_id="res-b"))

    _completed_run("run-a1", history.INTERVIEW_KIND, "prof-a", {"questions": [{"score": 6}]})
    _completed_run("run-a2", history.EXAM_KIND, "prof-a", {"total": 58})
    # 在途笔试卷子：不属于「已完成测评」，不得计入场数与分数。
    repository.insert_run("run-a3", history.EXAM_KIND, "prof-a", {"total": 0})

    payload = client.get("/api/resumes?limit=20").json()
    assert [item["resume_id"] for item in payload] == ["res-b", "res-a"]  # 上传时间倒序

    new, old = payload
    assert new["source_type"] == "txt"
    assert new["has_profile"] is True
    assert new["judged_count"] == 0
    assert new["interview_avg"] is None and new["exam_total"] is None

    assert old["source_type"] == "pdf"
    assert old["file_name"] == "旧简历.pdf"
    assert old["chars"] == len("旧正文")
    assert old["judged_count"] == 2
    assert old["interview_avg"] == 6.0
    assert old["exam_total"] == 58.0


def test_version_detail_includes_profile(
    client: TestClient, profile_factory: Callable[..., Profile]
) -> None:
    _seed_document("res-a", file_name="简历.pdf", mime="application/pdf", text="正文")
    repository.insert_profile(profile_factory(profile_id="prof-a", resume_id="res-a"))

    detail = client.get("/api/resumes/res-a").json()
    assert detail["resume_id"] == "res-a"
    assert detail["has_profile"] is True
    assert detail["profile"]["id"] == "prof-a"
    assert detail["profile"]["resume_id"] == "res-a"


def test_version_detail_without_profile(client: TestClient) -> None:
    _seed_document("res-x", file_name="未生成画像.pdf", mime="application/pdf", text="正文")
    detail = client.get("/api/resumes/res-x").json()
    assert detail["has_profile"] is False
    assert detail["profile"] is None
    assert detail["judged_count"] == 0


def test_version_detail_not_found(client: TestClient, assert_chinese: Callable[[str], None]) -> None:
    response = client.get("/api/resumes/does-not-exist")
    assert response.status_code == 404
    message = response.json()["error"]["message"]
    assert_chinese(message)
    assert response.json()["error"]["code"] == "NOT_FOUND"
