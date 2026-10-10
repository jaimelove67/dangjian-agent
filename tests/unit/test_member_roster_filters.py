"""年度、批次筛选先于分页，且不能扩大支部范围；实际执行 SQLite 查询。"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
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
            user=user,
            db=RosterSession(db),
        )
        assert page.data.total == len(expected)
        assert len(page.data.items) == 1
    engine.dispose()
