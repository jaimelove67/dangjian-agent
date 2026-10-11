# 数据库迁移指南

更新日期：2026-10-11。从项目根目录、安装项目依赖的 Python 环境执行。目标数据库为支持 pgvector 的 PostgreSQL，连接读取 `DATABASE_URL`。

## 当前迁移链

当前唯一头为 `012_member_self`：

| revision | 内容 |
| --- | --- |
| `001` | 租户、组织、用户、审计、知识文档、向量片段与扩展 |
| `002` | 中文全文检索配置和索引 |
| `003` | `qa_sessions` 持久历史 |
| `004` | `member_profiles` 名册 |
| `005` | 问答历史元数据和名册组织范围 |
| `006` | `study_plans`、`study_plan_items`、`meeting_records`、`content_revisions` |
| `007_assessment` | 指标、任务、佐证、归集版本、计划、学校策略、提醒、归档八张考核表 |
| `008_org_life_tasks` | 组织生活任务台账 |
| `009_member_workflow` | 年度批次、组织材料记录、阶段历史、提醒、培养、投票和档案检查 |
| `010_security_governance` | 配置版本、人工审核、耐久任务、模型用量与安全治理字段 |
| `011_governance_timestamps` | 对治理表的时间默认值进行兼容修正 |
| `012_member_self` | 在既有名册和组织材料表上增加账号关联、私有原件与提交重试字段；不自动按姓名匹配 |

## 应用与核对

迁移前确认目标库和备份；项目已有 Alembic 环境，无需重新初始化。

```bash
python -m alembic heads
python -m alembic current
python -m alembic upgrade head
python -m alembic current
```

容器开发环境：

```bash
docker compose -f docker-compose.dev.yml exec app python -m alembic upgrade head
docker compose -f docker-compose.dev.yml exec app python -m alembic current
```

生产容器去掉 `-f docker-compose.dev.yml`。应用启动不会自动执行迁移；`/api/v1/health/ready` 只核对基础核心表与全文检索，不核对学习/考核表及完整迁移头，仍须检查 `alembic current`。

## 旧数据库接管

仅包含手工创建 `users` 表的旧库，备份并核对后按[运行指南](../docs/RUNNING.md)执行：

```bash
python -m alembic -x adopt_existing_users=true upgrade head
```

不要通过 `alembic stamp head` 跳过建表。`scripts/init_db.py` 先执行 `Base.metadata.drop_all`，会删除已有表和数据，只适用于经明确确认的可丢弃开发库，不能用于升级或接管。根目录临时建表 SQL 不能替代完整迁移。

## 开发迁移与回退

```bash
python -m alembic revision --autogenerate -m "描述变更"
python -m alembic history
python -m alembic show head
```

人工检查生成结果的租户字段、外键、索引、默认值及数据影响，保持连续单头。`downgrade` 可能删除表，应先在独立库验证；空表回退不能证明已有数据可安全回退。生产回滚须匹配代码、结构和已确认的备份恢复方案。

学习和考核迁移历史证据来自独立测试库，不代表业务库已升级。验证边界见[测试指南](../docs/TESTING.md)。
