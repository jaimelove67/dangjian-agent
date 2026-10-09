# 代码审查记录：权限 / 审计 / 租户隔离

> Day5-DevA 交付项之一。审查范围为内核安全机制（权限、审计、租户隔离）的实现与测试覆盖。

## 1. 权限（RBAC + 数据范围）

**实现**：`app/core/security.py`（角色画像 + 接口权限矩阵）、`app/deps.py`（`require_roles` / `require_permissions`）。

| 检查项 | 结论 |
| --- | --- |
| 角色/数据范围双层模型（框架 9.1） | ✅ 7 角色画像，含知识库可见范围、业务数据范围、数据级别上限 |
| 接口权限矩阵（开发规范 8.3） | ✅ 知识库维护=院系级及以上；党员发展查询/流转=支部书记及以上；配置/审计=系统管理员 |
| 数据级别由角色推导（不接受前端传入） | ✅ `resolve_data_level(role)`，请求体不接收 data_level |
| 越权测试 | ✅ `tests/security/test_permission.py`、接口 401/403 用例（知识库、党员发展） |

**发现**：`require_roles/require_permissions` 为 FastAPI 依赖工厂（非字面装饰器），符合规范 7.5 的 `Depends(get_current_user)` 用法。

## 2. 审计

**实现**：`app/core/audit.py`（统一接口 + 只追加约束）、`app/models/audit.py`。

| 检查项 | 结论 |
| --- | --- |
| 覆盖字段：操作人/时间/动作/对象/数据级别/结果/来源 | ✅ `make_audit_log` 强校验必填项 |
| 敏感操作记录变更前后值 | ✅ `old_value` / `new_value` |
| 只追加不修改 | ⚠️ 应用层已拦截 UPDATE/DELETE（`_prevent_audit_mutation`）；**数据库级** `REVOKE UPDATE, DELETE` 待补（部署项，见 `deploy/DEPLOYMENT.md`） |
| 单元测试 | ✅ `tests/unit/test_audit.py` |

## 3. 租户隔离

**实现**：`app/core/tenant.py`（上下文 + 写入注入 + 查询过滤）、`app/deps.py`（认证后注入上下文）。

| 检查项 | 结论 |
| --- | --- |
| 租户来源为登录态（框架 8.2） | ✅ 取自 JWT 声明，不接受前端传入 |
| 写入自动注入 tenant_id | ✅ `before_flush` 注入，缺失即拒绝（`TenantIsolationError`） |
| 查询强制过滤 | ✅ `do_orm_execute` 自动追加租户条件（可 `bypass_tenant_filter` 用于系统级操作） |
| 会话隔离 | ✅ 会话缓存键含租户标识（`session:{tenant}:{sid}`） |
| 越权测试 | ✅ `tests/security/test_tenant_isolation.py` |

## 4. 敏感数据出网

**实现**：`app/llm/gateway.py`（开发者B）。

| 检查项 | 结论 |
| --- | --- |
| 涉密直接拒绝 | ✅ |
| 敏感强制本地模型 | ✅ |
| 安全测试 | ✅ `tests/security/test_data_egress.py`（依赖 structlog，缺失时跳过） |

## 5. 结论与待办

- 权限、审计、租户隔离三项机制**实现到位且均有测试覆盖**（`pytest -m security`）。
- 待办（非阻塞）：
  1. 审计表**数据库级**只追加权限（`GRANT INSERT / REVOKE UPDATE, DELETE`）。
  2. `role` 等原生枚举列的迁移/模型一致性已修复（PR #15），后续新增枚举列需同步核对。
  3. 越权专项测试建议纳入 CI 卡点（框架 9.2）。
