"""Server grading, private progress, finite seats and time-bounded video coverage."""

from datetime import UTC, datetime, timedelta

import pytest

from app.api.v1 import education
from app.models.education import EducationEnrollment, EducationOffering
from tests.integration.test_school_business_workflow import auth
from tests.integration.test_school_business_workflow import case as imported_school_case
from tests.integration.test_school_business_workflow import data
from tests.integration.test_school_business_workflow import workspace as imported_workspace

school_case = imported_school_case
workspace = imported_workspace

BASE = "/api/v1/education"


@pytest.fixture
def case(school_case):
    for table in [EducationOffering.__table__, EducationEnrollment.__table__]:
        table.create(school_case.session.get_bind(), checkfirst=True)
    school_case.client.app.include_router(education.router, prefix="/api/v1")
    return school_case


def post(case, path, body=None, actor=None):
    return case.client.post(BASE + path, json=body, headers=auth(actor or case.actor))


def course(case, video=False, **override):
    return data(
        post(
            case,
            "/courses",
            {
                "org_unit_id": "branch-a",
                "title": "合成视频与考核课程",
                "description": "合成联调，无真实学校制度",
                "video_url": "http://127.0.0.1:4178/synthetic.mp4" if video else None,
                "duration_seconds": 20 if video else 0,
                "questions": (
                    []
                    if video
                    else [
                        {
                            "id": "Q1",
                            "text": "合成题目一",
                            "options": ["选项一", "选项二"],
                            "correct_index": 0,
                            "explanation": "合成解析一：应选择选项一。",
                        },
                        {
                            "id": "Q2",
                            "text": "合成题目二",
                            "options": ["选项一", "选项二"],
                            "correct_index": 1,
                            "explanation": "合成解析二：应选择选项二。",
                        },
                    ]
                ),
                "passing_score": 75,
                "max_attempts": 2,
                "points": 5,
                **override,
            },
        )
    )


def publish(case, row):
    return data(
        post(
            case,
            f"/offerings/{row['id']}/publish",
            {"expected_revision": row["revision"], "reason": "已核对合成课程内容"},
        )
    )


def test_real_server_grading_attempts_and_idempotent_own_credits(case):
    student = case.actors["student"]
    row = publish(case, course(case))
    path = f"/offerings/{row['id']}"
    visible = data(case.client.get(BASE + path, headers=auth(student)))
    assert all("correct_index" not in question for question in visible["content"]["questions"])
    assert all("explanation" not in question for question in visible["content"]["questions"])
    assert post(case, path + "/exam", {"answers": {"Q1": 0, "Q2": 1}}, student).status_code == 409
    enrolled = data(post(case, path + "/enroll", actor=student))
    assert enrolled["own"]["points"] == 0
    assert post(case, path + "/exam", {"answers": {"Q1": 0}}, student).status_code == 422
    failed = data(post(case, path + "/exam", {"answers": {"Q1": 1, "Q2": 1}}, student))
    assert failed["score"] == 50 and failed["attempts"] == 1 and failed["points"] == 0
    assert failed["exam_review"][0]["selected_index"] == 1
    assert failed["exam_review"][0]["correct_index"] == 0
    assert failed["exam_review"][0]["correct"] is False
    assert failed["exam_review"][0]["explanation"] == "合成解析一：应选择选项一。"
    assert (
        data(case.client.get(BASE + path, headers=auth(student)))["own"]["exam_review"]
        == failed["exam_review"]
    )
    passed = data(post(case, path + "/exam", {"answers": {"Q1": 0, "Q2": 1}}, student))
    assert passed["status"] == "completed" and passed["score"] == 100 and passed["points"] == 5
    assert passed["exam_review"][0]["selected_index"] == 0
    assert passed["exam_review"][0]["correct"] is True
    repeated = data(post(case, path + "/exam", {"answers": {"Q1": 0, "Q2": 1}}, student))
    assert repeated == passed
    credits = data(case.client.get(BASE + "/credits", headers=auth(student)))
    assert credits["total_points"] == 5 and len(credits["items"]) == 1
    outsider_credits = data(
        case.client.get(BASE + "/credits", headers=auth(case.actors["outsider"]))
    )
    assert outsider_credits["total_points"] == 0
    assert case.client.get(BASE + path + "/enrollments", headers=auth(student)).status_code == 403
    roster = data(case.client.get(BASE + path + "/enrollments", headers=auth(case.actor)))["items"]
    assert len(roster) == 1 and roster[0]["score"] == 100


