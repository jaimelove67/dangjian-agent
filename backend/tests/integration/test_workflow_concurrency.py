"""Independent PostgreSQL transactions race for one password grant and the final event seat."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.security import hash_password
from app.core.tenant import tenant_context
from app.models.account_security import PasswordChange, PasswordRequest
from app.models.education import EducationEnrollment, EducationOffering
from app.models.org import OrgUnit
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services.account_security_service import change
from app.services.education_service import EducationService
from tests.integration.test_repaired_storage import storage_url as isolated_storage_url

storage_url = isolated_storage_url


@pytest.fixture(scope="module")
def migrated_url(storage_url):
    async def migrate():
        engine = create_async_engine(storage_url, poolclass=NullPool, hide_parameters=True)
        async with engine.begin() as connection:

            def upgrade(sync):
                config = Config()
                config.set_main_option("script_location", "migrations")
                config.attributes["connection"] = sync
                command.upgrade(config, "head")

            await connection.run_sync(upgrade)
        await engine.dispose()

    asyncio.run(migrate())
    return storage_url


@pytest.mark.parametrize("approved", [False, True])
async def test_concurrent_password_changes_spend_exactly_one_allowance(
    migrated_url, approved, monkeypatch
):
    monkeypatch.setattr("app.core.config.settings.BCRYPT_ROUNDS", 4)
    engine = create_async_engine(migrated_url, poolclass=NullPool, hide_parameters=True)
    tenant_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    with tenant_context(tenant_id):
        async with AsyncSession(engine) as db:
            db.add(
                Tenant(
                    id=tenant_id,
                    tenant_id=tenant_id,
                    name="合成并发测试学校",
                    tenant_type="school",
                    path="/" + tenant_id,
                )
            )
            db.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    username=user_id,
                    name="合成并发改密账号",
                    role=UserRole.MEMBER,
                    password_hash=hash_password("synthetic-before", rounds=4),
                    is_active=True,
                )
            )
            if approved:
                db.add(PasswordChange(tenant_id=tenant_id, user_id=user_id))
                db.add(
                    PasswordRequest(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        reason="合成一次授权",
                        status="approved",
                        version=1,
                    )
                )
            await db.commit()

        async def attempt():
            with tenant_context(tenant_id):
                async with AsyncSession(engine, expire_on_commit=False) as db:
                    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
                    try:
                        await change(db, user, "synthetic-before", "synthetic-after")
                        await db.commit()
                        return 200
                    except HTTPException as exc:
                        await db.rollback()
                        return exc.status_code

        assert sorted(await asyncio.gather(attempt(), attempt())) == [200, 409]
        async with AsyncSession(engine) as db:
            count = await db.scalar(
                select(func.count())
                .select_from(PasswordChange)
                .where(PasswordChange.user_id == user_id)
            )
            assert count == (2 if approved else 1)
            if approved:
                grant = (
                    await db.execute(
                        select(PasswordRequest).where(PasswordRequest.user_id == user_id)
                    )
                ).scalar_one()
                assert grant.status == "consumed" and grant.version == 2 and grant.consumed_at
    await engine.dispose()


async def test_two_registrations_cannot_overbook_the_final_seat(migrated_url):
    engine = create_async_engine(migrated_url, poolclass=NullPool, hide_parameters=True)
    tenant_id, org_id, event_id = [str(uuid.uuid4()) for _ in range(3)]
    user_ids = [str(uuid.uuid4()) for _ in range(2)]
    with tenant_context(tenant_id):
        async with AsyncSession(engine) as db:
            db.add(
                Tenant(
                    id=tenant_id,
                    tenant_id=tenant_id,
                    name="合成报名学校",
                    tenant_type="school",
                    path="/" + tenant_id,
                )
            )
            db.add(
                OrgUnit(
                    id=org_id,
                    tenant_id=tenant_id,
                    name="合成支部",
                    org_type="branch",
                    path="/" + org_id,
                )
            )
            for user_id in user_ids:
                db.add(
                    User(
                        id=user_id,
                        tenant_id=tenant_id,
                        username=user_id,
                        name="合成报名人",
                        role=UserRole.MEMBER,
                        password_hash="unused",
                        org_unit_id=org_id,
                        is_active=True,
                    )
                )
            db.add(
                EducationOffering(
                    id=event_id,
                    tenant_id=tenant_id,
                    org_unit_id=org_id,
                    kind="event",
                    title="最后一个名额",
                    status="published",
                    created_by=user_ids[0],
                    content={
                        "registration_deadline": (
                            datetime.now(UTC) + timedelta(hours=1)
                        ).isoformat(),
                        "starts_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
                        "capacity": 1,
                        "points": 1,
                    },
                )
            )
            await db.commit()

        async def attempt(user_id):
            with tenant_context(tenant_id):
                async with AsyncSession(engine, expire_on_commit=False) as db:
                    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
                    service = EducationService(db, user)
                    row = await service.offering(event_id, lock=True)
                    try:
                        await service.enroll(row)
                        await db.commit()
                        return 200
                    except HTTPException as exc:
                        await db.rollback()
                        return exc.status_code

        assert sorted(await asyncio.gather(*(attempt(user) for user in user_ids))) == [200, 409]
        async with AsyncSession(engine) as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(EducationEnrollment)
                    .where(EducationEnrollment.offering_id == event_id)
                )
                == 1
            )
    await engine.dispose()
