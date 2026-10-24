"""Real education, events, server-side examinations and idempotent credit records."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import audit_operation
from app.db.session import get_db
from app.deps import get_current_user
from app.models.education import EducationEnrollment
from app.models.user import User
from app.schemas import education as schema
from app.schemas.common import APIResponse
from app.services.education_service import EducationService
from app.services.identity_service import masked_username

router = APIRouter()


async def service(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> EducationService:
    return EducationService(db, user)


async def respond(
    s: EducationService, request: Request, data: Any, action: str, resource_id: str
) -> APIResponse:
    await audit_operation(
        s.db, request, s.user, action=action, resource_type="education", resource_id=resource_id
    )
    await s.db.commit()
    return APIResponse(data=data)


@router.get("/education/offerings")
async def offerings(
    kind: Literal["course", "event"] = "course", s: EducationService = Depends(service)
) -> APIResponse:
    return APIResponse(data=await s.list_records(kind))


@router.post("/education/courses")
async def create_course(
    body: schema.CourseCreate, request: Request, s: EducationService = Depends(service)
) -> APIResponse:
    row = await s.create("course", body)
    return await respond(s, request, await s.view(row), "education_course_create", row.id)


@router.post("/education/events")
async def create_event(
    body: schema.EventCreate, request: Request, s: EducationService = Depends(service)
) -> APIResponse:
    row = await s.create("event", body)
    return await respond(s, request, await s.view(row), "education_event_create", row.id)


@router.get("/education/offerings/{offering_id}")
async def detail(offering_id: str, s: EducationService = Depends(service)) -> APIResponse:
    row = await s.offering(offering_id)
    return APIResponse(data=await s.view(row, await s.enrollment(row)))


@router.post("/education/offerings/{offering_id}/publish")
async def publish(
    offering_id: str,
    body: schema.OfferingAction,
    request: Request,
    s: EducationService = Depends(service),
) -> APIResponse:
    row = await s.offering(offering_id, lock=True, manage=True)
    await s.publish(row, body)
    return await respond(s, request, await s.view(row), "education_publish", row.id)


@router.post("/education/offerings/{offering_id}/enroll")
async def enroll(
    offering_id: str, request: Request, s: EducationService = Depends(service)
) -> APIResponse:
    row = await s.offering(offering_id, lock=True)
    own = await s.enroll(row)
    return await respond(s, request, await s.view(row, own), "education_enroll", row.id)


@router.post("/education/offerings/{offering_id}/cancel")
async def cancel(
    offering_id: str, request: Request, s: EducationService = Depends(service)
) -> APIResponse:
    row = await s.offering(offering_id, lock=True)
    own = await s.cancel(row)
    return await respond(s, request, await s.view(row, own), "education_cancel_enrollment", row.id)


@router.post("/education/offerings/{offering_id}/heartbeat")
async def heartbeat(
    offering_id: str,
    body: schema.Heartbeat,
    request: Request,
    s: EducationService = Depends(service),
) -> APIResponse:
    row = await s.offering(offering_id)
    own = await s.heartbeat(row, body)
    # Progress updates contain no transcript, answers, credentials or unrelated identities.
    await s.db.commit()
    return APIResponse(data=s.progress_view(own))


@router.post("/education/offerings/{offering_id}/exam")
async def exam(
    offering_id: str,
    body: schema.ExamSubmit,
    request: Request,
    s: EducationService = Depends(service),
) -> APIResponse:
    row = await s.offering(offering_id)
    own = await s.exam(row, body)
    return await respond(s, request, s.progress_view(own), "education_exam_submit", row.id)


@router.get("/education/offerings/{offering_id}/enrollments")
async def enrollments(offering_id: str, s: EducationService = Depends(service)) -> APIResponse:
    row = await s.offering(offering_id, manage=True)
    records = (
        await s.db.execute(
            select(EducationEnrollment, User)
            .join(User, User.id == EducationEnrollment.user_id)
            .where(
                EducationEnrollment.tenant_id == s.user.tenant_id,
                EducationEnrollment.offering_id == row.id,
                User.tenant_id == s.user.tenant_id,
            )
            .order_by(EducationEnrollment.created_at)
            .limit(10000)
        )
    ).all()
    return APIResponse(
        data={
            "items": [
                {
                    "id": r.id,
                    "user_id": r.user_id,
                    "name": u.name,
                    "username": masked_username(u.username),
                    "status": r.status,
                    "points": r.points,
                    "score": r.progress.get("score"),
                    "attempts": r.progress.get("attempts", 0),
                    "watched_seconds": r.progress.get("watched_seconds", 0),
                }
                for r, u in records
            ]
        }
    )


@router.post("/education/offerings/{offering_id}/attendance")
async def attendance(
    offering_id: str,
    body: schema.Attendance,
    request: Request,
    s: EducationService = Depends(service),
) -> APIResponse:
    row = await s.offering(offering_id, lock=True, manage=True)
    own = await s.attendance(row, body)
    return await respond(s, request, s.progress_view(own), "education_attendance_confirm", row.id)


@router.get("/education/credits")
async def credits(s: EducationService = Depends(service)) -> APIResponse:
    return APIResponse(data=await s.own_credits())