def test_attempt_limit_and_forged_credit_fields(case):
    student = case.actors["student"]
    row = publish(case, course(case))
    path = f"/offerings/{row['id']}"
    data(post(case, path + "/enroll", actor=student))
    for count in [1, 2]:
        result = data(post(case, path + "/exam", {"answers": {"Q1": 1, "Q2": 0}}, student))
        assert result["attempts"] == count and result["points"] == 0
    assert post(case, path + "/exam", {"answers": {"Q1": 0, "Q2": 1}}, student).status_code == 409
    assert (
        post(
            case,
            path + "/exam",
            {"answers": {"Q1": 0, "Q2": 1}, "points": 1000, "score": 100},
            student,
        ).status_code
        == 422
    )


@pytest.mark.parametrize("name", ["outsider", "foreign"])
def test_draft_and_cross_scope_information_are_hidden(case, name):
    row = course(case)
    path = f"/offerings/{row['id']}"
    assert case.client.get(BASE + path, headers=auth(case.actors["student"])).status_code == 404
    row = publish(case, row)
    assert case.client.get(BASE + path, headers=auth(case.actors[name])).status_code == 404
    assert not data(
        case.client.get(BASE + "/offerings?kind=course", headers=auth(case.actors[name]))
    )["items"]
    assert (
        post(case, path + "/publish", {"expected_revision": 1, "reason": "重复发布"}).status_code
        == 409
    )


def test_real_video_time_replay_and_coverage_gate(case, monkeypatch):
    clock = [datetime.now(UTC)]
    monkeypatch.setattr("app.services.education_service.now", lambda: clock[0])
    student = case.actors["student"]
    row = publish(case, course(case, video=True))
    path = f"/offerings/{row['id']}"
    data(post(case, path + "/enroll", actor=student))
    assert post(case, path + "/heartbeat", {"position_seconds": 20}, student).status_code == 422
    clock[0] += timedelta(seconds=10)
    progress = data(post(case, path + "/heartbeat", {"position_seconds": 10}, student))
    assert progress["watched_seconds"] == 10 and progress["points"] == 0
    data(post(case, path + "/heartbeat", {"position_seconds": 0}, student))
    clock[0] += timedelta(seconds=10)
    progress = data(post(case, path + "/heartbeat", {"position_seconds": 10}, student))
    assert progress["watched_seconds"] == 10 and progress["points"] == 0
    clock[0] += timedelta(seconds=10)
    progress = data(post(case, path + "/heartbeat", {"position_seconds": 20}, student))
    assert progress["watched_seconds"] == 20 and progress["points"] == 5
    credits = data(case.client.get(BASE + "/credits", headers=auth(student)))
    assert credits["total_points"] == 5 and len(credits["items"]) == 1


def test_video_completion_required_before_exam(case):
    row = publish(
        case,
        course(
            case,
            video=True,
            questions=[
                {"id": "Q1", "text": "合成单题", "options": ["一", "二"], "correct_index": 0}
            ],
        ),
    )
    student = case.actors["student"]
    path = f"/offerings/{row['id']}"
    data(post(case, path + "/enroll", actor=student))
    assert post(case, path + "/exam", {"answers": {"Q1": 0}}, student).status_code == 409


