"""上传审查发现的权限与日期回归；SQLite 实际执行汇总 SQL，不调用云模型。"""

import json
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1 import knowledge
from app.core.tenant import tenant_context
from app.models.meeting import ContentRevision, MeetingRecord, MeetingTask
from app.models.member import MemberCultivation, MemberMaterial, MemberProfile, MemberVote
from app.models.user import User, UserRole
from app.schemas.meeting import ActivityCreate, ActivityUpdate
from app.schemas.member_ext import MaterialCreate, MaterialReview, ScoringRequest, TransitionRequest
from app.services import activity_service
from app.services.file_store import read_original, save_original
from app.services.member_service import MemberDevelopment


class LocalSession:
    """用真实 SQLite SQL 验证查询范围，保留业务服务的异步会话接口。"""

    def __init__(self, session):
        self.session = session

    async def execute(self, statement):
        return self.session.execute(statement)

    async def scalar(self, statement):
        return self.session.scalar(statement)

    async def flush(self):
        self.session.flush()

    def add(self, record):
        self.session.add(record)


@pytest.fixture
def member_data():
    engine = create_engine("sqlite:///:memory:")
    for model in (MemberProfile, MemberVote, MemberCultivation, MemberMaterial, ContentRevision):
        model.__table__.create(engine)
    with Session(engine, expire_on_commit=False) as db, tenant_context("review-a"):
        manager = User(id="reviewer-a", tenant_id="review-a", role=UserRole.BRANCH_SECRETARY)
        service = MemberDevelopment(LocalSession(db), manager)
        service.org_ids = ["branch-a"]
        for identifier, org in (("own", "branch-a"), ("other", "branch-b")):
            db.add(
                MemberProfile(
                    id=identifier,
                    tenant_id="review-a",
                    org_unit_id=org,
                    org_name=org,
                    name=identifier,
                    current_stage="activist",
                    stage_joined_on=date.today(),
                    year=2026,
                    batch_no="B1",
                )
            )
        db.commit()
        yield service, db
    engine.dispose()


@pytest.mark.asyncio
async def test_vote_summary_and_stats_stay_within_branch(member_data):
    service, db = member_data
    for profile_id in ("own", "other"):
        db.add(
            MemberVote(
                tenant_id="review-a",
                profile_id=profile_id,
                batch_no="B1",
                round_no=1,
                voter_id="voter-" + profile_id,
                vote="agree",
                comment="private vote",
            )
        )
    db.commit()
    votes = await service.vote_summary("B1", 1)
    assert set(votes["tally"]) == {"own"}
    assert votes["voter_count"] == 1
    # 无记名（T-MEM-12）：只回答"我投没投"，不回答"谁投了"
    assert votes["tally"]["own"]["voted_by_me"] is False
    assert votes["data_level"] == "sensitive" and votes["cloud_allowed"] is False
    assert "voter-own" not in json.dumps(votes, ensure_ascii=False)
    assert "voters" not in votes["tally"]["own"]
    stats = await service.roster_stats(year=2026, batch_no="B1")
    assert stats["total"] == 1 and stats["by_stage"] == {"activist": 1}
    service.org_ids = []
    assert (await service.vote_summary("B1", 1))["tally"] == {}
    assert (await service.roster_stats(year=None, batch_no=None))["total"] == 0


