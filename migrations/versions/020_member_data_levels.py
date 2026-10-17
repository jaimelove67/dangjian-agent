"""数据库迁移脚本：党员材料 / 民主评议的字段级敏感分级（T-MEM-12）

Revision ID: 020_member_data_levels
Revises: 019_member_upper_reports
Create Date: 2026-10-16

给 ``member_materials`` 与 ``member_reviews`` 各加一列 ``data_level``（密级快照），
用于 SEC-01 的分级管理与 SEC-04 的敏感内容收敛：

- 材料密级**登记时**按材料类型带出，之后配置调整不回改历史记录（快照语义，
  与 ``member_transfers`` / ``member_upper_reports`` 一致）；
- 政治审查材料含第三人（亲属、证明人）信息，默认按**涉密级**处理（第三人字段正文
  对全部角色都不返回，只留元数据）；若学校认为按敏感级（组织人员可见正文）更合适，
  改 ``config/business_rules.yaml`` 的 ``data_sensitivity.member_material_levels``
  即可，**不回改已有行**（已有行的密级仍是登记时点的取值）。

下方的一次性回填映射按本迁移时点的 ``config/business_rules.yaml`` **冻结**写入，
不 import 应用规则模块：迁移要能独立重放，不能随配置漂移。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "020_member_data_levels"
down_revision = "019_member_upper_reports"
branch_labels = None
depends_on = None

# 冻结的材料类型 → 密级映射（与迁移时点的 config 一致）
_CLASSIFIED_MATERIAL_TYPES = ("政治审查材料", "政审材料", "政治审查")
_SENSITIVE_MATERIAL_TYPES = ("群众评议材料", "群众评议")


def _backfill(data_level: str, material_types: tuple[str, ...]) -> None:
    op.execute(
        sa.text(
            "UPDATE member_materials SET data_level = :level WHERE material_type IN :types"
        ).bindparams(
            sa.bindparam("level", value=data_level),
            sa.bindparam("types", value=list(material_types), expanding=True),
        )
    )


def upgrade() -> None:
    """升级数据库"""
    op.add_column(
        "member_materials",
        sa.Column("data_level", sa.String(20), nullable=False, server_default="internal"),
    )
    op.add_column(
        "member_reviews",
        sa.Column("data_level", sa.String(20), nullable=False, server_default="sensitive"),
    )
    # 存量材料按材料类型补密级；新登记由服务层显式写值（配置改了也不回改历史）。
    _backfill("classified", _CLASSIFIED_MATERIAL_TYPES)
    _backfill("sensitive", _SENSITIVE_MATERIAL_TYPES)


def downgrade() -> None:
    """回滚数据库"""
    op.drop_column("member_reviews", "data_level")
    op.drop_column("member_materials", "data_level")
