"""真实 PostgreSQL 验证个人材料提交、支部书记审核、退回重交与前次记录。"""

import asyncio
from contextlib import asynccontextmanager
from datetime import date
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.tenant import tenant_context
from app.db.session import get_db
from app.deps import get_current_user
from app.main import app
from app.models.member import MemberProfile
from app.models.org import OrgUnit
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from tests.integration import test_repaired_storage as storage_fixtures

storage_url = storage_fixtures.storage_url
pytestmark = pytest.mark.integration

TENANT = "material-review-a"
BRANCH = "material-branch-a"
OTHER_BRANCH = "material-branch-b"
PROFILE = "material-profile-1"


@pytest.fixture(scope="module")
def material_url(storage_url):
    async def prepare():
        engine = create_async_engine(storage_url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:

                def migrate(sync):
                    config = Config()
                    config.set_main_option("script_location", "migrations")
                    config.attributes["connection"] = sync
                    command.upgrade(config, "head")

                await connection.run_sync(migrate)
            async with AsyncSession(engine, expire_on_commit=False) as db:
                db.add(
                    Tenant(
                        id=TENANT,
                        tenant_id=TENANT,
                        name="合成材料审核学校",
                        tenant_type="school",
                        path=TENANT,
                        config={},
                    )
                )
                for org_id, kind, parent in [
                    ("material-school", "school", None),
                    ("material-department", "department", "material-school"),
                    (BRANCH, "branch", "material-department"),
                    (OTHER_BRANCH, "branch", "material-department"),
                ]:
                    db.add(
                        OrgUnit(
                            id=org_id,
                            tenant_id=TENANT,
                            name="合成材料组织-" + org_id,
                            org_type=kind,
                            parent_id=parent,
                            path=org_id,
                        )
                    )
                for user_id, name, role, org in [
                    ("material-member", "合成党员", UserRole.MEMBER, BRANCH),
                    (
                        "material-secretary",
                        "合成支部书记",
                        UserRole.BRANCH_SECRETARY,
                        BRANCH,
                    ),
                    ("material-organizer", "合成组织员", UserRole.ORGANIZER, BRANCH),
                    (
                        "material-outsider",
                        "其他支部书记",
                        UserRole.BRANCH_SECRETARY,
                        OTHER_BRANCH,
                    ),
                ]:
                    db.add(
                        User(
                            id=user_id,
                            tenant_id=TENANT,
                            username=user_id,
                            name=name,
                            password_hash="synthetic",
                            role=role,
                            org_unit_id=org,
                            is_active=True,
                        )
                    )
                await db.flush()
                db.add(
                    MemberProfile(
                        id=PROFILE,
                        tenant_id=TENANT,
                        user_id="material-member",
                        name="合成党员",
                        org_name=BRANCH,
                        org_unit_id=BRANCH,
                        current_stage="member",
                        stage_joined_on=date(2020, 1, 1),
                        materials=[],
                    )
                )
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(prepare())
    return storage_url


def actor(user_id: str, name: str, role: UserRole, org: str = BRANCH) -> User:
    user = User(
        id=user_id,
        tenant_id=TENANT,
        username=user_id,
        name=name,
        role=role,
        org_unit_id=org,
        is_active=True,
        is_deleted=False,
    )
    user.knowledge_org_ids = [org, "material-school"]
    return user


@asynccontextmanager
async def client_for(url: str, current_user: User):
    engine = create_async_engine(url, poolclass=NullPool, hide_parameters=True)

    async def database():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            try:
                yield db
            except Exception:
                await db.rollback()
                raise

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: current_user
    try:
        with tenant_context(current_user.tenant_id, user_id=current_user.id):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                yield client
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_personal_material_review_return_resubmit_and_history(material_url):
    member = actor("material-member", "合成党员", UserRole.MEMBER)
    secretary = actor(
        "material-secretary", "合成支部书记", UserRole.BRANCH_SECRETARY
    )
    organizer = actor("material-organizer", "合成组织员", UserRole.ORGANIZER)
    outsider = actor(
        "material-outsider",
        "其他支部书记",
        UserRole.BRANCH_SECRETARY,
        OTHER_BRANCH,
    )

    async with client_for(material_url, member) as client:
        submitted = await client.post(
            "/api/v1/member/self/materials",
            data={
                "title": "合成个人思想汇报",
                "category": "thought_report",
                "description": "审核联调",
                "submission_key": str(uuid4()),
            },
            files={
                "file": (
                    "思想汇报.txt",
                    "合成材料内容".encode("utf-8"),
                    "text/plain",
                )
            },
        )
        assert submitted.status_code == 200, submitted.text
        material_id = submitted.json()["data"]["id"]

    async with client_for(material_url, organizer) as client:
        forbidden = await client.post(
            f"/api/v1/member/roster/{PROFILE}/materials/{material_id}/review",
            json={"decision": "approved"},
        )
        assert forbidden.status_code == 403

    async with client_for(material_url, outsider) as client:
        outside = await client.post(
            f"/api/v1/member/roster/{PROFILE}/materials/{material_id}/review",
            json={"decision": "approved"},
        )
        assert outside.status_code == 404

    async with client_for(material_url, secretary) as client:
        returned = await client.post(
            f"/api/v1/member/roster/{PROFILE}/materials/{material_id}/review",
            json={"decision": "returned", "opinion": "请补充落款日期"},
        )
        assert returned.status_code == 200, returned.text
        data = returned.json()["data"]
        assert data["material"]["review_status"] == "returned"
        assert data["material"]["review_note"] == "请补充落款日期"
        assert data["material"]["reviewer_name"] == "合成支部书记"
        assert data["reviews"][0]["decision"] == "returned"

    async with client_for(material_url, member) as client:
        listed = await client.get("/api/v1/member/self/materials")
        assert listed.status_code == 200
        row = next(
            item for item in listed.json()["data"]["items"] if item["id"] == material_id
        )
        assert row["review_status"] == "returned"
        assert row["review_note"] == "请补充落款日期"
        assert row["reviewer_name"] == "合成支部书记"

        resubmitted = await client.post(
            "/api/v1/member/self/materials",
            data={
                "title": "合成个人思想汇报（补充版）",
                "category": "thought_report",
                "description": "已补充落款日期",
                "submission_key": str(uuid4()),
                "previous_material_id": material_id,
            },
            files={
                "file": (
                    "思想汇报-补充.txt",
                    "补充后的合成材料".encode("utf-8"),
                    "text/plain",
                )
            },
        )
        assert resubmitted.status_code == 200, resubmitted.text
        new_id = resubmitted.json()["data"]["id"]
        assert new_id != material_id
        assert resubmitted.json()["data"]["previous_material_id"] == material_id

        history = await client.get(
            f"/api/v1/member/self/materials/{new_id}/reviews"
        )
        assert history.status_code == 200
        previous = history.json()["data"]["previous_material"]
        assert previous["id"] == material_id
        assert previous["reviews"][0]["opinion"] == "请补充落款日期"

    async with client_for(material_url, secretary) as client:
        approved = await client.post(
            f"/api/v1/member/roster/{PROFILE}/materials/{new_id}/review",
            json={"decision": "approved", "opinion": "材料齐全"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["data"]["material"]["review_status"] == "approved"

        duplicate = await client.post(
            f"/api/v1/member/roster/{PROFILE}/materials/{new_id}/review",
            json={"decision": "approved", "opinion": "重复审核"},
        )
        assert duplicate.status_code == 409

    async with client_for(material_url, organizer) as client:
        history = await client.get(
            f"/api/v1/member/roster/{PROFILE}/materials/{new_id}/reviews"
        )
        assert history.status_code == 200
        assert history.json()["data"]["reviews"][0]["decision"] == "approved"
