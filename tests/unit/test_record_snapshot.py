"""版本快照序列化：延迟列不得触发懒加载，材料接口不因此 500。

``MemberMaterial.content`` 是 ``deferred(LargeBinary)``；在异步会话里直接
``getattr`` 读它会在同步栈上发起懒加载 SQL，SQLAlchemy 抛 ``MissingGreenlet``。
"""

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models.member import MemberMaterial
from app.utils.snapshot import record_snapshot


def _engine():
    engine = create_engine("sqlite:///:memory:")
    MemberMaterial.__table__.create(engine)
    return engine


def test_deferred_binary_column_is_skipped():
    engine = _engine()
    with Session(engine) as db:
        db.add(MemberMaterial(id="m1", tenant_id="t1", profile_id="p1", content=b"synthetic"))
        db.commit()

    with Session(engine) as db:
        material = db.get(MemberMaterial, "m1")
        assert "content" in inspect(material).unloaded
        snapshot = record_snapshot(material)

    assert "content" not in snapshot
    assert snapshot["id"] == "m1" and snapshot["profile_id"] == "p1"
    assert set(snapshot) == {column.key for column in MemberMaterial.__table__.columns} - {
        "content"
    }


def test_transient_object_keeps_full_key_set():
    """新建对象没有可回查的行，未赋值列按 None 保留，键集合与旧实现一致。"""
    material = MemberMaterial(id="m2", tenant_id="t1", profile_id="p1")
    snapshot = record_snapshot(material)
    assert snapshot["id"] == "m2"
    assert set(snapshot) == {column.key for column in MemberMaterial.__table__.columns}
    assert snapshot["content"] is None


def test_datetime_and_bytes_are_jsonable():
    engine = _engine()
    with Session(engine) as db:
        db.add(MemberMaterial(id="m3", tenant_id="t1", profile_id="p1", file_name="合成.txt"))
        db.commit()

    with Session(engine) as db:
        snapshot = record_snapshot(db.get(MemberMaterial, "m3"))

    assert snapshot["file_name"] == "合成.txt"
    assert isinstance(snapshot["created_at"], str)
