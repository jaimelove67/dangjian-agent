"""年度、批次筛选先于分页，且不能扩大支部范围；实际执行 SQLite 查询。"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.v1 import member
from app.core.tenant import tenant_context
from app.models.member import MemberProfile
from app.models.user import User, UserRole


class RosterSession:
    def __init__(self, session):
        self.session = session

    async def execute(self, statement):
        return self.session.execute(statement)

    async def commit(self):
        self.session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("year", "batch", "expected"),
    [
        (2026, "B1", {"current-b1"}),
        (2025, "B1", {"previous-b1"}),
        (None, "B1", {"current-b1", "previous-b1"}),
        (None, None, {"current-b1", "current-b2", "previous-b1"}),
    ],
)
async def test_roster_year_and_batch_preserve_org_scope(monkeypatch, year, batch, expected):
    engine = create_engine("sqlite:///:memory:")
    MemberProfile.__table__.create(engine)
    monkeypatch.setattr(member, "audit_operation", AsyncMock())
    monkeypatch.setattr(
        member, "accessible_org_units", AsyncMock(return_value=[SimpleNamespace(id="branch-a")])
    )
    with Session(engine, expire_on_commit=False) as db, tenant_context("roster-test"):
        for identifier, item_year, item_batch, org_id, active in [
            ("current-b1", 2026, "B1", "branch-a", True),
            ("current-b2", 2026, "B2", "branch-a", True),
            ("previous-b1", 2025, "B1", "branch-a", True),
            ("outside-branch", 2026, "B1", "branch-b", True),
            ("inactive", 2026, "B1", "branch-a", False),
        ]:
            db.add(
                MemberProfile(
                    id=identifier,
                    tenant_id="roster-test",
                    name=identifier,
                    org_name=org_id,
                    org_unit_id=org_id,
                    year=item_year,
                    batch_no=item_batch,
                    current_stage="activist",
                    stage_joined_on=date(2025, 1, 12),
                    is_active=active,
                )
            )
        db.commit()
        user = User(tenant_id="roster-test", role=UserRole.BRANCH_SECRETARY)
        response = await member.member_roster(
            Request({"type": "http"}),
            page=1,
            page_size=100,
            year=year,
            batch_no=batch,
            # 直接调用端点函数时不会走 FastAPI 的默认值解析：这里显式传入解析后的默认值，
            # 否则 include_transferred / org_unit_id 会是 Query 对象（真值），把默认口径测歪。
            include_transferred=False,
            org_unit_id=None,
            user=user,
            db=RosterSession(db),
        )
        assert response.data.total == len(expected)
        assert {item.id for item in response.data.items} == expected
        assert all(item.org_unit_id == "branch-a" for item in response.data.items)
        if year is not None:
            assert all(item.year == year for item in response.data.items)
        page = await member.member_roster(
            Request({"type": "http"}),
            page=1,
            page_size=1,
            year=year,
            batch_no=batch,
            include_transferred=False,
            org_unit_id=None,
            user=user,
            db=RosterSession(db),
        )
        assert page.data.total == len(expected)
        assert len(page.data.items) == 1
    engine.dispose()


@pytest.mark.asyncio
async def test_roster_org_filter_narrows_within_scope_and_rejects_outside(monkeypatch):
    """T-MEM-02：组织筛选只在权限范围内收窄；范围外 / 不存在一律 403，不静默忽略。"""
    engine = create_engine("sqlite:///:memory:")
    MemberProfile.__table__.create(engine)
    monkeypatch.setattr(member, "audit_operation", AsyncMock())
    monkeypatch.setattr(
        member,
        "accessible_org_units",
        AsyncMock(
            return_value=[SimpleNamespace(id="branch-a"), SimpleNamespace(id="branch-b")]
        ),
    )
    with Session(engine, expire_on_commit=False) as db, tenant_context("roster-test"):
        for identifier, org_id in [
            ("a-1", "branch-a"),
            ("b-1", "branch-b"),
            ("c-1", "branch-c"),
        ]:
            db.add(
                MemberProfile(
                    id=identifier,
                    tenant_id="roster-test",
                    name=identifier,
                    org_name=org_id,
                    org_unit_id=org_id,
                    year=2026,
                    batch_no="B1",
                    current_stage="activist",
                    stage_joined_on=date(2025, 1, 12),
                )
            )
        db.commit()
        user = User(tenant_id="roster-test", role=UserRole.BRANCH_SECRETARY)
        only_b = await member.member_roster(
            Request({"type": "http"}),
            page=1,
            page_size=100,
            year=None,
            batch_no=None,
            include_transferred=False,
            org_unit_id="branch-b",
            user=user,
            db=RosterSession(db),
        )
        # 权限范围内的显式组织只回该组织人员（"c-1" 不在范围内，本来就看不到）
        assert {item.id for item in only_b.data.items} == {"b-1"}
        assert only_b.data.total == 1
        with pytest.raises(HTTPException) as rejected:
            await member.member_roster(
                Request({"type": "http"}),
                page=1,
                page_size=100,
                year=None,
                batch_no=None,
                include_transferred=False,
                org_unit_id="branch-c",
                user=user,
                db=RosterSession(db),
            )
        # 传了范围外的组织：403 而不是"忽略参数后返回全量"
        assert rejected.value.status_code == 403
    engine.dispose()
