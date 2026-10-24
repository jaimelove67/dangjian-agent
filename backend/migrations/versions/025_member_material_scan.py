"""数据库迁移脚本：党员档案支持扫描件归档

Revision ID: 025_member_material_scan
Revises: 024_member_id_card
Create Date: 2026-10-22

组织干事把纸质档案扫描后归档，材料记录需要能指向库外的影像件，并保留识别出的文本。

- ``file_path``：影像件在文件卷里的相对路径（已加密），**不把二进制塞进数据库**——
  一份扫描件 5–20MB，一千人就是几十 GB，全进 bytea 会让 pg_dump 变成几十 GB。
  原有的 ``content`` 列保留，用于小文件与历史数据。
- ``extracted_text``：OCR / 文字层抽取结果，供核验与检索；识别不是原件，界面须标注。
- ``ocr_status``：none（纯登记，无文件）/ done / skipped（未开启或未同意）/ failed。
- ``ocr_pages``：实际识别页数，页数超上限时界面要告知"只识别了前 N 页"。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "025_member_material_scan"
down_revision = "024_member_id_card"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级数据库"""
    op.add_column(
        "member_materials",
        sa.Column("file_path", sa.String(length=512), nullable=False, server_default=""),
    )
    op.add_column(
        "member_materials",
        sa.Column("extracted_text", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "member_materials",
        sa.Column("ocr_status", sa.String(length=20), nullable=False, server_default="none"),
    )
    op.add_column(
        "member_materials",
        sa.Column("ocr_pages", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    """回滚数据库"""
    op.drop_column("member_materials", "ocr_pages")
    op.drop_column("member_materials", "ocr_status")
    op.drop_column("member_materials", "extracted_text")
    op.drop_column("member_materials", "file_path")
