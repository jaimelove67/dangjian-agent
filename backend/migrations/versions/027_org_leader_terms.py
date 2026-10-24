"""数据库迁移脚本：组织负责人职务拆分与任职记录

Revision ID: 027_org_leader_terms
Revises: 026_member_material_fields
Create Date: 2026-10-23

原先 ``org_units`` 只有一个 ``leader_name``，实际使用中把职务也写在里面
（"周明远 党委书记"），换职务就得整串改名，且没有任何任职履历。本迁移做两件事：

1. ``org_units`` 增加 ``leader_title``：姓名与职务分开，换职务只改职务；
   现有数据里"姓名 空格 职务"的记录在 upgrade 阶段按首个空格自动拆开。
2. 新建 ``org_leader_terms``：一条记录 = 一人在一个组织的一段任职，
   ``ended_on`` 为空表示仍在任，离任只写日期不删记录；``is_primary`` 标记主要负责人，
   变更后由服务层回写 ``org_units.leader_name / leader_title / leader_phone``。

干部任职与党员组织关系接转（``member_transfers``）是两件事，本表不改发展阶段。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "027_org_leader_terms"
down_revision = "026_member_material_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级数据库"""
    op.add_column("org_units", sa.Column("leader_title", sa.String(50), nullable=True))

    # 历史数据：把"姓名 职务"按第一个空格拆开，拆不出职务的保持原名不动
    op.execute(
        """
        UPDATE org_units
           SET leader_name = split_part(leader_name, ' ', 1),
               leader_title = nullif(trim(substr(leader_name, strpos(leader_name, ' ') + 1)), '')
         WHERE leader_name IS NOT NULL
           AND strpos(leader_name, ' ') > 0
        """
    )

    op.create_table(
        "org_leader_terms",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("org_unit_id", sa.String(36), nullable=False, index=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("title", sa.String(50), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("started_on", sa.Date(), nullable=True),
        sa.Column("ended_on", sa.Date(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remark", sa.String(200), nullable=True),
    )

    # 已登记负责人的组织，补一条在任记录，履历从"有数据那天"开始
    op.execute(
        """
        INSERT INTO org_leader_terms
            (id, tenant_id, org_unit_id, name, title, phone, is_primary, created_at, updated_at, is_deleted)
        SELECT gen_random_uuid()::text, tenant_id, id, leader_name,
               coalesce(leader_title, '负责人'), leader_phone, true, now(), now(), false
          FROM org_units
         WHERE leader_name IS NOT NULL AND leader_name <> ''
        """
    )


def downgrade() -> None:
    """回滚数据库"""
    op.drop_table("org_leader_terms")
    op.drop_column("org_units", "leader_title")
