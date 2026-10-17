"""数据库迁移脚本：多轮选优投票去重按批次（T-MEM-06 / T-SEC-13 回归）

Revision ID: 022_member_vote_dedup_batch
Revises: 021_member_selection
Create Date: 2026-10-17

009 建表时把 ``uq_member_vote_dedup`` 定成 ``(tenant_id, round_no, voter_id, profile_id)``，
漏了 ``batch_no``；服务层的查重却是"同一投票人同一批次同一轮只能提交一次"（批次是一次独立
的选优）。两条规则不一致的后果不是"更严格"，而是**正常业务变成内部错误**：同一投票人在另一个
年度批次的第 1 轮投票时，查重放行、数据库约束报冲突，接口把 IntegrityError 抛成 500，错误里
还带着唯一约束名——用户从界面上看不出自己哪一步做错了。

这里给约束补上 ``batch_no``：一个投票人在一个批次的一个轮次里，对名单中的每个人只能有一条
记录。约束仍然保留 ``profile_id``（一次提交本来就要给每个人各留一条记录，只按投票人去重会把
正常提交挡在门外）。这是**放宽**约束，存量数据不会冲突。
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "022_member_vote_dedup_batch"
down_revision = "021_member_selection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级数据库"""
    op.drop_constraint("uq_member_vote_dedup", "member_votes", type_="unique")
    op.create_unique_constraint(
        "uq_member_vote_dedup",
        "member_votes",
        ["tenant_id", "batch_no", "round_no", "voter_id", "profile_id"],
    )


def downgrade() -> None:
    """回滚数据库

    回滚会把约束收紧回"跨批次也不能重复投票"：升级后已经产生的跨批次投票记录会让这一步
    失败（数据确实不满足旧约束）。此时要么先删掉那些记录，要么保留在 022——不在这里悄悄删
    业务数据（留痕优先）。
    """
    op.drop_constraint("uq_member_vote_dedup", "member_votes", type_="unique")
    op.create_unique_constraint(
        "uq_member_vote_dedup",
        "member_votes",
        ["tenant_id", "round_no", "voter_id", "profile_id"],
    )
