"""党员基本信息采集表的字段校验与流转前置条件。"""

from datetime import date
from types import SimpleNamespace

from app.models.member import MemberProfile
from app.models.user import UserRole
from app.schemas.member_info import InfoPayload
from app.services.member_info_service import (
    can_edit_branch,
    can_review,
    merge_payload,
    new_collection,
    person_category,
    validate_complete,
    validate_self,
)


def payload(**overrides):
    values = {
        "gender": "male",
        "ethnicity": "汉族",
        "education_code": "22",
        "mobile": "13800001234",
        "address": "示范大学学生公寓 1 栋 101",
        "lost_contact": False,
        "floating": False,
        "join_party_on": date(2021, 6, 1),
        "full_member_on": date(2022, 6, 1),
        "job_code": "321",
        "party_status": "normal",
        "filing_type": "new",
        "relation_transfer": False,
    }
    values.update(overrides)
    return InfoPayload(**values)


def test_self_validation_requires_contact_and_conditional_addresses():
    errors = validate_self(
        payload(mobile="123", address="", floating=True, floating_province="")
    )
    assert "mobile" in errors
    assert "address" in errors
    assert "floating_province" in errors
    assert not validate_self(payload())


def test_complete_validation_checks_dates_and_branch_fields():
    profile = SimpleNamespace(current_stage="member", birth_date=date(2000, 1, 1))
    errors = validate_complete(payload(full_member_on=None), profile)
    assert "full_member_on" in errors

    errors = validate_complete(
        payload(
            filing_type="supplement",
            supplement_reason="",
            relation_transfer=True,
            transfer_branch="",
        ),
        profile,
    )
    assert "supplement_reason" in errors
    assert "transfer_branch" in errors

    probationary = SimpleNamespace(
        current_stage="probationary", birth_date=date(2000, 1, 1)
    )
    assert "full_member_on" in validate_complete(payload(), probationary)


def test_merge_payload_preserves_branch_fields_when_member_saves_self_fields():
    existing = payload()
    incoming = InfoPayload(gender="female", address="新地址 2 号")
    merged = merge_payload(existing, incoming, keys={"gender", "address"})
    assert merged.gender == "female"
    assert merged.address == "新地址 2 号"
    assert merged.join_party_on == existing.join_party_on
    assert merged.job_code == existing.job_code


def test_new_collection_masks_id_and_never_copies_full_number():
    profile = MemberProfile(
        id="profile-1",
        tenant_id="school-1",
        name="张三",
        id_card_no="110101199001011234",
        birth_date=date(1990, 1, 1),
        org_name="示范大学学生第 1 党支部",
        org_unit_id="org-1",
        current_stage="member",
        stage_joined_on=date(2022, 7, 1),
    )
    collection = new_collection(profile, SimpleNamespace(tenant_id="school-1"))
    assert collection.member_name == "张三"
    assert collection.id_card_masked == "110101********1234"
    assert "110101199001011234" not in str(collection.payload)
    assert person_category("member") == "正式党员"


def test_review_and_branch_edit_are_bound_to_current_stage():
    submitted = SimpleNamespace(status="submitted")
    branch_approved = SimpleNamespace(status="branch_approved")
    department_approved = SimpleNamespace(status="department_approved")
    secretary = SimpleNamespace(role=UserRole.BRANCH_SECRETARY)
    department = SimpleNamespace(role=UserRole.DEPARTMENT_ADMIN)
    school = SimpleNamespace(role=UserRole.SCHOOL_ADMIN)
    organizer = SimpleNamespace(role=UserRole.ORGANIZER)

    assert can_edit_branch(organizer, submitted)
    assert not can_edit_branch(organizer, branch_approved)
    assert can_review(secretary, submitted)
    assert can_review(department, branch_approved)
    assert can_review(school, department_approved)
    assert not can_review(department, submitted)
