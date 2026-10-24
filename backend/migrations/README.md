# 数据库迁移指南

更新日期：2026-10-24。从后端目录、安装项目依赖的 Python 环境执行。目标数据库为支持 pgvector 的 PostgreSQL，连接读取 `DATABASE_URL`。

## 当前迁移链

当前唯一头为 `031_backup_jobs`：

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
| `013_notification_delivery` | 通知投递台账（站内 / 外部渠道投递与重试留痕） |
| `014_knowledge_authority_validity` | 知识条目权威来源 / 效力状态 / 公共库审核发布字段；存量按层级回填 |
| `015_knowledge_review_schedule` | 知识条目供给复核日程；存量不回填（按当前配置倒推会伪造来源） |
| `016_qa_session_versions` | 问答记录版本留痕（JSON 可空）；存量不回填 |
| `017_member_reviews` | 民主评议党员；一人一年一条，唯一约束租户 × 年度 × 档案，年月与等次由人工形成 |
| `018_member_transfers` | 组织关系接转台账与名册组织关系缓存列；存量按「在册」处理，接转记录不回填 |
| `019_member_upper_reports` | 上级审批 / 备案报送台账；存量不回填（凭空补报送记录等于伪造事实） |
| `020_member_data_levels` | 材料 / 民主评议字段级密级；存量材料按材料类型回填，映射在迁移内冻结 |
| `021_member_selection` | 选优结论与团组织推优台账；名单与依据由人填写，存量不回填 |
| `022_member_vote_dedup_batch` | 投票去重唯一约束补 `batch_no`，与服务层查重同一条规则；放宽约束，存量不冲突 |
| `023_qa_session_attachments` | 问答附件元数据，不长期保存附件正文 |
| `024_member_id_card` | 档案账号标识字段，展示与审计沿用脱敏规则 |
| `025_member_material_scan` | 扫描原件路径与识别文本，识别内容不代替原件 |
| `026_member_material_fields` | 扫描件结构化建议值，待人工核对 |
| `027_org_leader_terms` | 组织负责人职务及任职履历 |
| `028_account_security` | 实际登录会话、改密申请、累计成功自主改密台账及一次授权约束 |
| `029_school_business` | 校内通知、版本化督办任务及业务角色申请 |
| `030_education` | 课程/考试/主题党日及每账号唯一的学习、报名、积分记录 |
| `031_backup_jobs` | 实际备份与隔离恢复任务、请求去重及执行结果 |

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

生产容器去掉 `-f docker-compose.dev.yml`。应用启动不会自动执行迁移。`/api/v1/health/ready` 核对基础核心表、全文检索及源码解析出的完整迁移头；仍须明确确认目标连接和 `alembic current`，不能据进程存活推断迁移完成。新增迁移为增量升级，不清空原业务表，不回填虚构通知、改密次数、学习或维护记录。

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

## 文档分支合并说明

本次保留主分支的 `008_org_life_tasks → 009_member_workflow → 010_security_governance → 011_governance_timestamps → 012_member_self` 连续迁移链。本地工作台的 `008_member_self/009_admin_workspace` 属于另一开发基线，没有合入此主分支，不能替代以上迁移。新增会话版本能力须另行设计兼容迁移，不能直接复制旧编号脚本。
