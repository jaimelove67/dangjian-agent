"""数据库迁移脚本：知识条目权威来源、效力状态与公共库审核发布

Revision ID: 014_knowledge_authority_validity
Revises: 013_notification_delivery
Create Date: 2026-10-15

为 ``knowledge_docs`` 补齐 T-DATA-05 要求的字段，并支撑 T-KB-12 的公共库审核发布流：

- ``authority``      权威来源类别（党章 / 党内法规 / 上级文件 / 学校制度 / 参考资料）；
- ``validity``       效力状态（现行有效 / 尚未生效 / 已被新版替代 / 已废止）；
- ``review_status``  公共库审核发布状态（pending / published / rejected）；
- ``reviewed_by`` / ``reviewed_at`` / ``review_note``  审核留痕；
- ``field_levels``   字段级敏感等级（JSON，供脱敏与外发规则使用）。

回填口径（不改变现有检索结果的可见性）：

1. 权威来源按已有层级推定——中央 / 省级文件属「上级文件」，学校 / 院系文件属
   「学校制度」；维护人员可随后通过元数据修正接口调整。
2. 效力状态统一回填``effective``（现行有效）。
3. 审核状态统一回填``published``：存量条目已在使用中，按已审核发布承接；
   只有迁移之后新入库的公共可见内容才需要走审核。
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401  （与既有迁移保持一致的导入风格）

# revision identifiers, used by Alembic.
revision = "014_knowledge_authority_validity"
down_revision = "013_notification_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级数据库"""
    op.add_column(
        "knowledge_docs",
        sa.Column("authority", sa.String(30), nullable=False, server_default="reference"),
    )
    op.add_column(
        "knowledge_docs",
        sa.Column("validity", sa.String(20), nullable=False, server_default="effective"),
    )
    op.add_column(
        "knowledge_docs",
        sa.Column("review_status", sa.String(20), nullable=False, server_default="published"),
    )
    op.add_column("knowledge_docs", sa.Column("reviewed_by", sa.String(36), nullable=True))
    op.add_column("knowledge_docs", sa.Column("reviewed_at", sa.DateTime(), nullable=True))
    op.add_column("knowledge_docs", sa.Column("review_note", sa.String(500), nullable=True))
    op.add_column("knowledge_docs", sa.Column("field_levels", sa.JSON(), nullable=True))

    # 存量条目按层级推定权威来源；未匹配层级的保持「参考资料」默认值，由维护人员确认。
    op.execute(
        "UPDATE knowledge_docs SET authority='superior_document' "
        "WHERE level IN ('central', 'provincial')"
    )
    op.execute(
        "UPDATE knowledge_docs SET authority='school_policy' "
        "WHERE level IN ('school', 'department')"
    )

    op.create_index("ix_knowledge_docs_authority", "knowledge_docs", ["authority"])
    op.create_index("ix_knowledge_docs_validity", "knowledge_docs", ["validity"])
    op.create_index("ix_knowledge_docs_review_status", "knowledge_docs", ["review_status"])


def downgrade() -> None:
    """回滚数据库"""
    op.drop_index("ix_knowledge_docs_review_status", table_name="knowledge_docs")
    op.drop_index("ix_knowledge_docs_validity", table_name="knowledge_docs")
    op.drop_index("ix_knowledge_docs_authority", table_name="knowledge_docs")
    op.drop_column("knowledge_docs", "field_levels")
    op.drop_column("knowledge_docs", "review_note")
    op.drop_column("knowledge_docs", "reviewed_at")
    op.drop_column("knowledge_docs", "reviewed_by")
    op.drop_column("knowledge_docs", "review_status")
    op.drop_column("knowledge_docs", "validity")
    op.drop_column("knowledge_docs", "authority")