@pytest.mark.asyncio
async def test_material_level_is_snapshotted_and_third_party_text_is_hidden(member_data):
    """T-MEM-12：材料密级在登记时带出；第三人字段高于查看者等级时不返回正文。"""
    service, _ = member_data
    classified = await service.add_material(
        "own", MaterialCreate(material_type="政治审查材料", reason="登记政审材料")
    )
    mass = await service.add_material(
        "own", MaterialCreate(material_type="政审材料", reason="用简称登记也要认得出")
    )
    sensitive = await service.add_material(
        "own", MaterialCreate(material_type="群众评议材料", reason="登记群众评议材料")
    )
    await service.review_material(
        str(classified.id),
        MaterialReview(review_status="approved", note="经向其舅舅王某某核实", reason="人工核验"),
    )
    await service.review_material(
        str(sensitive.id),
        MaterialReview(review_status="approved", note="群众反映良好", reason="人工核验"),
    )
    items = {item["material_type"]: item for item in await service.list_materials("own")}
    politics = items["政治审查材料"]
    assert politics["data_level"] == "classified"
    assert politics["data_level_label"] == "涉密"
    assert politics["cloud_allowed"] is False and politics["embedding_allowed"] is False
    assert "note" in politics["redacted_fields"]
    # 正文与留痕快照里的第三人信息都不出界面
    assert "王某某" not in json.dumps(politics, ensure_ascii=False)
    assert "王某某" not in json.dumps(politics["review_history"], ensure_ascii=False)
    # 简称登记的材料同样按正式名给密级（不给"换个写法"留缝）
    assert items["政审材料"]["data_level"] == "classified"
    # 组织人员本人（敏感级）看得到群众评议材料的备注
    assert items["群众评议材料"]["data_level"] == "sensitive"
    assert items["群众评议材料"]["note"] == "群众反映良好"
    assert items["群众评议材料"]["redacted_fields"] == []
    # 未登记过的材料类型按内部处理
    plain = await service.add_material(
        "own", MaterialCreate(material_type="入党申请书", reason="登记入党申请书")
    )
    plain_item = next(
        item for item in await service.list_materials("own") if item.get("id") == str(plain.id)
    )
    assert plain_item["data_level"] == "internal"
    assert plain_item["cloud_allowed"] is True and plain_item["embedding_allowed"] is True


@pytest.mark.asyncio
async def test_future_decision_cannot_skip_training_period(member_data):
    service, _ = member_data
    with pytest.raises(HTTPException) as error:
        await service.transition(
            "own",
            TransitionRequest(
                target_stage="candidate",
                decision_date=date.today() + timedelta(days=366),
                basis="test decision",
            ),
        )
    assert error.value.status_code == 422
    assert (await service.profile("own")).current_stage == "activist"


@pytest.mark.asyncio
async def test_scoring_uses_only_requested_year_evidence_and_risks(member_data):
    service, db = member_data
    for year, score in (("2025", 100), ("2026", 20)):
        db.add(
            MemberCultivation(
                tenant_id="review-a",
                profile_id="own",
                org_unit_id="branch-a",
                category="theory_test",
                period=year,
                score=score,
                source_note="verified synthetic result",
            )
        )
    db.add(
        MemberCultivation(
            tenant_id="review-a",
            profile_id="own",
            org_unit_id="branch-a",
            category="academic",
            period="2025",
            is_risk=True,
            risk_note="old period risk",
        )
    )
    db.commit()
    score = await service.scoring(ScoringRequest(profile_id="own", year=2026))
    assert score["year"] == 2026
    assert score["dimensions"]["theory_test"]["value"] == 20
    assert score["risks"] == []
    missing = await service.scoring(ScoringRequest(profile_id="own", year=2027))
    assert missing["weighted_score"] is None


@pytest.mark.asyncio
async def test_material_review_retains_both_reviewers_and_opinions(member_data):
    service, db = member_data
    material = MemberMaterial(
        id="material-a",
        tenant_id="review-a",
        profile_id="own",
        org_unit_id="branch-a",
        stage="activist",
        material_type="test",
    )
    db.add(material)
    db.commit()
    await service.review_material(
        "material-a",
        MaterialReview(review_status="approved", note="first opinion", reason="first review"),
    )
    service.user.id = "reviewer-b"
    await service.review_material(
        "material-a",
        MaterialReview(review_status="rejected", note="second opinion", reason="second review"),
    )
    history = (await service.list_materials("own"))[0]["review_history"]
    assert [item["action"] for item in history] == ["baseline", "review", "review"]
    assert [item["actor_id"] for item in history[1:]] == ["reviewer-a", "reviewer-b"]
    assert [item["snapshot"]["note"] for item in history[1:]] == ["first opinion", "second opinion"]
    assert [item["reason"] for item in history[1:]] == ["first review", "second review"]


