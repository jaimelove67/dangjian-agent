"""数据库模型冒烟测试（纯元数据，不依赖真实数据库）

覆盖 Day1 数据库设计的关键约束：
- 6 张核心表全部注册到 Base.metadata
- 公共字段（id / created_at / updated_at / is_deleted / tenant_id）齐全
- 关键字段类型正确（users.is_active 为布尔、embedding 为 1024 维向量）
- 中文全文检索生成列 search_vector 定义正确
"""
import uuid

import pytest
from sqlalchemy import Boolean
from sqlalchemy.dialects.postgresql import TSVECTOR
from pgvector.sqlalchemy import Vector

from app.db.base import Base
from app.models.user import User, UserRole
from app.models.tenant import Tenant
from app.models.org import OrgUnit
from app.models.knowledge import KnowledgeDoc, EmbeddingChunk
from app.models.audit import AuditLog


EXPECTED_TABLES = {
    "tenants",
    "org_units",
    "users",
    "knowledge_docs",
    "audit_logs",
    "embedding_chunks",
}

COMMON_COLUMNS = {"id", "created_at", "updated_at", "is_deleted", "tenant_id"}


class TestModelRegistration:
    """模型注册与公共字段"""

    def test_all_core_tables_registered(self):
        assert EXPECTED_TABLES <= set(Base.metadata.tables.keys())

    @pytest.mark.parametrize("table_name", sorted(EXPECTED_TABLES))
    def test_common_columns_present(self, table_name):
        table = Base.metadata.tables[table_name]
        assert COMMON_COLUMNS <= {column.name for column in table.columns}

    def test_tablenames_are_snake_case(self):
        assert Tenant.__tablename__ == "tenants"
        assert OrgUnit.__tablename__ == "org_units"
        assert User.__tablename__ == "users"
        assert KnowledgeDoc.__tablename__ == "knowledge_docs"
        assert AuditLog.__tablename__ == "audit_logs"
        assert EmbeddingChunk.__tablename__ == "embedding_chunks"


class TestBaseModel:
    """基类行为"""

    def test_id_has_uuid_default(self):
        column = Base.metadata.tables["tenants"].columns["id"]
        assert column.primary_key is True
        assert column.default is not None
        # 默认值工厂应生成合法的 UUID 字符串
        generated = column.default.arg(None)
        assert isinstance(generated, str)
        uuid.UUID(generated)  # 非法 UUID 会抛异常

    def test_dict_serialization(self):
        user = User(
            username="zhangsan",
            name="张三",
            password_hash="hashed",
            role=UserRole.MEMBER,
            tenant_id="tenant-001",
        )
        data = user.dict()
        assert data["username"] == "zhangsan"
        assert data["tenant_id"] == "tenant-001"
        assert set(COMMON_COLUMNS) <= set(data.keys())


class TestUserModel:
    """用户模型"""

    def test_is_active_is_boolean(self):
        column = Base.metadata.tables["users"].columns["is_active"]
        assert isinstance(column.type, Boolean)
        assert column.default.arg is True

    def test_role_enum_has_seven_values(self):
        assert len(list(UserRole)) == 7
        assert UserRole.SYSTEM_ADMIN.value == "system_admin"
        assert UserRole.APPLICANT.value == "applicant"


class TestKnowledgeModel:
    """知识文档与向量片段"""

    def test_embedding_is_1024_dim_vector(self):
        column = Base.metadata.tables["embedding_chunks"].columns["embedding"]
        assert isinstance(column.type, Vector)
        assert column.type.dim == 1024

    def test_search_vector_is_generated_tsvector(self):
        column = Base.metadata.tables["knowledge_docs"].columns["search_vector"]
        assert isinstance(column.type, TSVECTOR)
        assert column.computed is not None, "search_vector 应为生成列"
        assert "chinese_zh" in str(column.computed.sqltext)

    def test_metadata_column_physical_name(self):
        # Python 属性 doc_metadata 映射到物理列 metadata
        assert "metadata" in Base.metadata.tables["knowledge_docs"].columns
