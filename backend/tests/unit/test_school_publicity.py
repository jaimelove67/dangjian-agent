"""Publicity attachment authorization and immutable publication revisions, without external services."""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.models.knowledge import KnowledgeDoc
from app.models.school_business import SchoolBusinessRecord
from app.models.user import User, UserRole
from app.schemas.school_business import Action, NoticeCreate
from app.services.school_business_service import SchoolBusinessService


@pytest.mark.parametrize(
    "utc_time,visible",
    [
        (datetime(2026, 10, 28, 15, 59, 59), False),
        (datetime(2026, 10, 28, 16), True),
        (datetime(2026, 10, 29, 15, 59, 59), True),
        (datetime(2026, 10, 29, 16), False),
    ],
)
@pytest.mark.asyncio
async def test_publicity_visibility_uses_beijing_day_at_utc_midnight_boundary(
    monkeypatch, utc_time, visible
):
    monkeypatch.setattr("app.services.school_business_service.now", lambda: utc_time)
    current = service([])
    current.user.role = UserRole.MEMBER
    current.user.org_unit_id = "branch"
    row = SchoolBusinessRecord(
        id="notice",
        tenant_id="school-tenant",
        org_unit_id="school",
        kind="notice",
        status="published",
        body={"category": "publicity", "starts_on": "2026-10-29", "expires_on": "2026-10-29"},
    )
    assert await current.readable(row) is visible


def service(documents):
    database = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: documents))
    )
    actor = User(
        id="school-admin",
        tenant_id="school-tenant",
        role=UserRole.SCHOOL_ADMIN,
        org_unit_id="school",
    )
    result = SchoolBusinessService(database, actor)
    result._tree = {
        "school": SimpleNamespace(parent_id=None, name="合成学校"),
        "department": SimpleNamespace(parent_id="school", name="合成院系"),
        "branch": SimpleNamespace(parent_id="department", name="合成支部"),
        "other-branch": SimpleNamespace(parent_id="department", name="其他支部"),
    }
    return result


def document(**overrides):
    return KnowledgeDoc(
        tenant_id="school-tenant",
        doc_id="school-file",
        title="已发布原件",
        file_name="原件.pdf",
        issuer="学校党委",
        level="school",
        visibility="school",
        security_level="internal",
        review_status="published",
        effective_date=date.today(),
        doc_metadata={"content_revision": 2, "original_file": {"revision": 2}},
        **overrides,
    )


@pytest.mark.asyncio
async def test_notice_attachment_snapshot_keeps_validated_original_revision():
    result = await service([document()]).documents(["school-file"], notice_org_id="school")
    assert result == [{"doc_id": "school-file", "title": "已发布原件", "revision": 2}]


@pytest.mark.asyncio
async def test_notice_creation_stores_only_validated_attachment_snapshot_and_organization_names():
    current = service([document()])
    current.org_ids = AsyncMock(return_value={"branch"})
    current.db.add = Mock()
    current.append = AsyncMock()
    row = await current.create(
        "notice",
        NoticeCreate(
            org_unit_id="branch",
            title="支部公示附件",
            content="已核对发布范围和原件版本",
            category="publicity",
            starts_on=date.today(),
            expires_on=date.today(),
            doc_ids=["school-file"],
        ),
    )
    assert row.status == "draft"
    assert "doc_ids" not in row.body
    assert row.body["evidence"] == [{"doc_id": "school-file", "title": "已发布原件", "revision": 2}]
    assert row.body["organization_name"] == "合成支部"
    assert row.body["issuer"] == "合成学校"


@pytest.mark.asyncio
async def test_notice_rejects_unknown_or_unauthorized_attachment():
    with pytest.raises(HTTPException) as error:
        await service([]).documents(["foreign-file"], notice_org_id="school")
    assert error.value.status_code == 403


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"review_status": "pending"}, 403),
        ({"security_level": "sensitive"}, 403),
        ({"doc_metadata": {}}, 422),
        ({"doc_metadata": {"content_revision": 3, "original_file": {"revision": 2}}}, 422),
        (
            {
                "visibility": "branch",
                "doc_metadata": {
                    "org_unit_id": "other-branch",
                    "content_revision": 2,
                    "original_file": {"revision": 2},
                },
            },
            403,
        ),
    ],
)
@pytest.mark.asyncio
async def test_notice_rejects_unpublished_sensitive_or_invalid_original(change, expected):
    item = document()
    for field, value in change.items():
        setattr(item, field, value)
    with pytest.raises(HTTPException) as error:
        await service([item]).documents([item.doc_id], notice_org_id="school")
    assert error.value.status_code == expected


@pytest.mark.asyncio
async def test_branch_notice_can_reference_its_ancestor_department_document():
    item = document()
    item.visibility = "department"
    item.doc_metadata = {
        **item.doc_metadata,
        "org_unit_id": "department",
    }
    assert await service([item]).documents([item.doc_id], notice_org_id="branch")
    with pytest.raises(HTTPException) as error:
        await service([item]).documents([item.doc_id], notice_org_id="school")
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_publication_rechecks_attachment_revision_before_changing_record():
    current = service([])
    current.documents = AsyncMock(
        return_value=[{"doc_id": "school-file", "title": "新版本", "revision": 3}]
    )
    current.append = AsyncMock()
    row = SchoolBusinessRecord(
        id="notice",
        tenant_id="school-tenant",
        org_unit_id="school",
        kind="notice",
        status="draft",
        revision=1,
        body={"evidence": [{"doc_id": "school-file", "title": "原版本", "revision": 2}]},
    )
    with pytest.raises(HTTPException) as error:
        await current.publish(row, Action(expected_revision=1, reason="核对后发布"))
    assert error.value.status_code == 409
    assert row.status == "draft"
    current.append.assert_not_awaited()


@pytest.mark.asyncio
async def test_unavailable_attachment_stops_publication_without_changing_record():
    current = service([])
    current.documents = AsyncMock(side_effect=HTTPException(403, "附件已撤回"))
    current.append = AsyncMock()
    row = SchoolBusinessRecord(
        id="notice",
        tenant_id="school-tenant",
        org_unit_id="school",
        kind="notice",
        status="draft",
        revision=1,
        body={"evidence": [{"doc_id": "school-file", "title": "原版本", "revision": 2}]},
    )
    with pytest.raises(HTTPException) as error:
        await current.publish(row, Action(expected_revision=1, reason="核对后发布"))
    assert error.value.status_code == 403
    assert row.status == "draft"
    current.append.assert_not_awaited()
