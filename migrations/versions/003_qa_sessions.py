"""数据库迁移脚本：问答历史表

Revision ID: 003
Revises: 002
Create Date: 2026-10-10

新增 ``qa_sessions`` 表，持久化每次成功问答（问题 / 答案 / 引用 / 分级 / 检索明细），
供 ``GET /api/v1/qa/sessions`` 分页查询历史记录。租户隔离字段由 Base 提供。
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401  （与 001/002 保持一致的导入风格）

# revision identifiers, used by Alembic.
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级数据库"""
    op.create_table(
        "qa_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("user_id", sa.String(36), nullable=False, index=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column(
            "citations", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")
        ),
        sa.Column(
            "data_level", sa.String(20), nullable=False, server_default="public"
        ),
        sa.Column(
            "has_sufficient_evidence",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "retrieved_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    # 常见查询路径：某租户下某用户的历史列表（按时间倒序）
    op.create_index(
        "ix_qa_sessions_user_created",
        "qa_sessions",
        ["tenant_id", "user_id", "created_at"],
    )


def downgrade() -> None:
    """回滚数据库"""
    op.drop_index("ix_qa_sessions_user_created", table_name="qa_sessions")
    op.drop_table("qa_sessions")