def event(case, **override):
    starts = datetime.now(UTC) + timedelta(hours=2)
    return data(
        post(
            case,
            "/events",
            {
                "org_unit_id": "school-a",
                "title": "合成主题党日",
                "description": "合成报名及出席核验",
                "starts_at": starts.isoformat(),
                "registration_deadline": (starts - timedelta(hours=1)).isoformat(),
                "location": "合成测试教室",
                "capacity": 1,
                "points": 3,
                **override,
            },
        )
    )


def test_event_seats_idempotent_registration_cancel_and_real_attendance(case, monkeypatch):
    student, outsider = case.actors["student"], case.actors["outsider"]
    row = publish(case, event(case))
    path = f"/offerings/{row['id']}"
    first = data(post(case, path + "/enroll", actor=student))
    again = data(post(case, path + "/enroll", actor=student))
    assert first["own"]["id"] == again["own"]["id"]
    assert post(case, path + "/enroll", actor=outsider).status_code == 409
    assert data(post(case, path + "/cancel", actor=student))["own"]["status"] == "cancelled"
    data(post(case, path + "/enroll", actor=outsider))
    assert (
        post(
            case,
            path + "/attendance",
            {"user_id": outsider.id, "attended": True, "reason": "尚未开始"},
        ).status_code
        == 409
    )
    clock = datetime.now(UTC) + timedelta(hours=3)
    monkeypatch.setattr("app.services.education_service.now", lambda: clock)
    assert post(case, path + "/cancel", actor=outsider).status_code == 409
    assert (
        post(
            case,
            path + "/attendance",
            {"user_id": outsider.id, "attended": True, "reason": "本人冒充组织核验"},
            outsider,
        ).status_code
        == 403
    )
    attended = data(
        post(
            case,
            path + "/attendance",
            {"user_id": outsider.id, "attended": True, "reason": "合成现场签到核对"},
        )
    )
    assert attended["status"] == "completed" and attended["points"] == 3
    data(
        post(
            case,
            path + "/attendance",
            {"user_id": outsider.id, "attended": True, "reason": "重复签到不重复积分"},
        )
    )
    credits = data(case.client.get(BASE + "/credits", headers=auth(outsider)))
    assert credits["total_points"] == 3 and len(credits["items"]) == 1


@pytest.mark.parametrize(
    "invalid",
    [
        {"questions": [], "video_url": None},
        {
            "questions": [
                {"id": "Q1", "text": "无效答案", "options": ["一", "二"], "correct_index": 2}
            ]
        },
        {"video_url": "http://user:password@127.0.0.1/video.mp4", "duration_seconds": 10},
        {"max_attempts": 0},
    ],
)
def test_invalid_teaching_content_never_publishes(case, invalid):
    response = post(
        case,
        "/courses",
        {
            "org_unit_id": "branch-a",
            "title": "非法草稿",
            "description": "测试",
            "questions": [
                {"id": "Q1", "text": "题目", "options": ["一", "二"], "correct_index": 0}
            ],
            **invalid,
        },
    )
    assert response.status_code == 422


def test_own_notes_require_enrollment_and_never_complete_or_award_points(case):
    student = case.actors["student"]
    row = publish(case, course(case))
    path = f"/offerings/{row['id']}"
    assert post(case, path + "/notes", {"note": "尚未开始"}, student).status_code == 409
    data(post(case, path + "/enroll", actor=student))
    saved = data(post(case, path + "/notes", {"note": "本人课程笔记"}, student))
    assert saved["note"] == "本人课程笔记"
    assert saved["status"] == "enrolled" and saved["points"] == 0
    assert saved.get("attempts") == 0 and saved.get("score") is None
    own = data(case.client.get(BASE + path, headers=auth(student)))["own"]
    assert own["note"] == "本人课程笔记"
    assert data(case.client.get(BASE + "/credits", headers=auth(student)))["total_points"] == 0
    assert data(post(case, path + "/notes", {"note": ""}, student))["note"] == ""


