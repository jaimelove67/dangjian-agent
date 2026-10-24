"""Teaching content and own progress; answers and credit mutations stay on the server."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.education import EducationEnrollment as Enrollment
from app.models.education import EducationOffering as Offering
from app.models.meeting import ContentRevision
from app.models.user import User, UserRole
from app.schemas import education as schema
from app.services.org_scope import accessible_org_units, load_org_tree

MANAGERS = {
    UserRole.SCHOOL_ADMIN,
    UserRole.DEPARTMENT_ADMIN,
    UserRole.BRANCH_SECRETARY,
    UserRole.ORGANIZER,
}


def now() -> datetime:
    return datetime.now(UTC)


class EducationService:
    def __init__(self, db: AsyncSession, user: User) -> None:
        self.db, self.user = db, user
        self._managed: set[str] | None = None
        self._visible: set[str] | None = None

    async def managed(self) -> set[str]:
        if self._managed is None:
            self._managed = (
                {str(o.id) for o in await accessible_org_units(self.db, self.user)}
                if self.user.role in MANAGERS
                else set()
            )
        return self._managed

    async def visible(self) -> set[str]:
        if self._visible is None:
            tree = await load_org_tree(self.db, str(self.user.tenant_id))
            ids, cursor = set(await self.managed()), self.user.org_unit_id
            while cursor and cursor not in ids:
                ids.add(cursor)
                cursor = tree[cursor].parent_id if cursor in tree else None
            # A manager already has its root in managed(); still include ancestor notices/courses.
            cursor, visited = self.user.org_unit_id, set()
            while cursor and cursor not in visited:
                visited.add(cursor)
                ids.add(cursor)
                cursor = tree[cursor].parent_id if cursor in tree else None
            self._visible = ids
        return self._visible

    async def offering(
        self, offering_id: str, *, lock: bool = False, manage: bool = False
    ) -> Offering:
        stmt = select(Offering).where(
            Offering.id == offering_id,
            Offering.tenant_id == self.user.tenant_id,
            Offering.is_deleted.is_(False),
        )
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None or row.org_unit_id not in await self.visible():
            raise HTTPException(404, "课程或活动不存在或不在当前组织范围")
        if manage and row.org_unit_id not in await self.managed():
            raise HTTPException(403, "无权维护该组织的课程或活动")
        if row.status != "published" and row.org_unit_id not in await self.managed():
            raise HTTPException(404, "课程或活动尚未发布")
        return row

    async def enrollment(
        self, offering: Offering, *, user_id: str | None = None, lock: bool = False
    ) -> Enrollment | None:
        stmt = select(Enrollment).where(
            Enrollment.tenant_id == self.user.tenant_id,
            Enrollment.offering_id == offering.id,
            Enrollment.user_id == (user_id or self.user.id),
        )
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    def progress_view(self, row: Enrollment | None) -> dict[str, Any] | None:
        if not row:
            return None
        return {
            "id": row.id,
            "status": row.status,
            "points": row.points,
            **{
                k: v
                for k, v in row.progress.items()
                if k
                in {
                    "watched_seconds",
                    "position_seconds",
                    "attempts",
                    "score",
                    "passed",
                    "completed_at",
                    "attended_at",
                }
            },
        }

    async def view(self, row: Offering, enrollment: Enrollment | None = None) -> dict[str, Any]:
        can_manage = row.org_unit_id in await self.managed()
        content = {**row.content}
        if "questions" in content:
            content["questions"] = [
                {k: v for k, v in q.items() if can_manage or k != "correct_index"}
                for q in content["questions"]
            ]
        result = {
            "id": row.id,
            "title": row.title,
            "kind": row.kind,
            "org_unit_id": row.org_unit_id,
            "status": row.status,
            "revision": row.revision,
            "created_by": row.created_by,
            "content": content,
            "can_manage": can_manage,
            "own": self.progress_view(enrollment),
        }
        if row.kind == "event":
            result["enrolled_count"] = await self.db.scalar(
                select(func.count())
                .select_from(Enrollment)
                .where(
                    Enrollment.offering_id == row.id,
                    Enrollment.tenant_id == self.user.tenant_id,
                    Enrollment.status != "cancelled",
                )
            )
        return result

    async def list_records(self, kind: str) -> dict[str, Any]:
        records = list(
            (
                await self.db.execute(
                    select(Offering)
                    .where(
                        Offering.tenant_id == self.user.tenant_id,
                        Offering.org_unit_id.in_(await self.visible()),
                        Offering.kind == kind,
                        Offering.is_deleted.is_(False),
                    )
                    .order_by(Offering.created_at.desc())
                    .limit(100)
                )
            ).scalars()
        )
        enrollments = list(
            (
                await self.db.execute(
                    select(Enrollment).where(
                        Enrollment.tenant_id == self.user.tenant_id,
                        Enrollment.user_id == self.user.id,
                        Enrollment.offering_id.in_([r.id for r in records]),
                    )
                )
            ).scalars()
        )
        own = {e.offering_id: e for e in enrollments}
        return {
            "items": [
                await self.view(r, own.get(r.id))
                for r in records
                if r.status == "published" or r.org_unit_id in await self.managed()
            ],
            "limit": 100,
        }

    async def revision(
        self, row: Offering, action: str, reason: str, *, initial: bool = False
    ) -> None:
        if not initial:
            row.revision += 1
        await self.db.flush()
        self.db.add(
            ContentRevision(
                tenant_id=row.tenant_id,
                resource_type="education",
                resource_id=row.id,
                revision=row.revision,
                actor_id=self.user.id,
                action=action,
                reason=reason,
                snapshot={"title": row.title, "status": row.status, "kind": row.kind},
            )
        )
        await self.db.flush()

    async def create(self, kind: str, body: schema.CourseCreate | schema.EventCreate) -> Offering:
        if body.org_unit_id not in await self.managed():
            raise HTTPException(403, "请选择有权维护的组织")
        data = body.model_dump(mode="json")
        row = Offering(
            tenant_id=self.user.tenant_id,
            kind=kind,
            org_unit_id=data.pop("org_unit_id"),
            title=data.pop("title"),
            content=data,
            created_by=self.user.id,
            revision=1,
            status="draft",
        )
        self.db.add(row)
        await self.revision(row, "create", "登记教育内容草稿", initial=True)
        return row

    async def publish(self, row: Offering, body: schema.OfferingAction) -> None:
        if row.revision != body.expected_revision or row.status != "draft":
            raise HTTPException(409, "版本已变化或内容已经发布")
        if (
            row.kind == "event"
            and datetime.fromisoformat(row.content["registration_deadline"]) <= now()
        ):
            raise HTTPException(422, "报名截止时间已过，请编制新的活动")
        row.status = "published"
        await self.revision(row, "publish", body.reason)

    async def enroll(self, row: Offering) -> Enrollment:
        if row.status != "published":
            raise HTTPException(409, "尚未发布，不能报名或开始学习")
        current = await self.enrollment(row, lock=True)
        if current and current.status != "cancelled":
            return current
        if row.kind == "event":
            if datetime.fromisoformat(row.content["registration_deadline"]) <= now():
                raise HTTPException(409, "已超过报名截止时间")
            count = await self.db.scalar(
                select(func.count())
                .select_from(Enrollment)
                .where(
                    Enrollment.offering_id == row.id,
                    Enrollment.tenant_id == self.user.tenant_id,
                    Enrollment.status != "cancelled",
                )
            )
            if (count or 0) >= row.content["capacity"]:
                raise HTTPException(409, "报名名额已满")
        if current:
            current.status = "enrolled"
        else:
            current = Enrollment(
                tenant_id=self.user.tenant_id,
                offering_id=row.id,
                user_id=self.user.id,
                status="enrolled",
                points=0,
                progress={
                    "watched_seconds": 0,
                    "position_seconds": 0,
                    "attempts": 0,
                    "last_tick": now().isoformat(),
                },
            )
            self.db.add(current)
        await self.db.flush()
        return current

    async def cancel(self, row: Offering) -> Enrollment:
        if (
            row.kind != "event"
            or datetime.fromisoformat(row.content["registration_deadline"]) <= now()
        ):
            raise HTTPException(409, "当前活动不能取消报名")
        current = await self.enrollment(row, lock=True)
        if current is None or current.status == "completed":
            raise HTTPException(409, "报名不存在或已经登记出席")
        current.status = "cancelled"
        await self.db.flush()
        return current

    def video_complete(self, offering: Offering, progress: dict[str, Any]) -> bool:
        return (
            not offering.content.get("video_url")
            or progress.get("watched_seconds", 0) >= offering.content["duration_seconds"] * 0.9
        )

    def complete(self, offering: Offering, enrollment: Enrollment) -> None:
        if self.video_complete(offering, enrollment.progress) and (
            not offering.content.get("questions") or enrollment.progress.get("passed")
        ):
            enrollment.status = "completed"
            enrollment.points = offering.content["points"]
            enrollment.progress = {
                **enrollment.progress,
                "completed_at": enrollment.progress.get("completed_at", now().isoformat()),
            }

    async def heartbeat(self, row: Offering, body: schema.Heartbeat) -> Enrollment:
        current = await self.enrollment(row, lock=True)
        if (
            not current
            or row.kind != "course"
            or row.status != "published"
            or not row.content.get("video_url")
        ):
            raise HTTPException(409, "请先开始有视频的已发布课程")
        progress = dict(current.progress)
        elapsed = max(0, (now() - datetime.fromisoformat(progress["last_tick"])).total_seconds())
        delta = body.position_seconds - progress.get("position_seconds", 0)
        if (
            body.position_seconds > row.content["duration_seconds"] + 2
            or delta > min(60, elapsed) * 1.25 + 2
        ):
            raise HTTPException(422, "播放进度增长超过实际经过时间，请正常观看后重试")
        segments = [list(pair) for pair in progress.get("watched_segments", [])]
        if delta > 0:
            end = min(body.position_seconds, row.content["duration_seconds"])
            segments.append([max(0, end - min(delta, elapsed, 60)), end])
        merged: list[list[float]] = []
        for start, end in sorted(segments):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        # Replaying one interval cannot manufacture coverage of the rest of the video.
        watched = sum(end - start for start, end in merged)
        progress.update(
            watched_seconds=min(watched, row.content["duration_seconds"]),
            watched_segments=merged,
            position_seconds=body.position_seconds,
            last_tick=now().isoformat(),
        )
        current.progress = progress
        self.complete(row, current)
        await self.db.flush()
        return current

    async def exam(self, row: Offering, body: schema.ExamSubmit) -> Enrollment:
        current = await self.enrollment(row, lock=True)
        questions = row.content.get("questions", [])
        if current is None or not questions or row.status != "published" or row.kind != "course":
            raise HTTPException(409, "请先开始包含考试的已发布课程")
        if current.status == "completed":
            return current
        if not self.video_complete(row, current.progress):
            raise HTTPException(409, "请先完成视频学习")
        if current.progress.get("attempts", 0) >= row.content["max_attempts"]:
            raise HTTPException(409, "已达到本课程考试次数上限")
        if set(body.answers) != {q["id"] for q in questions} or any(
            body.answers[q["id"]] < 0 or body.answers[q["id"]] >= len(q["options"])
            for q in questions
        ):
            raise HTTPException(422, "请按当前试题逐题作答，不得添加或遗漏题目")
        correct = sum(body.answers[q["id"]] == q["correct_index"] for q in questions)
        score = math.floor(correct * 100 / len(questions))
        current.progress = {
            **current.progress,
            "attempts": current.progress.get("attempts", 0) + 1,
            "score": score,
            "passed": score >= row.content["passing_score"],
        }
        self.complete(row, current)
        await self.db.flush()
        return current

    async def attendance(self, row: Offering, body: schema.Attendance) -> Enrollment:
        if (
            row.kind != "event"
            or row.status != "published"
            or datetime.fromisoformat(row.content["starts_at"]) > now()
        ):
            raise HTTPException(409, "只能为已开展的已发布活动登记真实出席")
        if body.user_id == self.user.id:
            raise HTTPException(403, "本人出席须由其他组织人员核验")
        enrollment = await self.enrollment(row, user_id=body.user_id, lock=True)
        if not enrollment or enrollment.status == "cancelled":
            raise HTTPException(404, "该账号没有有效报名记录")
        enrollment.status, enrollment.points = "completed", row.content["points"]
        enrollment.progress = {
            **enrollment.progress,
            "attended_at": enrollment.progress.get("attended_at", now().isoformat()),
            "attended_by": self.user.id,
            "attendance_reason": body.reason,
        }
        await self.db.flush()
        return enrollment

    async def own_credits(self) -> dict[str, Any]:
        records = list(
            (
                await self.db.execute(
                    select(Enrollment, Offering.title)
                    .join(Offering, Offering.id == Enrollment.offering_id)
                    .where(
                        Enrollment.tenant_id == self.user.tenant_id,
                        Enrollment.user_id == self.user.id,
                        Enrollment.status == "completed",
                        Offering.tenant_id == self.user.tenant_id,
                    )
                    .order_by(Enrollment.updated_at.desc())
                )
            ).all()
        )
        return {
            "total_points": sum(r.points for r, _ in records),
            "items": [
                {
                    "id": r.id,
                    "offering_id": r.offering_id,
                    "title": title,
                    "points": r.points,
                    "completed_at": r.progress.get("completed_at") or r.progress.get("attended_at"),
                }
                for r, title in records
            ],
        }
