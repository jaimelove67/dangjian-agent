"""数据库迁移脚本：初始化核心表

Revision ID: 001
Revises:
Create Date: 2026-01-04

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """升级数据库"""
    # 启用 pgvector 扩展
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # 创建租户表
    op.create_table(
        'tenants',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
        sa.Column('tenant_id', sa.String(36), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('tenant_type', sa.String(20), nullable=False),
        sa.Column('parent_id', sa.String(36), nullable=True),
        sa.Column('path', sa.String(500), nullable=False),
        sa.Column('config', postgresql.JSON(), nullable=True),
        sa.Column('contact_name', sa.String(50), nullable=True),
        sa.Column('contact_phone', sa.String(20), nullable=True),
        sa.Column('contact_email', sa.String(100), nullable=True),
        sa.Column('remark', sa.Text(), nullable=True),
    )
    op.create_index('ix_tenants_id', 'tenants', ['id'])
    op.create_index('ix_tenants_tenant_id', 'tenants', ['tenant_id'])
    op.create_index('ix_tenants_parent_id', 'tenants', ['parent_id'])
    op.create_index('ix_tenants_path', 'tenants', ['path'])

    # 创建组织单元表
    op.create_table(
        'org_units',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
        sa.Column('tenant_id', sa.String(36), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('org_type', sa.String(20), nullable=False),
        sa.Column('parent_id', sa.String(36), nullable=True),
        sa.Column('path', sa.String(500), nullable=False),
        sa.Column('leader_name', sa.String(50), nullable=True),
        sa.Column('leader_phone', sa.String(20), nullable=True),
        sa.Column('remark', sa.Text(), nullable=True),
    )
    op.create_index('ix_org_units_id', 'org_units', ['id'])
    op.create_index('ix_org_units_tenant_id', 'org_units', ['tenant_id'])
    op.create_index('ix_org_units_parent_id', 'org_units', ['parent_id'])
    op.create_index('ix_org_units_path', 'org_units', ['path'])

    # 创建用户表
    op.create_table(
        'users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
        sa.Column('tenant_id', sa.String(36), nullable=False),
        sa.Column('username', sa.String(50), nullable=False, unique=True),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('email', sa.String(100), nullable=True, unique=True),
        sa.Column('phone', sa.String(20), nullable=True),
        sa.Column('role', sa.String(50), nullable=False),
        sa.Column('org_unit_id', sa.String(36), nullable=True),
        sa.Column('is_active', sa.String(10), nullable=False, default='true'),
    )
    op.create_index('ix_users_id', 'users', ['id'])
    op.create_index('ix_users_tenant_id', 'users', ['tenant_id'])
    op.create_index('ix_users_username', 'users', ['username'])
    op.create_index('ix_users_email', 'users', ['email'])
    op.create_index('ix_users_org_unit_id', 'users', ['org_unit_id'])

    # 创建审计日志表
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
        sa.Column('tenant_id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('user_name', sa.String(50), nullable=False),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('resource_type', sa.String(50), nullable=False),
        sa.Column('resource_id', sa.String(36), nullable=True),
        sa.Column('data_level', sa.String(20), nullable=False),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('request_id', sa.String(64), nullable=False),
        sa.Column('result', sa.String(20), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('old_value', postgresql.JSON(), nullable=True),
        sa.Column('new_value', postgresql.JSON(), nullable=True),
    )
    op.create_index('ix_audit_logs_id', 'audit_logs', ['id'])
    op.create_index('ix_audit_logs_tenant_id', 'audit_logs', ['tenant_id'])
    op.create_index('ix_audit_logs_user_id', 'audit_logs', ['user_id'])
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('ix_audit_logs_resource_type', 'audit_logs', ['resource_type'])
    op.create_index('ix_audit_logs_resource_id', 'audit_logs', ['resource_id'])
    op.create_index('ix_audit_logs_data_level', 'audit_logs', ['data_level'])
    op.create_index('ix_audit_logs_request_id', 'audit_logs', ['request_id'])
    op.create_index('ix_audit_logs_result', 'audit_logs', ['result'])


def downgrade():
    """回滚数据库"""
    op.drop_table('audit_logs')
    op.drop_table('users')
    op.drop_table('org_units')
    op.drop_table('tenants')

    op.execute('DROP EXTENSION IF EXISTS vector')
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