def test_notes_cannot_target_other_accounts_or_leak_through_management_roster(case):
    student, outsider = case.actors["student"], case.actors["outsider"]
    row = publish(case, course(case, org_unit_id="school-a"))
    path = f"/offerings/{row['id']}"
    data(post(case, path + "/enroll", actor=student))
    data(post(case, path + "/notes", {"note": "不向其他学员展示的个人体会"}, student))
    assert data(case.client.get(BASE + path, headers=auth(outsider)))["own"] is None
    roster = data(case.client.get(BASE + path + "/enrollments", headers=auth(case.actor)))
    assert "note" not in roster["items"][0]
    assert (
        post(case, path + "/notes", {"note": "冒名", "user_id": student.id}, outsider).status_code
        == 422
    )
    assert post(case, path + "/notes", {"note": "冒名", "points": 999}, student).status_code == 422
    assert post(case, path + "/notes", {"note": "长" * 5001}, student).status_code == 422
    assert post(case, path + "/notes", {"note": "跨校"}, case.actors["foreign"]).status_code == 404


def test_chapter_notes_preserve_other_materials_and_validate_the_material(case):
    student = case.actors["student"]
    row = publish(case, course(case, video=True))
    path = f"/offerings/{row['id']}"
    data(post(case, path + "/enroll", actor=student))
    data(post(case, path + "/notes", {"material_id": "reading", "note": "导读体会"}, student))
    saved = data(
        post(case, path + "/notes", {"material_id": "lesson", "note": "视频体会"}, student)
    )
    assert saved["material_notes"] == {"reading": "导读体会", "lesson": "视频体会"}
    assert saved["note"] == "导读体会"
    assert saved["points"] == 0 and saved["status"] == "enrolled"
    saved = data(post(case, path + "/notes", {"material_id": "reading", "note": ""}, student))
    assert saved["material_notes"] == {"reading": "", "lesson": "视频体会"}
    assert saved["note"] == ""
    assert (
        post(
            case, path + "/notes", {"material_id": "missing", "note": "无效资料"}, student
        ).status_code
        == 422
    )
    text_course = publish(case, course(case))
    text_path = f"/offerings/{text_course['id']}"
    data(post(case, text_path + "/enroll", actor=student))
    assert (
        post(
            case, text_path + "/notes", {"material_id": "lesson", "note": "不存在的视频"}, student
        ).status_code
        == 422
    )


def test_exam_reviews_are_private_and_legacy_attempts_never_invent_selected_answers(case):
    student, outsider = case.actors["student"], case.actors["outsider"]
    row = publish(case, course(case, org_unit_id="school-a"))
    path = f"/offerings/{row['id']}"
    data(post(case, path + "/enroll", actor=student))
    result = data(post(case, path + "/exam", {"answers": {"Q1": 0, "Q2": 1}}, student))
    assert len(result["exam_review"]) == 2
    other = data(case.client.get(BASE + path, headers=auth(outsider)))
    assert other["own"] is None
    assert all(
        "correct_index" not in q and "explanation" not in q for q in other["content"]["questions"]
    )
    roster = data(case.client.get(BASE + path + "/enrollments", headers=auth(case.actor)))
    assert all(
        "exam_review" not in enrollment and "material_notes" not in enrollment
        for enrollment in roster["items"]
    )
    enrollment = case.session.get(EducationEnrollment, result["id"])
    enrollment.progress = {k: v for k, v in enrollment.progress.items() if k != "exam_review"}
    case.session.commit()
    historical = data(case.client.get(BASE + path, headers=auth(student)))["own"]["exam_review"]
    assert all(q["selected_index"] is None and q["correct"] is None for q in historical)
    assert historical[0]["correct_index"] == 0
    saved = data(post(case, path + "/notes", {"note": "补充学习体会"}, student))
    assert saved["exam_review"] == historical