@pytest.mark.parametrize(
    "doc_id",
    [
        "../escaped",
        "..\\..\\tenant-b\\originals\\secret",
        "C:\\escaped",
        "/escaped",
        "x*",
        "..",
        "id:stream",
    ],
)
def test_original_files_reject_path_and_glob_identifiers(tmp_path, monkeypatch, doc_id):
    monkeypatch.setenv("FILE_STORAGE_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        save_original("tenant-a", doc_id, 1, b"private", "source.txt")
    with pytest.raises(ValueError):
        read_original("tenant-a", doc_id, 1)
    assert list(tmp_path.iterdir()) == []


def test_original_versions_remain_distinct_and_tenant_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FILE_STORAGE_DIR", str(tmp_path))
    save_original("tenant-a", "doc-a", 1, b"first", "first.txt")
    save_original("tenant-a", "doc-a", 2, b"second", "second.txt")
    assert read_original("tenant-a", "doc-a", 1) == b"first"
    assert read_original("tenant-a", "doc-a", 2) == b"second"
    assert read_original("tenant-b", "doc-a", 1) is None


def document_for_patch():
    return SimpleNamespace(
        id="record-a",
        tenant_id="review-a",
        doc_id="doc-a",
        file_name="test.txt",
        title="policy",
        issuer="school",
        doc_number=None,
        level="school",
        visibility="department",
        security_level="sensitive",
        effective_date=date(2026, 1, 1),
        expiration_date=None,
        status="effective",
        tags=["test"],
        summary="policy",
        authority="school_policy",
        validity="effective",
        review_status="published",
        reviewed_by=None,
        reviewed_at=None,
        review_note=None,
        field_levels=None,
        maintained_at=None,
        next_review_at=None,
        doc_metadata={"org_unit_id": "branch-a"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"level": "central", "visibility": "public", "security_level": "public"}, 403),
        ({"expiration_date": "2025-01-01"}, 422),
        ({"effective_date": "2026-13-01"}, 422),
        ({"title": None}, 422),
        ({"tags": ""}, 422),
    ],
)
async def test_metadata_changes_preserve_upload_validation(monkeypatch, payload, expected):
    doc = document_for_patch()
    monkeypatch.setattr(knowledge, "_readable_document", AsyncMock(return_value=doc))
    db = AsyncMock()
    manager = User(id="reviewer-a", tenant_id="review-a", role=UserRole.DEPARTMENT_ADMIN)
    with pytest.raises(HTTPException) as error:
        await knowledge.patch_knowledge_document_metadata(
            "doc-a",
            knowledge.DocumentMetadataPatch(reason="correction", **payload),
            None,
            manager,
            db,
        )
    assert error.value.status_code == expected
    assert doc.level == "school" and doc.security_level == "sensitive"
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_metadata_cannot_downgrade_private_old_version_content(monkeypatch):
    doc = document_for_patch()
    monkeypatch.setattr(knowledge, "_readable_document", AsyncMock(return_value=doc))
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: ["old version phone: 13800000000"])
    )
    manager = User(id="reviewer-a", tenant_id="review-a", role=UserRole.SYSTEM_ADMIN)
    with pytest.raises(HTTPException) as error:
        await knowledge.patch_knowledge_document_metadata(
            "doc-a",
            knowledge.DocumentMetadataPatch(reason="correction", security_level="public"),
            None,
            manager,
            db,
        )
    assert error.value.status_code == 422
    assert doc.security_level == "sensitive"
    db.commit.assert_not_awaited()


def restricted_activity(monkeypatch):
    record = MeetingRecord(
        id="meeting-a",
        tenant_id="review-a",
        org_unit_id="branch-a",
        activity_type="branch_member_meeting",
        title="private title",
        scheduled_on=date.today(),
        host="host",
        participants=[],
        transcript="private transcript",
        minutes={},
        sources=[{"doc_id": "private"}],
        context={
            "agenda": "private policy excerpt",
            "notice": "private notice",
            "content_sources": [{"doc_id": "private"}],
        },
    )
    task = MeetingTask(
        id="task-a",
        tenant_id="review-a",
        record_id="meeting-a",
        org_unit_id="branch-a",
        task_text="private task excerpt",
        status="pending",
    )
    user = User(id="reviewer-a", tenant_id="review-a", role=UserRole.BRANCH_SECRETARY)
    service = activity_service.ActivityService(AsyncMock(), user)
    service.org_ids = ["branch-a"]
    service.record = AsyncMock(return_value=record)
    monkeypatch.setattr(activity_service, "visible_sources", AsyncMock(return_value=([], [], True)))
    return service, record, task


