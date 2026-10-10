"""合并带入的开发脚本不得向生产写入或将演示语料当作正式依据。"""

from argparse import Namespace

import pytest

from scripts import create_test_user, seed_knowledge_docs, seed_member_profiles


@pytest.mark.parametrize("script", ["user", "members", "knowledge"])
async def test_production_rejects_seed_scripts_before_io(monkeypatch, script):
    monkeypatch.setattr(create_test_user.settings, "ENV", "production")

    def forbidden(*args, **kwargs):
        pytest.fail("生产环境拒绝必须发生在数据库或网络操作前")

    monkeypatch.setattr(create_test_user, "sessionmaker", forbidden)
    monkeypatch.setattr(seed_member_profiles, "sessionmaker", forbidden)
    monkeypatch.setattr(seed_knowledge_docs.httpx, "Client", forbidden)
    with pytest.raises(RuntimeError, match="development/testing"):
        if script == "user":
            await create_test_user.create_user(Namespace())
        elif script == "members":
            await seed_member_profiles.seed("synthetic-tenant", "synthetic-org")
        else:
            seed_knowledge_docs.main()


def test_demo_knowledge_cannot_enter_effective_or_shared_library():
    for doc in seed_knowledge_docs.DOCS:
        metadata = seed_knowledge_docs._metadata_fields(doc)
        assert metadata["status"] == "expired"
        assert metadata["level"] == "school" and metadata["visibility"] == "school"
        assert metadata["doc_id"].startswith("DEMO-")
        assert metadata["title"].startswith("[未核验演示]")
