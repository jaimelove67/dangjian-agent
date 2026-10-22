"""数据库迁移脚本：扫描件结构化抽取结果

Revision ID: 026_member_material_fields
Revises: 025_member_material_scan
Create Date: 2026-10-22

扫描件识别出文字后，再让文本模型抽一次"材料类型 / 所属人 / 落款日期 / 出具单位 / 要点"，
存成 JSON 供人工核对。**这些只是建议值**：材料类型仍由归档人选定，抽取结果不写台账字段，
避免模型判断直接变成组织记录。抽取为空（未识别、失败、敏感材料不出网）时存 `{}`。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "026_member_material_fields"
down_revision = "025_member_material_scan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级数据库"""
    op.add_column(
        "member_materials",
        sa.Column("extracted_fields", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    """回滚数据库"""
    op.drop_column("member_materials", "extracted_fields")