@pytest.mark.asyncio
async def test_restricted_activity_redacts_agenda_notice_and_tasks(monkeypatch):
    service, record, task = restricted_activity(monkeypatch)
    service.tasks_of = AsyncMock(return_value=[task])
    data = await service.record_data(record)
    assert data["restricted"] is True
    assert data["context"] == {} and data["tasks"] == []
    assert "private" not in str(data)


@pytest.mark.asyncio
async def test_task_list_and_task_access_recheck_parent_source_permissions(monkeypatch):
    service, _, task = restricted_activity(monkeypatch)
    service.db.scalar.return_value = 1
    service.db.execute.return_value = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [task])
    )
    data = await service.list_tasks(org_unit_id=None, year=None, status=None, page=1, page_size=20)
    assert data["items"] == [{"id": "task-a", "restricted": True}]
    service.db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: task)
    with pytest.raises(HTTPException) as error:
        await service.task("task-a")
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_future_meeting_plan_can_be_created_and_revised(monkeypatch):
    tomorrow = date.today() + timedelta(days=1)
    body = ActivityCreate(
        org_unit_id="branch-a",
        activity_type="branch_member_meeting",
        title="planned meeting",
        scheduled_on=tomorrow,
        reason="plan",
    )
    assert body.scheduled_on == tomorrow
    service, record, _ = restricted_activity(monkeypatch)
    record.revision = 1
    service.save_revision = AsyncMock()
    await service.update(
        "meeting-a", ActivityUpdate(expected_revision=1, reason="reschedule", scheduled_on=tomorrow)
    )
    assert record.scheduled_on == tomorrow


@pytest.mark.asyncio
async def test_removing_sources_does_not_release_old_derived_content(monkeypatch):
    service, record, task = restricted_activity(monkeypatch)
    record.revision = 1
    service.save_revision = AsyncMock()
    service.tasks_of = AsyncMock(return_value=[task])
    monkeypatch.setattr(activity_service, "selected_sources", AsyncMock(return_value=[]))
    await service.update(
        "meeting-a", ActivityUpdate(expected_revision=1, reason="unselect", source_doc_ids=[])
    )
    assert record.sources == []
    checked = []

    async def current_access(db, user, org, sources):
        checked.extend(sources)
        return [], [], any(source.get("doc_id") == "private" for source in sources)

    monkeypatch.setattr(activity_service, "visible_sources", current_access)
    data = await service.record_data(record)
    assert any(source.get("doc_id") == "private" for source in checked)
    assert data["restricted"] and not data["context"] and not data["tasks"]
    with pytest.raises(HTTPException) as error:
        await service.recommendations("meeting-a")
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_old_unlinked_record_recovers_sources_from_immutable_history(monkeypatch):
    service, record, _ = restricted_activity(monkeypatch)
    record.sources = []
    record.context.pop("content_sources")
    service.db.execute.return_value = SimpleNamespace(
        scalars=lambda: SimpleNamespace(
            all=lambda: [{"sources": [{"doc_id": "old-private"}], "context": {}}]
        )
    )
    assert await service.content_sources(record) == [{"doc_id": "old-private"}]


@pytest.mark.asyncio
async def test_shared_original_download_reads_the_authorized_document_tenant(tmp_path, monkeypatch):
    monkeypatch.setenv("FILE_STORAGE_DIR", str(tmp_path))
    stored = save_original("publisher", "shared", 1, b"authorized public source", "public.txt")
    save_original("reader", "shared", 1, b"different tenant file", "other.txt")
    document = document_for_patch()
    document.tenant_id = "publisher"
    document.doc_id = "shared"
    document.doc_metadata = {"original_file": stored}
    monkeypatch.setattr(knowledge, "_readable_document", AsyncMock(return_value=document))
    monkeypatch.setattr(knowledge, "audit_operation", AsyncMock())
    reader = User(id="reader", tenant_id="reader", role=UserRole.MEMBER)
    response = await knowledge.download_original_file("shared", None, None, reader, AsyncMock())
    assert response.body == b"authorized public source"
