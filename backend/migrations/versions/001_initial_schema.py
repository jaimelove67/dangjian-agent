"""数据库迁移脚本：初始化核心表

Revision ID: 001
Revises:
Create Date: 2026-01-04

"""

import sqlalchemy as sa
from alembic import context, op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """升级数据库"""
    # 启用 pgvector 扩展
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # 创建租户表
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), default=False, nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("tenant_type", sa.String(20), nullable=False),
        sa.Column("parent_id", sa.String(36), nullable=True),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("config", postgresql.JSON(), nullable=True),
        sa.Column("contact_name", sa.String(50), nullable=True),
        sa.Column("contact_phone", sa.String(20), nullable=True),
        sa.Column("contact_email", sa.String(100), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
    )
    op.create_index("ix_tenants_id", "tenants", ["id"])
    op.create_index("ix_tenants_tenant_id", "tenants", ["tenant_id"])
    op.create_index("ix_tenants_parent_id", "tenants", ["parent_id"])
    op.create_index("ix_tenants_path", "tenants", ["path"])

    # 创建组织单元表
    op.create_table(
        "org_units",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), default=False, nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("org_type", sa.String(20), nullable=False),
        sa.Column("parent_id", sa.String(36), nullable=True),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("leader_name", sa.String(50), nullable=True),
        sa.Column("leader_phone", sa.String(20), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
    )
    op.create_index("ix_org_units_id", "org_units", ["id"])
    op.create_index("ix_org_units_tenant_id", "org_units", ["tenant_id"])
    op.create_index("ix_org_units_parent_id", "org_units", ["parent_id"])
    op.create_index("ix_org_units_path", "org_units", ["path"])

    # 历史本地启动脚本可能已经创建 users，却没有 Alembic 版本表。
    # 只有显式指定 -x adopt_existing_users=true 且结构兼容时才接管；绝不清空数据。
    existing_users = not context.is_offline_mode() and sa.inspect(op.get_bind()).has_table("users")
    if existing_users:
        if context.get_x_argument(as_dictionary=True).get("adopt_existing_users") != "true":
            raise RuntimeError(
                "已有 users 表。核对结构后使用 -x adopt_existing_users=true 保留数据并迁移"
            )
        inspector = sa.inspect(op.get_bind())
        columns = {column["name"]: column for column in inspector.get_columns("users")}
        required = {
            "id",
            "created_at",
            "updated_at",
            "is_deleted",
            "tenant_id",
            "username",
            "name",
            "password_hash",
            "email",
            "phone",
            "role",
            "org_unit_id",
            "is_active",
        }
        if not required.issubset(columns) or inspector.get_pk_constraint("users")[
            "constrained_columns"
        ] != ["id"]:
            raise RuntimeError("已有 users 表结构不兼容；迁移已停止，不会修改已有用户数据")
        for name in ("id", "tenant_id", "username", "name", "password_hash", "role"):
            if columns[name]["nullable"] or not isinstance(columns[name]["type"], sa.String):
                raise RuntimeError(f"已有 users.{name} 类型或空值约束不兼容")
    else:
        _create_users()
    existing_indexes = (
        {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("users")}
        if existing_users
        else set()
    )
    for name, column in [
        ("ix_users_id", "id"),
        ("ix_users_tenant_id", "tenant_id"),
        ("ix_users_username", "username"),
        ("ix_users_email", "email"),
        ("ix_users_org_unit_id", "org_unit_id"),
    ]:
        if name not in existing_indexes:
            op.create_index(name, "users", [column])
    if existing_users:
        # UNIQUE 索引只添加约束，不更改任何记录；若有重复，整次迁移回滚。
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_users_adopt_username ON users (username)")
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_users_adopt_email ON users (email)")

    _create_remaining_tables()


def _create_users():
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), default=False, nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("username", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("email", sa.String(100), nullable=True, unique=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("org_unit_id", sa.String(36), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def _create_remaining_tables():
    # 创建审计日志表
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), default=False, nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("user_name", sa.String(50), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=True),
        sa.Column("data_level", sa.String(20), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("old_value", postgresql.JSON(), nullable=True),
        sa.Column("new_value", postgresql.JSON(), nullable=True),
    )
    op.create_index("ix_audit_logs_id", "audit_logs", ["id"])
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_resource_type", "audit_logs", ["resource_type"])
    op.create_index("ix_audit_logs_resource_id", "audit_logs", ["resource_id"])
    op.create_index("ix_audit_logs_data_level", "audit_logs", ["data_level"])
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])
    op.create_index("ix_audit_logs_result", "audit_logs", ["result"])

    # 创建知识文档表
    op.create_table(
        "knowledge_docs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), default=False, nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("doc_id", sa.String(100), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("issuer", sa.String(200), nullable=False),
        sa.Column("doc_number", sa.String(100), nullable=True),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("visibility", sa.String(20), nullable=False),
        sa.Column("security_level", sa.String(20), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("expiration_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="effective"),
        sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("file_path", sa.String(500), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("metadata", postgresql.JSON(), nullable=True),
    )
    op.create_index("ix_knowledge_docs_id", "knowledge_docs", ["id"])
    op.create_index("ix_knowledge_docs_tenant_id", "knowledge_docs", ["tenant_id"])
    op.create_index("ix_knowledge_docs_doc_id", "knowledge_docs", ["doc_id"], unique=True)
    op.create_index("ix_knowledge_docs_doc_number", "knowledge_docs", ["doc_number"])
    op.create_index("ix_knowledge_docs_level", "knowledge_docs", ["level"])
    op.create_index("ix_knowledge_docs_visibility", "knowledge_docs", ["visibility"])
    op.create_index("ix_knowledge_docs_security_level", "knowledge_docs", ["security_level"])
    op.create_index("ix_knowledge_docs_effective_date", "knowledge_docs", ["effective_date"])
    op.create_index("ix_knowledge_docs_expiration_date", "knowledge_docs", ["expiration_date"])
    op.create_index("ix_knowledge_docs_status", "knowledge_docs", ["status"])

    # 创建向量化片段表
    op.create_table(
        "embedding_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), default=False, nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("doc_id", sa.String(36), nullable=False),
        sa.Column("chunk_id", sa.String(100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("article", sa.String(50), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("metadata", postgresql.JSON(), nullable=True),
    )
    op.create_index("ix_embedding_chunks_id", "embedding_chunks", ["id"])
    op.create_index("ix_embedding_chunks_tenant_id", "embedding_chunks", ["tenant_id"])
    op.create_index("ix_embedding_chunks_doc_id", "embedding_chunks", ["doc_id"])
    op.create_index("ix_embedding_chunks_chunk_id", "embedding_chunks", ["chunk_id"])
    op.create_index("ix_embedding_chunks_article", "embedding_chunks", ["article"])


def downgrade():
    """回滚数据库"""
    op.drop_table("embedding_chunks")
    op.drop_table("knowledge_docs")
    op.drop_table("audit_logs")
    op.drop_table("users")
    op.drop_table("org_units")
    op.drop_table("tenants")

    op.execute("DROP EXTENSION IF EXISTS vector")
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
