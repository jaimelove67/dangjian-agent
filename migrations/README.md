# 数据库迁移指南

## 初始化迁移环境

```bash
# 使用 Alembic 初始化迁移
alembic init migrations

# 或者使用已配置好的环境（已完成）
```

## 创建迁移脚本

```bash
# 自动生成迁移脚本
alembic revision --autogenerate -m "描述信息"

# 手动创建迁移脚本
alembic revision -m "描述信息"
```

## 应用迁移

```bash
# 升级到最新版本
alembic upgrade head

# 升级到指定版本
alembic upgrade +1  # 升级一个版本
alembic upgrade revision_id  # 升级到指定版本

# 降级
alembic downgrade -1  # 降级一个版本
alembic downgrade base  # 降级到初始状态
```

## 查看迁移历史

```bash
# 查看当前版本
alembic current

# 查看迁移历史
alembic history

# 查看待应用的迁移
alembic show head
```

## Docker 环境中运行迁移

```bash
# 进入应用容器
docker-compose -f docker-compose.dev.yml exec app bash

# 运行迁移
alembic upgrade head
```

## 初始化脚本

### 方式1：使用 Python 脚本（开发环境）

```bash
python scripts/init_db.py
```

### 方式2：使用 Alembic（生产环境推荐）

```bash
alembic upgrade head
```

## 数据库表结构

### 核心表

- `tenants` - 租户表（支持多级租户）
- `org_units` - 组织单元表（学校/院系/支部）
- `users` - 用户表
- `audit_logs` - 审计日志表（只追加）

### 知识库表

- `knowledge_docs` - 知识文档表
- `embedding_chunks` - 向量化片段表

## 注意事项

1. **生产环境**：始终使用 Alembic 进行迁移，不要直接运行 `init_db.py`
2. **迁移前备份**：生产环境迁移前务必备份数据库
3. **审计表**：`audit_logs` 表只追加，不可更新或删除
4. **pgvector**：确保数据库已启用 pgvector 扩展
