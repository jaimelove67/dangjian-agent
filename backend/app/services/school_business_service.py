"""Persistent school operations with version locks, organization scope and separate archiving."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import bypass_tenant_filter
from app.models.knowledge import KnowledgeDoc
from app.models.meeting import ContentRevision
from app.models.member import MemberMaterial
from app.models.org import OrgUnit
from app.models.school_business import SchoolBusinessRecord as Record
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.rag.retrieval.access import apply_knowledge_access, knowledge_filters
from app.schemas import school_business as schema
from app.services.archive_service import require_archive_policy
from app.services.identity_service import IdentityService, is_platform_admin
from app.services.org_scope import accessible_org_units, load_org_tree


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def view(row: Record) -> dict[str, Any]:
    data = row.dict()
    data.pop("is_deleted", None)
    due = row.body.get("due_date")
    data["overdue"] = bool(
        due and due < date.today().isoformat() and row.status not in {"approved", "archived"}
    )
    return data


class SchoolBusinessService:
    def __init__(self, db: AsyncSession, user: User) -> None:
        self.db, self.user = db, user
        self._org_ids: set[str] | None = None
        self._tree: dict[str, OrgUnit] | None = None

    def school(self) -> None:
        if self.user.role != UserRole.SCHOOL_ADMIN:
            raise HTTPException(403, "仅学校管理员可以发布、布置任务或维护学校参数")

    async def org_ids(self) -> set[str]:
        if self._org_ids is None:
            self._org_ids = {str(o.id) for o in await accessible_org_units(self.db, self.user)}
        return self._org_ids

    async def readable(self, row: Record) -> bool:
        if row.tenant_id != self.user.tenant_id:
            if row.kind != "permission" or not await is_platform_admin(self.db, self.user):
                return False
            await IdentityService(self.db, self.user).tenant(str(row.tenant_id))
            return True
        if row.kind == "permission":
            return self.user.role == UserRole.SCHOOL_ADMIN or await is_platform_admin(
                self.db, self.user
            )
        if row.kind == "notice":
            if row.status != "published" and self.user.role != UserRole.SCHOOL_ADMIN:
                return False
            # Notices addressed to an ancestor are visible to members of that subtree.
            if self._tree is None:
                self._tree = await load_org_tree(self.db, str(self.user.tenant_id))
            tree = self._tree
            cursor, visited = self.user.org_unit_id, set()
            while cursor and cursor not in visited:
                if cursor == row.org_unit_id:
                    return True
                visited.add(cursor)
                cursor = tree[cursor].parent_id if cursor in tree else None
        return (
            row.org_unit_id in await self.org_ids() or row.body.get("assignee_id") == self.user.id
        )

    async def record(self, record_id: str, *, lock: bool = False) -> Record:
        with bypass_tenant_filter():
            stmt = select(Record).where(Record.id == record_id, Record.is_deleted.is_(False))
            if lock:
                stmt = stmt.with_for_update().execution_options(populate_existing=True)
            row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None or not await self.readable(row):
            raise HTTPException(404, "业务记录不存在或不在授权范围")
        return row

    async def list_records(self, kind: str, tenant_id: str | None = None) -> dict[str, Any]:
        target = str(self.user.tenant_id)
        if tenant_id and tenant_id != target:
            if kind != "permission" or not await is_platform_admin(self.db, self.user):
                raise HTTPException(403, "不能查询其他租户的业务")
            target = str((await IdentityService(self.db, self.user).tenant(tenant_id)).id)
        with bypass_tenant_filter():
            records = list(
                (
                    await self.db.execute(
                        select(Record)
                        .where(
                            Record.tenant_id == target,
                            Record.kind == kind,
                            Record.is_deleted.is_(False),
                        )
                        .order_by(Record.created_at.desc())
                        .limit(500)
                    )
                ).scalars()
            )
        result = []
        for row in records:
            if await self.readable(row):
                if (
                    kind == "notice"
                    and row.body.get("expires_on")
                    and row.body["expires_on"] < date.today().isoformat()
                    and self.user.role != UserRole.SCHOOL_ADMIN
                ):
                    continue
                result.append(view(row))
        if kind == "task":
            _, rules = await self.rules()
            upcoming_date = (date.today() + timedelta(days=rules["reminder_days"])).isoformat()
            review_cutoff = now() - timedelta(days=rules["review_days"])
            by_id = {r.id: r for r in records}
            for item in result:
                due = item["body"].get("due_date")
                item["upcoming"] = bool(
                    due
                    and date.today().isoformat() <= due <= upcoming_date
                    and item["status"] not in {"approved", "archived"}
                )
                item["review_overdue"] = (
                    item["status"] == "pending" and by_id[item["id"]].updated_at < review_cutoff
                )
        return {"items": result, "limit": 500}

    async def append(self, row: Record, action: str, reason: str, *, initial: bool = False) -> None:
        if not initial:
            row.revision += 1
        await self.db.flush()
        self.db.add(
            ContentRevision(
                tenant_id=row.tenant_id,
                resource_type="school_business",
                resource_id=row.id,
                revision=row.revision,
                action=action,
                actor_id=self.user.id,
                reason=reason,
                snapshot=json.loads(json.dumps(view(row), default=str)),
            )
        )
        await self.db.flush()

    async def create(
        self, kind: str, body: schema.NoticeCreate | schema.TaskCreate | schema.PermissionCreate
    ) -> Record:
        self.school()
        if body.org_unit_id not in await self.org_ids():
            raise HTTPException(403, "组织不在本校管理范围")
        values = body.model_dump(mode="json")
        if isinstance(body, schema.TaskCreate):
            _, rules = await self.rules()
            values["rules_snapshot"] = {
                k: rules[k] for k in ("revision", "development_materials", "archive_requirements")
            }
            assignee = (
                await self.db.execute(
                    select(User).where(
                        User.id == body.assignee_id,
                        User.tenant_id == self.user.tenant_id,
                        User.is_active.is_(True),
                        User.is_deleted.is_(False),
                    )
                )
            ).scalar_one_or_none()
            if assignee is None or assignee.org_unit_id != body.org_unit_id:
                raise HTTPException(422, "请选择任务组织内的有效责任账号")
        if isinstance(body, schema.PermissionCreate):
            if body.role == UserRole.SYSTEM_ADMIN:
                raise HTTPException(403, "学校业务申请不能授予平台权限")
            target = (
                await self.db.execute(
                    select(User).where(
                        User.id == body.user_id,
                        User.tenant_id == self.user.tenant_id,
                        User.is_deleted.is_(False),
                        User.is_active.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if target is None:
                raise HTTPException(404, "本校目标账号不存在")
            values.update(
                previous_role=target.role.value,
                previous_org_unit_id=target.org_unit_id,
                title=f"{target.name} · 业务角色申请",
            )
        row = Record(
            tenant_id=self.user.tenant_id,
            kind=kind,
            org_unit_id=body.org_unit_id,
            title=values.pop("title", "业务角色及组织范围申请"),
            body=values,
            created_by=self.user.id,
            status="pending" if kind == "permission" else "draft",
            revision=1,
            submitted_by=self.user.id if kind == "permission" else None,
        )
        self.db.add(row)
        await self.append(row, "create", getattr(body, "reason", "登记学校业务"), initial=True)
        return row

    def revision(self, row: Record, expected: int) -> None:
        if row.revision != expected:
            raise HTTPException(409, "业务版本已变化，请刷新后办理")
        if row.archived_at:
            raise HTTPException(409, "已归档业务不能修改")

    async def publish(self, row: Record, body: schema.Action) -> None:
        self.school()
        self.revision(row, body.expected_revision)
        if row.kind not in {"notice", "task"} or row.status != "draft":
            raise HTTPException(409, "当前记录不能发布")
        row.status = "published" if row.kind == "notice" else "assigned"
        row.submitted_by = self.user.id
        await self.append(row, "publish", body.reason)

    async def documents(self, doc_ids: list[str]) -> list[dict[str, Any]]:
        if not doc_ids:
            return []
        filters = knowledge_filters(self.user, include_unpublished=False)
        statement = apply_knowledge_access(select(KnowledgeDoc), filters, chunks=False).where(
            KnowledgeDoc.doc_id.in_(doc_ids)
        )
        with bypass_tenant_filter():
            docs = list((await self.db.execute(statement)).scalars())
        if len(docs) != len(set(doc_ids)):
            raise HTTPException(403, "部分佐证文件不可访问或未发布")
        return [
            {
                "doc_id": d.doc_id,
                "title": d.title,
                "revision": (d.doc_metadata or {}).get("content_revision", 1),
            }
            for d in docs
        ]

    async def complete(self, row: Record, body: schema.Complete) -> None:
        self.revision(row, body.expected_revision)
        if row.kind != "task" or row.status not in {"assigned", "rejected"}:
            raise HTTPException(409, "任务当前不能提交")
        if row.body.get("assignee_id") != self.user.id:
            raise HTTPException(403, "仅指定责任人可以提交任务完成记录")
        evidence = await self.documents(body.doc_ids)
        materials = (
            list(
                (
                    await self.db.execute(
                        select(MemberMaterial).where(
                            MemberMaterial.id.in_(body.material_ids),
                            MemberMaterial.tenant_id == self.user.tenant_id,
                            MemberMaterial.user_id == self.user.id,
                            MemberMaterial.is_deleted.is_(False),
                            MemberMaterial.content_sha256.isnot(None),
                        )
                    )
                ).scalars()
            )
            if body.material_ids
            else []
        )
        if len(materials) != len(set(body.material_ids)):
            raise HTTPException(403, "部分本人原件不存在或不属于当前账号")
        if row.body.get("evidence_required") and not evidence and not materials:
            raise HTTPException(422, "本任务要求提交真实文件佐证")
        row.body = {
            **row.body,
            "report": body.report,
            "evidence": evidence,
            "materials": [
                {
                    "id": m.id,
                    "title": m.title,
                    "sha256": m.content_sha256,
                    "profile_id": m.profile_id,
                    "file_version": m.file_version,
                }
                for m in materials
            ],
        }
        row.status, row.submitted_by = "pending", self.user.id
        row.review_comment, row.reviewed_by, row.reviewed_at = None, None, None
        await self.append(row, "submit", body.reason)

    async def review(self, row: Record, body: schema.Review) -> None:
        self.revision(row, body.expected_revision)
        if row.status != "pending" or row.kind not in {"task", "permission"}:
            raise HTTPException(409, "当前记录不在待审核状态")
        if row.submitted_by == self.user.id:
            raise HTTPException(403, "不能审核本人提交的版本")
        if row.kind == "permission":
            if not await is_platform_admin(self.db, self.user):
                raise HTTPException(403, "业务角色申请须由平台管理员审核")
            if body.decision == "approved":
                # Reuse the account guards for tenant ancestry, linked profiles and last admins.
                target = await IdentityService(self.db, self.user).tenant(
                    str(row.tenant_id), lock=True
                )
                with bypass_tenant_filter():
                    account = (
                        await self.db.execute(
                            select(User).where(
                                User.id == row.body["user_id"], User.tenant_id == target.id
                            )
                        )
                    ).scalar_one_or_none()
                if (
                    account is None
                    or account.role.value != row.body["previous_role"]
                    or account.org_unit_id != row.body["previous_org_unit_id"]
                ):
                    raise HTTPException(409, "申请期间账号权限已变化，请重新申请")
                await IdentityService(self.db, self.user).save_user(
                    str(target.id),
                    {"role": UserRole(row.body["role"]), "org_unit_id": row.body["org_unit_id"]},
                    str(account.id),
                )
        else:
            if self.user.role not in {UserRole.SCHOOL_ADMIN, UserRole.DEPARTMENT_ADMIN}:
                raise HTTPException(403, "任务完成须由学校或院系管理员核验")
            if body.decision == "approved":
                saved = row.body.get("evidence", [])
                current = await self.documents([e["doc_id"] for e in saved])
                if sorted(saved, key=lambda d: d["doc_id"]) != sorted(
                    current, key=lambda d: d["doc_id"]
                ):
                    raise HTTPException(409, "佐证文件已更新，请退回责任人重新提交")
        row.status, row.reviewed_by, row.review_comment = body.decision, self.user.id, body.reason
        row.reviewed_at = now()
        await self.append(row, "review", body.reason)

    async def archive(self, row: Record, body: schema.Action) -> None:
        self.school()
        self.revision(row, body.expected_revision)
        if row.kind != "task" or row.status != "approved":
            raise HTTPException(409, "仅人工审核通过的任务可以归档")
        await require_archive_policy(self.db, str(row.tenant_id))
        row.archived_at, row.status = now(), "archived"
        await self.append(row, "archive", body.reason)

    async def rules(self, *, lock: bool = False) -> tuple[Tenant, dict[str, Any]]:
        tenant = await IdentityService(self.db, self.user).tenant(lock=lock)
        current = (tenant.config or {}).get("school_business", {})
        return tenant, {
            "revision": 0,
            "year": date.today().year,
            "review_days": 5,
            "reminder_days": 3,
            "development_materials": "按本校现行制度逐项核验",
            "archive_requirements": "独立审核后确认归档，并核对学校电子效力依据",
            **current,
        }

    async def save_rules(self, body: schema.Rules) -> dict[str, Any]:
        self.school()
        tenant, current = await self.rules(lock=True)
        if current["revision"] != body.expected_revision:
            raise HTTPException(409, "学校参数已变化，请刷新后保存")
        values = {
            **body.model_dump(exclude={"expected_revision", "reason"}),
            "revision": current["revision"] + 1,
            "updated_by": self.user.id,
            "updated_at": now().isoformat(),
        }
        tenant.config = {**(tenant.config or {}), "school_business": values}
        await self.db.flush()
        return values
